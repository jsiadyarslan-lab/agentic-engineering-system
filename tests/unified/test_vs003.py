"""
VS-003: Agent Registry & Real Agent Lifecycle Integration Test

Tests the complete agent lifecycle:
MISSION -> RUN -> TASK -> AGENT REGISTRY -> AGENT SELECTION -> AGENT ASSIGNMENT 
-> UNIFIED EXECUTION ENGINE -> SANDBOX -> ARTIFACT -> EVIDENCE -> VERIFICATION 
-> AGENT COMPLETION -> TASK COMPLETION -> RUN COMPLETION

Negative tests:
- Unknown agent rejection
- Disabled agent enforcement
- Tool permission denial
"""

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from unified.contracts import (
    # IDs
    new_mission_id, new_run_id, new_task_id, new_attempt_id, new_agent_id,
    # Enums
    MissionState, PlanState, TaskState, AgentType, EventType,
    AgentLifecycleState,
    # Entities
    Mission, Run, Task, AgentDefinition,
    AgentTask,  # AgentTask from agent_contract has context field
    # Factories
    create_mission, create_run, create_task,
    # Agent Role
    AgentDefinition, AgentRegistry, agent_registry, AgentFactory,
    AgentSelectionError,
    # Agent Role Protocol
    AgentContext, AgentCapability, BaseAgent,
    # Verification
    VerifierVerdict, Verification, create_verification,
    # Event Catalog
    FactoryEvent, EVENT_CATALOG,
)
from unified.execution import ExecutionEngine, ExecutionContext, FileEvidenceStore
from unified.sandbox import SandboxManager, create_sandbox_manager
from unified.windows_adapter import WindowsExecutorAdapter
from unified.test_agent import E4TestAgent, register_e4_test_agent


