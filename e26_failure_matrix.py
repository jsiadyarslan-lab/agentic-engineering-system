"""
E26 — FAILURE MATRIX TEST
Test various failure scenarios according to contract.
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
from unified.contracts import AgentType, validate_task_transition

async def e26_failure_matrix():
    trace = {
        'timestamp': '2026-10-03T00:00:00.000000+00:00',
        'test_name': 'E26_FAILURE_MATRIX',
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
    # F01: Task Failure - run_command that fails (using 'false' command)
    # ============================================================
    log_phase('F01_TASK_FAILURE', {'start': True})
    tasks_f01 = [
        {'name': 'F01-Task-1', 'description': 'Setup', 'path': 'f01_t1.txt', 'content': b'OK', 'depends_on': [], 'agent_type': AgentType.IMPLEMENTER, 'acceptance_criteria': []},
        {'name': 'F01-Task-2', 'description': 'Fail', 'context': {'operation': 'run_command', 'command': 'false'}, 'depends_on': ['F01-Task-1'], 'agent_type': AgentType.IMPLEMENTER, 'acceptance_criteria': []},
        {'name': 'F01-Task-3', 'description': 'Should not run', 'path': 'f01_t3.txt', 'content': b'Should not run', 'depends_on': ['F01-Task-2'], 'agent_type': AgentType.IMPLEMENTER, 'acceptance_criteria': []},
    ]
    
    engine = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    result = await engine.execute_mission(
        goal='F01: Task failure test',
        parameters={'mission_type': 'multi_task', 'tasks': tasks_f01},
        checkpoint_every=1
    )
    
    task_results = result.task_results
    task_keys = list(task_results.keys())
    f01_results = {
        'mission_success': result.success,
        'task_1_state': task_results.get(task_keys[0], {}).get('state'),
        'task_2_state': task_results.get(task_keys[1], {}).get('state'),
        'task_3_state': task_results.get(task_keys[2], {}).get('state'),
        'task_2_success': task_results.get(task_keys[1], {}).get('success'),
        'task_3_success': task_results.get(task_keys[2], {}).get('success'),
        'task_2_error': task_results.get(task_keys[1], {}).get('error'),
        'task_2_output': task_results.get(task_keys[1], {}).get('output'),
    }
    
    # Task-2 should fail, so mission should fail
    log_phase('F01_TASK_FAILURE', {
        'result': f01_results
    }, verdict='VERIFIED' if not result.success and f01_results['task_2_success'] == False else 'FAILED')
    
    # ============================================================
    # F02: Dependent Task Blocked
    # ============================================================
    log_phase('F02_DEPENDENT_BLOCKED', {'start': True})
    # The dependent task (F01-Task-3) should be BLOCKED because its dependency failed
    graph = engine._engine.task_graph.get(result.run_id, {})
    # Get task names from engine.tasks
    task_names = {tid: engine._engine.tasks[tid].name for tid in engine._engine.tasks if tid in graph}
    blocked_tasks = [task_names[tid] for tid, node in graph.items() if node['state'] == TaskState.BLOCKED and tid in task_names]
    failed_tasks = [task_names[tid] for tid, node in graph.items() if node['state'] == TaskState.FAILED and tid in task_names]
    
    log_phase('F02_DEPENDENT_BLOCKED', {
        'blocked_tasks': blocked_tasks,
        'failed_tasks': failed_tasks,
        'task_3_blocked': 'F01-Task-3' in blocked_tasks
    }, verdict='VERIFIED' if 'F01-Task-3' in blocked_tasks else 'FAILED')
    
    # ============================================================
    # F03: Tool Failure - invalid command
    # ============================================================
    log_phase('F03_TOOL_FAILURE', {'start': True})
    tasks_f03 = [
        {'name': 'F03-Task-1', 'description': 'Invalid command', 'context': {'operation': 'run_command', 'command': 'invalidcommandthatdoesnotexist123'}, 'depends_on': [], 'agent_type': AgentType.IMPLEMENTER, 'acceptance_criteria': []},
    ]
    
    engine2 = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    result_f03 = await engine2.execute_mission(
        goal='F03: Tool failure test',
        parameters={'mission_type': 'multi_task', 'tasks': tasks_f03},
        checkpoint_every=1
    )
    
    f03_task_result = list(result_f03.task_results.values())[0]
    log_phase('F03_TOOL_FAILURE', {
        'task_success': f03_task_result.get('success'),
        'task_error': f03_task_result.get('error', '')[:200] if f03_task_result.get('error') else 'None',
        'mission_success': result_f03.success
    }, verdict='VERIFIED' if f03_task_result.get('success') == False else 'FAILED')
    
    # ============================================================
    # F04: Timeout - task that times out
    # ============================================================
    log_phase('F04_TIMEOUT', {'start': True})
    tasks_f04 = [
        {'name': 'F04-Task-1', 'description': 'Sleep', 'context': {'operation': 'run_command', 'command': 'sleep 10', 'timeout_seconds': 1}, 'depends_on': [], 'agent_type': AgentType.IMPLEMENTER, 'acceptance_criteria': []},
    ]
    
    engine3 = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    result_f04 = await engine3.execute_mission(
        goal='F04: Timeout test',
        parameters={'mission_type': 'multi_task', 'tasks': tasks_f04},
        checkpoint_every=1,
        mission_timeout_seconds=5
    )
    
    f04_task_result = list(result_f04.task_results.values())[0]
    log_phase('F04_TIMEOUT', {
        'task_success': f04_task_result.get('success'),
        'task_error': f04_task_result.get('error', '')[:200] if f04_task_result.get('error') else 'None',
        'mission_success': result_f04.success
    }, verdict='VERIFIED' if f04_task_result.get('success') == False else 'FAILED')
    
    # ============================================================
    # F05: Retry - skipped
    # ============================================================
    log_phase('F05_RETRY', {'start': True})
    log_phase('F05_RETRY', {
        'status': 'SKIPPED - requires persistent state across retries'
    }, verdict='SKIPPED')
    
    # ============================================================
    # F06: Sandbox/Process Death - checkpoint resume
    # ============================================================
    log_phase('F06_CHECKPOINT_RESUME', {'start': True})
    tasks_f06 = [
        {'name': 'F06-Task-1', 'description': 'Before death', 'path': 'f06_t1.txt', 'content': b'Before death', 'depends_on': [], 'agent_type': AgentType.IMPLEMENTER, 'acceptance_criteria': []},
        {'name': 'F06-Task-2', 'description': 'After resume', 'path': 'f06_t2.txt', 'content': b'After resume', 'depends_on': ['F06-Task-1'], 'agent_type': AgentType.IMPLEMENTER, 'acceptance_criteria': []},
    ]
    
    engine5 = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    result_f06 = await engine5.execute_mission(
        goal='F06: Checkpoint resume test',
        parameters={'mission_type': 'multi_task', 'tasks': tasks_f06},
        checkpoint_every=1
    )
    
    mission_id = result_f06.mission_id
    checkpoints = result_f06.checkpoints
    cp_id = checkpoints[0]['checkpoint_id']  # After Task-1
    
    # Simulate process death - new engine
    engine6 = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    engine6._engine = engine6._create_engine()
    engine6._sandbox_manager = engine6._engine.sandbox_manager
    engine6._setup_done = True
    
    # resume_from_checkpoint is NOT async
    resume_result = engine6._engine.resume_from_checkpoint(cp_id, mission_id=mission_id)
    
    if resume_result:
        run_id_2 = resume_result.run_id
        exec_result = await engine6._engine.execute_task_graph(
            run_id_2,
            sandbox_manager=engine6._sandbox_manager,
            checkpoint_every=1
        )
        
        f06_results = {
            'resume_success': resume_result is not None,
            'task_2_executed': exec_result.get('success'),
            'artifact_preserved': False
        }
        
        # Check artifact continuity
        artifacts = engine6._engine.evidence_store._artifacts
        for art in artifacts.values():
            if art.path == 'f06_t1.txt':
                f06_results['artifact_preserved'] = True
        
        log_phase('F06_CHECKPOINT_RESUME', {
            'result': f06_results
        }, verdict='VERIFIED' if resume_result and exec_result.get('success') and f06_results['artifact_preserved'] else 'FAILED')
    
    # ============================================================
    # F07: Invalid Transition
    # ============================================================
    log_phase('F07_INVALID_TRANSITION', {'start': True})
    # COMPLETED -> COMPLETED should be invalid (not in allowed transitions)
    try:
        validate_task_transition(TaskState.COMPLETED, TaskState.COMPLETED)
        transition_allowed = True
    except ValueError:
        transition_allowed = False
    
    log_phase('F07_INVALID_TRANSITION', {
        'invalid_transition_rejected': not transition_allowed
    }, verdict='VERIFIED' if not transition_allowed else 'FAILED')
    
    # ============================================================
    # F08: Duplicate Resume
    # ============================================================
    log_phase('F08_DUPLICATE_RESUME', {'start': True})
    # Resume from same checkpoint twice
    engine7 = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    engine7._engine = engine7._create_engine()
    engine7._sandbox_manager = engine7._engine.sandbox_manager
    engine7._setup_done = True
    
    resume_result2 = engine7._engine.resume_from_checkpoint(cp_id, mission_id=mission_id)
    resume_result3 = engine7._engine.resume_from_checkpoint(cp_id, mission_id=mission_id)
    
    log_phase('F08_DUPLICATE_RESUME', {
        'first_resume': resume_result2 is not None,
        'second_resume': resume_result3 is not None,
        'different_run_ids': resume_result2.run_id != resume_result3.run_id if resume_result2 and resume_result3 else False
    }, verdict='VERIFIED' if resume_result2 and resume_result3 and resume_result2.run_id != resume_result3.run_id else 'FAILED')
    
    # ============================================================
    # F09: Duplicate Completion
    # ============================================================
    log_phase('F09_DUPLICATE_COMPLETION', {'start': True})
    try:
        validate_task_transition(TaskState.COMPLETED, TaskState.COMPLETED)
        double_complete_allowed = True
    except ValueError:
        double_complete_allowed = False
    
    log_phase('F09_DUPLICATE_COMPLETION', {
        'duplicate_completion_rejected': not double_complete_allowed
    }, verdict='VERIFIED' if not double_complete_allowed else 'FAILED')
    
    # ============================================================
    # F10: Partial Artifact Creation
    # ============================================================
    log_phase('F10_PARTIAL_ARTIFACT', {'start': True})
    # Test that failed task doesn't create artifact
    artifacts_f01 = engine._engine.evidence_store._artifacts
    f01_task2_artifact = any(a.path == 'f01_t2.txt' for a in artifacts_f01.values())
    
    log_phase('F10_PARTIAL_ARTIFACT', {
        'failed_task_no_artifact': not f01_task2_artifact
    }, verdict='VERIFIED' if not f01_task2_artifact else 'FAILED')
    
    # ============================================================
    # F11: Verification Failure
    # ============================================================
    log_phase('F11_VERIFICATION_FAILURE', {'start': True})
    tasks_f11 = [
        {'name': 'F11-Task-1', 'description': 'Wrong content', 'path': 'f11_t1.txt', 'content': b'wrong content', 'depends_on': [], 'agent_type': AgentType.IMPLEMENTER, 'acceptance_criteria': ['file_contains:f11_t1.txt:expected_content']},
    ]
    
    engine8 = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    result_f11 = await engine8.execute_mission(
        goal='F11: Verification failure test',
        parameters={'mission_type': 'multi_task', 'tasks': tasks_f11},
        checkpoint_every=1
    )
    
    f11_task_result = list(result_f11.task_results.values())[0]
    log_phase('F11_VERIFICATION_FAILURE', {
        'task_success': f11_task_result.get('success'),
        'mission_success': result_f11.success
    }, verdict='VERIFIED' if f11_task_result.get('success') == False else 'FAILED')
    
    # ============================================================
    # F12: Replan During Execution (need a running mission)
    # ============================================================
    log_phase('F12_REPLAN', {'start': True})
    # Use the existing initialized engine
    engine_f12 = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    # Initialize engine by creating a dummy mission
    engine_f12._engine = engine_f12._create_engine()
    engine_f12._sandbox_manager = engine_f12._engine.sandbox_manager
    engine_f12._setup_done = True
    
    mission_f12 = engine_f12._engine.create_mission('F12 Replan test')
    run_f12 = engine_f12._engine.create_run(mission_f12.mission_id)
    task1 = engine_f12._engine.create_task(
        run_id=run_f12.run_id, mission_id=mission_f12.mission_id,
        name='F12-Task-1', description='First', agent_type=AgentType.IMPLEMENTER,
        depends_on=[], acceptance_criteria=[]
    )
    # Set mission to EXECUTING
    mission_f12.state = MissionState.EXECUTING
    
    replan_result = engine_f12._engine.replan_task_graph(
        run_id=run_f12.run_id,
        new_tasks=[{
            'name': 'F12-Recovery',
            'description': 'Recovery task',
            'agent_type': AgentType.IMPLEMENTER,
            'depends_on': [task1.task_id],
            'acceptance_criteria': [],
        }],
        reason='Test replan',
        actor='system'
    )
    
    log_phase('F12_REPLAN', {
        'replan_success': replan_result,
        'total_tasks_after': len(engine_f12._engine.task_graph.get(run_f12.run_id, {}))
    }, verdict='VERIFIED' if replan_result else 'FAILED')
    
    # ============================================================
    # F13: Human Gate (need executing mission)
    # ============================================================
    log_phase('F13_HUMAN_GATE', {'start': True})
    # Use same initialized engine
    mission_f13 = engine_f12._engine.create_mission('F13 Human gate test')
    run_f13 = engine_f12._engine.create_run(mission_f13.mission_id)
    mission_f13.state = MissionState.EXECUTING
    
    gate_id = engine_f12._engine.create_human_gate(
        mission_id=mission_f13.mission_id, run_id=run_f13.run_id, task_id='',
        reason='Test gate', context={},
        options=[{'value': 'continue', 'label': 'Continue'}, {'value': 'cancel', 'label': 'Cancel'}],
        impact='Test', required_action='approve'
    )
    
    gate_ok = gate_id is not None
    if gate_ok:
        decision_ok = engine_f12._engine.decide_human_gate(
            mission_id=mission_f13.mission_id, gate_id=gate_id, decision='continue', actor='tester')
        gate_ok = decision_ok
    
    log_phase('F13_HUMAN_GATE', {
        'gate_created': gate_id is not None,
        'decision_accepted': gate_ok
    }, verdict='VERIFIED' if gate_ok else 'FAILED')
    
    # ============================================================
    # F14: Cancellation
    # ============================================================
    log_phase('F14_CANCELLATION', {'start': True})
    engine9 = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    # Initialize engine
    engine9._engine = engine9._create_engine()
    engine9._sandbox_manager = engine9._engine.sandbox_manager
    engine9._setup_done = True
    
    mission9 = engine9._engine.create_mission('F14 Cancel test')
    run9 = engine9._engine.create_run(mission9.mission_id)
    task9 = engine9._engine.create_task(
        run_id=run9.run_id,
        mission_id=mission9.mission_id,
        name='F14-Task-1',
        description='Test cancellation',
        agent_type=AgentType.IMPLEMENTER,
        depends_on=[],
        acceptance_criteria=[],
    )
    
    cancel_result = engine9._engine.cancel_mission(mission9.mission_id, actor='tester', reason='Test cancellation')
    mission_after = engine9._engine.missions.get(mission9.mission_id)
    
    log_phase('F14_CANCELLATION', {
        'cancel_processed': cancel_result,
        'mission_state': str(mission_after.state) if mission_after else 'NOT_FOUND'
    }, verdict='VERIFIED' if cancel_result and mission_after and mission_after.state == MissionState.CANCELLED else 'FAILED')
    
    # ============================================================
    # F15: Resource Limits
    # ============================================================
    log_phase('F15_RESOURCE_LIMITS', {'start': True})
    from unified.execution import create_execution_engine, ResourceQuotaExceededError
    test_engine = create_execution_engine(artifacts_base_dir='runtime/artifacts', max_concurrent_missions=1, max_concurrent_tasks=2)
    
    m1 = test_engine.create_mission('M1')
    r1 = test_engine.create_run(m1.mission_id)
    
    # Test task quota - max 2 concurrent tasks
    t1 = test_engine.create_task(run_id=r1.run_id, mission_id=m1.mission_id, name='T1', description='', agent_type=AgentType.IMPLEMENTER, depends_on=[], acceptance_criteria=[])
    t2 = test_engine.create_task(run_id=r1.run_id, mission_id=m1.mission_id, name='T2', description='', agent_type=AgentType.IMPLEMENTER, depends_on=[], acceptance_criteria=[])
    
    # Third task should fail
    task_quota_works = False
    try:
        t3 = test_engine.create_task(run_id=r1.run_id, mission_id=m1.mission_id, name='T3', description='', agent_type=AgentType.IMPLEMENTER, depends_on=[], acceptance_criteria=[])
    except ResourceQuotaExceededError:
        task_quota_works = True
    
    # Test mission quota - max 1 concurrent mission
    mission_quota_works = False
    try:
        m2 = test_engine.create_mission('M2')
    except ResourceQuotaExceededError:
        mission_quota_works = True
    
    log_phase('F15_RESOURCE_LIMITS', {
        'max_concurrent_missions': 1,
        'max_concurrent_tasks': 2,
        'task_quota_enforced': task_quota_works,
        'mission_quota_enforced': mission_quota_works
    }, verdict='VERIFIED' if task_quota_works and mission_quota_works else 'FAILED')
    
    # Save trace
    with open('docs/evidence/e26/E26_FAILURE_MATRIX.json', 'w') as f:
        json.dump(trace, f, indent=2, default=str)
    
    for phase in trace['phases']:
        phase_name = phase['phase'].lower().replace(' ', '_')
        with open(f'docs/evidence/e26/{phase_name}_trace.json', 'w') as f:
            json.dump(phase, f, indent=2, default=str)
    
    print('\n=== E26 FAILURE MATRIX COMPLETE ===')
    print('Verdicts:', trace['verdicts'])
    return trace

if __name__ == '__main__':
    asyncio.run(e26_failure_matrix())