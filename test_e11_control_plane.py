import asyncio
import json
from unified.execution import create_execution_engine
from unified.sandbox import SandboxBackend
from unified.agent_contract import AgentType
from unified.contracts import MissionState, validate_mission_transition

async def test_mission_cancellation():
    """Test mission cancellation."""
    print("=== TEST: Mission Cancellation ===")
    engine = create_execution_engine(
        sandbox_backend=SandboxBackend.WINDOWS_EXECUTOR,
        max_concurrent_missions=5,
        max_concurrent_tasks=10
    )
    
    # Create mission
    mission = engine.create_mission("Test cancellation mission")
    print(f"Mission created: {mission.mission_id}, state: {mission.state}")
    
    # Create run
    run = engine.create_run(mission.mission_id)
    print(f"Run created: {run.run_id}")
    
    # Create task
    task = engine.create_task(
        run_id=run.run_id,
        mission_id=mission.mission_id,
        name="Test Task",
        description="Test",
        agent_type=AgentType.IMPLEMENTER,
    )
    print(f"Task created: {task.task_id}")
    
    # Test cancellation
    result = engine.cancel_mission(mission.mission_id, actor="human", reason="Test cancellation")
    print(f"Cancellation result: {result}")
    print(f"Mission state after cancel: {mission.state}")
    
    # Check events
    events = engine.get_event_history(mission.mission_id)
    cancel_events = [e for e in events if 'cancel' in e.event_type.value.lower()]
    print(f"Cancel events: {len(cancel_events)}")
    for e in cancel_events:
        print(f"  {e.event_type.value}: {e.payload}")
    
    # Test idempotent cancellation
    result2 = engine.cancel_mission(mission.mission_id, actor="human", reason="Duplicate cancellation")
    print(f"Duplicate cancellation result: {result2}")
    print(f"Mission state after duplicate cancel: {mission.state}")
    
    return {
        'mission_state': mission.state.value,
        'cancellation_success': result,
        'duplicate_cancellation_safe': mission.state == MissionState.CANCELLED,
        'events_emitted': len(cancel_events) >= 2,
    }

async def test_mission_pause_resume():
    """Test mission pause and resume."""
    print("\n=== TEST: Mission Pause/Resume ===")
    engine = create_execution_engine(
        sandbox_backend=SandboxBackend.WINDOWS_EXECUTOR,
        max_concurrent_missions=5,
        max_concurrent_tasks=10
    )
    
    # Create mission and set to EXECUTING
    mission = engine.create_mission("Test pause/resume mission")
    run = engine.create_run(mission.mission_id)
    task = engine.create_task(
        run_id=run.run_id,
        mission_id=mission.mission_id,
        name="Test Task",
        description="Test",
        agent_type=AgentType.IMPLEMENTER,
    )
    
    # Manually set mission to EXECUTING
    mission.state = MissionState.EXECUTING
    
    # Test pause request
    result = engine.pause_mission(mission.mission_id, actor="human", reason="Test pause")
    print(f"Pause request result: {result}")
    print(f"Pause flag set: {mission.metadata.get('pause_requested')}")
    print(f"Pause actor: {mission.metadata.get('pause_actor')}")
    print(f"Pause reason: {mission.metadata.get('pause_reason')}")
    
    # The actual pause happens during execute_task_graph at checkpoint
    # For now just verify the flag is set
    print(f"Mission state: {mission.state} (should still be EXECUTING)")
    
    # Test resume
    mission.state = MissionState.PAUSED  # Simulate paused state
    result = engine.resume_mission(mission.mission_id, actor="human", reason="Test resume")
    print(f"Resume result: {result}")
    print(f"Mission state after resume: {mission.state}")
    
    return {
        'pause_flag_set': mission.metadata.get('pause_requested') is not None,
        'resume_works': mission.state == MissionState.EXECUTING,
    }

