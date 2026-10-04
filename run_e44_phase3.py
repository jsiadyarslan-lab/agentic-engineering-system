#!/usr/bin/env python3
"""
E44 Self-Hosting Mission Execution Script - Phase 3: Implementation
Reads actual implementation from working files.
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

def read_file(path):
    """Read file content."""
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

async def run_e44_phase3():
    """Execute E44 Phase 3: Implementation (6 parallel tasks)."""
    
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
    
    # Read actual implementation content from working files
    evidence_chain_content = read_file("src/unified/evidence_chain.py")
    tamper_detection_content = read_file("tests/e44/test_tamper_detection.py")
    golden_chain_content = read_file("tests/e44/test_golden_chain.py")
    integration_test_content = read_file("tests/e44/test_integration.py")
    
    # For execution.py, operational.py, verification_standard.py - use current content
    # (they already have the E44 integration code)
    execution_content = read_file("src/unified/execution.py")
    operational_content = read_file("src/unified/operational.py")
    verification_standard_content = read_file("src/unified/verification_standard.py")
    
    # Define Phase 3 tasks - Implementation
    tasks = [
        TaskSpec(
            key="e44_t7_evidence_chain_core",
            name="Implement EvidenceChain Core",
            description="Implement EvidenceChain class with Ed25519 signing, Merkle tree, verification API",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:src/unified/evidence_chain.py",
                "file_contains:src/unified/evidence_chain.py:class EvidenceChain",
                "file_contains:src/unified/evidence_chain.py:Ed25519",
                "file_contains:src/unified/evidence_chain.py:Merkle"
            ],
            context={"operation": "write_file", "path": "src/unified/evidence_chain.py", "content": evidence_chain_content}
        ),
        TaskSpec(
            key="e44_t8_evidence_store_integration",
            name="Integrate EvidenceChain with FileEvidenceStore",
            description="Modify FileEvidenceStore in execution.py to integrate with EvidenceChain",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:src/unified/execution.py",
                "file_contains:src/unified/execution.py:evidence_chain",
                "file_contains:src/unified/execution.py:add_artifact",
                "file_contains:src/unified/execution.py:create_checkpoint"
            ],
            context={"operation": "write_file", "path": "src/unified/execution.py", "content": execution_content}
        ),
        TaskSpec(
            key="e44_t9_verifier_integration",
            name="Integrate VerifierAgent with EvidenceChain",
            description="Modify OperationalVerifierAgent to use EvidenceChain.verify_chain()",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:src/unified/operational.py",
                "file_contains:src/unified/operational.py:EvidenceChain",
                "file_contains:src/unified/operational.py:verify_chain"
            ],
            context={"operation": "write_file", "path": "src/unified/operational.py", "content": operational_content}
        ),
        TaskSpec(
            key="e44_t10_acceptance_criterion_extension",
            name="Extend AcceptanceCriterion with tamper evidence",
            description="Add tamper_evidence, chain_verification fields to AcceptanceCriterion",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:src/unified/verification_standard.py",
                "file_contains:src/unified/verification_standard.py:tamper_evidence",
                "file_contains:src/unified/verification_standard.py:chain_verification"
            ],
            context={"operation": "write_file", "path": "src/unified/verification_standard.py", "content": verification_standard_content}
        ),
        TaskSpec(
            key="e44_t11_tamper_detection_tests",
            name="Create Tamper Detection Tests",
            description="Create test_tamper_detection.py for EvidenceChain tamper detection",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:tests/e44/test_tamper_detection.py",
                "file_contains:tests/e44/test_tamper_detection.py:test_tamper_detection",
                "file_contains:tests/e44/test_tamper_detection.py:test_chain_linkage_verification",
                "file_contains:tests/e44/test_tamper_detection.py:test_signature_verification"
            ],
            context={"operation": "write_file", "path": "tests/e44/test_tamper_detection.py", "content": tamper_detection_content}
        ),
        TaskSpec(
            key="e44_t12_golden_chain_test",
            name="Create Golden Chain Integration Test",
            description="Create test_golden_chain.py for end-to-end evidence chain test",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:tests/e44/test_golden_chain.py",
                "file_contains:tests/e44/test_golden_chain.py:test_golden_chain",
                "file_contains:tests/e44/test_golden_chain.py:MissionController"
            ],
            context={"operation": "write_file", "path": "tests/e44/test_golden_chain.py", "content": golden_chain_content}
        ),
    ]
    
    # Define mission
    mission, run, _ = mission_controller.define_mission(
        user_request="E44 Phase 3: Implementation - EvidenceChain core and integration",
        specs=tasks
    )
    
    # Execute mission
    result = await mission_controller.execute_run(run.run_id, max_parallel=6)
    
    print(f"\nPhase 3 Result: {result}")
    return result

if __name__ == "__main__":
    asyncio.run(run_e44_phase3())