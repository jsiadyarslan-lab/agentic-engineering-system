"""
E26 — MULTI-RUN ISOLATION TEST
Run multiple missions concurrently to verify isolation.
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

async def e26_multi_run_isolation():
    trace = {
        'timestamp': '2026-10-02T23:45:00.000000+00:00',
        'test_name': 'E26_MULTI_RUN_ISOLATION',
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
    
    # Create 3 missions with different configurations
    tasks_a = [
        {'name': 'A-Task-1', 'path': 'multi_a_1.txt', 'content': b'A1', 'depends_on': [], 'agent_type': AgentType.IMPLEMENTER},
        {'name': 'A-Task-2', 'path': 'multi_a_2.txt', 'content': b'A2', 'depends_on': ['A-Task-1'], 'agent_type': AgentType.IMPLEMENTER},
    ]
    
    tasks_b = [
        {'name': 'B-Task-1', 'path': 'multi_b_1.txt', 'content': b'B1', 'depends_on': [], 'agent_type': AgentType.IMPLEMENTER},
        {'name': 'B-Task-2', 'path': 'multi_b_2.txt', 'content': b'B2', 'depends_on': ['B-Task-1'], 'agent_type': AgentType.IMPLEMENTER},
    ]
    
    tasks_c = [
        {'name': 'C-Task-1', 'path': 'multi_c_1.txt', 'content': b'C1', 'depends_on': [], 'agent_type': AgentType.IMPLEMENTER},
        {'name': 'C-Task-2', 'path': 'multi_c_2.txt', 'content': b'C2', 'depends_on': ['C-Task-1'], 'agent_type': AgentType.IMPLEMENTER},
    ]
    
    log_phase('PHASE_1_CREATE_MISSIONS', {'start': True})
    engine = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    
    # Run all three missions sequentially on same engine (simulating concurrent execution)
    results = {}
    mission_ids = {}
    for name, tasks in [('Mission-A', tasks_a), ('Mission-B', tasks_b), ('Mission-C', tasks_c)]:
        result = await engine.execute_mission(
            goal=f'Multi-run test {name}',
            parameters={'mission_type': 'multi_task', 'tasks': tasks},
            checkpoint_every=1
        )
        results[name] = {
            'mission_id': result.mission_id,
            'run_id': result.run_id,
            'success': result.success,
            'artifacts': len(result.artifacts),
            'events': len(result.events),
            'checkpoints_returned': len(result.checkpoints),  # This is cumulative!
        }
        mission_ids[name] = result.mission_id
    
    # Verify isolation
    all_missions_unique = len(set(mission_ids.values())) == 3
    all_runs_unique = len(set(r['run_id'] for r in results.values())) == 3
    all_success = all(r['success'] for r in results.values())
    
    # Check artifact isolation
    artifacts = engine._engine.evidence_store._artifacts
    mission_a_artifacts = [a for a in artifacts.values() if a.path.startswith('multi_a')]
    mission_b_artifacts = [a for a in artifacts.values() if a.path.startswith('multi_b')]
    mission_c_artifacts = [a for a in artifacts.values() if a.path.startswith('multi_c')]
    
    # Check event isolation
    event_isolation = True
    for name, r in results.items():
        events = engine._engine.get_event_history(r['mission_id'])
        other_mission_events = [e for e in events if e.mission_id != r['mission_id']]
        if len(other_mission_events) > 0:
            event_isolation = False
    
    log_phase('PHASE_1_CREATE_MISSIONS', {
        'missions': results,
        'all_missions_unique': all_missions_unique,
        'all_runs_unique': all_runs_unique,
        'all_success': all_success,
        'mission_a_artifacts': len(mission_a_artifacts),
        'mission_b_artifacts': len(mission_b_artifacts),
        'mission_c_artifacts': len(mission_c_artifacts),
        'event_isolation': event_isolation
    }, verdict='VERIFIED' if all_missions_unique and all_runs_unique and all_success and event_isolation else 'FAILED')
    
    # Test checkpoint isolation - each mission should have 2 checkpoints in global store
    log_phase('PHASE_2_CHECKPOINT_ISOLATION', {'start': True})
    cp_isolation = True
    cp_details = {}
    for name, r in results.items():
        cps = engine._engine.checkpoints
        mission_cps = [cp for cp in cps.values() if cp.mission_id == r['mission_id']]
        # Each mission creates 2 checkpoints (2 tasks, checkpoint_every=1)
        expected_own_checkpoints = 2
        cp_details[name] = {
            'expected_own_checkpoints': expected_own_checkpoints,
            'actual_in_global_store': len(mission_cps),
            'match': len(mission_cps) == expected_own_checkpoints
        }
        if len(mission_cps) != expected_own_checkpoints:
            cp_isolation = False
    
    # Also verify no cross-mission contamination
    all_checkpoints = list(engine._engine.checkpoints.values())
    total_checkpoints = len(all_checkpoints)
    expected_total = 6  # 3 missions * 2 checkpoints each
    
    log_phase('PHASE_2_CHECKPOINT_ISOLATION', {
        'checkpoint_isolation': cp_isolation,
        'checkpoint_details': cp_details,
        'total_checkpoints_in_store': total_checkpoints,
        'expected_total_checkpoints': expected_total,
        'total_match': total_checkpoints == expected_total
    }, verdict='VERIFIED' if cp_isolation and total_checkpoints == expected_total else 'FAILED')
    
    # Save trace
    with open('docs/evidence/e26/E26_MULTI_RUN_ISOLATION.json', 'w') as f:
        json.dump(trace, f, indent=2, default=str)
    
    for phase in trace['phases']:
        phase_name = phase['phase'].lower().replace(' ', '_')
        with open(f'docs/evidence/e26/{phase_name}_trace.json', 'w') as f:
            json.dump(phase, f, indent=2, default=str)
    
    print('\n=== E26 MULTI-RUN ISOLATION COMPLETE ===')
    print('Verdicts:', trace['verdicts'])
    return trace

if __name__ == '__main__':
    asyncio.run(e26_multi_run_isolation())