async def test_human_gate():
    """Test human gate creation and decision."""
    print("\n=== TEST: Human Gate ===")
    engine = create_execution_engine(
        sandbox_backend=SandboxBackend.WINDOWS_EXECUTOR,
        max_concurrent_missions=5,
        max_concurrent_tasks=10
    )
    
    # Create mission and set to EXECUTING
    mission = engine.create_mission("Test human gate mission")
    run = engine.create_run(mission.mission_id)
    task = engine.create_task(
        run_id=run.run_id,
        mission_id=mission.mission_id,
        name="Test Task",
        description="Test",
        agent_type=AgentType.IMPLEMENTER,
    )
    
    mission.state = MissionState.EXECUTING
    
    # Create human gate
    gate_id = engine.create_human_gate(
        mission_id=mission.mission_id,
        run_id=run.run_id,
        task_id=task.task_id,
        reason="Need human approval for deployment",
        context={"environment": "production", "risk": "high"},
        options=[
            {"value": "continue", "label": "Continue deployment"},
            {"value": "cancel", "label": "Cancel deployment"},
        ],
        impact="Production deployment will proceed",
        required_action="Human must approve or cancel",
    )
    print(f"Gate created: {gate_id}")
    print(f"Mission state: {mission.state}")
    gate_info = mission.metadata.get('human_gate')
    print(f"Gate info stored: {gate_info is not None}")
    if gate_info:
        print(f"  Gate ID matches: {gate_info.get('gate_id') == gate_id}")
    
    # Test continue decision
    continue_works = False
    cancel_works = False
    if gate_id:
        result = engine.decide_human_gate(mission.mission_id, gate_id, "continue", "human", "Approved")
        print(f"Continue decision result: {result}")
        print(f"Mission state after continue: {mission.state}")
        continue_works = (mission.state == MissionState.EXECUTING)
        
        # Check events
        events = engine.get_event_history(mission.mission_id)
        gate_events = [e for e in events if 'gate' in e.event_type.value.lower() or 'decision' in e.event_type.value.lower()]
        print(f"Gate events: {len(gate_events)}")
        for e in gate_events:
            print(f"  {e.event_type.value}: {e.payload}")
    
    # Test cancel decision on new mission
    mission2 = engine.create_mission("Test human gate cancel")
    run2 = engine.create_run(mission2.mission_id)
    task2 = engine.create_task(
        run_id=run2.run_id,
        mission_id=mission2.mission_id,
        name="Test Task",
        description="Test",
        agent_type=AgentType.IMPLEMENTER,
    )
    mission2.state = MissionState.EXECUTING
    
    gate_id2 = engine.create_human_gate(
        mission_id=mission2.mission_id,
        run_id=run2.run_id,
        task_id=task2.task_id,
        reason="Need human approval",
        context={},
        options=[{"value": "continue", "label": "Continue"}, {"value": "cancel", "label": "Cancel"}],
        impact="Will continue or cancel",
        required_action="Decide",
    )
    
    result = engine.decide_human_gate(mission2.mission_id, gate_id2, "cancel", "human", "Not approved")
    print(f"Cancel decision result: {result}")
    print(f"Mission state after cancel: {mission2.state}")
    cancel_works = (mission2.state == MissionState.CANCELLED)
    
    return {
        'gate_created': gate_id is not None,
        'gate_info_stored': gate_info is not None,
        'gate_id_matches': gate_info is not None and gate_info.get('gate_id') == gate_id,
        'continue_decision_works': continue_works,
        'cancel_decision_works': cancel_works,
    }

