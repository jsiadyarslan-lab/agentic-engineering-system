#!/usr/bin/env python3
"""
E44 Self-Hosting Mission Execution Script - Phase 4: Integration (Fixed)
"""
import asyncio
import sys
import os
sys.path.insert(0, 'src')

from unified.mission_controller import MissionController, TaskSpec
from unified.domain_model import AgentType
from unified.execution import create_execution_engine
from unified.agent_role import agent_registry, AgentDefinition, AgentLifecycleState
from unified.operational import (
    OperationalExplorerAgent, OperationalAnalystAgent, OperationalPlannerAgent,
    OperationalDesignerAgent, OperationalImplementerAgent, OperationalVerifierAgent,
    OperationalReviewerAgent, OperationalSecurityAgent
)

async def run_e44_phase4():
    """Execute E44 Phase 4: Integration (4 parallel tasks)."""
    
    # Create engine
    artifacts_dir = os.path.join(os.getcwd(), "runtime", "e44_artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)
    
    engine = create_execution_engine(artifacts_base_dir=artifacts_dir)
    
    # Register all 8 operational agents
    agent_types = [
        (AgentType.EXPLORER, "explorer", "Explorer", "Exploration and discovery", OperationalExplorerAgent),
        (AgentType.ANALYST, "analyst", "Analyst", "Analysis and requirements", OperationalAnalystAgent),
        (AgentType.PLANNER, "planner", "Planner", "Planning and task decomposition", OperationalPlannerAgent),
        (AgentType.DESIGNER, "designer", "Designer", "Design and architecture", OperationalDesignerAgent),
        (AgentType.IMPLEMENTER, "implementer", "Implementer", "Implementation and coding", OperationalImplementerAgent),
        (AgentType.VERIFIER, "verifier", "Verifier", "Verification and validation", OperationalVerifierAgent),
        (AgentType.REVIEWER, "reviewer", "Reviewer", "Review and approval", OperationalReviewerAgent),
        (AgentType.SECURITY, "security", "Security", "Security audit and scanning", OperationalSecurityAgent),
    ]

    for agent_type, agent_id_suffix, name, description, impl_class in agent_types:
        agent_def = AgentDefinition(
            agent_id=f"e44-{agent_id_suffix}-001",
            agent_type=agent_type,
            name=name,
            version="1.0",
            description=f"{description} (E44 - operational)",
            tools=["write_artifact", "read_artifact", "run_command", "security_audit"],
            permissions=["write", "read", "execute", "security_scan"],
            max_tokens=50000,
            timeout_seconds=300,
            requires_sandbox=True,
            supported_domains=["file_operations", "code_execution", "data_processing", "security"],
            implementation_class=f"unified.operational.{impl_class.__name__}",
            state=AgentLifecycleState.REGISTERED,
        )

        try:
            agent_registry.register_definition(agent_def)
            agent_registry.enable_agent(f"e44-{agent_id_suffix}-001")
        except ValueError:
            agent_registry.replace_definition(agent_def)
            agent_registry.enable_agent(f"e44-{agent_id_suffix}-001")

        agent_registry.replace_implementation(agent_type, impl_class)

    print("  Factory agents registered: all 8 operational agents active")
    
    # Create MissionController
    mission_controller = MissionController(engine, state_dir=artifacts_dir)
    
    # Read existing files - use the sandbox version for operational.py which has chain_verification
    with open("src/unified/mission_controller.py", "r", encoding="utf-8") as f:
        mission_controller_content = f.read()
    
    # Use the sandbox version of operational.py that has the chain_verification code
    with open("runtime/e44_artifacts/sandbox-task-1f4721fa1255/src/unified/operational.py", "r", encoding="utf-8") as f:
        operational_content = f.read()
    
    with open("src/unified/execution.py", "r", encoding="utf-8") as f:
        execution_content = f.read()
    
    # Define Phase 4 tasks - Integration
    tasks = [
        TaskSpec(
            key="e44_t13_mission_controller_integration",
            name="Integrate EvidenceChain into MissionController",
            description="Modify MissionController to initialize EvidenceChain and create checkpoints at mission milestones",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:src/unified/mission_controller.py",
                "file_contains:src/unified/mission_controller.py:evidence_chain",
                "file_contains:src/unified/mission_controller.py:create_checkpoint",
            ],
            context={
                "operation": "write_file",
                "path": "src/unified/mission_controller.py",
                "content": mission_controller_content.replace(
                    "from unified.execution import (\n    ExecutionEngine, create_execution_engine, ExecutionContext,\n    SimpleEventBus, FileEvidenceStore,\n)",
                    """from unified.evidence_chain import EvidenceChain
from unified.execution import (
    ExecutionEngine, create_execution_engine, ExecutionContext,
    SimpleEventBus, FileEvidenceStore,
)"""
                ).replace(
                    "self.engine = engine\n        self.state_dir = state_dir\n        self._key_to_task: Dict[str, str] = {}\n        self._task_to_key: Dict[str, str] = {}\n        self.phase_log: List[Dict] = []",
                    """self.engine = engine
        self.state_dir = state_dir
        self._key_to_task: Dict[str, str] = {}
        self._task_to_key: Dict[str, str] = {}
        self.phase_log: List[Dict] = []
        # E44: Evidence chain for mission integrity
        self.evidence_chain: Optional[EvidenceChain] = None"""
                ).replace(
                    "run = self.engine.create_run(mission.mission_id)",
                    """run = self.engine.create_run(mission.mission_id)
        # E44: Initialize evidence chain for this mission
        self.evidence_chain = EvidenceChain(mission_id=mission.mission_id, run_id=run.run_id)
        # Set evidence chain on engine's evidence store
        if hasattr(self.engine, 'evidence_store') and hasattr(self.engine.evidence_store, 'set_evidence_chain'):
            self.engine.evidence_store.set_evidence_chain(self.evidence_chain)"""
                ).replace(
                    "# If execution completed successfully (not paused) and all tasks done, transition to EVIDENCED",
                    """# E44: Create checkpoint after mission execution
        if hasattr(self, 'evidence_chain') and self.evidence_chain:
            self.evidence_chain.create_checkpoint()
        
        # If execution completed successfully (not paused) and all tasks done, transition to EVIDENCED"""
                )
            }
        ),
        TaskSpec(
            key="e44_t14_engine_evidence_chain_init",
            name="Initialize EvidenceChain in ExecutionEngine",
            description="Modify ExecutionEngine to pass mission_id and run_id to FileEvidenceStore for EvidenceChain initialization",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:src/unified/execution.py",
                "file_contains:src/unified/execution.py:mission_id",
                "file_contains:src/unified/execution.py:run_id",
            ],
            context={
                "operation": "write_file",
                "path": "src/unified/execution.py",
                "content": execution_content.replace(
                    "self.evidence_store = FileEvidenceStore(artifacts_base_dir)",
                    """self.evidence_store = FileEvidenceStore(artifacts_base_dir, mission_id="", run_id="")"""
                ).replace(
                    "async def execute_task_graph(\n        self,\n        run_id: str,\n        max_parallel: int = 1,\n        task_timeout: Optional[float] = None,\n    ) -> Dict[str, Any]:",
                    """async def execute_task_graph(
        self,
        run_id: str,
        max_parallel: int = 1,
        task_timeout: Optional[float] = None,
        mission_id: str = "",
    ) -> Dict[str, Any]:"""
                ).replace(
                    "# --- Verification ---\n    async def verify_task(",
                    """# E44: Update evidence store with mission/run IDs for EvidenceChain
        if mission_id and hasattr(self.evidence_store, 'mission_id'):
            self.evidence_store.mission_id = mission_id
        if run_id and hasattr(self.evidence_store, 'run_id'):
            self.evidence_store.run_id = run_id
        
        # --- Verification ---
    async def verify_task("""
                )
            }
        ),
        TaskSpec(
            key="e44_t15_verification_report_artifact",
            name="Add EvidenceChain verification to verification report artifacts",
            description="Ensure OperationalVerifierAgent includes chain_verification in output - write updated operational.py",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:src/unified/operational.py",
                "file_contains:src/unified/operational.py:chain_verification",
            ],
            context={
                "operation": "write_file",
                "path": "src/unified/operational.py",
                "content": operational_content
            }
        ),
        TaskSpec(
            key="e44_t16_integration_test",
            name="Create Integration Test for EvidenceChain",
            description="Create test demonstrating EvidenceChain integration across MissionController, ExecutionEngine, and VerifierAgent",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:tests/e44/test_integration.py",
                "file_contains:tests/e44/test_integration.py:test_evidence_chain_integration",
                "file_contains:tests/e44/test_integration.py:MissionController",
            ],
            context={
                "operation": "write_file",
                "path": "tests/e44/test_integration.py",
                "content": """#!/usr/bin/env python3
\"\"\"Integration Test for EvidenceChain across factory components.\"\"\"
import sys
import os
import tempfile
sys.path.insert(0, 'src')

from unified.mission_controller import MissionController, TaskSpec
from unified.domain_model import AgentType
from unified.execution import create_execution_engine
from unified.agent_role import agent_registry, AgentDefinition, AgentLifecycleState
from unified.operational import (
    OperationalExplorerAgent, OperationalAnalystAgent, OperationalPlannerAgent,
    OperationalDesignerAgent, OperationalImplementerAgent, OperationalVerifierAgent,
    OperationalReviewerAgent, OperationalSecurityAgent
)
from unified.evidence_chain import EvidenceChain

async def test_evidence_chain_integration():
    \"\"\"Test EvidenceChain integration across factory components.\"\"\"
    
    # Create engine
    artifacts_dir = os.path.join(tempfile.gettempdir(), "e44_integration_test")
    os.makedirs(artifacts_dir, exist_ok=True)
    
    engine = create_execution_engine(artifacts_base_dir=artifacts_dir)
    
    # Register agents
    agent_types = [
        (AgentType.EXPLORER, "explorer", "Explorer", "Exploration", OperationalExplorerAgent),
        (AgentType.ANALYST, "analyst", "Analyst", "Analysis", OperationalAnalystAgent),
        (AgentType.IMPLEMENTER, "implementer", "Implementer", "Implementation", OperationalImplementerAgent),
        (AgentType.VERIFIER, "verifier", "Verifier", "Verification", OperationalVerifierAgent),
    ]

    for agent_type, agent_id_suffix, name, description, impl_class in agent_types:
        agent_def = AgentDefinition(
            agent_id=f"integration-{agent_id_suffix}-001",
            agent_type=agent_type,
            name=name,
            version="1.0",
            description=f"{description} (Integration Test)",
            tools=["write_artifact", "read_artifact", "run_command"],
            permissions=["write", "read", "execute"],
            max_tokens=50000,
            timeout_seconds=300,
            requires_sandbox=True,
            supported_domains=["file_operations", "code_execution", "data_processing"],
            implementation_class=f"unified.operational.{impl_class.__name__}",
            state=AgentLifecycleState.REGISTERED,
        )
        try:
            agent_registry.register_definition(agent_def)
            agent_registry.enable_agent(f"integration-{agent_id_suffix}-001")
        except ValueError:
            agent_registry.replace_definition(agent_def)
            agent_registry.enable_agent(f"integration-{agent_id_suffix}-001")
        agent_registry.replace_implementation(agent_type, impl_class)

    mission_controller = MissionController(engine, state_dir=artifacts_dir)
    
    # Define a mission with multiple tasks
    tasks = [
        TaskSpec(
            key="int_t1_create",
            name="Create Integration Test File",
            description="Create a test file",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:integration_test.txt",
                "file_contains:integration_test.txt:Integration Test",
            ],
            context={"operation": "write_file", "path": "integration_test.txt", "content": "Integration Test Content"}
        ),
        TaskSpec(
            key="int_t2_create",
            name="Create Second File",
            description="Create another test file",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:integration_test2.txt",
                "file_contains:integration_test2.txt:Second File",
            ],
            context={"operation": "write_file", "path": "integration_test2.txt", "content": "Second File Content"}
        ),
        TaskSpec(
            key="int_t3_verify",
            name="Verify Both Files",
            description="Verify both created files",
            agent_type=AgentType.VERIFIER,
            acceptance_criteria=[
                "file_exists:integration_test.txt",
                "file_exists:integration_test2.txt",
            ],
            depends_on=["int_t1_create", "int_t2_create"]
        ),
    ]
    
    mission = mission_controller.define_mission(
        user_request="Integration Test Mission",
        specs=tasks
    )
    
    # Execute mission
    result = await mission_controller.execute_run(
        list(mission_controller._run_to_mission.keys())[0] if mission_controller._run_to_mission else list(mission_controller.phase_log)[-1].get('run_id', '') if mission_controller.phase_log else '',
        max_parallel=2
    )
    
    # Verify mission completed
    assert result.get("success", False) == True, f"Mission failed: {result}"
    
    # Check evidence chain was created
    assert mission_controller.evidence_chain is not None, "EvidenceChain not initialized in MissionController"
    assert len(mission_controller.evidence_chain.checkpoints) > 0, "No checkpoints created"
    
    # Check evidence chain on engine's evidence store
    if hasattr(engine.evidence_store, 'get_evidence_chain'):
        store_chain = engine.evidence_store.get_evidence_chain()
        assert store_chain is not None, "EvidenceChain not set on FileEvidenceStore"
    
    # Verify chain integrity
    artifacts = {
        art_id: meta.get("sha256", "") 
        for art_id, meta in engine.evidence_store._artifacts.items()
    }
    chain_result = mission_controller.evidence_chain.verify_chain(artifacts)
    assert chain_result.valid == True, f"Evidence chain verification failed: {chain_result.details}"
    
    print("PASS: test_evidence_chain_integration - Full integration verified")
    return True

if __name__ == "__main__":
    result = asyncio.run(test_evidence_chain_integration())
    print("\\nEvidenceChain Integration Test PASSED!")
"""
            }
        ),
    ]
    
    print("Defining Phase 4 mission...")
    mission, run, key_to_id = mission_controller.define_mission(
        user_request="E44 Phase 4: Integration - Connect EvidenceChain across MissionController, ExecutionEngine, and VerifierAgent",
        specs=tasks
    )
    print(f"Mission defined: {mission.mission_id}")
    print(f"Run created: {run.run_id}")
    print(f"Tasks: {len(tasks)}")
    for task in tasks:
        print(f"  {task.key} -> will be assigned task ID")
    
    print("Executing mission...")
    result = await mission_controller.execute_run(run.run_id, max_parallel=4)
    
    print(f"Mission result: success={result.get('success', False)}, paused={result.get('paused', False)}")
    task_results = result.get('task_results', {})
    print(f"Completed tasks: {sum(1 for t in task_results.values() if t.get('success'))}")
    print(f"Failed tasks: {sum(1 for t in task_results.values() if not t.get('success'))}")
    
    for task_id, task_result in task_results.items():
        print(f"  {task_id}: success={task_result.get('success')}, error={task_result.get('error')}")
    
    final_status = result.get('final_status', {})
    if final_status:
        for task_id, status in final_status.items():
            state = status.get('state', 'UNKNOWN')
            name = status.get('name', 'Unknown')
            agent = status.get('agent_type', 'Unknown')
            print(f"  {task_id} ({name}, {agent}): {state}")
    
    return result.get('success', False)

if __name__ == "__main__":
    success = asyncio.run(run_e44_phase4())
    sys.exit(0 if success else 1)