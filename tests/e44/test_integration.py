#!/usr/bin/env python3
"""Integration Test for EvidenceChain across factory components."""
import sys
import os
import tempfile
import asyncio
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
    """Test EvidenceChain integration across factory components."""
    
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
    
    mission, run, _ = mission_controller.define_mission(
        user_request="Integration Test Mission",
        specs=tasks
    )
    
    # Execute mission
    result = await mission_controller.execute_run(run.run_id, max_parallel=2)
    
    # Verify mission completed
    assert result.get("success", False) == True, f"Mission failed: {result}"
    
    # Verify artifacts exist in evidence store
    artifacts = {
        art_id: meta.sha256 
        for art_id, meta in engine.evidence_store._artifacts.items()
    }
    
    print(f"Artifacts in store: {len(artifacts)}")
    for art_id, sha in artifacts.items():
        print(f"  {art_id}: {sha[:16]}...")
    
    print("PASS: test_evidence_chain_integration - Full integration verified")
    return True

if __name__ == "__main__":
    result = asyncio.run(test_evidence_chain_integration())
    print("\nEvidenceChain Integration Test PASSED!")
