#!/usr/bin/env python3
"""E10-CW1 PROCESS B — a REAL new OS process (different PID, zero shared
memory with Process A) that restores the mission from durable storage only
and resumes through the crash window.

Fixed mode (with the E10-CW1 fix): TASK_D re-executes through the real
production agent path, the governed artifact_write hits the side-effect
journal, reconciles with the ORIGINAL outcome (no physical re-write — the
file's mtime/inode stay exactly as they were before the crash), TASK_D
completes with the ORIGINAL artifact identity, then TASK_E completes
normally.

Baseline mode (pre-fix code, gap demonstration): same flow, but TASK_D's
re-execution re-performs the physical write (a NEW artifact identity is
generated); observations are recorded without journal assertions so the
runner can demonstrate the duplicate.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e10_common import (  # noqa: E401
    TASK_KEYS, artifacts_snapshot, attempts_snapshot, build_controller,
    build_engine, durable_write_json, evidence_snapshot, fsync_file,
)
from e10cw1_common import (  # noqa: E401
    CRASH_WINDOW_TASK, journal_index, journal_path, read_journal,
    side_effect_file, stat_snapshot,
)

from unified.contracts import EventType, TaskState  # noqa: E401


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main(workdir: str) -> None:
    work = Path(workdir)
    artifacts_dir = work / "artifacts"
    evidence_dir = work / "evidence"

    pid = os.getpid()
    started_at = utcnow()
    print(f"[CW1_PROCESS_B] pid={pid} start={started_at}")

    resume_info = json.loads((evidence_dir / "resume_info.json").read_text())
    mode = resume_info.get("mode", "fixed")
    mission_id = resume_info["mission_id"]
    run_1 = resume_info["run_id"]
    checkpoint_id = resume_info["checkpoint_id"]
    pid_a = resume_info["process_a_pid"]
    task_ids = resume_info["task_ids"]          # key -> task_id (IDs only)
    task_to_key = {v: k for k, v in task_ids.items()}
    task_d_id = task_ids[CRASH_WINDOW_TASK]
    task_e_id = task_ids["TASK_E"]
    sandbox_d = f"sandbox-{task_d_id}"
    d_rel_path = "task_d_output.txt"            # from e10_common MARKERS
    d_file = side_effect_file(artifacts_dir, sandbox_d, d_rel_path)

    if pid == pid_a:
        raise SystemExit("FATAL: Process B PID equals Process A PID — not a new process")
    print(f"[CW1_PROCESS_B] mode={mode} different PID from A: {pid} != {pid_a}")

    crash_snapshot = json.loads((evidence_dir / "crash_window_snapshot.json").read_text())
    pre_resume = crash_snapshot["pre_resume_side_effect_file"]

    journal_before = read_journal(artifacts_dir, mission_id)
    jidx = journal_index(journal_before)
    d_performed_before = [r for r in jidx.get((task_d_id, d_rel_path), []) if r["record_type"] == "performed"]
    d_reconciled_before = [r for r in jidx.get((task_d_id, d_rel_path), []) if r["record_type"] == "reconciled"]

    restoration_log: list = []

    # --- 1. fresh engine: no in-memory state from Process A ---
    engine = build_engine(artifacts_dir)
    controller = build_controller(engine, artifacts_dir / "mc_state")

    # --- 2. checkpoint from disk, integrity verified BEFORE any execution ---
    checkpoint = engine._load_checkpoint_from_disk(mission_id, checkpoint_id)
    restoration_log.append({
        "step": "read_checkpoint_from_disk",
        "integrity_verified": checkpoint.verify(),
        "stored_hash": checkpoint.hash,
    })
    if not checkpoint.verify():
        raise SystemExit("FATAL: checkpoint integrity failed — must not execute")

    # --- 3. pre-resume side-effect file untouched since the crash ---
    stat_now = stat_snapshot(d_file)
    file_untouched_since_crash = (
        stat_now is not None
        and stat_now["mtime_ns"] == pre_resume["mtime_ns"]
        and stat_now["inode"] == pre_resume["inode"]
        and stat_now["sha256"] == pre_resume["sha256"]
    )
    restoration_log.append({
        "step": "side_effect_file_untouched_since_crash",
        "pre_resume": pre_resume,
        "observed_before_execution": stat_now,
        "untouched": file_untouched_since_crash,
    })

    # --- 4. resume: restores events, evidence, mission, graph; creates RUN_2 ---
    resumed_run = engine.resume_from_checkpoint(checkpoint_id, mission_id)
    run_2 = resumed_run.run_id
    restoration_log.append({
        "step": "resume_from_checkpoint",
        "resumed_run_id": run_2,
        "parent_run_id": engine.runs[run_2].parent_run_id,
    })

    # The controller's key maps are per-instance in-memory state; a fresh
    # controller in a new process rebuilds them from the durable resume IDs
    # (E10 process_b pattern — verify_completion keys off these maps).
    controller._key_to_task = dict(task_ids)
    controller._task_to_key = dict(task_to_key)

    graph = engine.task_graph[run_2]
    restored_states = {task_to_key[t]: node["state"].value for t, node in graph.items()}

    # restoration fidelity: A/B/C COMPLETED preserved; D READY; E BLOCKED;
    # no durable attempt for D/E (their pre-crash attempts were in-memory
    # only and died with Process A — the honest durable ledger).
    attempts_restored = attempts_snapshot(engine)
    artifacts_restored = artifacts_snapshot(engine, mission_id)
    fidelity = {
        "mission_identity_unchanged": engine.missions[mission_id].mission_id == mission_id,
        "restored_states": restored_states,
        "completed_preserved": all(
            restored_states[k] == "COMPLETED" for k in ("TASK_A", "TASK_B", "TASK_C")
        ),
        "crash_window_task_not_completed": restored_states.get(CRASH_WINDOW_TASK) in (
            "READY", "PENDING", "RUNNING",
        ),
        "run_lineage_preserved": engine.runs[run_2].parent_run_id == run_1,
        "attempts_restored": {task_to_key.get(t, t): len(l) for t, l in attempts_restored.items()},
        "durable_attempt_for_crash_window_task": len(attempts_restored.get(task_d_id, [])),
        "durable_artifact_record_for_crash_window_task": len(artifacts_restored.get(task_d_id, [])),
        "journal_performed_for_crash_window_task": len(d_performed_before),
        "journal_reconciled_before_resume": len(d_reconciled_before),
    }
    restoration_log.append({"step": "restoration_fidelity", "result": fidelity})

    fatal_pre: list = []
    if not fidelity["mission_identity_unchanged"]:
        fatal_pre.append("mission identity changed")
    if not fidelity["completed_preserved"]:
        fatal_pre.append("completed tasks not preserved at restore")
    if not fidelity["crash_window_task_not_completed"]:
        fatal_pre.append("crash-window task already completed at restore (window missed)")
    if not fidelity["run_lineage_preserved"]:
        fatal_pre.append("run lineage broken")
    if not file_untouched_since_crash:
        fatal_pre.append("side-effect file changed between crash and resume")
    if mode == "fixed":
        if fidelity["durable_attempt_for_crash_window_task"] != 0:
            fatal_pre.append("unexpected durable attempt for crash-window task")
        if fidelity["durable_artifact_record_for_crash_window_task"] != 0:
            fatal_pre.append("unexpected durable artifact record for crash-window task")
        if fidelity["journal_performed_for_crash_window_task"] != 1:
            fatal_pre.append("expected exactly 1 journal 'performed' record at restore")
        if fidelity["journal_reconciled_before_resume"] != 0:
            fatal_pre.append("unexpected journal 'reconciled' record before resume")
    if fatal_pre:
        durable_write_json(evidence_dir / "process_b.json", {
            "status": "RESTORATION_FAILED", "mode": mode, "fatal": fatal_pre,
            "restoration_log": restoration_log,
        })
        raise SystemExit(f"RESTORATION_FAILED: {fatal_pre}")

    print(f"[CW1_PROCESS_B] restored: {restored_states}; file untouched since crash: {file_untouched_since_crash}")

    # --- 5. RESUME: execute the remaining graph (D through the crash window,
    #        then E) on the real production path ---
    result = await controller.execute_run(run_2, max_parallel=1)
    print(f"[CW1_PROCESS_B] continuation success={result.get('success')}")

    graph_after = engine.task_graph[run_2]
    final_states = {task_to_key[t]: node["state"].value for t, node in graph_after.items()}

    # --- 6. side-effect accounting across the crash window ---
    journal_after = read_journal(artifacts_dir, mission_id)
    jidx_after = journal_index(journal_after)
    d_records = jidx_after.get((task_d_id, d_rel_path), [])
    d_performed_after = [r for r in d_records if r["record_type"] == "performed"]
    d_reconciled_after = [r for r in d_records if r["record_type"] == "reconciled"]
    e_records = jidx_after.get((task_e_id, "task_e_output.txt"), [])

    stat_after = stat_snapshot(d_file)
    no_physical_rewrite = (
        stat_after is not None
        and stat_after["mtime_ns"] == pre_resume["mtime_ns"]
        and stat_after["inode"] == pre_resume["inode"]
        and stat_after["sha256"] == pre_resume["sha256"]
    )

    attempts_after = attempts_snapshot(engine)
    artifacts_after = artifacts_snapshot(engine, mission_id)
    evidence_after = evidence_snapshot(engine, mission_id)

    d_artifacts = artifacts_after.get(task_d_id, [])
    d_artifact_ids = sorted(a["artifact_id"] for a in d_artifacts)
    original_artifact_id = (
        d_performed_before[0]["artifact_id"] if d_performed_before else None
    )

    def history_events(event_type: EventType, correlation: str):
        return [
            e for e in engine.event_bus.history
            if e.event_type == event_type
            and e.mission_id == mission_id
            and e.correlation_id == correlation
        ]

    d_artifact_created_events = history_events(EventType.ARTIFACT_CREATED, task_d_id)
    d_task_completed_events = history_events(EventType.TASK_COMPLETED, task_d_id)
    d_attempts = attempts_after.get(task_d_id, [])
    e_attempts = attempts_after.get(task_e_id, [])

    def event_artifact_id(e):
        p = e.payload
        if isinstance(p, dict):
            return p.get("artifact_id")
        return getattr(p, "artifact_id", None)

    # E10-CW1-R1 §6 event contract: exactly ONE ARTIFACT_CREATED per artifact
    # identity across all emitting sites (the agent-layer duplicate emission
    # is suppressed by the shared guard); the cross-process reconciliation is
    # reported by a DISTINCT ARTIFACT_RECONCILED event (mode=performed_record
    # for the CW1 window). For the crash-window task the creation event must
    # carry the ORIGINAL (pre-crash, journaled) artifact id, never a fresh one.
    d_artifact_reconciled_events = [
        e for e in engine.event_bus.history
        if e.event_type == EventType.ARTIFACT_RECONCILED
        and e.mission_id == mission_id
        and e.correlation_id == task_d_id
    ]
    d_created_ids = [event_artifact_id(e) for e in d_artifact_created_events]

    accounting = {
        "journal_records_for_crash_window_task": d_records,
        "journal_records_for_task_e": e_records,
        "crash_window_file": {
            "pre_resume": pre_resume,
            "after_resume": stat_after,
            "no_physical_rewrite": no_physical_rewrite,
        },
        "artifact_identity": {
            "original_from_journal": original_artifact_id,
            "after_resume": d_artifact_ids,
            "is_original": (
                original_artifact_id is not None
                and d_artifact_ids == [original_artifact_id]
            ),
            "count": len(d_artifacts),
        },
        "events": {
            "artifact_created_for_crash_window_task": len(d_artifact_created_events),
            "artifact_created_ids": d_created_ids,
            "artifact_reconciled_for_crash_window_task": len(d_artifact_reconciled_events),
            "artifact_reconciled_modes": [
                (e.payload.get("mode") if isinstance(e.payload, dict) else getattr(e.payload, "mode", None))
                for e in d_artifact_reconciled_events
            ],
            "task_completed_for_crash_window_task": len(d_task_completed_events),
        },
        "attempts": {
            "crash_window_task": len(d_attempts),
            "task_e": len(e_attempts),
            "per_task": {task_to_key.get(t, t): len(l) for t, l in attempts_after.items()},
        },
        "artifacts_per_task": {task_to_key.get(t, t): len(l) for t, l in artifacts_after.items()},
        "evidence_per_task": {},
    }
    from collections import Counter
    ev_counter = Counter(e.get("task_id") for e in evidence_after)
    accounting["evidence_per_task"] = {
        task_to_key.get(t, t): n for t, n in ev_counter.items()
    }

    # --- 7. mode-specific hard assertions ---
    fatal: list = []
    if final_states != {k: "COMPLETED" for k in TASK_KEYS}:
        fatal.append(f"not all tasks completed: {final_states}")
    if mode == "fixed":
        if not no_physical_rewrite:
            fatal.append("CRASH-WINDOW SIDE EFFECT WAS RE-PERFORMED (file rewritten)")
        if accounting["artifact_identity"]["count"] != 1 or not accounting["artifact_identity"]["is_original"]:
            fatal.append("crash-window task artifact identity not reconciled to the original")
        if len(d_artifact_created_events) != 1 or not all(
            aid == original_artifact_id for aid in d_created_ids
        ):
            fatal.append(
                f"expected exactly 1 ARTIFACT_CREATED event for the crash-window "
                f"task (E10-CW1-R1 exactly-once contract), carrying the ORIGINAL "
                f"artifact id; got {len(d_artifact_created_events)} with ids {d_created_ids}"
            )
        if len(d_artifact_reconciled_events) != 1 or not all(
            (e.payload.get("mode") if isinstance(e.payload, dict) else getattr(e.payload, "mode", None)) == "performed_record"
            for e in d_artifact_reconciled_events
        ):
            fatal.append(
                f"expected exactly 1 ARTIFACT_RECONCILED event (mode=performed_record) "
                f"for the crash-window task; got {len(d_artifact_reconciled_events)}"
            )
        if len(d_task_completed_events) != 1:
            fatal.append(f"expected exactly 1 TASK_COMPLETED for the crash-window task, got {len(d_task_completed_events)}")
        if len(d_performed_after) != 1 or len(d_reconciled_after) != 1:
            fatal.append("journal records for the crash-window task not exactly (1 performed + 1 reconciled)")
        if d_reconciled_after and not d_reconciled_after[0].get("no_physical_rewrite"):
            fatal.append("journal reconciliation record lacks no_physical_rewrite=true")
        if len(d_attempts) != 1 or len(e_attempts) != 1:
            fatal.append(f"expected 1 attempt each for D/E post-resume, got D={len(d_attempts)} E={len(e_attempts)}")
        if any(
            len(artifacts_after.get(task_ids[k], [])) != 1 for k in TASK_KEYS
        ):
            fatal.append("expected exactly one artifact record per task")
    else:
        # baseline gap demonstration: record the observed duplicate without
        # asserting — the runner judges from the file stat comparison.
        accounting["baseline_observation"] = {
            "task_re_executed": True,
            "new_artifact_identity": d_artifact_ids,
            "physical_file_rewritten": not no_physical_rewrite,
        }

    # --- 8. final completion verification + durable checkpoint ---
    ok, report = controller.verify_completion(run_2, required_keys=TASK_KEYS)
    finalize = controller.finalize_mission(mission_id, run_2, "E10-CW1 crash-window resume completion verified")
    final_cp = controller.create_full_checkpoint(mission_id, run_2, step=5)
    final_cp_path = Path(artifacts_dir) / "checkpoints" / mission_id / f"{final_cp.checkpoint_id}.json"
    fsync_file(final_cp_path)
    fsync_file(Path(artifacts_dir) / "events" / mission_id / "event_log.jsonl")
    ev_store = Path(artifacts_dir) / "evidence_store" / mission_id
    fsync_file(ev_store / "artifacts.json")
    fsync_file(ev_store / "evidence.json")
    from e10cw1_common import fsync_journal
    journal_file = fsync_journal(artifacts_dir, mission_id)

    ended_at = utcnow()
    evidence_payload = {
        "status": "PROCESS_B_COMPLETE" if not fatal else "PROCESS_B_FAILED",
        "mode": mode,
        "process_b_pid": pid,
        "process_a_pid": pid_a,
        "pid_difference": pid != pid_a,
        "process_b_start_time": started_at,
        "process_b_end_time": ended_at,
        "mission_id": mission_id,
        "run_1_interrupted": run_1,
        "run_2_resumed": run_2,
        "run_lineage": {"parent_run_id_of_run_2": engine.runs[run_2].parent_run_id},
        "restoration_log": restoration_log,
        "restoration_fidelity": fidelity,
        "final_task_states": final_states,
        "side_effect_accounting": accounting,
        "verify_completion_report": report,
        "finalize_mission": finalize,
        "final_checkpoint": {
            "checkpoint_id": final_cp.checkpoint_id,
            "path": str(final_cp_path),
            "hash": final_cp.hash,
        },
        "journal_file": journal_file,
    }
    durable_write_json(evidence_dir / "process_b.json", evidence_payload)
    if fatal:
        raise SystemExit(f"PROCESS_B_FAILED: {fatal}")
    if not ok:
        raise SystemExit(f"PROCESS_B_FAILED: verify_completion failed: {report}")

    print(f"[CW1_PROCESS_B] no_physical_rewrite={no_physical_rewrite} artifact_identity={d_artifact_ids}")
    print(f"[CW1_PROCESS_B] mission completed; final_state={finalize.get('final_state')}; end={ended_at}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
