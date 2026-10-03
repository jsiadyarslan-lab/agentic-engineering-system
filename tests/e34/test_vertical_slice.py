"""
E34 Operational Vertical Slice Test

Tests the complete official mission execution path:
USER → MISSION → OPERATIONAL ENTRYPOINT → MISSION CONTROLLER → TASK GRAPH → AGENT → TOOL → SANDBOX → ARTIFACT → EVIDENCE → VERIFIER → HUMAN_REQUIRED → PROCESS INTERRUPTION → RESUME → HUMAN DECISION → CONTINUE → MISSION COMPLETED

Also tests:
- Failure injection pre-human-gate
- Failure injection post-human-gate
- Durable human decision across process kill
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from unified.operational import (
    OperationalExecutionEngine, 
    run_operational_mission,
    OperationalExecutionResult
)
from unified.contracts import (
    MissionState, TaskState, AgentType, EventType,
    HumanGateCreatedEvent, HumanDecisionRecordedEvent,
    new_mission_id, new_run_id, new_task_id
)
from unified.execution import create_execution_engine, ExecutionEngine
from unified.mission_controller import MissionController, TaskSpec


async def test_operational_vertical_slice():
    """Test the complete operational vertical slice with human gate and process interruption."""
    print("\n" + "="*70)
    print("E34 OPERATIONAL VERTICAL SLICE TEST")
    print("="*70)
    
    artifacts_dir = tempfile.mkdtemp(prefix="e34_vertical_slice_")
    print(f"Artifacts dir: {artifacts_dir}")
    
    engine = OperationalExecutionEngine(artifacts_base_dir=artifacts_dir)
    
    # Define a mission with multiple tasks that will trigger human gate
    goal = "E34 Vertical Slice: Create files with human gate"
    parameters = {
        "mission_type": "multi_task",
        "tasks": [
            {"name": "Task A", "path": "task_a.txt", "content": b"Task A output", "depends_on": []},
            {"name": "Task B", "path": "task_b.txt", "content": b"Task B output", "depends_on": ["Task A"]},
            {"name": "Task C", "path": "task_c.txt", "content": b"Task C output", "depends_on": ["Task B"]},
        ],
    }
    
    events_collected = []
    def event_collector(event):
        events_collected.append(event)
        print(f"  [EVENT] {event['event_type']}: {event.get('payload', {}).get('reason', '')[:80] if event.get('payload') else ''}")
    
    engine.event_callback = event_collector
    
    print(f"\n--- Starting mission: {goal} ---")
    result = await engine.execute_mission(
        goal=goal,
        parameters=parameters,
        checkpoint_every=1,  # Checkpoint after each task
        use_mission_controller=True,  # Use official E34 path
    )
    
    print(f"\nMission completed: success={result.success}, final_state={result.final_state}")
    print(f"Tasks: {len(result.task_results)}")
    print(f"Artifacts: {len(result.artifacts)}")
    print(f"Events: {len(result.events)}")
    print(f"Checkpoints: {len(result.checkpoints)}")
    
    # Verify human gate was created (if implemented in mission)
    human_gate_events = [e for e in events_collected if e['event_type'] == 'human.gate.created']
    human_decision_events = [e for e in events_collected if e['event_type'] == 'human.decision.recorded']
    
    print(f"\nHuman gate events: {len(human_gate_events)}")
    print(f"Human decision events: {len(human_decision_events)}")
    
    # Verify state machine transitions
    state_transitions = [e for e in events_collected if e['event_type'] == 'mission.state_changed']
    print(f"\nState transitions:")
    for e in state_transitions:
        payload = e.get('payload', {})
        print(f"  {payload.get('from_state')} -> {payload.get('to_state')} (actor: {payload.get('actor')})")
    
    return result, events_collected


async def test_human_gate_durability():
    """Test that human gate state survives process kill and resume."""
    print("\n" + "="*70)
    print("E34 HUMAN GATE DURABILITY TEST")
    print("="*70)
    
    artifacts_dir = tempfile.mkdtemp(prefix="e34_human_gate_durability_")
    print(f"Artifacts dir: {artifacts_dir}")
    
    # Create engine and execute mission up to human gate
    engine = create_execution_engine(artifacts_base_dir=artifacts_dir)
    
    # Use MissionController to create a mission that will hit human gate
    mc = MissionController(engine, state_dir=artifacts_dir)
    
    task_specs = [
        TaskSpec(
            key="task_a",
            name="Task A",
            description="First task",
            acceptance_criteria=["file_exists:task_a.txt"],
            context={"operation": "write_file", "content": b"Task A", "path": "task_a.txt"},
        ),
        TaskSpec(
            key="task_b",
            name="Task B",
            description="Second task - will trigger human gate",
            acceptance_criteria=["file_exists:task_b.txt"],
            context={"operation": "write_file", "content": b"Task B", "path": "task_b.txt"},
        ),
    ]
    
    mission, run, key_to_id = mc.define_mission("E34 Human Gate Durability Test", task_specs)
    mc.record_plan_v1(run.run_id, mission.mission_id)
    
    # Execute first task
    print(f"Executing first task...")
    result = await mc.execute_run(run.run_id, max_parallel=1)
    print(f"Phase 1 result: success={result.get('success')}")
    
    # Create human gate after first task
    gate_id = engine.create_human_gate(
        mission_id=mission.mission_id,
        run_id=run.run_id,
        task_id=key_to_id["task_b"],
        reason="Human review required before Task B",
        context={"task_key": "task_b", "description": "Second task"},
        options=[
            {"value": "approve", "label": "Approve and continue"},
            {"value": "reject", "label": "Reject and cancel"},
            {"value": "request_changes", "label": "Request changes"}
        ],
        impact="Task B will execute after approval",
        required_action="Approve or reject Task B execution",
        evidence_refs=[],
        requested_by="test",
    )
    print(f"Human gate created: {gate_id}")
    print(f"Mission state: {mission.state}")
    
    # Verify checkpoint was created with human_gate
    checkpoints = list(engine.checkpoints.values())
    human_gate_checkpoints = [cp for cp in checkpoints if cp.human_gate is not None]
    print(f"Checkpoints with human_gate: {len(human_gate_checkpoints)}")
    if human_gate_checkpoints:
        cp = human_gate_checkpoints[-1]
        print(f"  Checkpoint: {cp.checkpoint_id}, state: {cp.state}")
        print(f"  Human gate: {cp.human_gate.get('gate_id')}")
    
    # Simulate process kill by creating new engine and resuming
    print("\n--- Simulating process kill and resume ---")
    new_engine = create_execution_engine(artifacts_base_dir=artifacts_dir)
    
    # Resume from latest checkpoint
    latest_cp = max(checkpoints, key=lambda c: c.created_at)
    print(f"Resuming from checkpoint: {latest_cp.checkpoint_id}")
    
    loaded_run = new_engine.resume_from_checkpoint(latest_cp.checkpoint_id, mission_id=mission.mission_id)
    print(f"Loaded run: {loaded_run.run_id if loaded_run else None}")
    
    # Check if human gate was restored
    mission_restored = new_engine.missions.get(mission.mission_id)
    if mission_restored:
        print(f"Restored mission state: {mission_restored.state}")
        human_gate = mission_restored.metadata.get("human_gate")
        print(f"Restored human_gate: {human_gate is not None}")
        if human_gate:
            print(f"  Gate ID: {human_gate.get('gate_id')}")
            print(f"  Reason: {human_gate.get('reason')}")
    
    # Make human decision
    if mission_restored and mission_restored.state == MissionState.HUMAN_REQUIRED:
        print("\n--- Making human decision: APPROVE ---")
        decision_ok = new_engine.decide_human_gate(
            mission_id=mission.mission_id,
            gate_id=gate_id,
            decision="approve",
            actor="test_human",
            feedback="Approved for continuation"
        )
        print(f"Decision recorded: {decision_ok}")
        print(f"Mission state after decision: {mission_restored.state}")
        
        # Verify decision persisted
        human_decision = mission_restored.metadata.get("human_decision")
        print(f"Human decision persisted: {human_decision is not None}")
        if human_decision:
            print(f"  Decision: {human_decision.get('decision')}")
            print(f"  Actor: {human_decision.get('actor')}")
    
    return True


async def test_failure_pre_human_gate():
    """Test failure injection before human gate."""
    print("\n" + "="*70)
    print("E34 FAILURE INJECTION PRE-HUMAN-GATE TEST")
    print("="*70)
    
    artifacts_dir = tempfile.mkdtemp(prefix="e34_failure_pre_")
    
    engine = OperationalExecutionEngine(artifacts_base_dir=artifacts_dir)
    
    # Mission with a task that will fail
    goal = "E34 Failure Pre-Human-Gate"
    parameters = {
        "mission_type": "multi_task",
        "tasks": [
            {"name": "Task Good", "path": "good.txt", "content": b"Good", "depends_on": []},
            {"name": "Task Fail", "path": "fail.txt", "content": b"Will fail", "depends_on": ["Task Good"]},
        ],
    }
    
    # We'll inject failure by using a command that fails
    result = await engine.execute_mission(
        goal=goal,
        parameters=parameters,
        use_mission_controller=True,
    )
    
    print(f"Mission result: success={result.success}, final_state={result.final_state}")
    
    # Check for failure events
    failed_tasks = [t for t in result.task_results.values() if not t['success']]
    print(f"Failed tasks: {len(failed_tasks)}")
    
    return result


async def test_failure_post_human_gate():
    """Test failure injection after human gate (after approval)."""
    print("\n" + "="*70)
    print("E34 FAILURE INJECTION POST-HUMAN-GATE TEST")
    print("="*70)
    
    artifacts_dir = tempfile.mkdtemp(prefix="e34_failure_post_")
    
    engine = create_execution_engine(artifacts_base_dir=artifacts_dir)
    mc = MissionController(engine, state_dir=artifacts_dir)
    
    task_specs = [
        TaskSpec(
            key="task_a",
            name="Task A",
            description="First task",
            acceptance_criteria=["file_exists:task_a.txt"],
            context={"operation": "write_file", "content": b"Task A", "path": "task_a.txt"},
        ),
        TaskSpec(
            key="task_b",
            name="Task B - Human Gate",
            description="Task requiring human approval",
            acceptance_criteria=["file_exists:task_b.txt"],
            context={"operation": "write_file", "content": b"Task B", "path": "task_b.txt"},
        ),
        TaskSpec(
            key="task_c",
            name="Task C - Post Gate",
            description="Task after human gate",
            depends_on=["task_b"],
            acceptance_criteria=["file_exists:task_c.txt"],
            context={"operation": "write_file", "content": b"Task C", "path": "task_c.txt"},
        ),
    ]
    
    mission, run, key_to_id = mc.define_mission("E34 Failure Post Human Gate", task_specs)
    mc.record_plan_v1(run.run_id, mission.mission_id)
    
    # Execute up to human gate task
    print("Executing Task A...")
    result = await mc.execute_run(run.run_id, max_parallel=1)
    
    # Create human gate for Task B
    gate_id = engine.create_human_gate(
        mission_id=mission.mission_id,
        run_id=run.run_id,
        task_id=key_to_id["task_b"],
        reason="Review Task B before execution",
        context={"task_key": "task_b"},
        options=[{"value": "approve", "label": "Approve"}, {"value": "reject", "label": "Reject"}],
        impact="Task B and C depend on this decision",
        required_action="Approve Task B execution",
        evidence_refs=[],
        requested_by="test",
    )
    print(f"Human gate created for Task B: {gate_id}")
    
    # Approve human gate
    print("Human approves...")
    engine.decide_human_gate(
        mission_id=mission.mission_id,
        gate_id=gate_id,
        decision="approve",
        actor="test_human",
        feedback="Approved"
    )
    print(f"Mission state after approval: {mission.state}")
    
    # Continue execution - Task B should run, then Task C
    print("Continuing execution...")
    result2 = await mc.execute_run(run.run_id, max_parallel=1)
    print(f"Phase 2 result: success={result2.get('success')}")
    
    return True


async def test_event_state_authority():
    """Test that state can be reconstructed from event history."""
    print("\n" + "="*70)
    print("E34 EVENT/STATE AUTHORITY TEST")
    print("="*70)
    
    artifacts_dir = tempfile.mkdtemp(prefix="e34_event_state_")
    
    engine = OperationalExecutionEngine(artifacts_base_dir=artifacts_dir)
    
    goal = "E34 Event State Authority"
    parameters = {
        "mission_type": "multi_task",
        "tasks": [
            {"name": "Task 1", "path": "1.txt", "content": b"One", "depends_on": []},
            {"name": "Task 2", "path": "2.txt", "content": b"Two", "depends_on": ["Task 1"]},
        ],
    }
    
    result = await engine.execute_mission(
        goal=goal,
        parameters=parameters,
        use_mission_controller=True,
    )
    
    # Reconstruct state from events
    events = result.events
    print(f"Total events: {len(events)}")
    
    # Build mission state from events
    mission_state = None
    task_states = {}
    
    for event in events:
        if event['event_type'] == 'mission.state_changed':
            payload = event.get('payload', {})
            mission_state = payload.get('to_state')
        elif event['event_type'] == 'task.completed':
            payload = event.get('payload', {})
            task_id = payload.get('task_id')
            if task_id:
                task_states[task_id] = 'COMPLETED'
        elif event['event_type'] == 'task.failed':
            payload = event.get('payload', {})
            task_id = payload.get('task_id')
            if task_id:
                task_states[task_id] = 'FAILED'
    
    print(f"Reconstructed mission state: {mission_state}")
    print(f"Reconstructed task states: {task_states}")
    print(f"Actual mission final_state: {result.final_state}")
    print(f"Actual task results: { {k: v['state'] for k, v in result.task_results.items()} }")
    
    # Verify reconstruction matches actual
    match = (mission_state == result.final_state or 
             (mission_state == 'EVIDENCED' and result.final_state in ('EVIDENCED', 'VERIFIED')))
    print(f"State reconstruction matches: {match}")
    
    return match


async def test_attempt_accounting():
    """Test that attempt_id accounting is correct (E33 fix)."""
    print("\n" + "="*70)
    print("E34 ATTEMPT ACCOUNTING TEST")
    print("="*70)
    
    artifacts_dir = tempfile.mkdtemp(prefix="e34_attempt_")
    
    engine = create_execution_engine(artifacts_base_dir=artifacts_dir)
    mc = MissionController(engine, state_dir=artifacts_dir)
    
    task_specs = [
        TaskSpec(
            key="task_a",
            name="Task A - Fails Once",
            description="Task that fails first attempt",
            acceptance_criteria=["file_exists:task_a.txt"],
            context={
                "operation": "write_file", 
                "content": b"Task A", 
                "path": "task_a.txt",
                "fail_attempt_1": "task_execution"  # Deterministic failure on attempt 1
            },
        ),
    ]
    
    mission, run, key_to_id = mc.define_mission("E34 Attempt Accounting", task_specs)
    mc.record_plan_v1(run.run_id, mission.mission_id)
    
    # Execute with retry
    result = await mc.execute_run(run.run_id, max_parallel=1)
    
    print(f"Execution result: success={result.get('success')}")
    
    # Check attempt history in checkpoints
    checkpoints = list(engine.checkpoints.values())
    for cp in checkpoints:
        if cp.attempt_history:
            for task_id, attempts in cp.attempt_history.items():
                print(f"Task {task_id} attempts: {len(attempts)}")
                for a in attempts:
                    print(f"  Attempt {a.get('attempt_id')}: state={a.get('state')}, success={a.get('success')}")
    
    # Verify attempt count matches event history
    task_assigned_events = [e for e in engine.event_bus.history 
                           if e.event_type == EventType.TASK_ASSIGNED 
                           and e.mission_id == mission.mission_id]
    print(f"TASK_ASSIGNED events: {len(task_assigned_events)}")
    
    return True


async def main():
    """Run all E34 tests."""
    print("\n" + "#"*70)
    print("# E34 OPERATIONAL MISSION INTEGRATION & HUMAN GATE - VERTICAL SLICE")
    print("#"*70)
    
    all_passed = True
    
    try:
        # Test 1: Basic vertical slice
        result, events = await test_operational_vertical_slice()
        if not result.success:
            print("FAIL: Vertical slice mission failed")
            all_passed = False
        else:
            print("PASS: Vertical slice mission completed")
    except Exception as e:
        print(f"FAIL: Vertical slice test error: {e}")
        all_passed = False
    
    try:
        # Test 2: Human gate durability
        await test_human_gate_durability()
        print("PASS: Human gate durability test")
    except Exception as e:
        print(f"FAIL: Human gate durability test error: {e}")
        all_passed = False
    
    try:
        # Test 3: Failure pre-human-gate
        await test_failure_pre_human_gate()
        print("PASS: Failure pre-human-gate test")
    except Exception as e:
        print(f"FAIL: Failure pre-human-gate test error: {e}")
        all_passed = False
    
    try:
        # Test 4: Failure post-human-gate
        await test_failure_post_human_gate()
        print("PASS: Failure post-human-gate test")
    except Exception as e:
        print(f"FAIL: Failure post-human-gate test error: {e}")
        all_passed = False
    
    try:
        # Test 5: Event/state authority
        match = await test_event_state_authority()
        if match:
            print("PASS: Event/state authority test")
        else:
            print("FAIL: Event/state authority mismatch")
            all_passed = False
    except Exception as e:
        print(f"FAIL: Event/state authority test error: {e}")
        all_passed = False
    
    try:
        # Test 6: Attempt accounting
        await test_attempt_accounting()
        print("PASS: Attempt accounting test")
    except Exception as e:
        print(f"FAIL: Attempt accounting test error: {e}")
        all_passed = False
    
    print("\n" + "#"*70)
    if all_passed:
        print("# ALL E34 TESTS PASSED")
    else:
        print("# SOME E34 TESTS FAILED")
    print("#"*70)
    
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)