#!/usr/bin/env python3
"""E10 PROCESS B — a REAL new OS process (different PID, zero shared memory
with Process A) that restores the mission from durable storage only and
resumes execution to completion.

Rules honored (E10 sections 12-17, 20-21):
  * The ONLY state source is durable storage: checkpoint file, event log,
    evidence store files, artifact files. Nothing is transferred from
    Process A except IDs (resume_info.json).
  * Integrity is verified BEFORE any execution starts (fail closed).
  * Completed work (A, B, C) must be preserved exactly: same task states,
    same attempt ledger, same artifact identities and hashes — no new
    attempts, no duplicate side effects.
  * Incomplete work (D READY, E BLOCKED) must actually resume and complete
    in dependency order.
  * Run lineage: RUN_2.parent_run_id == RUN_1, mission identity unchanged.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e10_common import (  # noqa: E402
    TASK_KEYS, artifacts_snapshot, attempts_snapshot, build_controller,
    build_engine, durable_write_json, evidence_snapshot, fsync_file,
)

from unified.contracts import EventType, TaskState  # noqa: E402


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main(workdir: str) -> None:
    work = Path(workdir)
    artifacts_dir = work / "artifacts"
    evidence_dir = work / "evidence"

    pid = os.getpid()
    started_at = utcnow()
    command = [sys.executable, os.path.abspath(__file__), workdir]
    print(f"[PROCESS_B] pid={pid} start={started_at}")

    resume_info = json.loads((evidence_dir / "resume_info.json").read_text())
    pa = json.loads((evidence_dir / "process_a.json").read_text())
    pid_a = resume_info["process_a_pid"]
    if pid == pid_a:
        raise SystemExit("FATAL: Process B PID equals Process A PID — not a new process")
    print(f"[PROCESS_B] different PID from A: {pid} != {pid_a} -> True")

    mission_id = resume_info["mission_id"]
    run_1 = resume_info["run_id"]
    checkpoint_id = resume_info["checkpoint_id"]

    restoration_log: list = []
    fidelity: dict = {}
    fail_closed: list = []

    # --- fresh engine: no in-memory state from Process A ---
    engine = build_engine(artifacts_dir)
    controller = build_controller(engine, artifacts_dir / "mc_state")

    # --- 1. read the checkpoint FROM DISK (integrity-verified load) ---
    checkpoint = engine._load_checkpoint_from_disk(mission_id, checkpoint_id)
    restoration_log.append({
        "step": "read_checkpoint_from_disk",
        "path": str(Path(artifacts_dir) / "checkpoints" / mission_id / f"{checkpoint_id}.json"),
        "integrity_verified": checkpoint.verify(),
        "stored_hash": checkpoint.hash,
        "recomputed_hash": checkpoint.compute_integrity_hash(),
    })
    if not checkpoint.verify():
        raise SystemExit("FATAL: checkpoint integrity failed — must not execute")

    # --- 2. resume (restores events, evidence, mission, graph; creates RUN_2) ---
    resumed_run = engine.resume_from_checkpoint(checkpoint_id, mission_id)
    run_2 = resumed_run.run_id
    restoration_log.append({
        "step": "resume_from_checkpoint",
        "resumed_run_id": run_2,
        "parent_run_id": engine.runs[run_2].parent_run_id,
        "source_run_id_from_checkpoint": checkpoint.run_id,
    })

    # --- 3. event durability (E10 s20): distinguish RESTORED vs NEW events ---
    # Restored history must match the durable file exactly (nothing lost,
    # nothing re-emitted twice). Events emitted BY the resume operation itself
    # (checkpoint.loaded, run.started for RUN_2, state.transition with
    # trigger=checkpoint_resume) are NEW events and must be exactly that set.
    from collections import Counter
    ev_file = Path(artifacts_dir) / "events" / mission_id / "event_log.jsonl"
    file_events = [json.loads(l) for l in ev_file.read_text().splitlines() if l.strip()]
    bus_events = [e for e in engine.event_bus.history if e.mission_id == mission_id]
    file_counter = Counter(
        (e["event_type"], e["run_id"], e["correlation_id"], e["timestamp"])
        for e in file_events
    )
    bus_counter = Counter(
        (e.event_type.value, e.run_id, e.correlation_id,
         e.timestamp.isoformat() if e.timestamp else None)
        for e in bus_events
    )
    lost_or_duplicated = {
        "lost": sum((file_counter - bus_counter).values()),
        "duplicated_old_events": sum(
            n for t, n in bus_counter.items()
            if t in file_counter and n > file_counter[t]
        ),
    }
    new_events = bus_counter - file_counter
    non_resume_new = []
    for e in bus_events:
        t = (e.event_type.value, e.run_id, e.correlation_id,
             e.timestamp.isoformat() if e.timestamp else None)
        if new_events.get(t, 0) <= 0:
            continue
        payload = e.payload if isinstance(e.payload, dict) else {}
        is_resume_emitted = (
            e.event_type == EventType.CHECKPOINT_LOADED
            or (e.event_type == EventType.RUN_STARTED and e.run_id == run_2)
            or (e.event_type == EventType.STATE_TRANSITION
                and (payload.get("trigger") == "checkpoint_resume"
                     or payload.get("to_state") in ("READY", "ASSIGNED")))
        )
        if not is_resume_emitted:
            non_resume_new.append(t)
    restoration_log.append({
        "step": "event_history_restored_from_disk",
        "events_in_file": len(file_events),
        "events_in_bus": len(bus_events),
        "restored_events_exact": lost_or_duplicated == {"lost": 0, "duplicated_old_events": 0},
        "lost": lost_or_duplicated["lost"],
        "duplicated_old_events": lost_or_duplicated["duplicated_old_events"],
        "new_events_emitted_by_resume": sum(new_events.values()),
        "new_events_all_resume_emitted": not non_resume_new,
        "non_resume_new_events": non_resume_new,
    })
    if lost_or_duplicated != {"lost": 0, "duplicated_old_events": 0} or non_resume_new:
        fail_closed.append(
            f"event restoration invalid: {lost_or_duplicated}, "
            f"non-resume new events: {non_resume_new[:3]}"
        )

    # --- 4. evidence + artifacts restored from disk ---
    restoration_log.append({
        "step": "evidence_store_loaded_from_disk",
        "artifacts_restored": len(engine.evidence_store._artifacts),
        "evidence_restored": len(engine.evidence_store._evidence),
    })

    # --- 5. restoration fidelity vs Process A's pre-termination snapshot (E10 s14) ---
    task_to_key = {}
    for tid, tdef in checkpoint.task_definitions.items():
        if tdef.get("key"):
            task_to_key[tid] = tdef["key"]
    controller._key_to_task = {k: t for t, k in task_to_key.items()}
    controller._task_to_key = task_to_key

    graph = engine.task_graph[run_2]
    restored_states = {task_to_key[t]: node["state"].value for t, node in graph.items()}
    restored_deps = {
        task_to_key[t]: sorted(task_to_key.get(d, d) for d in node["depends_on"])
        for t, node in graph.items()
    }
    pa_states = pa["boundary_task_states"]
    pa_deps = {
        k: sorted(v) for k, v in pa["checkpoint"]["dependencies_present"].items()
    }

    attempts_restored = attempts_snapshot(engine)
    artifacts_restored = artifacts_snapshot(engine, mission_id)

    pa_attempts = pa["attempts_before_termination"]
    pa_artifacts = pa["artifacts_before_termination"]

    def attempts_ids(snap):
        return {t: [a["attempt_id"] for a in lst] for t, lst in snap.items()}

    def artifacts_ids(snap):
        return {t: sorted(a["artifact_id"] for a in lst) for t, lst in snap.items()}

    def artifacts_hashes(snap):
        return {t: sorted(a["sha256"] for a in lst) for t, lst in snap.items()}

    fidelity = {
        "mission_identity_unchanged": engine.missions[mission_id].mission_id == mission_id,
        "task_count_identical": len(graph) == len(pa["task_ids"]) == 5,
        "task_ids_preserved": set(graph) == set(pa["task_ids"].values()),
        "task_dependencies_preserved": restored_deps == pa_deps,
        "completed_tasks_preserved": all(
            restored_states[k] == "COMPLETED" for k in ("TASK_A", "TASK_B", "TASK_C")
        ),
        "incomplete_tasks_preserved": (
            restored_states.get("TASK_D") in ("READY", "PENDING", "RUNNING")
            and restored_states.get("TASK_E") in ("BLOCKED", "PENDING")
        ),
        "attempt_history_preserved": attempts_ids(attempts_restored) == attempts_ids(pa_attempts),
        "artifact_ids_preserved": artifacts_ids(artifacts_restored) == artifacts_ids(pa_artifacts),
        "artifact_hashes_preserved": artifacts_hashes(artifacts_restored) == artifacts_hashes(pa_artifacts),
        "run_lineage_preserved": engine.runs[run_2].parent_run_id == run_1,
        "restored_states": restored_states,
    }
    restoration_log.append({"step": "restoration_fidelity", "result": fidelity})

    # --- 6. artifact/evidence continuity from persistent content (E10 s15) ---
    continuity = {}
    import hashlib
    for tid, lst in artifacts_restored.items():
        key = task_to_key.get(tid, tid)
        for a in lst:
            content = engine.evidence_store.read_artifact_content(a["artifact_id"])
            sha = hashlib.sha256(content).hexdigest() if content is not None else None
            continuity[f"{key}:{a['artifact_id']}"] = {
                "read_from_disk": content is not None,
                "sha256_matches_record": sha == a["sha256"],
                "bytes": len(content) if content else 0,
            }
    restoration_log.append({"step": "artifact_content_continuity", "result": continuity})

    hard_failures = [
        k for k, v in fidelity.items()
        if isinstance(v, bool) and not v
    ] + [
        f"{k}" for k, v in continuity.items()
        if not (v["read_from_disk"] and v["sha256_matches_record"])
    ] + fail_closed
    if hard_failures:
        durable_write_json(evidence_dir / "process_b.json", {
            "status": "RESTORATION_FAILED",
            "hard_failures": hard_failures,
            "fidelity": fidelity,
            "continuity": continuity,
            "restoration_log": restoration_log,
        })
        raise SystemExit(f"RESTORATION_FAILED: {hard_failures}")

    # --- 7. RESUME: execute the remaining graph (D, then E) ---
    resume_marker_ts = started_at
    result = await controller.execute_run(run_2, max_parallel=1)
    print(f"[PROCESS_B] continuation success={result.get('success')}")

    graph_after = engine.task_graph[run_2]
    final_states = {task_to_key[t]: node["state"].value for t, node in graph_after.items()}

    # --- 8. no-false-re-execution + side-effect accounting (E10 s16-s18) ---
    attempts_after = attempts_snapshot(engine)
    artifacts_after = artifacts_snapshot(engine, mission_id)
    evidence_after = evidence_snapshot(engine, mission_id)

    def new_attempts(task_id):
        before = {a["attempt_id"] for a in pa_attempts.get(task_id, [])}
        after = {a["attempt_id"] for a in attempts_after.get(task_id, [])}
        return sorted(after - before)

    side_effect_accounting = {
        "attempts_before": {task_to_key.get(t, t): len(lst) for t, lst in pa_attempts.items()},
        "attempts_after": {task_to_key.get(t, t): len(lst) for t, lst in attempts_after.items()},
        "new_attempts_post_resume": {
            task_to_key.get(t, t): new_attempts(t) for t in attempts_after
        },
        "artifact_count_before": {task_to_key.get(t, t): len(lst) for t, lst in pa_artifacts.items()},
        "artifact_count_after": {task_to_key.get(t, t): len(lst) for t, lst in artifacts_after.items()},
        "artifact_hashes_before": artifacts_hashes(pa_artifacts),
        "artifact_hashes_after": artifacts_hashes(artifacts_after),
        "artifact_ids_before": artifacts_ids(pa_artifacts),
        "artifact_ids_after": artifacts_ids(artifacts_after),
    }

    completed_not_reexecuted = all(
        new_attempts(pa["task_ids"][k]) == []
        for k in ("TASK_A", "TASK_B", "TASK_C")
    )
    completed_artifacts_unchanged = (
        artifacts_ids(pa_artifacts) == {
            t: ids for t, ids in artifacts_ids(artifacts_after).items()
            if t in {pa["task_ids"][k] for k in ("TASK_A", "TASK_B", "TASK_C")}
        }
        and artifacts_hashes(pa_artifacts) == {
            t: hs for t, hs in artifacts_hashes(artifacts_after).items()
            if t in {pa["task_ids"][k] for k in ("TASK_A", "TASK_B", "TASK_C")}
        }
    )

    # dependency ordering after resume: E was assigned only after D completed
    def event_ts(event_type, correlation):
        ts_list = [
            e.timestamp for e in engine.event_bus.history
            if e.event_type == event_type
            and e.mission_id == mission_id
            and e.correlation_id == correlation
        ]
        return min(ts_list) if ts_list else None

    d_id, e_id = pa["task_ids"]["TASK_D"], pa["task_ids"]["TASK_E"]
    d_completed_ts = event_ts(EventType.TASK_COMPLETED, d_id)
    # task start marker in this engine's event catalog is TASK_ASSIGNED
    e_started_ts = event_ts(EventType.TASK_ASSIGNED, e_id)
    dependency_order_ok = (
        d_completed_ts is not None and e_started_ts is not None and d_completed_ts <= e_started_ts
    )

    # resumed-task result entries carry the engine's own "resumed" marker
    resumed_markers = {
        k: result.get("task_results", {}).get(pa["task_ids"][k], {})
        for k in ("TASK_A", "TASK_B", "TASK_C")
    }

    # --- 9. final completion verification (E10 s24) ---
    ok, report = controller.verify_completion(run_2, required_keys=TASK_KEYS)
    finalize = controller.finalize_mission(mission_id, run_2, "E10 cross-process resume completion verified")

    # --- 10. final durable checkpoint (persists events+evidence for the verifier) ---
    final_checkpoint = controller.create_full_checkpoint(mission_id, run_2, step=5)
    final_cp_path = Path(artifacts_dir) / "checkpoints" / mission_id / f"{final_checkpoint.checkpoint_id}.json"
    fsync_file(final_cp_path)
    fsync_file(Path(artifacts_dir) / "events" / mission_id / "event_log.jsonl")
    ev_store = Path(artifacts_dir) / "evidence_store" / mission_id
    fsync_file(ev_store / "artifacts.json")
    fsync_file(ev_store / "evidence.json")

    ended_at = utcnow()
    process_b_evidence = {
        "status": "PROCESS_B_COMPLETE",
        "process_b_pid": pid,
        "process_a_pid": pid_a,
        "pid_difference": pid != pid_a,
        "process_b_start_time": started_at,
        "process_b_end_time": ended_at,
        "process_b_command": command,
        "mission_id": mission_id,
        "run_1_interrupted": run_1,
        "run_2_resumed": run_2,
        "run_lineage": {
            "parent_run_id_of_run_2": engine.runs[run_2].parent_run_id,
            "equals_run_1": engine.runs[run_2].parent_run_id == run_1,
        },
        "restoration_log": restoration_log,
        "restoration_fidelity": fidelity,
        "artifact_continuity": continuity,
        "final_task_states": final_states,
        "resumed_task_markers": resumed_markers,
        "completed_tasks_not_reexecuted": completed_not_reexecuted,
        "completed_artifacts_unchanged": completed_artifacts_unchanged,
        "dependency_order_after_resume_ok": dependency_order_ok,
        "side_effect_accounting": side_effect_accounting,
        "evidence_records_after": evidence_after,
        "verify_completion_report": report,
        "finalize_mission": finalize,
        "final_checkpoint": {
            "checkpoint_id": final_checkpoint.checkpoint_id,
            "path": str(final_cp_path),
            "hash": final_checkpoint.hash,
            "state": final_checkpoint.state.value,
        },
    }
    durable_write_json(evidence_dir / "process_b.json", process_b_evidence)

    # hard assertions — this script fails if any E10 invariant is violated
    fatal = []
    if not fidelity["mission_identity_unchanged"]:
        fatal.append("mission identity changed")
    if not fidelity["run_lineage_preserved"]:
        fatal.append("run lineage broken")
    if not completed_not_reexecuted:
        fatal.append("completed tasks were re-executed after resume")
    if not completed_artifacts_unchanged:
        fatal.append("completed task artifacts changed after resume")
    if any(
        len(side_effect_accounting["new_attempts_post_resume"].get(k, ["<missing>"])) != 0
        for k in ("TASK_A", "TASK_B", "TASK_C")
    ) or any(
        len(side_effect_accounting["new_attempts_post_resume"].get(k, [])) != 1
        for k in ("TASK_D", "TASK_E")
    ):
        fatal.append("unexpected attempt count post-resume")
    if final_states != {k: "COMPLETED" for k in TASK_KEYS}:
        fatal.append(f"not all tasks completed: {final_states}")
    if not dependency_order_ok:
        fatal.append("dependency ordering violated after resume")
    if not ok:
        fatal.append(f"verify_completion failed: {report}")
    if fatal:
        durable_write_json(evidence_dir / "process_b.json", {
            **process_b_evidence, "status": "PROCESS_B_FAILED", "fatal": fatal,
        })
        raise SystemExit(f"PROCESS_B_FAILED: {fatal}")

    print(f"[PROCESS_B] mission completed and verified; final_state={finalize.get('final_state')}")
    print(f"[PROCESS_B] pid={pid} end={ended_at}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
