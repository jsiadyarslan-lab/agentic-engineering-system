#!/usr/bin/env python3
"""E10-CW1 PROCESS A — real OS process that executes the mission until the
CRASH WINDOW, then dies by a real SIGKILL at a real lifecycle boundary.

Sequence (E10-CW1 order section 4, Process A):
  1. Fresh engine on the production path (grant-validated ToolExecutor).
  2. Same 5-task graph as E10; sequential execution (max_parallel=1).
     A, B, C complete normally — each completion durably checkpointed
     (checkpoint_every=1), so the last durable checkpoint at the crash is:
     A/B/C COMPLETED, TASK_D READY (never started), TASK_E BLOCKED.
  3. TASK_D starts. MissionTaskAgent.execute calls the governed
     ToolExecutor.execute_tool("artifact_write") -> engine.execute_tool:
       a. the sandbox adapter performs the PHYSICAL side effect
          (file write to artifacts/sandbox-<task_d>/<path>);
       b. the side-effect journal appends an fsynced durable record
          (BEFORE the call returns — this is what survives the crash);
       c. _emit_artifact_created emits ARTIFACT_CREATED.
  4. The deterministic failure injection: a harness subscriber watching for
     ARTIFACT_CREATED with correlation_id == TASK_D kills the process with
     SIGKILL at exactly that point — AFTER the side effect and its durable
     journal record, BEFORE any durable record of TASK_D's completion
     (no checkpoint is created to cover the gap; nothing is cleaned up).

The kill point is a REAL production lifecycle point (the artifact-created
emission of the governed tool execution), not a safe scheduling boundary
after task completion. The injection marker (evidence/injection.json) is
written + fsynced immediately before the kill so the moment is provable.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e10_common import build_controller, build_engine, durable_write_json  # noqa: E402
from e10cw1_common import CRASH_WINDOW_TASK  # noqa: E402

from unified.contracts import EventType  # noqa: E402


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main(workdir: str) -> None:
    work = Path(workdir)
    artifacts_dir = work / "artifacts"
    evidence_dir = work / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    pid = os.getpid()
    started_at = utcnow()
    print(f"[CW1_PROCESS_A] pid={pid} start={started_at}")

    # --- 1. production engine + mission (same graph as E10) ---
    engine = build_engine(artifacts_dir)
    controller = build_controller(engine, artifacts_dir / "mc_state")
    from e10_common import e10_specs
    mission, run, key_to_task = controller.define_mission(
        "E10-CW1 crash-window idempotency proof: same five-task graph as E10, "
        "interrupted by SIGKILL inside the side-effect window of TASK_D.",
        e10_specs(),
    )
    print(f"[CW1_PROCESS_A] mission={mission.mission_id} run={run.run_id}")

    task_d_id = key_to_task[CRASH_WINDOW_TASK]
    injection_facts: list = []

    # --- 2. deterministic failure injection at the real lifecycle boundary ---
    def on_event(event) -> None:
        if (
            event.event_type == EventType.ARTIFACT_CREATED
            and event.mission_id == mission.mission_id
            and event.correlation_id == task_d_id
        ):
            payload = event.payload
            artifact_id = (
                payload.get("artifact_id") if isinstance(payload, dict)
                else getattr(payload, "artifact_id", None)
            )
            # Durable marker of the injection point, then a REAL SIGKILL.
            # At this moment in the engine's lifecycle:
            #   * the physical side effect exists on disk;
            #   * its side-effect journal record exists and is fsynced;
            #   * TASK_D's completion is NOT durably recorded (no
            #     checkpoint covers the gap and none may be created now).
            marker = {
                "injection_point": "artifact_created_of_crash_window_task",
                "task_key": CRASH_WINDOW_TASK,
                "task_id": task_d_id,
                "artifact_id": artifact_id,
                "event_timestamp": event.timestamp.isoformat() if event.timestamp else utcnow(),
                "reached_at_utc": utcnow(),
                "process_pid": pid,
                "kill_signal": "SIGKILL",
                "lifecycle_position": (
                    "after the governed artifact write (the physical side "
                    "effect exists on disk), before any durable record of "
                    "task/attempt completion"
                ),
            }
            injection_facts.append(marker)
            durable_write_json(evidence_dir / "injection.json", marker)
            print(f"[CW1_PROCESS_A] INJECTION at {utcnow()}: after the governed artifact write, before any durable completion record")
            print(f"[CW1_PROCESS_A] pid={pid} committing SIGKILL on self")
            os.kill(pid, signal.SIGKILL)

    engine.event_bus.subscribe(on_event)

    # --- 3. execute: A, B, C complete + checkpoint; D starts; die in-window ---
    result = await controller.execute_run(run.run_id, max_parallel=1)
    # Unreachable when the injection fires; kept as an honest failure marker.
    durable_write_json(evidence_dir / "process_a.json", {
        "status": "INJECTION_NEVER_FIRED",
        "execute_run_result": {"success": result.get("success")},
    })
    raise SystemExit("FATAL: injection never fired — crash window not reached")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
