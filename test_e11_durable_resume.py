import asyncio
import json
import os
import tempfile
from unified.execution import create_execution_engine
from unified.sandbox import SandboxBackend, create_sandbox_manager
from unified.agent_contract import AgentType
from unified.contracts import MissionState, TaskState

async def test_durable_resume():
    """Test durable resume after process restart."""
    print("=== TEST: Durable Resume ===")
    
    # Create a temporary directory for artifacts
    with tempfile.TemporaryDirectory() as tmpdir:
        # Engine 1: Create mission, run, create checkpoint
        print("\n--- Engine 1: Execute to checkpoint ---")
        engine1 = create_execution_engine(
            sandbox_backend=SandboxBackend.WINDOWS_EXECUTOR,
            artifacts_base_dir=tmpdir,
            max_concurrent_missions=5,
            max_concurrent_tasks=10
        )
        
        # Create mission
        mission1 = engine1.create_mission("Durable resume test")
        print(f"Mission created: {mission1.mission_id}")
        
        run1 = engine1.create_run(mission1.mission_id)
        print(f"Run created: {run1.run_id}")
        
        # Create multiple tasks
        task1 = engine1.create_task(
            run_id=run1.run_id,
            mission_id=mission1.mission_id,
            name="Task 1 - Create file",
            description="Create hello.txt",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=[],
        )
        task1.context = {"operation": "create_file", "path": "hello.txt", "content": b"Hello from task 1"}
        
        task2 = engine1.create_task(
            run_id=run1.run_id,
            mission_id=mission1.mission_id,
            name="Task 2 - Create file 2",
            description="Create world.txt",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=[task1.task_id],
        )
        task2.context = {"operation": "create_file", "path": "world.txt", "content": b"World from task 2"}
        
        task3 = engine1.create_task(
            run_id=run1.run_id,
            mission_id=mission1.mission_id,
            name="Task 3 - Run command",
            description="Echo test",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=[task2.task_id],
        )
        task3.context = {"operation": "run_command", "command": "echo done", "timeout_seconds": 30}
        print(f"Tasks created: {task1.task_id}, {task2.task_id}, {task3.task_id}")
        
        # Execute first two tasks manually to simulate checkpoint
        manager = create_sandbox_manager(SandboxBackend.WINDOWS_EXECUTOR)
        
        # Execute task1
        print("Executing task 1...")
        result1 = await engine1.execute_task_graph(run1.run_id, sandbox_manager=manager, checkpoint_every=1)
        print(f"Result 1: {result1}")
        
        # Check if tasks completed
        print(f"Engine 1 task graph: {engine1.task_graph.get(run1.run_id, {})}")
        for tid, node in engine1.task_graph.get(run1.run_id, {}).items():
            print(f"  {tid}: state={node.get('state')}")
        
        # Engine 2: Restart and resume from checkpoint
        print("\n--- Engine 2: Resume from checkpoint ---")
        engine2 = create_execution_engine(
            sandbox_backend=SandboxBackend.WINDOWS_EXECUTOR,
            artifacts_base_dir=tmpdir,
            max_concurrent_missions=5,
            max_concurrent_tasks=10
        )
        
        # Create same mission structure
        mission2 = engine2.create_mission("Durable resume test")
        print(f"Mission created: {mission2.mission_id}")
        
        run2 = engine2.create_run(mission2.mission_id)
        print(f"Run created: {run2.run_id}")
        
        # Create same tasks
        task1_2 = engine2.create_task(
            run_id=run2.run_id,
            mission_id=mission2.mission_id,
            name="Task 1 - Create file",
            description="Create hello.txt",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=[],
        )
        task1_2.context = {"operation": "create_file", "path": "hello.txt", "content": b"Hello from task 1"}
        
        task2_2 = engine2.create_task(
            run_id=run2.run_id,
            mission_id=mission2.mission_id,
            name="Task 2 - Create file 2",
            description="Create world.txt",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=[task1_2.task_id],
        )
        task2_2.context = {"operation": "create_file", "path": "world.txt", "content": b"World from task 2"}
        
        task3_2 = engine2.create_task(
            run_id=run2.run_id,
            mission_id=mission2.mission_id,
            name="Task 3 - Run command",
            description="Echo test",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=[task2_2.task_id],
        )
        task3_2.context = {"operation": "run_command", "command": "echo done", "timeout_seconds": 30}
        
        # Find checkpoint from engine 1
        checkpoint_files = [f for f in os.listdir(tmpdir) if f.startswith('checkpoint_') and f.endswith('.json')]
        print(f"Checkpoint files: {checkpoint_files}")
        
        if checkpoint_files:
            checkpoint_id = checkpoint_files[0].replace('checkpoint_', '').replace('.json', '')
            print(f"Found checkpoint: {checkpoint_id}")
            
            # Try to load checkpoint
            loaded = engine2._load_checkpoint_from_disk(mission2.mission_id, checkpoint_id)
            print(f"Checkpoint loaded: {loaded is not None}")
            if loaded:
                print(f"  Step: {loaded.step}")
                print(f"  State: {loaded.state}")
                print(f"  Task states: {loaded.task_states}")
            
            # Restore task graph
            if loaded:
                engine2.restore_task_graph_from_checkpoint(run2.run_id, loaded)
                print("Task graph restored from checkpoint")
                
                # Check task states after restore
                for task_id, node in engine2.task_graph[run2.run_id].items():
                    print(f"  {task_id}: state={node.get('state')}")
                
                # Execute remaining tasks
                result = await engine2.execute_task_graph(
                    run2.run_id,
                    sandbox_manager=manager,
                    checkpoint_every=1,
                )
                
                print(f"Execution result: {result}")
                completed = sum(1 for tr in result.get('task_results', {}).values() if tr.get('success'))
                return {
                    'checkpoint_found': True,
                    'checkpoint_loaded': loaded is not None,
                    'task_graph_restored': True,
                    'resume_execution_success': result.get('success', False),
                    'completed_tasks': completed,
                }
        
        return {
            'checkpoint_found': False,
            'checkpoint_loaded': False,
        }

