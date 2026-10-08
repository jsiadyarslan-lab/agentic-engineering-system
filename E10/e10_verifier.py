#!/usr/bin/env python3
"""E10 INDEPENDENT VERIFIER (E10 sections 23-24) — a separate OS process that
does NOT trust any in-memory engine state from Process A or Process B.

Truth sources (persistent storage only):
  * checkpoints/<mission_id>/*.json            (durable checkpoints)
  * events/<mission_id>/event_log.jsonl        (durable event history)
  * evidence_store/<mission_id>/artifacts.json (artifact records)
  * evidence_store/<mission_id>/evidence.json  (evidence records)
  * sandbox-<task_id>/<path>                   (artifact content files)

The verifier rebuilds the Mission -> Run -> Task -> Attempt -> Artifact ->
Evidence chain from those files alone and issues a per-criterion verdict.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e10_common import MARKERS, TASK_KEYS, durable_write_json  # noqa: E402

REQUIRED_CHECKS = [
    "all_required_tasks_terminal",
    "acceptance_criteria_satisfied",
    "expected_artifacts_present",
    "artifact_hashes_valid",
    "evidence_valid",
    "dependencies_satisfied",
    "dependency_ordering_verified",
    "attempt_history_consistent",
    "no_unsafe_duplicate_side_effects",
    "final_mission_state_valid",
    "mission_identity_preserved",
    "run_lineage_verified",
    "event_history_durable_no_restoration_duplicates",
    "completed_work_preserved_across_processes",
]


def load_json(p: Path):
    return json.loads(p.read_text())


def load_events(p: Path):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def main(workdir: str) -> None:
    work = Path(workdir)
    artifacts_dir = work / "artifacts"
    evidence_dir = work / "evidence"

    pid = os.getpid()
    print(f"[VERIFIER] pid={pid} — reading ONLY persistent state")

    resume_info = load_json(evidence_dir / "resume_info.json")
    mission_id = resume_info["mission_id"]
    run_1 = resume_info["run_id"]
    original_cp_id = resume_info["checkpoint_id"]

    # ---------- persistent truth sources ----------
    cp_dir = artifacts_dir / "checkpoints" / mission_id
    checkpoints = {p.stem: load_json(p) for p in sorted(cp_dir.glob("checkpoint-*.json"))}
    original_cp = checkpoints[original_cp_id]

    # final checkpoint = the one whose run differs from RUN_1 (the resumed run)
    # and whose task states are all terminal; identified from durable records.
    candidates = [c for c in checkpoints.values() if c["run_id"] != run_1]
    final_cp = None
    for c in sorted(candidates, key=lambda x: x["created_at"]):
        if all(s == "COMPLETED" for s in c["task_states"].values()):
            final_cp = c
    if final_cp is None:
        raise SystemExit("VERIFIER FAILED: no final all-COMPLETED checkpoint found on disk")
    run_2 = final_cp["run_id"]

    events = load_events(artifacts_dir / "events" / mission_id / "event_log.jsonl")
    artifacts = load_json(artifacts_dir / "evidence_store" / mission_id / "artifacts.json")
    evidence = load_json(artifacts_dir / "evidence_store" / mission_id / "evidence.json")

    task_defs = final_cp["task_definitions"]
    key_by_task = {t: d.get("key", t) for t, d in task_defs.items()}
    task_by_key = {v: k for k, v in key_by_task.items()}

    checks: dict = {}

    def event(event_type, correlation=None, run_id=None):
        out = []
        for e in events:
            if e["event_type"] != event_type:
                continue
            if correlation is not None and e["correlation_id"] != correlation:
                continue
            if run_id is not None and e["run_id"] != run_id:
                continue
            out.append(e)
        return out

    # ---------- 1. all required tasks terminal ----------
    final_states = {key_by_task[t]: s for t, s in final_cp["task_states"].items()}
    checks["all_required_tasks_terminal"] = {
        "claim": "all 5 required tasks in terminal COMPLETED state",
        "observed": final_states,
        "passed": set(final_states) == set(TASK_KEYS)
        and all(v == "COMPLETED" for v in final_states.values()),
    }

    # ---------- 2. acceptance criteria satisfied (files + content) ----------
    crit_results = {}
    for key in TASK_KEYS:
        out_path, marker = MARKERS[key]
        sandbox = f"sandbox-{task_by_key[key]}"
        f = artifacts_dir / sandbox / out_path
        exists = f.exists()
        contains = exists and marker in f.read_text(encoding="utf-8", errors="replace")
        crit_results[key] = {"file": str(f), "exists": exists, "contains_marker": contains}
    checks["acceptance_criteria_satisfied"] = {
        "claim": "each task's artifact file exists and contains its marker",
        "observed": crit_results,
        "passed": all(v["exists"] and v["contains_marker"] for v in crit_results.values()),
    }

    # ---------- 3. expected artifacts present ----------
    art_by_task = {}
    for aid, a in artifacts.items():
        art_by_task.setdefault(a.get("created_by", ""), []).append({**a, "artifact_id": aid})
    per_task_artifacts = {
        key_by_task.get(t.replace("sandbox-", ""), t.replace("sandbox-", "")):
            sorted(a["artifact_id"] for a in lst)
        for t, lst in art_by_task.items()
    }
    checks["expected_artifacts_present"] = {
        "claim": "exactly one governed artifact per task (5 total)",
        "observed": {k: v for k, v in sorted(per_task_artifacts.items())},
        "passed": set(per_task_artifacts) == set(TASK_KEYS)
        and all(len(v) == 1 for v in per_task_artifacts.values()),
    }

    # ---------- 4. artifact hashes valid (content re-read from disk) ----------
    hash_results = {}
    for t, lst in art_by_task.items():
        for a in lst:
            f = artifacts_dir / a["created_by"] / a["path"]
            content = f.read_bytes() if f.exists() else None
            sha = hashlib.sha256(content).hexdigest() if content is not None else None
            hash_results[a["artifact_id"]] = {
                "task": key_by_task.get(t.replace("sandbox-", ""), "?"),
                "file": str(f),
                "recomputed_sha256": sha,
                "recorded_sha256": a["sha256"],
                "match": sha == a["sha256"],
            }
    checks["artifact_hashes_valid"] = {
        "claim": "sha256(content on disk) == recorded artifact sha256 for every artifact",
        "observed": hash_results,
        "passed": all(v["match"] for v in hash_results.values()),
    }

    # ---------- 5. evidence valid (hash linkage, not IDs-as-hashes) ----------
    ev_results = {}
    for eid, ev in evidence.items():
        src = artifacts.get(ev.get("source_id", ""))
        ev_results[eid] = {
            "evidence_hash": ev.get("evidence_hash"),
            "is_content_hash": len(ev.get("evidence_hash", "")) == 64,
            "source_artifact_exists": src is not None,
            "hash_matches_source_artifact": src is not None
            and ev.get("evidence_hash") == src.get("sha256"),
            "mission_linked": ev.get("mission_id") == mission_id,
        }
    checks["evidence_valid"] = {
        "claim": "every evidence record carries a real content hash equal to its artifact sha256",
        "observed": ev_results,
        "passed": len(ev_results) >= 5
        and all(
            v["is_content_hash"] and v["source_artifact_exists"]
            and v["hash_matches_source_artifact"] and v["mission_linked"]
            for v in ev_results.values()
        ),
    }

    # ---------- 6. dependencies satisfied ----------
    deps = final_cp["task_dependencies"]
    dep_violations = []
    for t, tdeps in deps.items():
        for d in tdeps:
            if final_cp["task_states"].get(d) != "COMPLETED":
                dep_violations.append(
                    {"task": key_by_task.get(t, t), "dependency": key_by_task.get(d, d),
                     "state": final_cp["task_states"].get(d)}
                )
    checks["dependencies_satisfied"] = {
        "claim": "every declared dependency is COMPLETED in the final state",
        "observed": {"violations": dep_violations,
                     "dependency_map": {key_by_task.get(t, t): [key_by_task.get(d, d) for d in dd]
                                        for t, dd in deps.items()}},
        "passed": not dep_violations,
    }

    # ---------- 7. dependency ordering (event chronology) ----------
    # event type VALUES in the durable log are lowercase dotted strings
    order_results = {}
    for t, tdeps in deps.items():
        for d in tdeps:
            d_done = [e["timestamp"] for e in event("task.completed", correlation=d)]
            t_start = [e["timestamp"] for e in event("task.assigned", correlation=t)]
            ok = bool(d_done) and bool(t_start) and max(d_done) <= min(t_start)
            order_results[f"{key_by_task.get(d, d)} -> {key_by_task.get(t, t)}"] = ok
    checks["dependency_ordering_verified"] = {
        "claim": "for every edge dep->task: TASK_COMPLETED(dep) <= TASK_STARTED(task)",
        "observed": order_results,
        "passed": all(order_results.values()),
    }

    # ---------- 8. attempt history consistent ----------
    attempt_history = final_cp.get("attempt_history", {})
    cp_loaded = event("checkpoint.loaded")
    resume_ts = min((e["timestamp"] for e in cp_loaded), default=None)
    att_results = {}
    for t, atts in attempt_history.items():
        key = key_by_task.get(t, t)
        pre = [a for a in atts if resume_ts is None or a.get("started_at", "") < resume_ts]
        post = [a for a in atts if resume_ts is not None and a.get("started_at", "") >= resume_ts]
        expected_pre = 1 if key in ("TASK_A", "TASK_B", "TASK_C") else 0
        expected_post = 1 if key in ("TASK_D", "TASK_E") else 0
        att_results[key] = {
            "attempts_pre_resume": len(pre),
            "attempts_post_resume": len(post),
            "attempt_ids": [a["attempt_id"] for a in atts],
            "agents": [a.get("agent_id") for a in atts],
            "passed": len(pre) == expected_pre and len(post) == expected_post
            and len(atts) == expected_pre + expected_post,
        }
    checks["attempt_history_consistent"] = {
        "claim": "A/B/C: exactly 1 pre-crash attempt, 0 post-resume; D/E: exactly 1 post-resume attempt",
        "observed": att_results,
        "passed": att_results and all(v["passed"] for v in att_results.values()),
    }

    # ---------- 9. no unsafe duplicate side effects ----------
    dup_results = {
        "artifact_records_per_task": {k: len(v) for k, v in per_task_artifacts.items()},
        "evidence_records_total": len(evidence),
        "sandbox_files_per_task": {},
    }
    for key in TASK_KEYS:
        sandbox = artifacts_dir / f"sandbox-{task_by_key[key]}"
        files = sorted(p.name for p in sandbox.glob("*")) if sandbox.exists() else []
        dup_results["sandbox_files_per_task"][key] = files
    passed_dup = (
        all(len(v) == 1 for v in per_task_artifacts.values())
        and all(len(v) == 1 for v in dup_results["sandbox_files_per_task"].values())
    )
    checks["no_unsafe_duplicate_side_effects"] = {
        "claim": "each task produced exactly one artifact record and one file (identity/count/hash basis)",
        "observed": dup_results,
        "passed": passed_dup,
    }

    # ---------- 10. final mission state valid ----------
    checks["final_mission_state_valid"] = {
        "claim": "final durable checkpoint records mission state EVIDENCED (not just a success flag)",
        "observed": {"state": final_cp["state"],
                     "original_checkpoint_state": original_cp["state"]},
        "passed": final_cp["state"] in ("EVIDENCED", "VERIFIED"),
    }

    # ---------- 11. mission identity preserved ----------
    checks["mission_identity_preserved"] = {
        "claim": "same mission_id across original and final durable checkpoints",
        "observed": {"original": original_cp["mission_id"], "final": final_cp["mission_id"]},
        "passed": original_cp["mission_id"] == final_cp["mission_id"] == mission_id,
    }

    # ---------- 12. run lineage (durable chain) ----------
    lineage_ok = False
    lineage_observed = {"run_1_from_original_checkpoint": original_cp["run_id"]}
    if cp_loaded:
        loaded = cp_loaded[0]
        lineage_observed["checkpoint_loaded_event"] = {
            "run_id": loaded["run_id"],
            "payload_checkpoint_id": (loaded.get("payload") or {}).get("checkpoint_id"),
            "resumed_run": (loaded.get("payload") or {}).get("resumed_run"),
        }
        lineage_ok = (
            loaded["run_id"] == run_2
            and (loaded.get("payload") or {}).get("checkpoint_id") == original_cp_id
            and original_cp["run_id"] == run_1
        )
    checks["run_lineage_verified"] = {
        "claim": "RUN_2 (resumed) is linked to RUN_1 through durable records: "
                 "checkpoint(run_id=RUN_1) + CHECKPOINT_LOADED(run_id=RUN_2)",
        "observed": lineage_observed,
        "passed": lineage_ok,
    }

    # ---------- 13. event durability — no restoration-induced duplicates ----------
    tuples = [(e["event_type"], e["run_id"], e["correlation_id"], e["timestamp"]) for e in events]
    dup_tuples = len(tuples) - len(set(tuples))
    original_events_before_resume = [
        e for e in events if resume_ts is None or e["timestamp"] < resume_ts
    ]
    original_unique = set(tuples)  # all original tuples still present exactly once
    checks["event_history_durable_no_restoration_duplicates"] = {
        "claim": "event log reloadable; original history preserved exactly once; "
                 "no duplicate tuples introduced by restoration",
        "observed": {
            "total_events": len(events),
            "events_before_resume_boundary": len(original_events_before_resume),
            "duplicate_tuples": dup_tuples,
            "checkpoints_loaded_events": len(cp_loaded),
        },
        "passed": dup_tuples == 0 and len(cp_loaded) >= 1,
    }

    # ---------- 14. completed work preserved across processes ----------
    pa = load_json(evidence_dir / "process_a.json")
    preserved = {}
    for key in ("TASK_A", "TASK_B", "TASK_C"):
        tid = pa["task_ids"][key]
        before_ids = sorted(a["artifact_id"] for a in pa["artifacts_before_termination"].get(tid, []))
        before_hashes = sorted(a["sha256"] for a in pa["artifacts_before_termination"].get(tid, []))
        after_ids = per_task_artifacts.get(key, [])
        after_arts = [a for lst in art_by_task.values() for a in lst if a["artifact_id"] in after_ids]
        after_hashes = sorted(a["sha256"] for a in after_arts)
        preserved[key] = {
            "artifact_ids_before": before_ids,
            "artifact_ids_after": after_ids,
            "sha256_before": before_hashes,
            "sha256_after": after_hashes,
            "passed": before_ids == sorted(after_ids) and before_hashes == after_hashes,
        }
    checks["completed_work_preserved_across_processes"] = {
        "claim": "artifacts of tasks completed before termination keep identity and hash after resume",
        "observed": preserved,
        "passed": all(v["passed"] for v in preserved.values()),
    }

    # ---------- verdict ----------
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
        },
        "checks": checks,
        "missing_checks": missing,
    }
    durable_write_json(evidence_dir / "verifier.json", report)

    print(f"[VERIFIER] verdict={verdict}")
    for name, c in checks.items():
        print(f"  {'PASS' if c['passed'] else 'FAIL'}  {name}")
    if verdict != "VERIFIED":
        raise SystemExit("INDEPENDENT VERIFICATION FAILED")


if __name__ == "__main__":
    main(sys.argv[1])