async def test_state_transitions():
    """Test all state transitions."""
    print("\n=== TEST: State Transitions ===")
    results = {}
    
    # Test valid transitions
    transitions_to_test = [
        (MissionState.RECEIVED, MissionState.ANALYZING),
        (MissionState.ANALYZING, MissionState.PLANNING),
        (MissionState.EXECUTING, MissionState.PAUSED),
        (MissionState.PAUSED, MissionState.EXECUTING),
        (MissionState.EXECUTING, MissionState.CANCEL_REQUESTED),
        (MissionState.CANCEL_REQUESTED, MissionState.CANCELLED),
        (MissionState.EXECUTING, MissionState.HUMAN_REQUIRED),
        (MissionState.HUMAN_REQUIRED, MissionState.EXECUTING),
        (MissionState.HUMAN_REQUIRED, MissionState.CANCELLED),
    ]
    
    for from_state, to_state in transitions_to_test:
        try:
            validate_mission_transition(from_state, to_state)
            results[f"{from_state.value} -> {to_state.value}"] = "VALID"
        except Exception as e:
            results[f"{from_state.value} -> {to_state.value}"] = f"INVALID: {e}"
    
    # Test invalid transitions
    invalid_transitions = [
        (MissionState.CANCELLED, MissionState.EXECUTING),
        (MissionState.VERIFIED, MissionState.EXECUTING),
        (MissionState.PAUSED, MissionState.VERIFIED),
    ]
    
    for from_state, to_state in invalid_transitions:
        try:
            validate_mission_transition(from_state, to_state)
            results[f"{from_state.value} -> {to_state.value}"] = "UNEXPECTEDLY VALID"
        except Exception as e:
            results[f"{from_state.value} -> {to_state.value}"] = f"CORRECTLY REJECTED: {type(e).__name__}"
    
    for k, v in results.items():
        print(f"  {k}: {v}")
    
    return results

async def test_concurrent_control():
    """Test concurrent control requests."""
    print("\n=== TEST: Concurrent Control Safety ===")
    engine = create_execution_engine(
        sandbox_backend=SandboxBackend.WINDOWS_EXECUTOR,
        max_concurrent_missions=5,
        max_concurrent_tasks=10
    )
    
    mission = engine.create_mission("Test concurrent control")
    run = engine.create_run(mission.mission_id)
    task = engine.create_task(
        run_id=run.run_id,
        mission_id=mission.mission_id,
        name="Test Task",
        description="Test",
        agent_type=AgentType.IMPLEMENTER,
    )
    mission.state = MissionState.EXECUTING
    
    # Multiple pause requests
    engine.pause_mission(mission.mission_id, actor="human", reason="Pause 1")
    engine.pause_mission(mission.mission_id, actor="human", reason="Pause 2")
    print(f"Multiple pause requests: pause flag = {mission.metadata.get('pause_requested')}")
    
    # Multiple cancel requests
    result1 = engine.cancel_mission(mission.mission_id, actor="human", reason="Cancel 1")
    result2 = engine.cancel_mission(mission.mission_id, actor="human", reason="Cancel 2")
    print(f"Cancel 1 result: {result1}, Cancel 2 result: {result2}")
    print(f"Mission state: {mission.state}")
    
    # Multiple resume requests on paused mission
    mission2 = engine.create_mission("Test concurrent resume")
    run2 = engine.create_run(mission2.mission_id)
    mission2.state = MissionState.PAUSED
    result1 = engine.resume_mission(mission2.mission_id, actor="human", reason="Resume 1")
    result2 = engine.resume_mission(mission2.mission_id, actor="human", reason="Resume 2")
    print(f"Resume 1: {result1}, Resume 2: {result2}")
    print(f"Mission state: {mission2.state}")
    
    return {
        'multiple_pause_safe': mission.metadata.get('pause_requested') is not None,
        'multiple_cancel_safe': mission.state == MissionState.CANCELLED,
        'multiple_resume_safe': mission2.state == MissionState.EXECUTING,
    }

async def main():
    results = {
        'cancellation': await test_mission_cancellation(),
        'pause_resume': await test_mission_pause_resume(),
        'human_gate': await test_human_gate(),
        'state_transitions': await test_state_transitions(),
        'concurrent_control': await test_concurrent_control(),
    }
    
    with open('evidence/e11/control_plane.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print("\n=== SUMMARY ===")
    print(json.dumps(results, indent=2, default=str))

asyncio.run(main())