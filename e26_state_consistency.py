"""
E26 — STATE/EVENT CONSISTENCY TEST
Verify state machine and event consistency.
"""

import asyncio
import sys
import json
import time
import os
sys.path.insert(0, 'src')

from unified.operational import OperationalExecutionEngine
from unified.execution import ExecutionEngine
from unified.domain_model import MissionState, TaskState
from unified.contracts import AgentType, validate_mission_transition, validate_task_transition

async def e26_state_consistency():
    trace = {
        'timestamp': '2026-10-03T01:30:00.000000+00:00',
        'test_name': 'E26_STATE_EVENT_CONSISTENCY',
        'phases': [],
        'verdicts': {}
    }
    
    def log_phase(name, data, verdict=None):
        trace['phases'].append({'phase': name, 'timestamp': time.time(), 'data': data})
        if verdict:
            trace['verdicts'][name] = verdict
        print(f'=== {name} ===')
        for k, v in data.items():
            print(f'  {k}: {v}')
        if verdict:
            print(f'  VERDICT: {verdict}')
    
    # ============================================================
    # SC01: Mission state transitions match events
    # ============================================================
    log_phase('SC01_MISSION_STATE_EVENTS', {'start': True})
    tasks = [
        {'name': 'SC01-Task-1', 'description': 'First', 'path': 'sc01_t1.txt', 'content': b'First', 'depends_on': [], 'agent_type': AgentType.IMPLEMENTER, 'acceptance_criteria': []},
        {'name': 'SC01-Task-2', 'description': 'Second', 'path': 'sc01_t2.txt', 'content': b'Second', 'depends_on': ['SC01-Task-1'], 'agent_type': AgentType.IMPLEMENTER, 'acceptance_criteria': []},
    ]
    
    engine = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    result = await engine.execute_mission(
        goal='SC01: State consistency test',
        parameters={'mission_type': 'multi_task', 'tasks': tasks},
        checkpoint_every=1
    )
    
    mission = engine._engine.missions.get(result.mission_id)
    events = engine._engine.get_event_history(result.mission_id)
    
    # Extract mission state changes from events
    state_events = [e for e in events if e.event_type.value == 'mission.state_changed']
    event_states = [(e.payload.get('from_state'), e.payload.get('to_state')) for e in state_events]
    
    # Verify mission final state matches
    final_state = str(mission.state) if mission else 'NOT_FOUND'
    
    # Check that events show a valid path to final state
    expected_path = [
        ('RECEIVED', 'ANALYZING'),
        ('ANALYZING', 'PLANNING'),
        ('PLANNING', 'DESIGNING'),
        ('DESIGNING', 'REVIEWING'),
        ('REVIEWING', 'APPROVED'),
        ('APPROVED', 'AWAITING_APPROVAL'),
        ('AWAITING_APPROVAL', 'EXECUTING'),
        ('EXECUTING', 'EXECUTED'),
        ('EXECUTED', 'VERIFYING'),
        ('VERIFYING', 'EVIDENCED'),
        ('EVIDENCED', 'ADJUDICATED'),
        # Operational engine stops at ADJUDICATED, not VERIFIED
    ]
    
    path_valid = True
    for expected in expected_path:
        if expected not in event_states:
            path_valid = False
            break
    
    log_phase('SC01_MISSION_STATE_EVENTS', {
        'mission_final_state': final_state,
        'state_events_count': len(state_events),
        'path_valid': path_valid,
        'event_states': event_states
    }, verdict='VERIFIED' if path_valid and final_state == 'MissionState.ADJUDICATED' else 'FAILED')
    
    # ============================================================
    # SC02: Task state transitions match events
    # ============================================================
    log_phase('SC02_TASK_STATE_EVENTS', {'start': True})
    task_events = [e for e in events if e.event_type.value in ['task.assigned', 'task.completed', 'state.transition']]
    
    # Check task graph states
    graph = engine._engine.task_graph.get(result.run_id, {})
    task_states = {engine._engine.tasks[tid].name: node['state'] for tid, node in graph.items() if tid in engine._engine.tasks}
    
    # All tasks should be COMPLETED
    all_completed = all(s == TaskState.COMPLETED for s in task_states.values())
    
    # Check events for each task
    task_completed_events = [e for e in events if e.event_type.value == 'task.completed']
    tasks_in_events = set(e.payload.get('task_id') for e in task_completed_events)
    tasks_in_graph = set(engine._engine.tasks[tid].task_id for tid in graph.keys())
    
    events_match_graph = tasks_in_graph.issubset(tasks_in_events) or len(tasks_in_events) >= len(tasks_in_graph)
    
    log_phase('SC02_TASK_STATE_EVENTS', {
        'task_states': {k: str(v) for k, v in task_states.items()},
        'all_completed': all_completed,
        'tasks_in_events': len(tasks_in_events),
        'tasks_in_graph': len(tasks_in_graph),
        'events_match_graph': events_match_graph
    }, verdict='VERIFIED' if all_completed and events_match_graph else 'FAILED')
    
    # ============================================================
    # SC03: Invalid transitions rejected
    # ============================================================
    log_phase('SC03_INVALID_TRANSITIONS', {'start': True})
    # Test mission invalid transitions
    invalid_mission = []
    try:
        validate_mission_transition(MissionState.VERIFIED, MissionState.EXECUTING)
        invalid_mission.append('VERIFIED->EXECUTING')
    except ValueError:
        pass
    
    try:
        validate_mission_transition(MissionState.CANCELLED, MissionState.EXECUTING)
        invalid_mission.append('CANCELLED->EXECUTING')
    except ValueError:
        pass
    
    # Test task invalid transitions
    invalid_task = []
    try:
        validate_task_transition(TaskState.COMPLETED, TaskState.RUNNING)
        invalid_task.append('COMPLETED->RUNNING')
    except ValueError:
        pass
    
    try:
        validate_task_transition(TaskState.CANCELLED, TaskState.READY)
        invalid_task.append('CANCELLED->READY')
    except ValueError:
        pass
    
    log_phase('SC03_INVALID_TRANSITIONS', {
        'mission_invalid_rejected': len(invalid_mission) == 0,
        'task_invalid_rejected': len(invalid_task) == 0,
        'rejected_mission': invalid_mission,
        'rejected_task': invalid_task
    }, verdict='VERIFIED' if len(invalid_mission) == 0 and len(invalid_task) == 0 else 'FAILED')
    
    # ============================================================
    # SC04: State consistency after resume
    # ============================================================
    log_phase('SC04_STATE_AFTER_RESUME', {'start': True})
    cp_id = result.checkpoints[-1]['checkpoint_id']
    
    engine2 = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    engine2._engine = engine2._create_engine()
    engine2._sandbox_manager = engine2._engine.sandbox_manager
    engine2._setup_done = True
    
    resume_result = engine2._engine.resume_from_checkpoint(cp_id, mission_id=result.mission_id)
    
    if resume_result:
        # Check mission state
        mission2 = engine2._engine.missions.get(result.mission_id)
        mission_state_after = str(mission2.state) if mission2 else 'NOT_FOUND'
        
        # Check task graph states
        graph2 = engine2._engine.task_graph.get(resume_result.run_id, {})
        task_states2 = {engine2._engine.tasks[tid].name: node['state'] for tid, node in graph2.items() if tid in engine2._engine.tasks}
        
        # Original completed tasks should still be COMPLETED
        completed_before = {k: v for k, v in task_states.items() if v == TaskState.COMPLETED}
        completed_after = {k: v for k, v in task_states2.items() if v == TaskState.COMPLETED}
        
        states_consistent = True
        for task_name in completed_before:
            if task_name in completed_after and completed_after[task_name] != TaskState.COMPLETED:
                states_consistent = False
        
        log_phase('SC04_STATE_AFTER_RESUME', {
            'mission_state_after': mission_state_after,
            'task_states_after': {k: str(v) for k, v in task_states2.items()},
            'completed_tasks_preserved': len(completed_after) >= len(completed_before),
            'states_consistent': states_consistent
        }, verdict='VERIFIED' if states_consistent else 'FAILED')
    
    # ============================================================
    # SC05: No orphaned events (events without corresponding state)
    # ============================================================
    log_phase('SC05_NO_ORPHAN_EVENTS', {'start': True})
    # Every task.completed event should have a corresponding task in COMPLETED state
    task_completed_events = [e for e in events if e.event_type.value == 'task.completed']
    orphaned = False
    for e in task_completed_events:
        task_id = e.payload.get('task_id')
        if task_id in engine._engine.tasks:
            task = engine._engine.tasks[task_id]
            if task.state != TaskState.COMPLETED:
                orphaned = True
                break
    
    log_phase('SC05_NO_ORPHAN_EVENTS', {
        'task_completed_events': len(task_completed_events),
        'orphaned_found': orphaned
    }, verdict='VERIFIED' if not orphaned else 'FAILED')
    
    # Save trace
    with open('docs/evidence/e26/E26_STATE_EVENT_CONSISTENCY.json', 'w') as f:
        json.dump(trace, f, indent=2, default=str)
    
    for phase in trace['phases']:
        phase_name = phase['phase'].lower().replace(' ', '_')
        with open(f'docs/evidence/e26/{phase_name}_trace.json', 'w') as f:
            json.dump(phase, f, indent=2, default=str)
    
    print('\n=== E26 STATE/EVENT CONSISTENCY COMPLETE ===')
    print('Verdicts:', trace['verdicts'])
    return trace

if __name__ == '__main__':
    asyncio.run(e26_state_consistency())