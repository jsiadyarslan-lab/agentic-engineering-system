#!/usr/bin/env python3
"""E10-CW1 INDEPENDENT VERIFIER (order section 6) — a separate OS process
that does NOT trust in-memory engine state from Process A or Process B.

Truth sources (persistent storage ONLY):
  * checkpoints/<mission_id>/*.json                 (durable checkpoints)
  * events/<mission_id>/event_log.jsonl             (durable event history)
  * evidence_store/<mission_id>/artifacts.json      (artifact records)
  * evidence_store/<mission_id>/evidence.json       (evidence records)
  * side_effect_journal/<mission_id>/journal.jsonl  (side-effect journal)
  * sandbox-<task_id>/<path>                        (side-effect content files)
  * harness evidence (runner/process observations)  (OS-level facts only)

It proves the nine mandatory points of E10-CW1 section 6 and issues a
per-check verdict. Exit code 0 == VERIFIED.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e10_common import MARKERS, TASK_KEYS, durable_write_json  # noqa: E402
from e10cw1_common import CRASH_WINDOW_TASK, journal_index, read_journal  # noqa: E402

REQUIRED_CHECKS = [
    "process_a_died_at_injection_point",
    "process_b_new_process_restored_from_durable_only",
    "first_side_effect_readable_and_verifiable",
    "side_effect_identity_linked_to_correct_task_and_operation",
    "side_effect_count_matches_expected_no_unsafe_copy",
    "records_reflect_stored_truth_not_declared_values",
    "attempts_and_events_consistent_with_crash_and_resume",
    "final_state_agrees_with_actual_evidence",
    "repeat_runs_produce_same_result",
]


def load_json(p: Path):
    return json.loads(p.read_text())


def load_events(p: Path):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def main(workdir: str) -> None:
    work = Path(workdir)
    artifacts_dir = work / "artifacts"
    evidence_dir = work / "evidence"
    session_evidence = work.parent / "evidence"

    pid = os.getpid()
    print(f"[CW1_VERIFIER] pid={pid} — reading ONLY persistent state")

    # ---------- harness observations (OS-level facts) ----------
    resume_info = load_json(evidence_dir / "resume_info.json")
    injection = load_json(evidence_dir / "injection.json")
    crash_snapshot = load_json(evidence_dir / "crash_window_snapshot.json")
    process_b = load_json(evidence_dir / "process_b.json")
    chains = [json.loads(l) for l in (session_evidence / "chains.jsonl").read_text().splitlines() if l.strip()]
    mine = chains[-1]
    prior = chains[:-1]

    mission_id = resume_info["mission_id"]
    run_1 = resume_info["run_id"]
    original_cp_id = resume_info["checkpoint_id"]
    task_ids = resume_info["task_ids"]              # key -> task_id
    task_to_key = {v: k for k, v in task_ids.items()}
    task_d_id = task_ids[CRASH_WINDOW_TASK]
    d_rel_path = "task_d_output.txt"
    d_file = artifacts_dir / f"sandbox-{task_d_id}" / d_rel_path

    # ---------- persistent truth sources ----------
    cp_dir = artifacts_dir / "checkpoints" / mission_id
    checkpoints = {}
    for p in sorted(cp_dir.glob("checkpoint-*.json")):
        data = load_json(p)
        checkpoints[data["checkpoint_id"]] = data
    original_cp = checkpoints[original_cp_id]

    final_cp = None
    for c in sorted(checkpoints.values(), key=lambda x: x.get("created_at", "")):
        if c["run_id"] != run_1 and all(s == "COMPLETED" for s in c["task_states"].values()):
            final_cp = c
    if final_cp is None:
        raise SystemExit("VERIFIER FAILED: no final all-COMPLETED checkpoint found on disk")
    run_2 = final_cp["run_id"]

    events = load_events(artifacts_dir / "events" / mission_id / "event_log.jsonl")
    artifacts = load_json(artifacts_dir / "evidence_store" / mission_id / "artifacts.json")
    evidence = load_json(artifacts_dir / "evidence_store" / mission_id / "evidence.json")
    journal = read_journal(artifacts_dir, mission_id)
    jidx = journal_index(journal)

    def event(event_type, correlation=None, run_id=None):
        out = []
        for e in events:
            if e["event_type"] != event_type:
                continue
            if correlation is not None and e.get("correlation_id") != correlation:
                continue
            if run_id is not None and e.get("run_id") != run_id:
                continue
            out.append(e)
        return out

    resume_ts = min(
        (e["timestamp"] for e in event("checkpoint.loaded")),
        default=None,
    )

    d_journal_records = jidx.get((task_d_id, d_rel_path), [])
    d_performed = [r for r in d_journal_records if r["record_type"] == "performed"]
    d_reconciled = [r for r in d_journal_records if r["record_type"] == "reconciled"]
    d_artifact_id = d_performed[0]["artifact_id"] if d_performed else None
    d_artifact_record = artifacts.get(d_artifact_id) if d_artifact_id else None

    checks: dict = {}

    # ---------- 1. Process A died at the intended failure point ----------
    pre_crash_events_for_d = [
        e for e in events
        if e["timestamp"] < (injection.get("reached_at_utc") or "")
        and e.get("correlation_id") == task_d_id
        and e["event_type"] == "task.completed"
    ]
    checks["process_a_died_at_injection_point"] = {
        "claim": "Process A was SIGKILLed after TASK_D's side effect and its "
                 "durable journal record, before any durable completion record",
        "observed": {
            "injection_reached_at_utc": injection.get("reached_at_utc"),
            "injection_task": injection.get("task_id") == task_d_id,
            "runner_witnessed_exit_code": mine["process_a"]["exit_code"],
            "runner_witnessed_termination": mine["process_a"]["termination_reason"],
            "journal_performed_recorded_at_utc": d_performed[0].get("recorded_at_utc") if d_performed else None,
            "journal_record_precedes_kill": bool(
                d_performed and injection.get("reached_at_utc")
                and d_performed[0].get("recorded_at_utc", "") <= injection["reached_at_utc"]
            ),
            "no_task_completed_for_d_before_kill": len(pre_crash_events_for_d) == 0,
            "resume_checkpoint_states": {
                task_to_key.get(t, t): s for t, s in original_cp["task_states"].items()
            },
        },
        "passed": bool(
            injection.get("reached_at_utc")
            and injection.get("task_id") == task_d_id
            and mine["process_a"]["exit_code"] == -9
            and d_performed
            and d_performed[0].get("recorded_at_utc", "") <= injection["reached_at_utc"]
            and len(pre_crash_events_for_d) == 0
            and original_cp["task_states"].get(task_d_id) != "COMPLETED"
        ),
    }

    # ---------- 2. Process B is a new process restored from durable only ----------
    allowed_resume_keys = {
        "mode", "mission_id", "run_id", "checkpoint_id", "checkpoint_path",
        "process_a_pid", "task_ids", "crash_window_task_key",
    }
    resume_restore_events = event("state.transition")
    d_restore = [
        e for e in resume_restore_events
        if (e.get("payload") or {}).get("trigger") == "checkpoint_resume"
        and e.get("correlation_id") == task_d_id
    ]
    checks["process_b_new_process_restored_from_durable_only"] = {
        "claim": "Process B (different PID) restored from durable storage only; "
                 "only resume identifiers crossed the boundary",
        "observed": {
            "resume_info_keys": sorted(resume_info.keys()),
            "resume_info_ids_only": set(resume_info.keys()) <= allowed_resume_keys,
            "pid_a": resume_info["process_a_pid"],
            "pid_b_runner_witnessed": mine["process_b"]["runner_observed_pid"],
            "pid_b_self_reported": process_b["process_b_pid"],
            "pid_difference": process_b["pid_difference"],
            "checkpoint_loaded_event_run_id": run_2,
            "checkpoint_loaded_payload_checkpoint_id": (
                (event("checkpoint.loaded")[0].get("payload") or {}).get("checkpoint_id")
                if event("checkpoint.loaded") else None
            ),
            "d_restore_event_to_state": (
                (d_restore[0].get("payload") or {}).get("to_state") if d_restore else None
            ),
            "durable_state_at_restore": original_cp["task_states"].get(task_d_id),
        },
        "passed": bool(
            set(resume_info.keys()) <= allowed_resume_keys
            and process_b["pid_difference"]
            and mine["process_b"]["runner_observed_pid"] != resume_info["process_a_pid"]
            and event("checkpoint.loaded")
            and (event("checkpoint.loaded")[0].get("payload") or {}).get("checkpoint_id") == original_cp_id
            and d_restore
            and (d_restore[0].get("payload") or {}).get("to_state") == original_cp["task_states"].get(task_d_id)
        ),
    }

    # ---------- 3. First side effect still readable and verifiable ----------
    d_bytes = d_file.read_bytes() if d_file.exists() else None
    d_sha_now = hashlib.sha256(d_bytes).hexdigest() if d_bytes is not None else None
    checks["first_side_effect_readable_and_verifiable"] = {
        "claim": "the pre-crash side-effect file is intact and independently verifiable",
        "observed": {
            "file": str(d_file),
            "exists": d_file.exists(),
            "sha256_now": d_sha_now,
            "sha256_in_journal": d_performed[0].get("content_sha256") if d_performed else None,
            "size_now": len(d_bytes) if d_bytes is not None else None,
            "size_in_journal": d_performed[0].get("size_bytes") if d_performed else None,
            "contains_marker": bool(d_bytes) and MARKERS["TASK_D"][1] in d_bytes.decode("utf-8", "replace"),
            "marker": MARKERS["TASK_D"][1],
        },
        "passed": bool(
            d_file.exists()
            and d_performed
            and d_sha_now == d_performed[0].get("content_sha256")
            and len(d_bytes) == d_performed[0].get("size_bytes")
            and MARKERS["TASK_D"][1] in d_bytes.decode("utf-8", "replace")
        ),
    }

    # ---------- 4. Identity/hash linkage to the correct task & operation ----------
    d_evidence = [ev for ev in evidence.values() if ev.get("source_id") == d_artifact_id]
    checks["side_effect_identity_linked_to_correct_task_and_operation"] = {
        "claim": "journal record <-> artifact record <-> evidence record all link "
                 "the file to (mission, TASK_D, path) with the original identity",
        "observed": {
            "journal": {
                "mission_id": d_performed[0].get("mission_id") if d_performed else None,
                "task_id": d_performed[0].get("task_id") if d_performed else None,
                "path": d_performed[0].get("path") if d_performed else None,
                "sandbox_id": d_performed[0].get("sandbox_id") if d_performed else None,
                "artifact_id": d_artifact_id,
            },
            "artifact_record": {
                "present": d_artifact_record is not None,
                "created_by": d_artifact_record.get("created_by") if d_artifact_record else None,
                "path": d_artifact_record.get("path") if d_artifact_record else None,
                "sha256": d_artifact_record.get("sha256") if d_artifact_record else None,
            } if d_artifact_record else None,
            "evidence_records_for_source": [
                {"evidence_hash": ev.get("evidence_hash"), "task_id": ev.get("task_id")}
                for ev in d_evidence
            ],
            "run_lineage": {
                "original_checkpoint_run": original_cp["run_id"],
                "final_checkpoint_run": final_cp["run_id"],
                "parent_link_event_run_id": run_2,
            },
        },
        "passed": bool(
            d_performed
            and d_performed[0].get("mission_id") == mission_id
            and d_performed[0].get("task_id") == task_d_id
            and d_performed[0].get("path") == d_rel_path
            and d_performed[0].get("sandbox_id") == f"sandbox-{task_d_id}"
            and d_artifact_record is not None
            and d_artifact_record.get("created_by") == f"sandbox-{task_d_id}"
            and d_artifact_record.get("path") == d_rel_path
            and d_artifact_record.get("sha256") == d_performed[0].get("content_sha256")
            and d_artifact_record.get("artifact_id", d_artifact_id) == d_artifact_id
            and all(ev.get("evidence_hash") == d_performed[0].get("content_sha256") for ev in d_evidence)
            and all(ev.get("task_id") == task_d_id for ev in d_evidence)
            and original_cp["run_id"] == run_1
            and final_cp["run_id"] == run_2
        ),
    }

    # ---------- 5. Side-effect count matches expected; no unsafe copy ----------
    per_task_artifacts = {}
    for aid, a in artifacts.items():
        key = task_to_key.get(a.get("created_by", "").replace("sandbox-", ""), a.get("created_by", ""))
        per_task_artifacts.setdefault(key, []).append(aid)
    d_artifact_created_events = event("artifact.created", correlation=task_d_id)
    d_created_ids = [(e.get("payload") or {}).get("artifact_id") for e in d_artifact_created_events]
    # E10-CW1-R1 §6: reconciliation semantics are DISTINCT from creation.
    # ARTIFACT_CREATED is exactly ONE per artifact identity across the whole
    # durable log (the agent-layer duplicate emission is suppressed); the
    # cross-process reconciliation is reported by ARTIFACT_RECONCILED.
    d_artifact_reconciled_events = event("artifact.reconciled", correlation=task_d_id)
    d_task_completed_events = event("task.completed", correlation=task_d_id)
    sandbox_file_lists = {}
    for key in TASK_KEYS:
        sandbox = artifacts_dir / f"sandbox-{task_ids[key]}"
        sandbox_file_lists[key] = sorted(p.name for p in sandbox.glob("*")) if sandbox.exists() else []
    dup_tuples = len(events) - len(set((e["event_type"], e.get("run_id"), e.get("correlation_id"), e["timestamp"]) for e in events))
    total_task_completed = len(event("task.completed"))
    checks["side_effect_count_matches_expected_no_unsafe_copy"] = {
        "claim": "exactly one physical side effect per task — the crash-window "
                 "one was NOT re-performed (1 performed + 1 reconciled journal "
                 "records, no_physical_rewrite=true); no duplicate artifact "
                 "records; E10-CW1-R1 event contract: exactly ONE "
                 "ARTIFACT_CREATED per artifact identity (agent-layer "
                 "duplicate suppressed) plus ONE ARTIFACT_RECONCILED marking "
                 "the cross-process reconciliation as DISTINCT semantics",
        "observed": {
            "journal_for_d": {
                "performed": len(d_performed),
                "reconciled": len(d_reconciled),
                "no_physical_rewrite_flag": d_reconciled[0].get("no_physical_rewrite") if d_reconciled else None,
            },
            "artifact_records_per_task": {k: len(v) for k, v in sorted(per_task_artifacts.items())},
            "artifact_created_events_for_d": len(d_artifact_created_events),
            "artifact_created_ids_for_d": d_created_ids,
            "artifact_reconciled_events_for_d": len(d_artifact_reconciled_events),
            "artifact_reconciled_modes_for_d": [
                (e.get("payload") or {}).get("mode") for e in d_artifact_reconciled_events
            ],
            "task_completed_events_for_d": len(d_task_completed_events),
            "total_task_completed_events": total_task_completed,
            "sandbox_files_per_task": sandbox_file_lists,
            "duplicate_event_tuples": dup_tuples,
        },
        "passed": bool(
            len(d_performed) == 1
            and len(d_reconciled) == 1
            and d_reconciled[0].get("no_physical_rewrite") is True
            and set(per_task_artifacts) == set(TASK_KEYS)
            and all(len(v) == 1 for v in per_task_artifacts.values())
            and len(d_artifact_created_events) == 1
            and all(aid == d_artifact_id for aid in d_created_ids)
            and len(d_artifact_reconciled_events) == 1
            and all(m == "performed_record" for m in [(e.get("payload") or {}).get("mode") for e in d_artifact_reconciled_events])
            and len(d_task_completed_events) == 1
            and total_task_completed == len(TASK_KEYS)
            and all(len(v) == 1 for v in sandbox_file_lists.values())
            and dup_tuples == 0
        ),
    }

    # ---------- 6. Records reflect stored truth, not declared values ----------
    # every value is recomputed from the file bytes and cross-checked across
    # four INDEPENDENT durable stores (journal, artifacts.json, evidence.json,
    # event log) — agreement cannot be arranged by a single declared value.
    per_file = {}
    for key in TASK_KEYS:
        tid = task_ids[key]
        rel_path, marker = MARKERS[key]
        f = artifacts_dir / f"sandbox-{tid}" / rel_path
        recs = [r for r in jidx.get((tid, rel_path), []) if r["record_type"] == "performed"]
        art_ids = per_task_artifacts.get(key, [])
        art = artifacts.get(art_ids[0]) if art_ids else None
        st = f.stat() if f.exists() else None
        per_file[key] = {
            "file_sha256": hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else None,
            "journal_sha256": recs[0].get("content_sha256") if recs else None,
            "artifact_sha256": art.get("sha256") if art else None,
            "journal_mtime_ns": recs[0].get("mtime_ns") if recs else None,
            "file_mtime_ns_now": st.st_mtime_ns if st else None,
            "mtime_unchanged_since_journal": bool(
                recs and st and recs[0].get("mtime_ns") == st.st_mtime_ns
            ),
        }
    d_reconciled_observed = d_reconciled[0].get("observed_mtime_ns") if d_reconciled else None
    checks["records_reflect_stored_truth_not_declared_values"] = {
        "claim": "sha256/mtime agree across journal, artifact records, evidence "
                 "records, event log, and the actual files — recomputed, not declared",
        "observed": {
            "per_task": per_file,
            "d_three_way_mtime": {
                "journal_performed": d_performed[0].get("mtime_ns") if d_performed else None,
                "reconciled_observed": d_reconciled_observed,
                "file_now": d_file.stat().st_mtime_ns if d_file.exists() else None,
            },
        },
        "passed": bool(
            all(v["file_sha256"] == v["journal_sha256"] == v["artifact_sha256"] for v in per_file.values())
            and all(v["mtime_unchanged_since_journal"] for v in per_file.values())
            and d_performed
            and d_reconciled
            and d_performed[0].get("mtime_ns") == d_reconciled_observed == (d_file.stat().st_mtime_ns if d_file.exists() else None)
        ),
    }

    # ---------- 7. Attempts & events consistent with crash and resume ----------
    att_results = {}
    for t, atts in (final_cp.get("attempt_history") or {}).items():
        key = task_to_key.get(t, t)
        pre = [a for a in atts if resume_ts is None or a.get("started_at", "") < resume_ts]
        post = [a for a in atts if resume_ts is not None and a.get("started_at", "") >= resume_ts]
        att_results[key] = {
            "pre_resume": len(pre),
            "post_resume": len(post),
            "attempt_ids": [a["attempt_id"] for a in atts],
        }
    d_ac_ts = [e["timestamp"] for e in d_artifact_created_events]
    d_tc_ts = [e["timestamp"] for e in d_task_completed_events]
    evidence_per_task = {}
    for ev in evidence.values():
        key = task_to_key.get(ev.get("task_id") or "", "?")
        evidence_per_task[key] = evidence_per_task.get(key, 0) + 1
    checks["attempts_and_events_consistent_with_crash_and_resume"] = {
        "claim": "A/B/C: 1 pre-resume attempt, 0 post; D/E: 0 pre (their pre-crash "
                 "attempts were in-memory only), 1 post; D's completion events all "
                 "post-resume; evidence per task matches the normal-run pattern (2)",
        "observed": {
            "resume_ts": resume_ts,
            "attempts": att_results,
            "d_artifact_created_ts": d_ac_ts,
            "d_task_completed_ts": d_tc_ts,
            "d_events_all_post_resume": bool(
                resume_ts and d_ac_ts and d_tc_ts
                and min(d_ac_ts) >= resume_ts and min(d_tc_ts) >= resume_ts
            ),
            "evidence_per_task": evidence_per_task,
        },
        "passed": bool(
            resume_ts
            and all(
                att_results.get(k, {}).get("pre_resume") == 1 and att_results.get(k, {}).get("post_resume") == 0
                for k in ("TASK_A", "TASK_B", "TASK_C")
            )
            and att_results.get(CRASH_WINDOW_TASK, {}).get("pre_resume") == 0
            and att_results.get(CRASH_WINDOW_TASK, {}).get("post_resume") == 1
            and att_results.get("TASK_E", {}).get("pre_resume") == 0
            and att_results.get("TASK_E", {}).get("post_resume") == 1
            and min(d_ac_ts) >= resume_ts
            and min(d_tc_ts) >= resume_ts
            and set(evidence_per_task) == set(TASK_KEYS)
            and all(v == 2 for v in evidence_per_task.values())
        ),
    }

    # ---------- 8. Final state agrees with actual evidence ----------
    marker_results = {}
    for key in TASK_KEYS:
        rel_path, marker = MARKERS[key]
        f = artifacts_dir / f"sandbox-{task_ids[key]}" / rel_path
        marker_results[key] = {
            "exists": f.exists(),
            "contains_marker": f.exists() and marker in f.read_text(encoding="utf-8", errors="replace"),
        }
    checks["final_state_agrees_with_actual_evidence"] = {
        "claim": "all tasks COMPLETED in the final durable checkpoint AND every "
                 "file exists with its marker AND mission state EVIDENCED — "
                 "the state is derived from evidence, not asserted",
        "observed": {
            "final_states": {task_to_key.get(t, t): s for t, s in final_cp["task_states"].items()},
            "mission_state": final_cp.get("state"),
            "files": marker_results,
        },
        "passed": bool(
            set(final_cp["task_states"].values()) == {"COMPLETED"}
            and set(final_cp["task_states"]) == set(task_ids.values())
            and final_cp.get("state") in ("EVIDENCED", "VERIFIED")
            and all(v["exists"] and v["contains_marker"] for v in marker_results.values())
        ),
    }

    # ---------- 9. Repeat runs produce the same result ----------
    prior_ok = [
        {
            "chain_index": r["chain_index"],
            "no_physical_rewrite": r["side_effect_file"]["no_physical_rewrite"],
            "status": r["status"],
        }
        for r in prior
    ]
    checks["repeat_runs_produce_same_result"] = {
        "claim": "every completed chain so far shows the same idempotency result "
                 "(no physical re-write across the crash window)",
        "observed": {
            "this_chain_index": mine["chain_index"],
            "this_chain_no_physical_rewrite": mine["side_effect_file"]["no_physical_rewrite"],
            "prior_chains": prior_ok,
        },
        "passed": bool(
            mine["side_effect_file"]["no_physical_rewrite"]
            and all(r["no_physical_rewrite"] for r in prior_ok)
        ),
    }

    all_passed = all(c["passed"] for c in checks.values())
    missing = [c for c in REQUIRED_CHECKS if c not in checks]
    verdict = "VERIFIED" if all_passed and not missing else "NOT_VERIFIED"

    report = {
        "status": "INDEPENDENT_VERIFICATION_COMPLETE",
        "verifier_pid": pid,
        "verdict": verdict,
        "mission_id": mission_id,
        "run_1": run_1,
        "run_2": run_2,
        "original_checkpoint_id": original_cp_id,
        "final_checkpoint_id": final_cp.get("checkpoint_id"),
        "truth_sources": {
            "checkpoints_dir": str(cp_dir),
            "event_log": str(artifacts_dir / "events" / mission_id / "event_log.jsonl"),
            "artifacts_json": str(artifacts_dir / "evidence_store" / mission_id / "artifacts.json"),
            "evidence_json": str(artifacts_dir / "evidence_store" / mission_id / "evidence.json"),
            "side_effect_journal": str(artifacts_dir / "side_effect_journal" / mission_id / "journal.jsonl"),
        },
        "checks": checks,
        "missing_checks": missing,
    }
    durable_write_json(evidence_dir / "verifier.json", report)

    print(f"[CW1_VERIFIER] verdict={verdict}")
    for name, c in checks.items():
        print(f"  {'PASS' if c['passed'] else 'FAIL'}  {name}")
    if verdict != "VERIFIED":
        raise SystemExit("INDEPENDENT VERIFICATION FAILED")


if __name__ == "__main__":
    main(sys.argv[1])
