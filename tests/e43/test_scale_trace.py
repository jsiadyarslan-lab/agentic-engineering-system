#!/usr/bin/env python3
"""Trace scale mission task execution to identify failures."""

import asyncio
import sys
from pathlib import Path
import tempfile

sys.path.insert(0, 'src')

from unified.execution import create_execution_engine
from unified.operational import (
    OperationalExplorerAgent, OperationalAnalystAgent, OperationalPlannerAgent,
    OperationalDesignerAgent, OperationalImplementerAgent, OperationalVerifierAgent,
    OperationalSecurityAgent, OperationalReviewerAgent
)
from unified.domain_model import AgentType, TaskState
from unified.agent_role import AgentDefinition, AgentLifecycleState
from unified.mission_controller import TaskSpec, MissionController


async def test():
    with tempfile.TemporaryDirectory() as tmpdir:
        artifacts_dir = Path(tmpdir) / 'artifacts'
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        
        engine = create_execution_engine(artifacts_base_dir=str(artifacts_dir))
        
        # Register all 8 agents
        agent_types = [
            (AgentType.EXPLORER, 'explorer', OperationalExplorerAgent),
            (AgentType.ANALYST, 'analyst', OperationalAnalystAgent),
            (AgentType.PLANNER, 'planner', OperationalPlannerAgent),
            (AgentType.DESIGNER, 'designer', OperationalDesignerAgent),
            (AgentType.IMPLEMENTER, 'implementer', OperationalImplementerAgent),
            (AgentType.VERIFIER, 'verifier', OperationalVerifierAgent),
            (AgentType.SECURITY, 'security', OperationalSecurityAgent),
            (AgentType.REVIEWER, 'reviewer', OperationalReviewerAgent),
        ]
        
        for agent_type, agent_id_suffix, impl_class in agent_types:
            agent_def = AgentDefinition(
                agent_id=f'test-{agent_id_suffix}-001',
                agent_type=agent_type, name=agent_id_suffix.capitalize(),
                version='1.0', description=f'{agent_id_suffix} (test)',
                tools=['write_artifact', 'read_artifact', 'run_command', 'security_audit'],
                permissions=['write', 'read', 'execute', 'security_scan'],
                max_tokens=50000, timeout_seconds=300, requires_sandbox=True,
                supported_domains=['file_operations', 'code_execution', 'data_processing', 'security'],
                implementation_class=f'unified.operational.{impl_class.__name__}',
                state=AgentLifecycleState.REGISTERED,
            )
            engine.agent_registry.register_definition(agent_def)
            engine.agent_registry.enable_agent(f'test-{agent_id_suffix}-001')
            engine.agent_registry.replace_implementation(agent_type, impl_class)
        
        mc = MissionController(engine, state_dir=str(artifacts_dir))
        
        # Build a small scale mission like in the test
        target_count = 10  # SMALL
        specs = []
        keys = []
        
        foundation = [
            ('t1_discover', 'T1: Discover Codebase', 'Explore and document codebase structure', 
             ['file_exists:e43_t1_discover.md', 'file_contains:e43_t1_discover.md:Discover'], [], AgentType.EXPLORER),
            ('t2_analyze', 'T2: Analyze Requirements', 'Analyze and document requirements',
             ['file_exists:e43_t2_analyze.md', 'file_contains:e43_t2_analyze.md:Analyze'], ['t1_discover'], AgentType.ANALYST),
            ('t3_plan', 'T3: Create Plan', 'Create implementation plan',
             ['file_exists:e43_t3_plan.md', 'file_contains:e43_t3_plan.md:Plan'], ['t2_analyze'], AgentType.PLANNER),
            ('t4_design', 'T4: Design Architecture', 'Design system architecture',
             ['file_exists:e43_t4_design.md', 'file_contains:e43_t4_design.md:Design'], ['t3_plan'], AgentType.DESIGNER),
        ]
        
        for key, name, desc, criteria, deps, agent in foundation:
            specs.append(TaskSpec(
                key=key, name=name, description=desc,
                acceptance_criteria=criteria,
                depends_on=deps,
                context={'operation': 'write_file', 'path': f'e43_{key}.md', 'content': f'# {name}\nDone', 'working_dir': '.', 'timeout_seconds': 30, 'task_key': key},
                agent_type=agent,
            ))
            keys.append(key)
        
        impl_tasks = []
        impl_count = min(target_count - 8, 20)
        for i in range(impl_count):
            if i == 0:
                dep = ['t4_design']
            else:
                dep = [impl_tasks[-1]]
            if i > 0 and i % 3 == 0 and len(impl_tasks) >= 2:
                dep = [impl_tasks[-2], impl_tasks[-1]]
            
            key = f't{len(keys)+1}_impl_{i}'
            impl_tasks.append(key)
            specs.append(TaskSpec(
                key=key,
                name=f'T{len(keys)+1}: Implementation {i+1}',
                description=f'Implement component {i+1}',
                acceptance_criteria=[f'file_exists:e43_{key}.py', f'file_contains:e43_{key}.py:Implementation'],
                depends_on=dep,
                context={'operation': 'write_file', 'path': f'e43_{key}.py', 'content': f'# Component {i+1}\nImplementation', 'working_dir': '.', 'timeout_seconds': 30, 'task_key': key},
                agent_type=AgentType.IMPLEMENTER,
            ))
            keys.append(key)
        
        verify_deps = impl_tasks[-2:] if len(impl_tasks) >= 2 else (impl_tasks if impl_tasks else ['t4_design'])
        
        key_a = f't{len(keys)+1}_verify_a'
        specs.append(TaskSpec(
            key=key_a,
            name=f'T{len(keys)+1}: Verification A',
            description='Parallel verification A',
            acceptance_criteria=[f'file_exists:e43_{key_a}.json', f'file_contains:e43_{key_a}.json:passed'],
            depends_on=verify_deps,
            context={'operation': 'write_file', 'path': f'e43_{key_a}.json', 'content': '{"passed": true}', 'working_dir': '.', 'timeout_seconds': 30, 'task_key': key_a},
            agent_type=AgentType.VERIFIER,
        ))
        keys.append(key_a)
        
        key_b = f't{len(keys)+1}_verify_b'
        specs.append(TaskSpec(
            key=key_b,
            name=f'T{len(keys)+1}: Verification B',
            description='Parallel verification B',
            acceptance_criteria=[f'file_exists:e43_{key_b}.json', f'file_contains:e43_{key_b}.json:passed'],
            depends_on=verify_deps,
            context={'operation': 'write_file', 'path': f'e43_{key_b}.json', 'content': '{"passed": true}', 'working_dir': '.', 'timeout_seconds': 30, 'task_key': key_b},
            agent_type=AgentType.VERIFIER,
        ))
        keys.append(key_b)
        
        key_sec = f't{len(keys)+1}_security'
        specs.append(TaskSpec(
            key=key_sec,
            name=f'T{len(keys)+1}: Security Audit',
            description='Security audit of implementation',
            acceptance_criteria=[f'file_exists:e43_{key_sec}.json', f'file_contains:e43_{key_sec}.json:vulnerabilities_found'],
            depends_on=[key_b],
            context={'operation': 'security_audit', 'target_path': '.', 'scan_types': ['sast', 'secrets'], 'severity_threshold': 'medium', 'output_path': f'e43_{key_sec}.json', 'working_dir': '.', 'timeout_seconds': 60, 'task_key': key_sec},
            agent_type=AgentType.SECURITY,
        ))
        keys.append(key_sec)
        
        key_human = f't{len(keys)+1}_human'
        specs.append(TaskSpec(
            key=key_human,
            name=f'T{len(keys)+1}: Human Gate',
            description='Human review and approval',
            acceptance_criteria=[f'file_exists:e43_{key_human}.json', f'file_contains:e43_{key_human}.json:APPROVED'],
            depends_on=[key_sec],
            context={'operation': 'write_file', 'path': f'e43_{key_human}.json', 'content': '{"decision": "APPROVED", "reason": "All checks passed"}', 'working_dir': '.', 'timeout_seconds': 30, 'task_key': key_human},
            agent_type=AgentType.REVIEWER,
        ))
        keys.append(key_human)
        
        print(f'Total tasks: {len(specs)}')
        for s in specs:
            print(f'  {s.key}: {s.name} (agent={s.agent_type.value})')
        
        mission, run, key_to_id = mc.define_mission(
            user_request='Test scale mission',
            specs=specs,
        )
        
        print(f'\nMission: {mission.mission_id}')
        print(f'Run: {run.run_id}')
        
        run_result = await mc.execute_run(mission.current_run_id or run.run_id)
        
        print(f'\nRun result: {run_result.get("state", "unknown")}')
        
        # Check each task
        completed = 0
        failed = 0
        blocked = 0
        for key, task_id in key_to_id.items():
            task = engine.tasks.get(task_id)
            if task:
                print(f'  {key} ({task_id}): {task.state}')
                if task.state == TaskState.COMPLETED:
                    completed += 1
                elif task.state == TaskState.FAILED:
                    failed += 1
                elif task.state == TaskState.BLOCKED:
                    blocked += 1
        
        print(f'\nSummary: completed={completed}, failed={failed}, blocked={blocked}')
        
        # Check evidence store for security audit output
        for art_id, art in engine.evidence_store._artifacts.items():
            if 'security' in art.path:
                print(f'\nSecurity artifact: {art.path}')
                if hasattr(art, 'content') and art.content:
                    print(f'  Content: {art.content[:200]}')

result = asyncio.run(test())
print(f'Done')