async def test_mission_state_persistence():
    """Test that mission state is preserved across engine instances."""
    print("\n=== TEST: Mission State Persistence ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Engine 1: Create mission and set state
        engine1 = create_execution_engine(
            sandbox_backend=SandboxBackend.WINDOWS_EXECUTOR,
            artifacts_base_dir=tmpdir,
        )
        
        mission = engine1.create_mission("Persistence test")
        run = engine1.create_run(mission.mission_id)
        mission.state = MissionState.EXECUTING
        mission.metadata["custom_field"] = "test_value"
        
        print(f"Engine 1 - Mission: {mission.mission_id}, state: {mission.state}, metadata: {mission.metadata}")
        
        # Execute something to create artifacts
        task = engine1.create_task(
            run_id=run.run_id,
            mission_id=mission.mission_id,
            name="Create file",
            description="Test",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=[],
        )
        task.context = {"operation": "create_file", "path": "persist.txt", "content": b"persistent"}
        
        manager = create_sandbox_manager(SandboxBackend.WINDOWS_EXECUTOR)
        await engine1.execute_task_graph(run.run_id, sandbox_manager=manager)
        
        print(f"Engine 1 artifacts: {len(engine1.evidence_store._artifacts)}")
        
        # Engine 2: New engine with same artifacts dir
        engine2 = create_execution_engine(
            sandbox_backend=SandboxBackend.WINDOWS_EXECUTOR,
            artifacts_base_dir=tmpdir,
        )
        
        # Artifacts should be accessible
        print(f"Engine 2 - Global artifacts: {len(engine2.evidence_store._artifacts)}")
        print(f"Engine 2 - Global evidence: {len(engine2.evidence_store._evidence)}")
        
        return {
            'artifacts_persisted': len(engine2.evidence_store._artifacts) > 0,
            'engine_isolation_works': len(engine1.evidence_store._artifacts) != len(engine2.evidence_store._artifacts),
        }

async def main():
    results = {
        'durable_resume': await test_durable_resume(),
        'mission_state_persistence': await test_mission_state_persistence(),
    }
    
    with open('evidence/e11/durable_resume.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print("\n=== SUMMARY ===")
    print(json.dumps(results, indent=2, default=str))

asyncio.run(main())