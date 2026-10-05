"""E2-R2 §8 durability runner — executed as a REAL SEPARATE PROCESS.

Contract (mirrors the canonical e33_mission_runner.py pattern, E2-R2 scope):
  1. Resume the mission from checkpoint CP1 created by the parent process
     (cross-runtime handoff #1) — through the REAL P1+P2 public APIs.
  2. Execute the next chain task (pause deterministically at the task named
     by --pause-after-key, at the engine's scheduling boundary).
  3. Create full checkpoint CP2.
  4. Write the handshake file, then idle — the parent KILLS this process
     to prove crash/process recovery.

All state survives exclusively on disk under --state-dir.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--checkpoint-id", required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--handshake", required=True)
    parser.add_argument("--pause-after-key", required=True)
    args = parser.parse_args()

    from unified.agent_role import agent_registry
    from unified.contracts import EventType
    from unified.execution import ExecutionEngine
    from unified.mission_controller import MissionController, register_mission_agent

    state_dir = args.state_dir

    register_mission_agent(agent_registry)

    engine = ExecutionEngine(artifacts_base_dir=state_dir, max_retries=0)
    engine.event_bus.subscribe(lambda e: None)
    controller = MissionController(engine, state_dir=state_dir)

    # ---- Cross-runtime resume (handoff #1) ----
    run = engine.resume_from_checkpoint(args.checkpoint_id, mission_id=args.mission_id)
    if run is None:
        raise RuntimeError(f"resume_from_checkpoint returned None for {args.checkpoint_id}")
    mission_id = args.mission_id
    run_id = run.run_id

    # Rebuild key maps from the restored checkpoint definitions (context.task_key)
    graph = engine.task_graph.get(run_id, {})
    for tid, node in graph.items():
        task = engine.tasks.get(tid)
        key = (task.context or {}).get("task_key") if task else None
        if key:
            controller._key_to_task[key] = tid
            controller._task_to_key[tid] = key

    pause_tid = controller._key_to_task[args.pause_after_key]
    mission_obj = engine.missions[mission_id]

    def _pause_on_key_complete(event) -> None:
        if event.event_type == EventType.TASK_COMPLETED and event.correlation_id == pause_tid:
            mission_obj.metadata["pause_requested"] = True
            mission_obj.metadata["pause_actor"] = "mission_controller"
            mission_obj.metadata["pause_reason"] = (
                f"E2-R2 durability interruption point: {args.pause_after_key} verified; "
                "remaining tasks pending for post-kill resume"
            )

    engine.event_bus.subscribe(_pause_on_key_complete)

    result = await controller.execute_run(run_id, max_parallel=1)
    assert result.get("paused") is True, f"execution should pause after {args.pause_after_key}: {list(result.keys())}"
    executed_keys = [k for k, r in result["task_results"].items() if r.get("success")]
    assert executed_keys, "runner must execute at least one task before the pause"

    # ---- Full checkpoint CP2 (durable) ----
    controller.emit_marker(mission_id, run_id, "mission_controller_checkpoint", {
        "label": "CP2-pre-kill", "step": 6, "plan_version": controller.plan_version,
    })
    cp2 = controller.create_full_checkpoint(mission_id, run_id, step=6)

    ledger = controller.ledger_snapshot()
    ledger["runner_phase"] = {
        "run_id": run_id,
        "resumed_from_checkpoint": args.checkpoint_id,
        "pid": os.getpid(),
        "executed_keys": sorted(
            controller._task_to_key.get(t, t) for t in result["task_results"]
        ),
        "checkpoint_cp2": {
            "checkpoint_id": cp2.checkpoint_id,
            "mission_id": cp2.mission_id,
            "run_id": cp2.run_id,
            "step": cp2.step,
            "task_states": {k: v.value if hasattr(v, "value") else str(v)
                            for k, v in cp2.task_states.items()},
        },
    }
    d = Path(state_dir) / "mission_controller" / mission_id
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "runner_phase2.json", "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, default=str)

    # ---- Handshake: parent test now kills this process ----
    with open(args.handshake, "w", encoding="utf-8") as f:
        json.dump({
            "mission_id": mission_id,
            "run_id": run_id,
            "checkpoint_id": cp2.checkpoint_id,
            "pid": os.getpid(),
            "executed_keys": sorted(
                controller._task_to_key.get(t, t) for t in result["task_results"]
            ),
            "ready_at": time.time(),
        }, f, indent=2)

    # Idle until killed — no graceful shutdown.
    while True:
        await asyncio.sleep(1.0)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
