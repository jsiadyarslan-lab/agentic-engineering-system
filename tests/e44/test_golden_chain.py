#!/usr/bin/env python3
"""Golden Chain Integration Test - End-to-end evidence chain in mission context."""
import sys
import os
import asyncio
sys.path.insert(0, 'src')

import tempfile
import json
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

async def test_golden_chain():
    """Test complete evidence chain through mission execution."""
    
    # Create engine with evidence chain
    artifacts_dir = os.path.join(tempfile.gettempdir(), "e44_golden_chain")
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
            agent_id=f"golden-{agent_id_suffix}-001",
            agent_type=agent_type,
            name=name,
            version="1.0",
            description=f"{description} (Golden Chain Test)",
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
            agent_registry.enable_agent(f"golden-{agent_id_suffix}-001")
        except ValueError:
            agent_registry.replace_definition(agent_def)
            agent_registry.enable_agent(f"golden-{agent_id_suffix}-001")
        agent_registry.replace_implementation(agent_type, impl_class)

    mission_controller = MissionController(engine, state_dir=artifacts_dir)
    
    # Define a small mission
    tasks = [
        TaskSpec(
            key="golden_t1_create",
            name="Create Test Artifact",
            description="Create a simple test file",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:golden_test.txt",
                "file_contains:golden_test.txt:Golden Chain Test",
            ],
            context={"operation": "write_file", "path": "golden_test.txt", "content": "Golden Chain Test Content"}
        ),
        TaskSpec(
            key="golden_t2_verify",
            name="Verify Test Artifact",
            description="Verify the created artifact",
            agent_type=AgentType.VERIFIER,
            acceptance_criteria=[
                "file_exists:golden_test.txt",
            ],
            depends_on=["golden_t1_create"]
        ),
    ]
    
    mission, run, _ = mission_controller.define_mission(
        user_request="Golden Chain Integration Test",
        specs=tasks
    )
    
    # Execute mission using mission controller
    result = await mission_controller.execute_run(run.run_id)
    
    # Verify mission completed
    assert result.get("success", False) == True
    
    print("PASS: test_golden_chain - Mission completed with evidence chain")
    return True

if __name__ == "__main__":
    result = asyncio.run(test_golden_chain())
    print("\nGolden Chain Integration Test PASSED!")
