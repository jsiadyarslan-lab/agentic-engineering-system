"""
E25 — DURABLE LONG-RUN MISSION
Full integration test: multi-task mission with failure, replan, checkpoint, process death, resume, continuation, verification.
"""

import asyncio
import sys
import json
import time
import os
import hashlib
sys.path.insert(0, 'src')

from unified.operational import OperationalExecutionEngine
from unified.execution import ExecutionEngine
from unified.domain_model import MissionState, TaskState
from unified.contracts import validate_mission_transition, AgentType, new_mission_id, new_run_id, new_task_id

async def e25_long_run_mission():
    trace = {
        'timestamp': '2026-10-03T00:00:00.000000+00:00',
        'mission_name': 'E25-LONG-RUN',
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
    # PHASE 1: Initial Mission Execution (5 tasks with dependencies)
    # ============================================================
    # Task-001: Setup (no deps) - write file
    # Task-002: DataPrep (depends on Task-001) - write file
    # Task-003: Process (depends on Task-002) - run_command THAT FAILS
    # Task-004: Validate (depends on Task-003) - write file
    # Task-005: Finalize (depends on Task-004) - write file
    
    tasks_config = [
        {
            'name': 'Task-001-Setup', 
            'path': 'e25_task001_setup.txt', 
            'content': b'Setup complete', 
            'depends_on': [], 
            'agent_type': AgentType.IMPLEMENTER,
            'acceptance_criteria': ['file_exists:e25_task001_setup.txt']
        },
        {
            'name': 'Task-002-DataPrep', 
            'path': 'e25_task002_dataprep.txt', 
            'content': b'Data prepared', 
            'depends_on': ['Task-001-Setup'], 
            'agent_type': AgentType.IMPLEMENTER,
            'acceptance_criteria': ['file_exists:e25_task002_dataprep.txt']
        },
        {
            'name': 'Task-003-Process', 
            'operation': 'run_command',
            'command': 'cmd /c exit 1',  # This will fail on Windows
            'depends_on': ['Task-002-DataPrep'], 
            'agent_type': AgentType.IMPLEMENTER,
            'acceptance_criteria': []  # No acceptance criteria for failing task
        },
        {
            'name': 'Task-004-Validate', 
            'path': 'e25_task004_validate.txt', 
            'content': b'Validation complete', 
            'depends_on': ['Task-003-Process'], 
            'agent_type': AgentType.IMPLEMENTER,
            'acceptance_criteria': ['file_exists:e25_task004_validate.txt']
        },
        {
            'name': 'Task-005-Finalize', 
            'path': 'e25_task005_finalize.txt', 
            'content': b'Finalized', 
            'depends_on': ['Task-004-Validate'], 
            'agent_type': AgentType.IMPLEMENTER,
            'acceptance_criteria': ['file_exists:e25_task005_finalize.txt']
        },
    ]
    
    log_phase('PHASE_1_INITIAL_EXECUTION', {'start': True, 'tasks': [t['name'] for t in tasks_config]})
    engine1 = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    result1 = await engine1.execute_mission(
        goal='E25 Long-run mission test',
        parameters={
            'mission_type': 'multi_task',
            'tasks': tasks_config
        },
        checkpoint_every=1
    )
    
    mission_id = result1.mission_id
    run_id_1 = result1.run_id
    
    # Capture artifact state from evidence store
    artifacts_1 = {}
    for art in engine1._engine.evidence_store._artifacts.values():
        if art.path.startswith('e25_task'):
            artifacts_1[art.path] = {
                'artifact_id': art.artifact_id,
                'sha256': art.sha256,
                'size_bytes': art.size_bytes,
                'mission_id': art.mission_id
            }
    
    # Capture evidence
    evidence_1 = {}
    for ev in engine1._engine.evidence_store._evidence.values():
        if ev.artifact_id in [a['artifact_id'] for a in artifacts_1.values()]:
            evidence_1[ev.evidence_id] = {
                'artifact_id': ev.artifact_id,
                'criterion': ev.criterion,
                'verdict': ev.verdict,
                'checks_performed': ev.checks_performed,
                'sha256_verified': ev.sha256_verified
            }
    
    event_count_1 = len(result1.events)
    checkpoints_1 = result1.checkpoints
    # Use checkpoint after Task-003 (index 2, 0-based)
    checkpoint_id = checkpoints_1[2]['checkpoint_id']
    
    # Track which tasks were completed before this checkpoint
    # Checkpoint at index 2 is after Task-003, so Task-001, 002, 003 were completed/attempted
    tasks_completed_before_cp = {'Task-001-Setup', 'Task-002-DataPrep', 'Task-003-Process'}
    
    log_phase('PHASE_1_INITIAL_EXECUTION', {
        'mission_id': mission_id,
        'run_id': run_id_1,
        'success': result1.success,
        'artifacts_created': len(artifacts_1),
        'artifact_details': artifacts_1,
        'evidence_created': len(evidence_1),
        'verifications': len(result1.verifications),
        'events_emitted': event_count_1,
        'checkpoints_created': len(checkpoints_1),
        'checkpoint_for_resume': checkpoint_id,
        'tasks_completed_before_checkpoint': list(tasks_completed_before_cp),
        'task_results': {tid: {'state': tr.get('state', 'UNKNOWN'), 'success': tr.get('success', False), 'attempts': tr.get('attempts', 0), 'error': str(tr.get('error', ''))[:200]} for tid, tr in result1.task_results.items()}
    }, verdict='VERIFIED' if len(artifacts_1) >= 3 else 'FAILED')
    
    # ============================================================
    # PHASE 2: PROCESS DEATH (simulated by new engine instance)
    # ============================================================
    log_phase('PHASE_2_PROCESS_DEATH', {'simulated': True, 'new_engine_instance': True})
    
    # ============================================================
    # PHASE 3: FIRST RESTART - Resume from checkpoint (using ExecutionEngine directly)
    # ============================================================
    log_phase('PHASE_3_RESTART_1_RESUME', {'start': True})
    engine2 = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
    engine2._engine = engine2._create_engine()
    engine2._sandbox_manager = engine2._engine.sandbox_manager
    engine2._setup_done = True
    
    # Use ExecutionEngine's resume_from_checkpoint directly (without auto-executing)
    loaded_run = engine2._engine.resume_from_checkpoint(checkpoint_id, mission_id=mission_id)
    
    if loaded_run:
        run_id_2 = loaded_run.run_id
        
        # Check task states after resume (BEFORE executing remaining)
        graph = engine2._engine.task_graph.get(run_id_2, {})
        task_states_after_resume = {node['name']: str(node['state']) for node in graph.values()}
        
        # Capture artifact state AFTER resume (before executing remaining)
        artifacts_2 = {}
        for art in engine2._engine.evidence_store._artifacts.values():
            if art.path.startswith('e25_task'):
                artifacts_2[art.path] = {
                    'artifact_id': art.artifact_id,
                    'sha256': art.sha256,
                    'size_bytes': art.size_bytes,
                    'mission_id': art.mission_id
                }
        
        events_2 = engine2._engine.get_event_history(mission_id)
        event_count_2 = len(events_2)
        
        # Verify artifact identity continuity for tasks completed before checkpoint
        artifact_continuity = {}
        for path, art1 in artifacts_1.items():
            task_name = path.replace('e25_', '').replace('.txt', '').replace('task', 'Task-')
            # Map: task001_setup -> Task-001-Setup
            if '001' in path: task_name = 'Task-001-Setup'
            elif '002' in path: task_name = 'Task-002-DataPrep'
            elif '003' in path: task_name = 'Task-003-Process'
            elif '004' in path: task_name = 'Task-004-Validate'
            elif '005' in path: task_name = 'Task-005-Finalize'
            
            if path in artifacts_2:
                art2 = artifacts_2[path]
                artifact_continuity[path] = {
                    'task_name': task_name,
                    'completed_before_cp': task_name in tasks_completed_before_cp,
                    'artifact_id_match': art1['artifact_id'] == art2['artifact_id'],
                    'sha256_match': art1['sha256'] == art2['sha256'],
                    'size_match': art1['size_bytes'] == art2['size_bytes'],
                    'mission_id_match': art1.get('mission_id') == art2.get('mission_id')
                }
            else:
                artifact_continuity[path] = {
                    'task_name': task_name,
                    'completed_before_cp': task_name in tasks_completed_before_cp,
                    'artifact_id_match': False,
                    'sha256_match': False,
                    'size_match': False,
                    'missing_after_resume': True
                }
        
        # Only check continuity for tasks completed before checkpoint
        pre_cp_artifacts = {k: v for k, v in artifact_continuity.items() if v['completed_before_cp']}
        all_pre_cp_continuous = all(
            c['artifact_id_match'] and c['sha256_match'] and c['size_match'] 
            for c in pre_cp_artifacts.values()
        ) if pre_cp_artifacts else True
        
        log_phase('PHASE_3_RESTART_1_RESUME', {
            'resume_success': loaded_run is not None,
            'new_run_id': run_id_2,
            'mission_recreated': True,
            'task_states_after_resume': task_states_after_resume,
            'artifact_continuity': artifact_continuity,
            'pre_cp_artifacts_continuous': all_pre_cp_continuous,
            'events_before': event_count_1,
            'events_after': event_count_2,
            'events_restored': event_count_2 >= event_count_1
        }, verdict='VERIFIED' if loaded_run is not None and all_pre_cp_continuous else 'FAILED')
        
        # ============================================================
        # PHASE 4: Execute remaining tasks (Task-004, Task-005)
        # ============================================================
        log_phase('PHASE_4_EXECUTE_REMAINING', {'start': True})
        exec_result = await engine2._engine.execute_task_graph(
            run_id_2,
            sandbox_manager=engine2._sandbox_manager,
            checkpoint_every=1
        )
        
        artifacts_3 = {}
        for art in engine2._engine.evidence_store._artifacts.values():
            if art.path.startswith('e25_task'):
                artifacts_3[art.path] = {
                    'artifact_id': art.artifact_id,
                    'sha256': art.sha256,
                    'size_bytes': art.size_bytes,
                    'mission_id': art.mission_id
                }
        
        # Capture evidence after Phase 4
        evidence_3 = {}
        for ev in engine2._engine.evidence_store._evidence.values():
            if ev.artifact_id in [a['artifact_id'] for a in artifacts_3.values()]:
                evidence_3[ev.evidence_id] = {
                    'artifact_id': ev.artifact_id,
                    'criterion': ev.criterion,
                    'verdict': ev.verdict,
                    'checks_performed': ev.checks_performed,
                    'sha256_verified': ev.sha256_verified
                }
        
        failed_tasks = [tid for tid, tr in exec_result.get('task_results', {}).items() if not tr.get('success', True)]
        
        log_phase('PHASE_4_EXECUTE_REMAINING', {
            'execution_success': exec_result.get('success'),
            'total_artifacts': len(artifacts_3),
            'total_evidence': len(evidence_3),
            'failed_tasks': failed_tasks,
            'task_results': {tid: {'state': tr.get('state', 'UNKNOWN'), 'success': tr.get('success', False), 'resumed': tr.get('resumed', False), 'attempts': tr.get('attempts', 0), 'error': str(tr.get('error', ''))[:200]} for tid, tr in exec_result.get('task_results', {}).items()}
        }, verdict='VERIFIED' if exec_result.get('success') else 'PARTIAL')
        
        # ============================================================
        # PHASE 5: DYNAMIC REPLAN (add recovery task after failure)
        # ============================================================
        log_phase('PHASE_5_DYNAMIC_REPLAN', {'start': True})
        task_ids = list(engine2._engine.task_graph.get(run_id_2, {}).keys())
        replan_result = engine2._engine.replan_task_graph(
            run_id=run_id_2,
            new_tasks=[{
                'name': 'Task-006-Recovery',
                'description': 'Recovery after Task-003 failure',
                'agent_type': AgentType.IMPLEMENTER,
                'depends_on': [task_ids[-1]] if task_ids else [],
                'acceptance_criteria': ['file_exists:e25_task006_recovery.txt'],
                'context': {
                    'operation': 'write_file',
                    'path': 'e25_task006_recovery.txt',
                    'content': b'Recovery completed'
                }
            }],
            reason='Recovery task added after Task-003 failure',
            actor='system'
        )
        
        log_phase('PHASE_5_DYNAMIC_REPLAN', {
            'replan_success': replan_result,
            'total_tasks_after': len(engine2._engine.task_graph.get(run_id_2, {})),
            'graph_version': getattr(engine2._engine, '_graph_version', 'unknown')
        }, verdict='VERIFIED' if replan_result else 'FAILED')
        
        # Execute the recovery task
        exec_result2 = await engine2._engine.execute_task_graph(
            run_id_2,
            sandbox_manager=engine2._sandbox_manager,
            checkpoint_every=1
        )
        
        log_phase('PHASE_5_EXECUTE_RECOVERY', {
            'execution_success': exec_result2.get('success'),
            'task_results': {tid: {'state': tr.get('state', 'UNKNOWN'), 'success': tr.get('success', False), 'attempts': tr.get('attempts', 0)} for tid, tr in exec_result2.get('task_results', {}).items()}
        })
        
        # ============================================================
        # PHASE 6: HUMAN GATE
        # ============================================================
        log_phase('PHASE_6_HUMAN_GATE', {'start': True})
        gate_id = engine2.create_human_gate(
            mission_id=mission_id, run_id=run_id_2, task_id='',
            reason='Recovery complete, need approval to finalize',
            context={'recovery': True, 'failed_task': 'Task-003-Process'},
            options=[{'value': 'continue', 'label': 'Continue'}, {'value': 'cancel', 'label': 'Cancel'}],
            impact='Mission will finalize or be cancelled', required_action='approve_finalization'
        )
        gate_ok = gate_id is not None
        if gate_ok:
            decision_ok = engine2.decide_human_gate(mission_id=mission_id, gate_id=gate_id, decision='continue', actor='test_operator')
            gate_ok = decision_ok
        
        log_phase('PHASE_6_HUMAN_GATE', {
            'gate_created': gate_id is not None,
            'gate_id': gate_id,
            'decision_result': gate_ok,
            'mission_state_after': str(engine2._engine.missions.get(mission_id, {}).state) if mission_id in engine2._engine.missions else 'N/A'
        }, verdict='VERIFIED' if gate_ok else 'FAILED')
        
        # ============================================================
        # PHASE 7: SECOND CHECKPOINT (after human gate)
        # ============================================================
        log_phase('PHASE_7_SECOND_CHECKPOINT', {'start': True})
        cp_dir = f'runtime/artifacts/checkpoints/{mission_id}'
        if os.path.exists(cp_dir):
            cps = [f for f in os.listdir(cp_dir) if f.endswith('.json')]
            log_phase('PHASE_7_SECOND_CHECKPOINT', {
                'checkpoints_total': len(cps),
                'latest_checkpoint': max(cps) if cps else None
            })
        
        # ============================================================
        # PHASE 8: SECOND PROCESS DEATH
        # ============================================================
        log_phase('PHASE_8_SECOND_PROCESS_DEATH', {'simulated': True})
        
        # ============================================================
        # PHASE 9: SECOND RESTART
        # ============================================================
        log_phase('PHASE_9_RESTART_2_RESUME', {'start': True})
        engine3 = OperationalExecutionEngine(artifacts_base_dir='runtime/artifacts')
        engine3._engine = engine3._create_engine()
        engine3._sandbox_manager = engine3._engine.sandbox_manager
        engine3._setup_done = True
        
        cp_dir = f'runtime/artifacts/checkpoints/{mission_id}'
        latest_cp = max([f for f in os.listdir(cp_dir) if f.endswith('.json')])
        latest_cp_id = latest_cp.replace('.json', '')
        
        loaded_run2 = engine3._engine.resume_from_checkpoint(latest_cp_id, mission_id=mission_id)
        
        if loaded_run2:
            run_id_3 = loaded_run2.run_id
            
            # Ensure mission is in EXECUTING state
            if mission_id in engine3._engine.missions:
                mission = engine3._engine.missions[mission_id]
                if mission.state != MissionState.EXECUTING:
                    for state in [MissionState.ANALYZING, MissionState.PLANNING, MissionState.DESIGNING, MissionState.REVIEWING, MissionState.APPROVED, MissionState.AWAITING_APPROVAL, MissionState.EXECUTING]:
                        if mission.state != state:
                            validate_mission_transition(mission.state, state)
                            mission.state = state
            
            # Capture artifacts after second resume
            artifacts_4 = {}
            for art in engine3._engine.evidence_store._artifacts.values():
                if art.path.startswith('e25_task'):
                    artifacts_4[art.path] = {
                        'artifact_id': art.artifact_id,
                        'sha256': art.sha256,
                        'size_bytes': art.size_bytes,
                        'mission_id': art.mission_id
                    }
            
            # Capture evidence after second resume
            evidence_4 = {}
            for ev in engine3._engine.evidence_store._evidence.values():
                if ev.artifact_id in [a['artifact_id'] for a in artifacts_4.values()]:
                    evidence_4[ev.evidence_id] = {
                        'artifact_id': ev.artifact_id,
                        'criterion': ev.criterion,
                        'verdict': ev.verdict,
                        'checks_performed': ev.checks_performed,
                        'sha256_verified': ev.sha256_verified
                    }
            
            events_3 = engine3._engine.get_event_history(mission_id)
            event_count_3 = len(events_3)
            
            # Verify artifact identity continuity through second restart
            # For tasks completed before FIRST checkpoint: should match original
            # For tasks completed AFTER first checkpoint but before SECOND checkpoint: should match Phase 4 artifacts
            artifact_continuity_2 = {}
            for path, art1 in artifacts_1.items():
                task_name = path.replace('e25_', '').replace('.txt', '').replace('task', 'Task-')
                if '001' in path: task_name = 'Task-001-Setup'
                elif '002' in path: task_name = 'Task-002-DataPrep'
                elif '003' in path: task_name = 'Task-003-Process'
                elif '004' in path: task_name = 'Task-004-Validate'
                elif '005' in path: task_name = 'Task-005-Finalize'
                elif '006' in path: task_name = 'Task-006-Recovery'
                
                completed_before_cp1 = task_name in tasks_completed_before_cp
                completed_before_cp2 = task_name in tasks_completed_before_cp or task_name in {'Task-004-Validate', 'Task-005-Finalize', 'Task-006-Recovery'}
                
                if path in artifacts_4:
                    art4 = artifacts_4[path]
                    if completed_before_cp1:
                        # Should match original (artifacts_1)
                        artifact_continuity_2[path] = {
                            'task_name': task_name,
                            'expected_source': 'original',
                            'artifact_id_match': art1['artifact_id'] == art4['artifact_id'],
                            'sha256_match': art1['sha256'] == art4['sha256'],
                            'size_match': art1['size_bytes'] == art4['size_bytes'],
                            'mission_id_match': art1.get('mission_id') == art4.get('mission_id')
                        }
                    elif completed_before_cp2:
                        # Should match Phase 4 artifacts (artifacts_3)
                        artifact_continuity_2[path] = {
                            'task_name': task_name,
                            'expected_source': 'phase4',
                            'artifact_id_match': path in artifacts_3 and artifacts_3[path]['artifact_id'] == art4['artifact_id'],
                            'sha256_match': path in artifacts_3 and artifacts_3[path]['sha256'] == art4['sha256'],
                            'size_match': path in artifacts_3 and artifacts_3[path]['size_bytes'] == art4['size_bytes'],
                            'mission_id_match': art1.get('mission_id') == art4.get('mission_id')
                        }
                    else:
                        # New task (recovery) - just check it exists
                        artifact_continuity_2[path] = {
                            'task_name': task_name,
                            'expected_source': 'new',
                            'artifact_id_match': True,  # New task, just verify it exists
                            'sha256_match': True,
                            'size_match': True,
                            'mission_id_match': True
                        }
                else:
                    artifact_continuity_2[path] = {
                        'task_name': task_name,
                        'artifact_id_match': False,
                        'sha256_match': False,
                        'size_match': False,
                        'missing_after_second_resume': True
                    }
            
            all_artifacts_continuous_2 = all(
                c['artifact_id_match'] and c['sha256_match'] and c['size_match'] 
                for c in artifact_continuity_2.values()
            )
            
            # Verify evidence continuity through second restart
            evidence_continuity_2 = {}
            for ev_id, ev1 in evidence_1.items():
                matching_ev4 = None
                for ev_id4, ev4 in evidence_4.items():
                    if ev4['artifact_id'] == ev1['artifact_id'] and ev4['criterion'] == ev1['criterion']:
                        matching_ev4 = ev4
                        break
                if matching_ev4:
                    evidence_continuity_2[ev_id] = {
                        'found': True,
                        'verdict_match': ev1['verdict'] == matching_ev4['verdict'],
                        'criterion_match': ev1['criterion'] == matching_ev4['criterion']
                    }
                else:
                    evidence_continuity_2[ev_id] = {
                        'found': False
                    }
            
            all_evidence_continuous_2 = all(c['found'] for c in evidence_continuity_2.values()) if evidence_continuity_2 else True
            
            log_phase('PHASE_9_RESTART_2_RESUME', {
                'second_resume_success': loaded_run2 is not None,
                'new_run_id': run_id_3,
                'mission_recreated_again': True,
                'artifact_continuity_through_2_restarts': artifact_continuity_2,
                'all_artifacts_continuous': all_artifacts_continuous_2,
                'evidence_continuity_through_2_restarts': evidence_continuity_2,
                'all_evidence_continuous': all_evidence_continuous_2,
                'events_through_2_restarts': event_count_3,
                'events_monotonic': event_count_3 >= event_count_2
            }, verdict='VERIFIED' if loaded_run2 is not None and all_artifacts_continuous_2 else 'PARTIAL')
            
            # ============================================================
            # PHASE 10: Execute remaining recovery task (if any)
            # ============================================================
            log_phase('PHASE_10_EXECUTE_RECOVERY', {'start': True})
            exec_result3 = await engine3._engine.execute_task_graph(
                run_id_3,
                sandbox_manager=engine3._sandbox_manager,
                checkpoint_every=1
            )
            
            artifacts_5 = {}
            for art in engine3._engine.evidence_store._artifacts.values():
                if art.path.startswith('e25_task'):
                    artifacts_5[art.path] = {
                        'artifact_id': art.artifact_id,
                        'sha256': art.sha256,
                        'size_bytes': art.size_bytes,
                        'mission_id': art.mission_id
                    }
            
            log_phase('PHASE_10_EXECUTE_RECOVERY', {
                'execution_success': exec_result3.get('success'),
                'total_artifacts': len(artifacts_5),
                'task_results': {tid: {'state': tr.get('state', 'UNKNOWN'), 'success': tr.get('success', False), 'attempts': tr.get('attempts', 0)} for tid, tr in exec_result3.get('task_results', {}).items()}
            }, verdict='VERIFIED' if exec_result3.get('success') else 'FAILED')
            
            # ============================================================
            # PHASE 11: FINAL INDEPENDENT VERIFICATION
            # ============================================================
            log_phase('PHASE_11_FINAL_VERIFICATION', {'start': True})
            event_file = f'runtime/artifacts/events/{mission_id}/event_log.jsonl'
            events_count = len(open(event_file).readlines()) if os.path.exists(event_file) else 0
            artifacts_count = len([a for a in engine3._engine.evidence_store._artifacts.values() if a.path.startswith('e25_task')])
            evidence_count = len([e for e in engine3._engine.evidence_store._evidence.values() if e.artifact_id in [a['artifact_id'] for a in artifacts_5.values()]])
            
            # Check all tasks completed - need to check graph state, not task_results
            graph_final = engine3._engine.task_graph.get(run_id_3, {})
            all_tasks_completed = all(
                node['state'] == TaskState.COMPLETED
                for node in graph_final.values()
            )
            
            log_phase('PHASE_11_FINAL_VERIFICATION', {
                'mission_id': mission_id,
                'final_run_id': run_id_3,
                'events_persisted': events_count,
                'artifacts_in_store': artifacts_count,
                'evidence_in_store': evidence_count,
                'all_tasks_completed': all_tasks_completed,
                'artifacts_identity_preserved': all_artifacts_continuous_2,
                'evidence_continuity': all_evidence_continuous_2
            }, verdict='VERIFIED' if all_tasks_completed and all_artifacts_continuous_2 else 'FAILED')
    
    # Save trace
    with open('docs/evidence/e25/execution_trace.json', 'w') as f:
        json.dump(trace, f, indent=2, default=str)
    
    for phase in trace['phases']:
        phase_name = phase['phase'].lower().replace(' ', '_')
        with open(f'docs/evidence/e25/{phase_name}_trace.json', 'w') as f:
            json.dump(phase, f, indent=2, default=str)
    
    print('\n=== E25 LONG-RUN MISSION COMPLETE ===')
    print('Verdicts:', trace['verdicts'])
    return trace

if __name__ == '__main__':
    asyncio.run(e25_long_run_mission())