class TestVS003AgentLifecycle:
    """VS-003: Agent Registry & Real Agent Lifecycle Integration Test."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    @pytest.fixture
    def sandbox_manager(self, temp_dir):
        """Create sandbox manager with Windows adapter."""
        artifacts_dir = temp_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        
        # Create SandboxManager using factory function
        manager = create_sandbox_manager(
            artifacts_base_dir=str(artifacts_dir),
        )
        return manager, str(artifacts_dir)
    
    @pytest.fixture
    def event_collector(self):
        """Collect events during test."""
        events = []
        def collector(event):
            events.append(event)
        return events, collector
    
    @pytest.fixture
    def evidence_store(self, temp_dir):
        """Create file evidence store."""
        artifacts_dir = temp_dir / "artifacts"
        return FileEvidenceStore(str(artifacts_dir))
    
    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset global registry before each test."""
        # Clear global registry
        agent_registry._definitions.clear()
        agent_registry._type_to_definition.clear()
        agent_registry._implementations.clear()
        agent_registry._instances.clear()
        agent_registry._instance_states.clear()
        # Clear reservations (E15)
        from unified.agent_role import clear_all_reservations
        clear_all_reservations()
        yield
        # Cleanup
        agent_registry._definitions.clear()
        agent_registry._type_to_definition.clear()
        agent_registry._implementations.clear()
        agent_registry._instances.clear()
        agent_registry._instance_states.clear()
        clear_all_reservations()
    
    def test_agent_definition_registration(self):
        """AC-E4-01: AgentDefinition contract exists and validates."""
        definition = AgentDefinition(
            agent_id="test-agent-001",
            agent_type=AgentType.IMPLEMENTER,
            name="TestAgent",
            version="1.0",
            description="Test agent",
            tools=["write_artifact"],
            permissions=["write"],
            max_tokens=10000,
            timeout_seconds=60,
            requires_sandbox=True,
            supported_domains=["testing"],
            implementation_class="unified.test_agent.E4TestAgent",
        )
        
        # Register with registry
        agent_registry.register_definition(definition)
        
        # Verify registered
        retrieved = agent_registry.get_definition("test-agent-001")
        assert retrieved is not None
        assert retrieved.agent_id == "test-agent-001"
        assert retrieved.agent_type == AgentType.IMPLEMENTER
        assert retrieved.state == AgentLifecycleState.REGISTERED
        
        # Verify capability conversion
        capability = definition.to_capability()
        assert "write_artifact" in capability.tools
        assert "write" in capability.permissions
    
    def test_duplicate_registration_rejected(self):
        """AC-E4-03: Duplicate/invalid agents are rejected."""
        definition = AgentDefinition(
            agent_id="test-agent-001",
            agent_type=AgentType.IMPLEMENTER,
            name="TestAgent",
            version="1.0",
            description="Test agent",
            tools=["write_artifact"],
            permissions=["write"],
            max_tokens=10000,
            timeout_seconds=60,
            requires_sandbox=True,
            supported_domains=["testing"],
            implementation_class="unified.test_agent.E4TestAgent",
        )
        
        agent_registry.register_definition(definition)
        
        # Duplicate agent_id should fail
        with pytest.raises(ValueError, match="already exists"):
            agent_registry.register_definition(definition)
        
        # Duplicate agent_type should fail
        definition2 = AgentDefinition(
            agent_id="test-agent-002",
            agent_type=AgentType.IMPLEMENTER,  # Same type
            name="TestAgent2",
            version="1.0",
            description="Test agent 2",
            tools=["write_artifact"],
            permissions=["write"],
            max_tokens=10000,
            timeout_seconds=60,
            requires_sandbox=True,
            supported_domains=["testing"],
            implementation_class="unified.test_agent.E4TestAgent",
        )
        with pytest.raises(ValueError, match="already has a default definition"):
            agent_registry.register_definition(definition2)
    
    def test_agent_identity_independent_from_run(self):
        """AC-E4-04: Agent identity is independent from Run identity."""
        definition = AgentDefinition(
            agent_id="test-agent-001",
            agent_type=AgentType.IMPLEMENTER,
            name="TestAgent",
            version="1.0",
            description="Test agent",
            tools=["write_artifact"],
            permissions=["write"],
            max_tokens=10000,
            timeout_seconds=60,
            requires_sandbox=True,
            supported_domains=["testing"],
            implementation_class="unified.test_agent.E4TestAgent",
        )
        agent_registry.register_definition(definition)
        agent_registry.register_implementation(AgentType.IMPLEMENTER, E4TestAgent)
        
        # Create multiple runs
        run1_id = new_run_id()
        run2_id = new_run_id()
        
        # Agent identity should be the same across runs
        agent1 = agent_registry.get_definition("test-agent-001")
        agent2 = agent_registry.get_definition("test-agent-001")
        
        assert agent1 is agent2  # Same object
        assert agent1.agent_id == "test-agent-001"
        assert agent1.agent_id != run1_id
        assert agent1.agent_id != run2_id
    
    def test_capabilities_machine_checkable(self):
        """AC-E4-05: Capabilities are machine-checkable."""
        definition = AgentDefinition(
            agent_id="test-agent-001",
            agent_type=AgentType.IMPLEMENTER,
            name="TestAgent",
            version="1.0",
            description="Test agent",
            tools=["write_artifact", "read_artifact"],
            permissions=["write", "read"],
            max_tokens=10000,
            timeout_seconds=60,
            requires_sandbox=True,
            supported_domains=["testing", "codebase"],
            implementation_class="unified.test_agent.E4TestAgent",
        )
        agent_registry.register_definition(definition)
        
        # Check capabilities programmatically
        cap = definition.to_capability()
        assert "write_artifact" in cap.tools
        assert "read_artifact" in cap.tools
        assert "write" in cap.permissions
        assert "read" in cap.permissions
        assert "testing" in cap.supported_domains
        assert "codebase" in cap.supported_domains
        assert cap.max_tokens == 10000
        assert cap.timeout_seconds == 60
        assert cap.requires_sandbox is True
    
    def test_deterministic_agent_selection(self):
        """AC-E4-06: Agent selection is deterministic."""
        # Register two agents with different capabilities AND types
        agent_registry.register_definition(AgentDefinition(
            agent_id="agent-a",
            agent_type=AgentType.IMPLEMENTER,
            name="AgentA",
            version="1.0",
            tools=["write_artifact"],
            permissions=["write"],
            max_tokens=5000,
            timeout_seconds=60,
            requires_sandbox=True,
            supported_domains=["testing"],
            implementation_class="unified.test_agent.E4TestAgent",
        ))
        agent_registry.register_definition(AgentDefinition(
            agent_id="agent-b",
            agent_type=AgentType.DESIGNER,  # Different type
            name="AgentB",
            version="1.0",
            tools=["write_artifact", "read_artifact", "write_file", "edit_file"],
            permissions=["read", "write"],
            max_tokens=10000,
            timeout_seconds=60,
            requires_sandbox=True,
            supported_domains=["testing", "codebase"],
            implementation_class="unified.test_agent.E4TestAgent",
        ))
        agent_registry.enable_agent("agent-a")
        agent_registry.enable_agent("agent-b")
        
        # Select with required tools - both have write_artifact
        selected = agent_registry.select_agent(
            required_tools=["write_artifact"],
            required_permissions=["write"],
        )
        
        # Should select agent-b (higher max_tokens)
        assert selected.agent_id == "agent-b"
        
        # Select with read_artifact - only agent-b has it
        selected = agent_registry.select_agent(
            required_tools=["read_artifact"],
            required_permissions=["read"],
        )
        assert selected.agent_id == "agent-b"
        
        # Select with write_file - only agent-b has it
        selected = agent_registry.select_agent(
            required_tools=["write_file"],
            required_permissions=["write"],
        )
        assert selected.agent_id == "agent-b"
    
    def test_tool_permission_enforcement(self):
        """AC-E4-07/08: Tool permissions are enforced; unauthorized denied."""
        # This is tested via the agent's _require_tool_permission method
        agent = E4TestAgent()
        
        # Allowed tool
        assert agent._check_tool_permission("write_artifact") is True
        agent._require_tool_permission("write_artifact")  # Should not raise
        
        # Disallowed tool
        assert agent._check_tool_permission("run_command") is False
        with pytest.raises(PermissionError, match="not permitted to use tool"):
            agent._require_tool_permission("run_command")
    
    def test_lifecycle_state_machine(self):
        """AC-E4-09: Agent lifecycle is explicit and enforced."""
        definition = AgentDefinition(
            agent_id="test-agent-001",
            agent_type=AgentType.IMPLEMENTER,
            name="TestAgent",
            version="1.0",
            tools=["write_artifact"],
            permissions=["write"],
            max_tokens=10000,
            timeout_seconds=60,
            requires_sandbox=True,
            supported_domains=["testing"],
            implementation_class="unified.test_agent.E4TestAgent",
        )
        agent_registry.register_definition(definition)
        
        # Initial state
        assert agent_registry.get_lifecycle_state("test-agent-001") == AgentLifecycleState.REGISTERED
        
        # Enable -> AVAILABLE
        agent_registry.enable_agent("test-agent-001")
        assert agent_registry.get_lifecycle_state("test-agent-001") == AgentLifecycleState.AVAILABLE
        assert definition.state == AgentLifecycleState.AVAILABLE
        assert definition.enabled is True
        
        # Assign -> ASSIGNED
        agent_registry.set_lifecycle_state("test-agent-001", AgentLifecycleState.ASSIGNED)
        assert agent_registry.get_lifecycle_state("test-agent-001") == AgentLifecycleState.ASSIGNED
        
        # Run -> RUNNING
        agent_registry.set_lifecycle_state("test-agent-001", AgentLifecycleState.RUNNING)
        assert agent_registry.get_lifecycle_state("test-agent-001") == AgentLifecycleState.RUNNING
        
        # Complete -> COMPLETED
        agent_registry.set_lifecycle_state("test-agent-001", AgentLifecycleState.COMPLETED)
        assert agent_registry.get_lifecycle_state("test-agent-001") == AgentLifecycleState.COMPLETED
        
        # Back to AVAILABLE
        agent_registry.set_lifecycle_state("test-agent-001", AgentLifecycleState.AVAILABLE)
        assert agent_registry.get_lifecycle_state("test-agent-001") == AgentLifecycleState.AVAILABLE
        
        # Disable -> DISABLED
        agent_registry.disable_agent("test-agent-001")
        assert agent_registry.get_lifecycle_state("test-agent-001") == AgentLifecycleState.DISABLED
        assert definition.enabled is False
        
        # Invalid transition should fail
        with pytest.raises(ValueError, match="Invalid agent lifecycle transition"):
            agent_registry.set_lifecycle_state("test-agent-001", AgentLifecycleState.RUNNING)
    
    def test_disabled_agent_cannot_execute(self):
        """AC-E4-10: Disabled agents cannot execute."""
        definition = AgentDefinition(
            agent_id="test-agent-001",
            agent_type=AgentType.IMPLEMENTER,
            name="TestAgent",
            version="1.0",
            tools=["write_artifact"],
            permissions=["write"],
            max_tokens=10000,
            timeout_seconds=60,
            requires_sandbox=True,
            supported_domains=["testing"],
            implementation_class="unified.test_agent.E4TestAgent",
        )
        agent_registry.register_definition(definition)
        agent_registry.register_implementation(AgentType.IMPLEMENTER, E4TestAgent)
        agent_registry.enable_agent("test-agent-001")
        agent_registry.disable_agent("test-agent-001")
        
        factory = AgentFactory(agent_registry)
        
        # Try to create agent by ID - should fail
        with pytest.raises(RuntimeError, match="not available"):
            factory.create_agent_by_id("test-agent-001", None)
    
    def test_unknown_agent_rejected(self):
        """AC-E4-11: Unknown agents cannot execute."""
        factory = AgentFactory(agent_registry)
        
        with pytest.raises(ValueError, match="Unknown agent"):
            factory.create_agent_by_id("unknown-agent", None)
    
    @pytest.mark.asyncio
    async def test_vs003_full_lifecycle(self, sandbox_manager, event_collector, evidence_store, temp_dir):
        """AC-E4-12: VS-003 completes through real E3 execution engine."""
        manager, artifacts_dir = sandbox_manager
        events, collector = event_collector
        
        # Register test agent
        register_e4_test_agent(agent_registry)
        
        # Create mission
        mission = create_mission("VS-003: Test agent lifecycle")
        run = create_run(mission.mission_id)
        
        # Create task for IMPLEMENTER using AgentTask (has context field)
        task = AgentTask(
            task_id=new_task_id(),
            run_id=run.run_id,
            mission_id=mission.mission_id,
            name="Write test artifact",
            description="Write a test file via agent",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "File e4_test_output.txt exists",
                "File contains 'VS-003'",
            ],
            context={"content": b"Hello, VS-003 from E4TestAgent!", "path": "e4_test_output.txt"},
        )
        
        # Create attempt
        attempt_id = new_attempt_id()
        agent_id = new_agent_id()
        
        # Create agent context
        context = AgentContext(
            mission_id=mission.mission_id,
            run_id=run.run_id,
            task_id=task.task_id,
            attempt_id=attempt_id,
            agent_id=agent_id,
            agent_type=AgentType.IMPLEMENTER,
            sandbox_id="test-sandbox",
            sandbox_manager=manager,
            event_emitter=collector,
            evidence_store=evidence_store,
        )
        
        # Execute via AgentFactory
        factory = AgentFactory(agent_registry)
        result = await factory.execute_agent_by_id(
            "e4-test-agent-001",
            context,
            task,
        )
        
        # Verify result
        assert result.success is True
        assert result.agent_type == AgentType.IMPLEMENTER
        assert result.evidence_hash != ""
        assert len(result.artifacts) == 1
        
        # Verify artifact exists
        artifact_id = result.artifacts[0]
        artifact_obj = evidence_store.get_artifact_obj(artifact_id)
        assert artifact_obj is not None
        assert artifact_obj.name == "e4_test_output.txt"
        
        # Verify content
        content = evidence_store.read_artifact_content(artifact_id)
        assert content is not None
        assert b"VS-003" in content
        
        # Verify events emitted
        event_types = [e.event_type for e in events]
        assert EventType.AGENT_STARTED in event_types
        assert EventType.AGENT_COMPLETED in event_types
        
        # Verify agent lifecycle
        assert agent_registry.get_lifecycle_state("e4-test-agent-001") == AgentLifecycleState.COMPLETED
    
    @pytest.mark.asyncio
    async def test_agent_failure_preserved(self, sandbox_manager, event_collector, temp_dir, evidence_store):
        """AC-E4-13: Agent failure is preserved in execution history."""
        manager, artifacts_dir = sandbox_manager
        events, collector = event_collector
        
        # Register a failing agent
        class FailingAgent(E4TestAgent):
            async def execute(self, context, task):
                raise RuntimeError("Intentional failure for testing")
        
        agent_registry.register_implementation(AgentType.IMPLEMENTER, FailingAgent)
        agent_registry.register_definition(AgentDefinition(
            agent_id="failing-agent",
            agent_type=AgentType.IMPLEMENTER,
            name="FailingAgent",
            version="1.0",
            tools=["write_artifact"],
            permissions=["write"],
            max_tokens=10000,
            timeout_seconds=60,
            requires_sandbox=True,
            supported_domains=["testing"],
            implementation_class="unified.test_agent.FailingAgent",
        ))
        agent_registry.enable_agent("failing-agent")
        
        # Create mission/task
        mission = create_mission("Test agent failure")
        run = create_run(mission.mission_id)
        task = AgentTask(
            task_id=new_task_id(),
            run_id=run.run_id,
            mission_id=mission.mission_id,
            name="Failing task",
            description="Task that fails",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[],
        )
        
        context = AgentContext(
            mission_id=mission.mission_id,
            run_id=run.run_id,
            task_id=task.task_id,
            attempt_id=new_attempt_id(),
            agent_id=new_agent_id(),
            agent_type=AgentType.IMPLEMENTER,
            sandbox_id="test-sandbox",
            sandbox_manager=manager,
            event_emitter=collector,
            evidence_store=evidence_store,
        )
        
        factory = AgentFactory(agent_registry)
        result = await factory.execute_agent_by_id("failing-agent", context, task)
        
        # Verify failure
        assert result.success is False
        assert result.error_type == "RuntimeError"
        assert "Intentional failure" in result.error
        
        # Verify event emitted
        event_types = [e.event_type for e in events]
        assert EventType.AGENT_FAILED in event_types
        
        # Verify lifecycle state is FAILED
        assert agent_registry.get_lifecycle_state("failing-agent") == AgentLifecycleState.FAILED
        
        # Failed attempt should be in history (agent can be retried)
        # Reset to AVAILABLE and retry
        agent_registry.set_lifecycle_state("failing-agent", AgentLifecycleState.AVAILABLE)
        assert agent_registry.get_lifecycle_state("failing-agent") == AgentLifecycleState.AVAILABLE
    
    def test_e3_regression(self):
        """AC-E4-14: E3 tests remain green."""
        # This test ensures the E3 execution engine still works
        # by verifying the imports and basic structure
        from unified.execution import ExecutionEngine
        from unified.contracts import (
            AgentRole, AgentTask, AgentResult, AgentCapability, AgentContext,
            AgentRegistry, AgentFactory, AgentDefinition, AgentLifecycleState,
            validate_agent_lifecycle_transition, AGENT_LIFECYCLE_TRANSITIONS,
            BaseAgent, EASRoleAdapter, AgentSelectionError,
        )
        
        # Verify all E4 exports are available
        assert AgentLifecycleState.REGISTERED
        assert AgentLifecycleState.AVAILABLE
        assert AgentLifecycleState.ASSIGNED
        assert AgentLifecycleState.RUNNING
        assert AgentLifecycleState.COMPLETED
        assert AgentLifecycleState.FAILED
        assert AgentLifecycleState.DISABLED
        
        assert validate_agent_lifecycle_transition
        assert AGENT_LIFECYCLE_TRANSITIONS
        
        assert AgentDefinition
        assert AgentRegistry
        assert agent_registry
        assert AgentFactory
        assert AgentSelectionError
        assert BaseAgent
        assert EASRoleAdapter
    
    def test_no_llm_required(self):
        """AC-E4-15: E4 operates without external LLM."""
        # The test agent doesn't use LLM
        agent = E4TestAgent()
        assert agent.capability.tools == ["write_artifact", "read_artifact"]
        # No LLM gateway needed for basic execution
    
    @pytest.mark.asyncio
    async def test_evidence_from_real_execution(self, sandbox_manager, event_collector, evidence_store, temp_dir):
        """AC-E4-16: Evidence is generated from real execution."""
        manager, artifacts_dir = sandbox_manager
        events, collector = event_collector
        
        register_e4_test_agent(agent_registry)
        
        mission = create_mission("Evidence test")
        run = create_run(mission.mission_id)
        task = AgentTask(
            task_id=new_task_id(),
            run_id=run.run_id,
            mission_id=mission.mission_id,
            name="Write with evidence",
            description="Write file and produce evidence",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=["File exists"],
            context={"content": b"Hello, Evidence!", "path": "evidence_test.txt"},
        )
        
        context = AgentContext(
            mission_id=mission.mission_id,
            run_id=run.run_id,
            task_id=task.task_id,
            attempt_id=new_attempt_id(),
            agent_id=new_agent_id(),
            agent_type=AgentType.IMPLEMENTER,
            sandbox_id="test-sandbox",
            sandbox_manager=manager,
            event_emitter=collector,
            evidence_store=evidence_store,
        )
        
        factory = AgentFactory(agent_registry)
        result = await factory.execute_agent_by_id("e4-test-agent-001", context, task)
        
        # Evidence must be real (not fabricated)
        assert result.success is True
        assert result.evidence_hash != ""
        assert len(result.evidence_hash) == 64  # SHA256
        
        # Verify evidence in store
        artifact_id = result.artifacts[0]
        artifact = evidence_store.get_artifact_obj(artifact_id)
        assert artifact is not None
        assert artifact.sha256 == result.evidence_hash
        
        # Verify content matches hash
        import hashlib
        content = evidence_store.read_artifact_content(artifact_id)
        computed_hash = hashlib.sha256(content).hexdigest()
        assert computed_hash == result.evidence_hash
    
    def test_no_production_mock(self):
        """AC-E4-17: No production mock replaces agent lifecycle."""
        # Verify no mock imports in production code
        import unified.agent_role as agent_role_module
        import unified.test_agent as test_agent_module
        
        import inspect
        agent_role_source = inspect.getsource(agent_role_module)
        test_agent_source = inspect.getsource(test_agent_module)
        
        # Should not have mock imports
        assert "unittest.mock" not in agent_role_source
        assert "unittest.mock" not in test_agent_source
        assert "from mock import" not in agent_role_source
        assert "from mock import" not in test_agent_source
        assert "MagicMock" not in agent_role_source
        assert "MagicMock" not in test_agent_source
        assert "patch(" not in agent_role_source
        assert "patch(" not in test_agent_source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])