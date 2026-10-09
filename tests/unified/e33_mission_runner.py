"""
E33 mission runner — executed as a REAL SEPARATE PROCESS.

Purpose (executive order E33 sections 9-11):
  1. Resume the mission from a durable checkpoint created by the parent test
     process (cross-runtime handoff #1).
  2. Execute task D -> D fails verification (real deviation, F3).
  3. Detect + classify the deviation; generate and apply mission-level
     replan v1 -> v2 (invalidate E,F; add X; rewire G,H; correct D criteria).
  4. Execute D (corrected) and X to completion.
  5. Create full checkpoint CP2.
  6. Write the handshake file, then idle — the parent test KILLS this process
     (real TerminateProcess) to prove crash/process recovery.

All state survives exclusively on disk under --state-dir.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path


def _granted(artifacts_dir):
    """E10-RP2.2-R1 — REAL EOE authorization stack for governed
    artifact_write through ToolExecutor (order §2.1: path-bearing tools
    reject non-path-aware validators, so the legacy permissive 2-arg
    fixture is replaced by the production bridge on AccessAdmission with
    an owner-approved READ_WRITE PATH_GRANT over THIS test's own
    artifacts tree only). Returns kwargs for ExecutionEngine."""
    import os as _os
    import time as _time
    from eoe.access_gateway import (AccessAdmission, AccessLedger,
                                    GrantorService)
    from eoe.engine_bridge import build_engine_grant_validator
    from eoe.order_parser import AccessRequest, GrantKind
    ledger = AccessLedger()
    grantor = GrantorService(_os.urandom(32))
    admission = AccessAdmission(ledger, grantor, now=_time.time)
    grant = grantor.approve(grantor.propose(AccessRequest(
        kind=GrantKind.PATH_GRANT, scope="read_write",
        target=str(artifacts_dir))))
    ledger.register(grant)
    return {
        "grant_validator": build_engine_grant_validator(
            admission, str(artifacts_dir)),
        "grant_ids": [grant.grant_id],
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--checkpoint-id", required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--handshake", required=True)
    args = parser.parse_args()

    from unified.agent_role import agent_registry
    from unified.contracts import TaskState, EventType
    from unified.execution import ExecutionEngine
    from unified.mission_controller import (
        MissionController, register_mission_agent, FailureKind, RecoveryAction,
    )

    state_dir = args.state_dir

    register_mission_agent(agent_registry)

    engine = ExecutionEngine(
        artifacts_base_dir=state_dir, max_retries=0,
        **_granted(state_dir),  # E10-RP2.2-R1: real EOE bridge + owner-approved grant (order §2.1 fail-closed)
    )
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

    resume1_marker = {
        "run_id": run_id,
        "resumed_from_checkpoint": args.checkpoint_id,
        "pid": __import__("os").getpid(),
    }

    # ---- Phase 2 execution: D fails verification (real deviation) ----
    result1 = await controller.execute_run(run_id, max_parallel=1)
    d_key_id = controller._key_to_task.get("D")
    assert d_key_id in result1["task_results"], f"D missing from results: {list(result1['task_results'])}"
    d_res = result1["task_results"][d_key_id]
    assert d_res["success"] is False, f"D should fail verification, got {d_res}"

    # ---- DETECT + CLASSIFY ----
    failures = controller.scan_failures(list(engine.event_bus.history), result1["task_results"])
    deviation = next((f for f in failures if f.kind == FailureKind.PLAN_DEVIATION and f.task_id == d_key_id), None)
    assert deviation is not None, f"Plan deviation not detected: {[(f.kind.value, f.task_key) for f in failures]}"

    # ---- Data-driven plan correction: derive the real contract from D's artifact ----
    d_task = engine.tasks[d_key_id]
    d_node = graph[d_key_id]
    d_artifacts = []
    for art in engine.evidence_store._artifacts.values():
        if getattr(art, "mission_id", "") == mission_id and art.path == "e33_task_d.txt":
            d_artifacts.append(art)
    assert d_artifacts, "D artifact not found in evidence store"
    content = engine.evidence_store.get_artifact(d_artifacts[-1].artifact_id)
    assert content, "D artifact content unreadable"
    text = content.decode("utf-8")
    corrected_marker = text.strip().splitlines()[0].strip()
    corrected_criteria = [f"file_contains:e33_task_d.txt:{corrected_marker}"]

    # ---- Mission-level REPLAN v1 -> v2 (section 13) ----
    # E and F are invalidated by the deviation; X (remediation) is added and
    # G,H are rewired onto X ("NEW:X" resolves to X's real task_id inside the
    # controller after the engine creates the task). The controller also
    # re-baselines rewired tasks to BLOCKED until X completes.
    invalid_ids = [controller._key_to_task[k] for k in ("E", "F")]
    g_id = controller._key_to_task["G"]
    h_id = controller._key_to_task["H"]
    replan_record = controller.replan_mission(
        run_id=run_id,
        deviation=deviation,
        invalidate_task_ids=invalid_ids,
        corrected_criteria={d_key_id: corrected_criteria},
        add_specs=[{
            "name": "Task-X-Remediation",
            "description": "Remediation task required after deviation at D (downstream contract changed)",
            "agent_type": "implementer",
            "depends_on": [d_key_id],
            "acceptance_criteria": ["file_contains:e33_task_x.txt:E33-TASK-X-REMEDIATION-OUTPUT"],
            "context": {
                "task_key": "X",
                "content": "E33-TASK-X-REMEDIATION-OUTPUT",
                "output_path": "e33_task_x.txt",
                "sleep_s": 0.05,
            },
        }],
        rewire={g_id: ["NEW:X"], h_id: ["NEW:X"]},
        reason=(
            f"Deviation {deviation.failure_id} at task D: verification against plan v1 contract "
            f"failed; observed artifact defines the real downstream contract ({corrected_marker}). "
            "E and F (built on the invalidated expectation) are removed; remediation task X "
            "covers the contract; G and H are rewired onto X."
        ),
        plan_version="v2",
    )
    x_id = controller._key_to_task["X"]

    # ---- RECOVER: return D to READY under the corrected contract ----
    controller.recover_failed_task(run_id, d_key_id, reason="Plan corrected: D re-verified against observed contract")

    # ---- Deterministic mid-mission pause: when X completes, request pause so
    # the execution loop stops at the scheduling boundary BEFORE running G,H.
    # G,H remain as pending work for the post-termination resume (sections 9-11). ----
    mission_obj = engine.missions[mission_id]

    def _pause_on_x_complete(event) -> None:
        if event.event_type == EventType.TASK_COMPLETED and event.correlation_id == x_id:
            mission_obj.metadata["pause_requested"] = True
            mission_obj.metadata["pause_actor"] = "mission_controller"
            mission_obj.metadata["pause_reason"] = (
                "E33 deterministic interruption point: D and X verified; G,H pending for post-resume execution"
            )

    engine.event_bus.subscribe(_pause_on_x_complete)

    # ---- Execute replanned graph: D (corrected) + X complete; loop pauses before G,H ----
    result2 = await controller.execute_run(run_id, max_parallel=1)
    assert result2["task_results"][d_key_id]["success"] is True, f"D should pass after replan: {result2['task_results'][d_key_id]}"
    assert result2["task_results"][x_id]["success"] is True, f"X should pass: {result2['task_results'][x_id]}"
    assert result2.get("paused") is True, f"Execution should pause after X, got keys {list(result2.keys())}"
    assert g_id not in result2["task_results"] and h_id not in result2["task_results"], (
        "G,H must NOT execute in the killed process — they are pending work for the resume"
    )
    g_state = engine.task_graph[run_id][g_id]["state"]
    h_state = engine.task_graph[run_id][h_id]["state"]
    assert g_state in (TaskState.READY, TaskState.BLOCKED), f"G should be pending, got {g_state}"
    assert h_state in (TaskState.READY, TaskState.BLOCKED), f"H should be pending, got {h_state}"

    # ---- Full checkpoint CP2 (durable) ----
    controller.emit_marker(mission_id, run_id, "mission_controller_checkpoint", {
        "label": "CP2-post-replan", "step": 6, "plan_version": controller.plan_version,
    })
    cp2 = controller.create_full_checkpoint(mission_id, run_id, step=6)

    ledger = controller.ledger_snapshot()
    ledger["resume1"] = resume1_marker
    ledger["checkpoint_cp2"] = {
        "checkpoint_id": cp2.checkpoint_id,
        "mission_id": cp2.mission_id,
        "run_id": cp2.run_id,
        "step": cp2.step,
        "task_states": {k: v.value if hasattr(v, "value") else str(v) for k, v in cp2.task_states.items()},
        "attempt_counts": {k: len(v) for k, v in (cp2.attempt_history or {}).items()},
    }
    d = Path(state_dir) / "mission_controller" / mission_id
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "runner_phase2.json", "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, default=str)

    # ---- Handshake: parent test now kills this process (REAL termination) ----
    with open(args.handshake, "w", encoding="utf-8") as f:
        json.dump({
            "mission_id": mission_id,
            "run_id": run_id,
            "checkpoint_id": cp2.checkpoint_id,
            "plan_version": controller.plan_version,
            "pid": __import__("os").getpid(),
            "completed_keys": ["A", "B", "C", "D", "X"],
            "pending_keys": ["G", "H"],
            "ready_at": time.time(),
        }, f, indent=2)

    # Idle until killed — no graceful shutdown happens (TerminateProcess).
    while True:
        await asyncio.sleep(1.0)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
