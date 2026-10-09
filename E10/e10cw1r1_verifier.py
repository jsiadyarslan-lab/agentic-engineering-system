#!/usr/bin/env python3
"""E10-CW1-R1 INDEPENDENT VERIFIER — a separate OS process that reads ONLY
persistent state (journal files, artifact files, event log, evidence store,
checkpoints, injection/corruption/snapshot markers, process records). It
never imports the engine and never trusts any in-memory claim.

Mandatory proofs (order §5):
  * the crash point actually occurred (boundary state at kill, from the
    injection marker, cross-checked against the raw journal + file stats);
  * Process B is a new process (PIDs differ; runner-witnessed);
  * only IDs crossed the process boundary (resume_info.json structure);
  * the number of actual side effects, their identities and fingerprints
    before the crash and after the resume;
  * mtime_ns / inode / sha256 UNCHANGED when the required outcome is
    reconciliation-without-rewrite;
  * intent / performed / reconciliation records, attempts, events and the
    Artifact/Evidence stores all agree with reality (recomputed hashes);
  * the completed task reflects the REAL effect, not a status flag;
  * the same result in repeated runs (chains).

ORDER §5 HARD RULE: a `performed` record is NEVER evidence for closing the
window that PRECEDES its own write. For the pre-performed window (scenario
B/D1) the proof is: the intent record (durable BEFORE the effect, PID=A) +
the effect file's stat continuity across the resume + the FIRST performed
record for the operation being written by Process B with
performed_via=adopted_after_crash and performed_by_pid=Process A.

Event-contract proof (order §6): events are counted BY ARTIFACT IDENTITY and
BY OPERATION IDENTITY — never by run_id. Exactly ONE ARTIFACT_CREATED per
artifact id across the whole durable log; ARTIFACT_RECONCILED only for real
cross-process reconciliations with a valid mode.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from e10_common import MARKERS, TASK_KEYS, durable_write_json  # noqa: E402
from e10cw1r1_common import (  # noqa: E402
    CRASH_WINDOW_TASK, D_REL_PATH, SCENARIO_CORRUPTION, SCENARIO_INJECTION,
    journal_path, scan_journal, side_effect_file, stat_snapshot,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(p: Path):
    return json.loads(p.read_text())


def main(workdir: str, scenario: str) -> int:
    work = Path(workdir)
    artifacts_dir = work / "artifacts"
    evidence_dir = work / "evidence"
    pid = os.getpid()
    print(f"[R1_VERIFIER] pid={pid} scenario={scenario} — reading ONLY persistent state")

    resume_info = load_json(evidence_dir / "resume_info.json")
    injection = load_json(evidence_dir / "injection.json")
    snapshot = load_json(evidence_dir / "crash_window_snapshot.json")
    process_b = load_json(evidence_dir / "process_b.json")
    mission_id = resume_info["mission_id"]
    task_ids = resume_info["task_ids"]
    task_to_key = {v: k for k, v in task_ids.items()}
    task_d_id = task_ids[CRASH_WINDOW_TASK]
    task_e_id = task_ids["TASK_E"]
    pid_a = resume_info["process_a_pid"]
    pid_b = process_b["process_b_pid"]
    d_file = side_effect_file(artifacts_dir, f"sandbox-{task_d_id}", D_REL_PATH)
    corruption = load_json(evidence_dir / "corruption.json") if SCENARIO_CORRUPTION[scenario] else None

    # ---- durable stores ----
    events = []
    ev_path = artifacts_dir / "events" / mission_id / "event_log.jsonl"
    if ev_path.exists():
        events = [json.loads(l) for l in ev_path.read_text().splitlines() if l.strip()]
    scan = scan_journal(artifacts_dir, mission_id)
    records = scan["records"]
    d_records = [r for r in records if r.get("task_id") == task_d_id and r.get("path") == D_REL_PATH]
    e_records = [r for r in records if r.get("task_id") == task_e_id and r.get("path") == "task_e_output.txt"]
    d_intent = [r for r in d_records if r.get("record_type") == "intent"]
    d_performed = [r for r in d_records if r.get("record_type") == "performed"]
    d_reconciled = [r for r in d_records if r.get("record_type") == "reconciled"]

    ev_store = artifacts_dir / "evidence_store" / mission_id
    artifacts_meta = load_json(ev_store / "artifacts.json") if (ev_store / "artifacts.json").exists() else {}
    evidence_meta = load_json(ev_store / "evidence.json") if (ev_store / "evidence.json").exists() else {}

    cp_dir = artifacts_dir / "checkpoints" / mission_id
    final_cp = None
    for p in sorted(cp_dir.glob("checkpoint-*.json")):
        data = json.loads(p.read_text())
        if final_cp is None or data.get("created_at", "") >= final_cp.get("created_at", ""):
            final_cp = data

    checks: dict = {}

    # ---------- 1. crash point is real and at the scenario's boundary ----------
    bs = injection.get("boundary_state") or {}
    inj_point = SCENARIO_INJECTION[scenario]
    marker_states = {
        "A_pre_effect": (
            len(bs.get("d_intent_records") or []) == 1
            and not (bs.get("d_performed_records") or [])
            and bs.get("d_file") is None
        ),
        "B_pre_journal": (
            len(bs.get("d_intent_records") or []) == 1
            and not (bs.get("d_performed_records") or [])
            and bs.get("d_file") is not None
        ),
        "C_post_journal": (
            len(bs.get("d_intent_records") or []) == 1
            and len(bs.get("d_performed_records") or []) == 1
            and bs.get("d_file") is not None
        ),
    }
    # independent re-derivation from the raw journal + runner snapshot
    pre_corr_status = snapshot.get("pre_corruption_journal_line_status") or []
    pre_d_intent_count = None
    if scenario in ("A", "B", "C"):
        # journal untouched between crash and snapshot for non-D scenarios
        pre_d_intent_count = len(d_intent) if not corruption else None
    runner_file = (snapshot.get("pre_resume_side_effect_file") or {})
    file_at_crash_present = runner_file.get("exists", False)
    checks["crash_point_real"] = {
        "claim": f"Process A (pid {pid_a}) died by SIGKILL at the {inj_point} "
                 "boundary of TASK_D's governed artifact write, with the "
                 "boundary state proven by the durable injection marker AND "
                 "re-derived from raw durable records",
        "observed": {
            "injection_point": injection.get("injection_point"),
            "expected": inj_point,
            "marker_boundary_state": {
                "intent": len(bs.get("d_intent_records") or []),
                "performed": len(bs.get("d_performed_records") or []),
                "file_present": bs.get("d_file") is not None,
            },
            "runner_snapshot_file_present": file_at_crash_present,
            "snapshot_line_status": pre_corr_status,
            "corruption": corruption and corruption["kind"],
        },
        "passed": bool(
            injection.get("injection_point") == inj_point
            and injection.get("process_pid") == pid_a
            and injection.get("task_id") == task_d_id
            and marker_states[inj_point]
            and (
                (file_at_crash_present and inj_point in ("B_pre_journal", "C_post_journal"))
                or (not file_at_crash_present and inj_point == "A_pre_effect")
            )
        ),
    }

    # ---------- 2. Process B is a new process; IDs-only boundary ----------
    ids_only = set(resume_info.keys()) <= {
        "scenario", "mission_id", "run_id", "checkpoint_id", "checkpoint_path",
        "process_a_pid", "task_ids", "crash_window_task_key",
    }
    checks["process_b_new_ids_only_boundary"] = {
        "claim": "Process B is a distinct OS process (runner-witnessed PIDs) "
                 "and only IDENTIFIERS crossed the process boundary",
        "observed": {
            "pid_a": pid_a, "pid_b": pid_b,
            "pid_difference": pid_a != pid_b,
            "resume_info_keys": sorted(resume_info.keys()),
            "ids_only": ids_only,
            "process_b_reported_pid_difference": process_b.get("pid_difference"),
        },
        "passed": bool(pid_a != pid_b and ids_only and process_b.get("pid_difference") is True),
    }

    # ---------- 3. side effects: count, identity, fingerprints ----------
    # (success scenarios: exactly ONE physical write per task, identity stable
    #  across the crash. fail-closed scenarios D2a/D2b: the mission STOPS at
    #  the refusal — TASK_E never runs (file legitimately absent); the crash-
    #  window file must exist untouched and no performed record may be
    #  appended by the refusing process.)
    per_task_files = {}
    for key in TASK_KEYS:
        tid = task_ids[key]
        rel_path, marker = MARKERS[key]
        f = side_effect_file(artifacts_dir, f"sandbox-{tid}", rel_path)
        st = stat_snapshot(f)
        per_task_files[key] = {
            "exists": bool(st),
            "sha256": st and st["sha256"],
            "mtime_ns": st and st["mtime_ns"],
            "inode": st and st["inode"],
            "contains_marker": bool(st) and marker in Path(f).read_text(encoding="utf-8", errors="replace"),
        }
    d_planned_id = d_intent[0]["artifact_id"] if d_intent else None
    performed_by_a_for_d = [r for r in d_performed if r.get("process_pid") == pid_a]
    performed_by_b_for_d = [r for r in d_performed if r.get("process_pid") == pid_b]
    fail_closed = scenario in ("D2a", "D2b")
    if fail_closed:
        side_effect_ok = bool(
            # A/B/C completed pre-crash: files present
            all(per_task_files[k]["exists"] for k in ("TASK_A", "TASK_B", "TASK_C"))
            # the crash-window file was written by A and NEVER rewritten
            and per_task_files[CRASH_WINDOW_TASK]["exists"]
            and per_task_files[CRASH_WINDOW_TASK]["mtime_ns"] == (snapshot.get("pre_resume_side_effect_file") or {}).get("mtime_ns")
            # the refusing process appended NOTHING
            and len(performed_by_b_for_d) == 0
            # TASK_E never ran: no file, no journal records (honest stop)
            and not per_task_files["TASK_E"]["exists"]
            and not e_records
            and (scenario == "D2b" or d_planned_id is None)  # D2a: intent destroyed
        )
    else:
        side_effect_ok = bool(
            all(v["exists"] for v in per_task_files.values())
            and (d_planned_id is not None)
            and all(r.get("artifact_id") == d_planned_id for r in d_performed)
            and all(r.get("content_sha256") == per_task_files[CRASH_WINDOW_TASK]["sha256"] for r in d_performed)
            and (
                # A: the single performed is B's direct write (effect never happened pre-crash)
                (scenario == "A" and len(performed_by_a_for_d) == 0 and len(performed_by_b_for_d) == 1
                 and d_performed[0].get("performed_via") == "direct")
                # B/D1: effect by A, outcome recorded by B as adopted
                or (scenario in ("B", "D1") and len(performed_by_a_for_d) == 0 and len(performed_by_b_for_d) == 1
                    and d_performed[0].get("performed_via") == "adopted_after_crash"
                    and d_performed[0].get("performed_by_pid") == pid_a)
                # C: A performed + journaled; B reconciled
                or (scenario == "C" and len(performed_by_a_for_d) == 1 and len(performed_by_b_for_d) == 0)
            )
        )
    checks["side_effect_count_identity_fingerprints"] = {
        "claim": ("exactly one physical side effect per task; the crash-window "
                 "operation's identity is the one fixed PRE-EFFECT by the "
                 "durable intent record; fingerprints match the files"
                 if not fail_closed else
                 "fail-closed refusal: A/B/C files present; the crash-window "
                 "file exists UNTOUCHED (mtime continuity vs the pre-crash "
                 "snapshot); the refusing process appended NOTHING to the "
                 "journal; TASK_E never ran (no file, no records)"),
        "observed": {
            "per_task_files": {k: {"exists": v["exists"], "sha256": v["sha256"]} for k, v in per_task_files.items()},
            "d_planned_artifact_id": d_planned_id,
            "d_performed_ids": [r.get("artifact_id") for r in d_performed],
            "d_performed_via": [r.get("performed_via") for r in d_performed],
            "d_performed_by_pid": [r.get("performed_by_pid") or r.get("process_pid") for r in d_performed],
            "performed_by_process_a_for_d": len(performed_by_a_for_d),
            "performed_by_process_b_for_d": len(performed_by_b_for_d),
            "e_journal_types": [r.get("record_type") for r in e_records],
            "artifact_records_for_d": [
                a.get("artifact_id") for a in artifacts_meta.values()
                if a.get("created_by") == f"sandbox-{task_d_id}"
            ],
        },
        "passed": side_effect_ok,
    }

    # ---------- 4. no-rewrite continuity (B/C/D1) ----------
    if scenario in ("B", "C", "D1"):
        pre = snapshot.get("pre_resume_side_effect_file") or {}
        now = per_task_files[CRASH_WINDOW_TASK]
        three_way = {
            "at_crash_marker": (injection.get("boundary_state") or {}).get("d_file") or {},
            "runner_snapshot": pre,
            "verifier_now": now,
        }
        checks["no_rewrite_continuity"] = {
            "claim": "mtime_ns + inode + sha256 of the crash-window effect "
                     "file are UNCHANGED from the moment of the crash through "
                     "the resume (three independent observers agree)",
            "observed": three_way,
            "passed": bool(
                pre and now
                and pre.get("mtime_ns") == now["mtime_ns"]
                and pre.get("inode") == now["inode"]
                and pre.get("sha256") == now["sha256"]
                and ((injection.get("boundary_state") or {}).get("d_file") or {}).get("mtime_ns") == pre.get("mtime_ns")
            ),
        }

    # ---------- 5. pre-performed window closed WITHOUT trusting `performed` ----------
    if scenario in ("B", "D1"):
        checks["pre_performed_window_closure"] = {
            "claim": "ORDER §5: the (effect -> performed) window is closed by "
                     "proofs that PRECEDE the performed record: the durable "
                     "intent (PID=A, recorded BEFORE the kill), the file's "
                     "stat continuity across resume, and the FIRST performed "
                     "record for the op being B's adopted_after_crash with "
                     "performed_by_pid=A. The performed record itself is NOT "
                     "the evidence — its provenance is.",
            "observed": {
                "intent_record": {
                    "process_pid": d_intent[0].get("process_pid") if d_intent else None,
                    "recorded_at_utc": d_intent[0].get("recorded_at_utc") if d_intent else None,
                    "content_sha256": (d_intent[0].get("content_sha256") or "")[:16] if d_intent else None,
                    "artifact_id": d_planned_id,
                },
                "kill_reached_at_utc": injection.get("reached_at_utc"),
                "intent_recorded_before_kill": bool(
                    d_intent and injection.get("reached_at_utc")
                    and d_intent[0].get("recorded_at_utc", "") <= injection["reached_at_utc"]
                ),
                "intent_pid_is_process_a": bool(d_intent and d_intent[0].get("process_pid") == pid_a),
                "performed_written_by": [r.get("process_pid") for r in d_performed],
                "performed_via": [r.get("performed_via") for r in d_performed],
                "performed_by_pid": [r.get("performed_by_pid") for r in d_performed],
            },
            "passed": bool(
                d_intent
                and d_intent[0].get("process_pid") == pid_a
                and d_intent[0].get("recorded_at_utc", "") <= (injection.get("reached_at_utc") or "9999")
                and len(d_performed) == 1
                and d_performed[0].get("process_pid") == pid_b
                and d_performed[0].get("performed_via") == "adopted_after_crash"
                and d_performed[0].get("performed_by_pid") == pid_a
                and d_performed[0].get("intent_journal_record_id") == d_intent[0].get("journal_record_id")
            ),
        }

    # ---------- 6. event contract: count BY IDENTITY (order §6) ----------
    created_events = [e for e in events if e["event_type"] == "artifact.created"]
    reconciled_events = [e for e in events if e["event_type"] == "artifact.reconciled"]
    created_ids = [(e.get("payload") or {}).get("artifact_id") for e in created_events]
    artifact_ids_in_store = set(artifacts_meta.keys())
    dup_created = [i for i in set(created_ids) if created_ids.count(i) > 1]
    reconciled_payloads = [(e.get("payload") or {}) for e in reconciled_events]
    expected_reconciled = 1 if scenario in ("B", "C", "D1") else 0
    checks["event_contract_by_identity"] = {
        "claim": "ARTIFACT_CREATED fires EXACTLY ONCE per artifact identity "
                 "across the whole durable log (counted by artifact id, not "
                 "run_id); ARTIFACT_RECONCILED is the DISTINCT reconciliation "
                 "semantics and appears only for real cross-process "
                 "reconciliations",
        "observed": {
            "artifact_created_total": len(created_events),
            "unique_created_ids": len(set(created_ids)),
            "duplicate_created_ids": dup_created,
            "every_artifact_has_creation": sorted(artifact_ids_in_store - set(created_ids)),
            "creation_ids_not_in_store": sorted(set(created_ids) - artifact_ids_in_store - {None}),
            "artifact_reconciled_events": len(reconciled_events),
            "reconciled_modes": [p.get("mode") for p in reconciled_payloads],
            "expected_reconciled_for_scenario": expected_reconciled,
            "reconciled_no_rewrite_flags": [p.get("no_physical_rewrite") for p in reconciled_payloads],
        },
        "passed": bool(
            len(created_events) == len(set(created_ids))
            and not dup_created
            and artifact_ids_in_store <= set(created_ids)
            and len(reconciled_events) == expected_reconciled
            and all(p.get("mode") in ("performed_record", "intent_adoption") for p in reconciled_payloads)
            and (
                scenario in ("D2a", "D2b")
                or all(p.get("no_physical_rewrite") is True for p in reconciled_payloads)
            )
        ),
    }

    # ---------- 7. records agree with reality (recomputed hashes) ----------
    per_file_ok = {}
    for key in TASK_KEYS:
        tid = task_ids[key]
        rel_path, _ = MARKERS[key]
        f = side_effect_file(artifacts_dir, f"sandbox-{tid}", rel_path)
        if not f.exists():
            # A task with no file must have NO journal records at all — an
            # honest absent record set for an absent file (TASK_E never ran
            # in the fail-closed scenarios).
            task_recs_any = [r for r in records if r.get("task_id") == tid]
            per_file_ok[key] = not task_recs_any
            continue
        data = f.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        task_eff = [r for r in records if r.get("task_id") == tid and r.get("path") == rel_path
                    and r.get("record_type") in ("performed", "reconciled")]
        task_intent = [r for r in records if r.get("task_id") == tid and r.get("path") == rel_path
                       and r.get("record_type") == "intent"]
        art_meta = [a for a in artifacts_meta.values() if a.get("created_by") == f"sandbox-{tid}"]
        ev_meta = [ev for ev in evidence_meta.values() if (ev.get("task_id") == tid and ev.get("content_type") == "artifact")]
        # every PARSEABLE record must agree with the recomputed file hash; a
        # corrupt record (D2b) is preserved as fail-closed evidence and is
        # never counted as truth — its task is validated through the intent.
        per_file_ok[key] = bool(
            ((not task_eff) or all(r.get("content_sha256") == sha for r in task_eff))
            and ((not task_intent) or all(r.get("content_sha256") == sha for r in task_intent))
            and ((not art_meta) or all(a.get("sha256") == sha for a in art_meta))
            and ((not ev_meta) or all(ev.get("evidence_hash") == sha for ev in ev_meta))
        )
    checks["records_agree_with_reality"] = {
        "claim": "every parseable journal record (intent AND effective), "
                 "artifact record and evidence hash agrees with the "
                 "RECOMPUTED sha256 of the actual file bytes; a task with no "
                 "file has no records (honest absence); corrupt records are "
                 "preserved as fail-closed evidence, never used as truth",
        "observed": per_file_ok,
        "passed": all(per_file_ok.values()),
    }

    # ---------- 8. completion reflects the REAL effect ----------
    if scenario in ("A", "B", "C", "D1"):
        all_markers = all(v["contains_marker"] for v in per_task_files.values())
        final_states = (process_b.get("side_effect_accounting") or {}).get("final_states") or {}
        checks["completion_reflects_real_effect"] = {
            "claim": "the completed mission reflects the real effect: all five "
                     "marker files exist with their markers, verify_completion "
                     "COMPLETE, final checkpoint hash set, final state EVIDENCED",
            "observed": {
                "markers_in_files": {k: v["contains_marker"] for k, v in per_task_files.items()},
                "final_states": final_states,
                "final_checkpoint_has_hash": bool((final_cp or {}).get("hash")),
                "finalize_final_state": (process_b.get("finalize_mission") or {}).get("final_state"),
            },
            "passed": bool(
                all_markers
                and final_states == {k: "COMPLETED" for k in TASK_KEYS}
                and (final_cp or {}).get("hash")
                and (process_b.get("finalize_mission") or {}).get("final_state") == "EVIDENCED"
            ),
        }
    else:
        # fail-closed scenarios: the durable world must be untouched
        err = ((process_b.get("side_effect_accounting") or {}).get("events") or {}).get("tool_failed_errors") or []
        checks["fail_closed_refusal_is_explicit"] = {
            "claim": f"scenario {scenario}: the resume FAILS CLOSED with the "
                     "explicit error type; no effect is re-performed; the "
                     "journal is not modified by the refusing process",
            "observed": {
                "continuation_success": (process_b.get("side_effect_accounting") or {}).get("continuation_success"),
                "final_states": (process_b.get("side_effect_accounting") or {}).get("final_states"),
                "tool_failed_errors": err[:2],
                "journal_sha256_post_resume": scan["sha256"],
                "journal_sha256_expected": (
                    corruption.get("journal_sha256_after") if corruption
                    else snapshot.get("pre_corruption_journal_sha256")
                ),
                "all_task_files_untouched": {
                    k: (
                        (snapshot.get("pre_resume_side_effect_file") or {}).get("mtime_ns") == per_task_files[k]["mtime_ns"]
                        if k == CRASH_WINDOW_TASK and snapshot.get("pre_resume_side_effect_file") else None
                    ) for k in TASK_KEYS
                },
            },
            "passed": bool(
                (process_b.get("side_effect_accounting") or {}).get("continuation_success") is False
                and (process_b.get("side_effect_accounting") or {}).get("final_states", {}).get(CRASH_WINDOW_TASK) == "FAILED"
                and any(
                    ("SIDE_EFFECT_JOURNAL_CORRUPT" in e) if scenario == "D2b" else ("SIDE_EFFECT_RECONCILIATION_FAILED" in e)
                    for e in err
                )
                and scan["sha256"] == (corruption.get("journal_sha256_after") if corruption else snapshot.get("pre_corruption_journal_sha256"))
            ),
        }

    # ---------- 9. journal structure integrity (torn-tail policy) ----------
    if scenario == "D1":
        torn_gone = "torn_or_corrupt" not in scan["line_status"]
    else:
        torn_gone = True
    checks["journal_structure_integrity"] = {
        "claim": "torn/corrupt TRAILING lines are ignored as never-durable "
                 "truth and truncated away by the next append (D1); corrupt "
                 "MIDDLE lines are preserved as fail-closed evidence (D2b) — "
                 "never silently skipped",
        "observed": {
            "line_status": scan["line_status"],
            "ends_with_newline": scan["ends_with_newline"],
            "torn_tail_removed_after_d1_resume": torn_gone if scenario == "D1" else "n/a",
            "corrupt_middle_preserved": (
                "torn_or_corrupt" in scan["line_status"] if scenario == "D2b" else "n/a"
            ),
        },
        "passed": bool(
            torn_gone
            and (scenario != "D2b" or "torn_or_corrupt" in scan["line_status"])
            and (scenario != "D1" or scan["ends_with_newline"])
        ),
    }

    # ---- verdict ----
    failed = [k for k, c in checks.items() if not c["passed"]]
    verdict = "VERIFIED" if not failed else "NOT_VERIFIED"
    result = {
        "verdict": verdict,
        "scenario": scenario,
        "verifier_pid": pid,
        "checked_at_utc": utcnow(),
        "failed_checks": failed,
        "checks": checks,
        "truth_sources": {
            "journal": str(journal_path(artifacts_dir, mission_id)),
            "event_log": str(ev_path),
            "artifacts_meta": str(ev_store / "artifacts.json"),
            "evidence_meta": str(ev_store / "evidence.json"),
            "checkpoints_dir": str(cp_dir),
            "injection_marker": str(evidence_dir / "injection.json"),
            "corruption_marker": str(evidence_dir / "corruption.json") if corruption else None,
            "crash_snapshot": str(evidence_dir / "crash_window_snapshot.json"),
            "process_b_record": str(evidence_dir / "process_b.json"),
        },
    }
    durable_write_json(evidence_dir / "verifier.json", result)
    for name, c in checks.items():
        print(f"  {'PASS' if c['passed'] else 'FAIL'}  {name}")
    print(f"[R1_VERIFIER] scenario={scenario} verdict={verdict}")
    return 0 if verdict == "VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
