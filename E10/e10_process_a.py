#!/usr/bin/env python3
"""E10 PROCESS A — real OS process that executes part of the mission, writes a
durable checkpoint, verifies it ON DISK, and is then SIGKILLed.

Sequence (E10 sections 10-11):
  1. Fresh engine on the production path (grant-validated ToolExecutor).
  2. Define the 5-task graph; execute with max_parallel=1.
  3. An event subscriber requests the engine's production pause at the first
     safe scheduling boundary after TASK_C completes -> A/B/C COMPLETED,
     TASK_D READY (never started), TASK_E BLOCKED.
  4. create_full_checkpoint -> durable checkpoint + events + evidence on disk.
  5. DURABLE CHECKPOINT ASSERTION: re-open the checkpoint FILE and validate
     JSON, integrity hash, task states, dependencies, attempt history,
     artifact IDs, actual evidence hashes, mission/run identity.
  6. fsync every durable record.
  7. Write resume info for Process B (IDs only — no state objects).
  8. os.kill(self, SIGKILL) — real, forceful process termination.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e10_common import (  # noqa: E402
    MISSION_REQUEST, TASK_KEYS, EXPECTED_STATES_AT_PAUSE,
    artifacts_snapshot, attempts_snapshot, build_controller, build_engine,
    durable_write_json, e10_specs, evidence_snapshot, fsync_file,
)

from unified.contracts import EventType, TaskState  # noqa: E402


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main(workdir: str) -> None:
    work = Path(workdir)
    artifacts_dir = work / "artifacts"
    evidence_dir = work / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    pid = os.getpid()
    started_at = utcnow()
    command = [sys.executable, os.path.abspath(__file__), workdir]

    print(f"[PROCESS_A] pid={pid} start={started_at}")

    # --- 1. production engine ---
    engine = build_engine(artifacts_dir)
    controller = build_controller(engine, artifacts_dir / "mc_state")

    # --- 2. define the mission ---
    mission, run, key_to_task = controller.define_mission(MISSION_REQUEST, e10_specs())
    task_to_key = {v: k for k, v in key_to_task.items()}
    print(f"[PROCESS_A] mission={mission.mission_id} run={run.run_id}")

    # --- 3. pause-at-boundary subscriber (production E11 pause mechanism) ---
    task_b_id = key_to_task["TASK_B"]
    task_c_id = key_to_task["TASK_C"]
    completed_branches: set = set()
    pause_requested_at: list = []

    def on_event(event) -> None:
        if (
            event.event_type == EventType.TASK_COMPLETED
            and event.mission_id == mission.mission_id
            and event.correlation_id in (task_b_id, task_c_id)
        ):
            completed_branches.add(event.correlation_id)
            # Pause only when BOTH branches are done: TASK_D is then READY
            # (unblocked, never started) and TASK_E still BLOCKED. This is
            # deterministic regardless of B/C scheduling order.
            if completed_branches == {task_b_id, task_c_id}:
                mission.metadata["pause_requested"] = True
                mission.metadata["pause_actor"] = "e10_process_a"
                mission.metadata["pause_reason"] = (
                    "E10 controlled interruption boundary after TASK_B and "
                    "TASK_C (safe scheduling point before TASK_D starts)"
                )
                pause_requested_at.append(utcnow())

    engine.event_bus.subscribe(on_event)

    result = await controller.execute_run(run.run_id, max_parallel=1)

    graph = engine.task_graph.get(run.run_id, {})
    states = {task_to_key[tid]: node["state"].value for tid, node in graph.items()}
    print(f"[PROCESS_A] execute_run paused={result.get('paused')} states={states}")

    # Boundary state assertions (E10 section 10)
    boundary_ok = all(states[k] == v for k, v in EXPECTED_STATES_AT_PAUSE.items())
    if not boundary_ok:
        durable_write_json(evidence_dir / "process_a.json", {
            "status": "BOUNDARY_STATE_MISMATCH",
            "expected": EXPECTED_STATES_AT_PAUSE,
            "observed": states,
        })
        raise SystemExit(f"boundary state mismatch: {states}")

    # Pre-termination snapshots (the truth Process B must reproduce exactly)
    attempts_before = attempts_snapshot(engine)
    artifacts_before = artifacts_snapshot(engine, mission.mission_id)
    evidence_before = evidence_snapshot(engine, mission.mission_id)

    # --- 4. durable checkpoint at the boundary ---
    checkpoint = controller.create_full_checkpoint(
        mission.mission_id, run.run_id, step=3,
    )
    checkpoint_path = Path(artifacts_dir) / "checkpoints" / mission.mission_id / f"{checkpoint.checkpoint_id}.json"
    print(f"[PROCESS_A] checkpoint={checkpoint.checkpoint_id} hash={checkpoint.hash[:16]}...")

    # Persist events + evidence happen inside create_full_checkpoint ->
    # engine.create_checkpoint; fsync all of them for a hard kill that follows.
    fsync_file(checkpoint_path)
    fsync_file(Path(artifacts_dir) / "events" / mission.mission_id / "event_log.jsonl")
    ev_store = Path(artifacts_dir) / "evidence_store" / mission.mission_id
    fsync_file(ev_store / "artifacts.json")
    fsync_file(ev_store / "evidence.json")

    # --- 5. DURABLE CHECKPOINT ASSERTION on the actual file (E10 section 11) ---
    assertion: dict = {"checkpoint_file_exists": checkpoint_path.exists()}

    with open(checkpoint_path, "r", encoding="utf-8") as f:
        raw = f.read()
    cp_data = json.loads(raw)  # raises on invalid JSON
    assertion["checkpoint_json_valid"] = True

    # independent canonical-hash recomputation (same canonical form as the model)
    import hashlib
    canonical = json.dumps(
        {k: v for k, v in cp_data.items() if k != "hash"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    recomputed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    stored_hash = cp_data.get("hash", "")
    assertion["checkpoint_hash_valid"] = recomputed == stored_hash
    assertion["stored_hash"] = stored_hash
    assertion["recomputed_hash"] = recomputed

    # field-level presence checks
    dep_map = {task_to_key[t]: [task_to_key.get(d, d) for d in deps]
               for t, deps in cp_data["task_dependencies"].items()}
    assertion.update({
        "task_states_present": len(cp_data.get("task_states", {})) == 5,
        "task_states": {task_to_key[t]: s for t, s in cp_data["task_states"].items()},
        "dependencies_present": dep_map,
        "attempt_history_present": {
            task_to_key[t]: [a["attempt_id"] for a in atts]
            for t, atts in cp_data.get("attempt_history", {}).items()
        },
        "artifact_ids_present": sorted(cp_data.get("artifact_ids", [])),
        "evidence_hashes_present": sorted(cp_data.get("evidence_hashes", [])),
        "evidence_hashes_are_content_hashes": all(
            len(h) == 64 and all(c in "0123456789abcdef" for c in h)
            for h in cp_data.get("evidence_hashes", [])
        ),
        "mission_run_identity_present": (
            cp_data.get("mission_id") == mission.mission_id
            and cp_data.get("run_id") == run.run_id
        ),
    })

    all_valid = (
        assertion["checkpoint_file_exists"]
        and assertion["checkpoint_json_valid"]
        and assertion["checkpoint_hash_valid"]
        and assertion["task_states_present"]
        and assertion["dependencies_present"]
        and assertion["attempt_history_present"]
        and bool(assertion["artifact_ids_present"])
        and bool(assertion["evidence_hashes_present"])
        and assertion["evidence_hashes_are_content_hashes"]
        and assertion["mission_run_identity_present"]
    )
    assertion["ALL_DURABLE_CHECKPOINT_ASSERTIONS_PASSED"] = all_valid
    if not all_valid:
        durable_write_json(evidence_dir / "process_a.json", {
            "status": "DURABLE_CHECKPOINT_ASSERTION_FAILED", "assertion": assertion,
        })
        raise SystemExit("durable checkpoint assertion failed")

    # --- 7. resume info (IDs only — no state objects cross the boundary) ---
    ended_at = utcnow()
    resume_info = {
        "mission_id": mission.mission_id,
        "run_id": run.run_id,
        "checkpoint_id": checkpoint.checkpoint_id,
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_hash": stored_hash,
        "process_a_pid": pid,
        "process_a_started_at": started_at,
        "process_a_ended_at": ended_at,
        "command": command,
        "boundary_states": states,
    }
    durable_write_json(evidence_dir / "resume_info.json", resume_info)

    process_a_evidence = {
        "status": "PROCESS_A_COMPLETE",
        "process_a_pid": pid,
        "process_a_start_time": started_at,
        "process_a_end_time": ended_at,
        "process_a_command": command,
        "mission_id": mission.mission_id,
        "run_id": run.run_id,
        "task_ids": key_to_task,
        "boundary_task_states": states,
        "boundary_pause_requested_at": pause_requested_at[0] if pause_requested_at else None,
        "execute_run_result": {
            "success": result.get("success"),
            "paused": result.get("paused"),
            "task_results": result.get("task_results", {}),
        },
        "attempts_before_termination": attempts_before,
        "artifacts_before_termination": artifacts_before,
        "evidence_before_termination": evidence_before,
        "checkpoint": assertion,
        "git_head": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, text=True).stdout.strip(),
    }
    durable_write_json(evidence_dir / "process_a.json", process_a_evidence)

    print("[PROCESS_A] durable state verified on disk; committing SIGKILL on self")
    print(f"[PROCESS_A] pid={pid} terminating at {ended_at}")

    # --- 8. REAL process termination: SIGKILL, no cleanup, no atexit ---
    os.kill(pid, signal.SIGKILL)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
