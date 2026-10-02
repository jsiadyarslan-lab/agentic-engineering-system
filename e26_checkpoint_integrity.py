"""
E26 — CHECKPOINT INTEGRITY TEST
Verify checkpoint durability and integrity.
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
from unified.contracts import AgentType

async def e26_checkpoint_integrity():
    trace = {
        'timestamp': '2026-10-03T01:00:00.000000+00:00',
        'test_name': 'E26_CHECKPOINT_INTEGRITY',
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
    # CP01: Checkpoint contains complete task graph state
    # ============================================================
    log_phase('CP01_CHECKPOINT_COMPLETENESS', {'start': True})
    tasks = [
        {'name': 'CP01-Task-1', 'description': 'First', 'path': 'cp01_t1.txt', 'content': b'First', 'depends_on': [], 'agent_type': AgentType.IMPLEMENTER, 'acceptance_criteria': []},
        {'name': 'CP01-Task-2', 'description': 'Second', 'path': 'cp01_t2.txt', 'content': b'Second', 'depends_on': ['CP01-Task-1'], 'agent_type': AgentType.IMPLEMENTER, 'acceptance_criteria': []},
        {'name': 'CP01-Task-3', 'description': 'Third', 'path': 'cp01_t3.txt', 'content': b'Third', 'depends_on': ['CP01-Task-2'], 'agent_type': AgentType.IMPLEMENTER, 'acceptance_criteria': []},
    ]
    
    engine = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    result = await engine.execute_mission(
        goal='CP01: Checkpoint completeness',
        parameters={'mission_type': 'multi_task', 'tasks': tasks},
        checkpoint_every=1
    )
    
    # Check checkpoint contents
    checkpoints = result.checkpoints
    last_cp = checkpoints[-1]
    
    cp_fields = ['checkpoint_id', 'mission_id', 'run_id', 'task_states', 'attempt_history', 'agent_assignments', 'created_at']
    all_fields_present = all(f in last_cp for f in cp_fields)
    
    # Check task_states has all 3 tasks
    task_states = last_cp.get('task_states', {})
    all_tasks_in_cp = len(task_states) == 3
    
    log_phase('CP01_CHECKPOINT_COMPLETENESS', {
        'all_fields_present': all_fields_present,
        'all_tasks_in_cp': all_tasks_in_cp,
        'task_states': task_states
    }, verdict='VERIFIED' if all_fields_present and all_tasks_in_cp else 'FAILED')
    
    # ============================================================
    # CP02: Checkpoint can be serialized and deserialized
    # ============================================================
    log_phase('CP02_CHECKPOINT_SERIALIZATION', {'start': True})
    # Checkpoints are saved to disk - verify they can be loaded
    cp_id = last_cp['checkpoint_id']
    
    # Simulate process death - new engine
    engine2 = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    engine2._engine = engine2._create_engine()
    engine2._sandbox_manager = engine2._engine.sandbox_manager
    engine2._setup_done = True
    
    resume_result = engine2._engine.resume_from_checkpoint(cp_id, mission_id=result.mission_id)
    
    log_phase('CP02_CHECKPOINT_SERIALIZATION', {
        'resume_success': resume_result is not None,
        'run_id_restored': resume_result.run_id if resume_result else None,
        'task_graph_restored': len(engine2._engine.task_graph.get(resume_result.run_id, {})) == 3 if resume_result else False
    }, verdict='VERIFIED' if resume_result and len(engine2._engine.task_graph.get(resume_result.run_id, {})) == 3 else 'FAILED')
    
    # ============================================================
    # CP03: Checkpoint task states match actual execution state
    # ============================================================
    log_phase('CP03_CHECKPOINT_STATE_ACCURACY', {'start': True})
    # Resume and check states match
    if resume_result:
        graph = engine2._engine.task_graph.get(resume_result.run_id, {})
        restored_states = {engine2._engine.tasks[tid].name: node['state'] for tid, node in graph.items() if tid in engine2._engine.tasks}
        original_states = last_cp.get('task_states', {})
        
        # Original states used task names as keys in checkpoint
        states_match = True
        for task_name, expected_state in original_states.items():
            if task_name in restored_states and str(restored_states[task_name]) != expected_state:
                states_match = False
                break
        
        log_phase('CP03_CHECKPOINT_STATE_ACCURACY', {
            'original_states': original_states,
            'restored_states': {k: str(v) for k, v in restored_states.items()},
            'states_match': states_match
        }, verdict='VERIFIED' if states_match else 'FAILED')
    
    # ============================================================
    # CP04: Checkpoint includes evidence store reference
    # ============================================================
    log_phase('CP04_CHECKPOINT_EVIDENCE', {'start': True})
    # Evidence store should be persisted separately
    artifacts_before = len(engine._engine.evidence_store._artifacts)
    
    # After resume, artifacts should be available
    artifacts_after = len(engine2._engine.evidence_store._artifacts)
    
    log_phase('CP04_CHECKPOINT_EVIDENCE', {
        'artifacts_before_resume': artifacts_before,
        'artifacts_after_resume': artifacts_after,
        'evidence_preserved': artifacts_after >= artifacts_before
    }, verdict='VERIFIED' if artifacts_after >= artifacts_before else 'FAILED')
    
    # ============================================================
    # CP05: Checkpoint corruption detection
    # ============================================================
    log_phase('CP05_CHECKPOINT_CORRUPTION', {'start': True})
    # Try to resume from non-existent checkpoint
    engine3 = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    engine3._engine = engine3._create_engine()
    engine3._sandbox_manager = engine3._engine.sandbox_manager
    engine3._setup_done = True
    
    bad_resume = engine3._engine.resume_from_checkpoint('non-existent-checkpoint-id', mission_id=result.mission_id)
    
    log_phase('CP05_CHECKPOINT_CORRUPTION', {
        'bad_checkpoint_rejected': bad_resume is None
    }, verdict='VERIFIED' if bad_resume is None else 'FAILED')
    
    # Save trace
    with open('docs/evidence/e26/E26_CHECKPOINT_INTEGRITY.json', 'w') as f:
        json.dump(trace, f, indent=2, default=str)
    
    for phase in trace['phases']:
        phase_name = phase['phase'].lower().replace(' ', '_')
        with open(f'docs/evidence/e26/{phase_name}_trace.json', 'w') as f:
            json.dump(phase, f, indent=2, default=str)
    
    print('\n=== E26 CHECKPOINT INTEGRITY COMPLETE ===')
    print('Verdicts:', trace['verdicts'])
    return trace

if __name__ == '__main__':
    asyncio.run(e26_checkpoint_integrity())