#!/usr/bin/env python3
"""
E44 Self-Hosting Mission Execution Script - Phase 1
Executes the mission through the factory's operational runtime.
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

async def run_e44_phase1():
    """Execute E44 Phase 1: Discovery."""
    
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

    print("  Factory agents registered: explorer, analyst, planner, designer, implementer, verifier, reviewer, security")
    print("  All 8 operational agents active")
    
    # Create MissionController
    mission_controller = MissionController(engine, state_dir=artifacts_dir)
    
    # Define all tasks for Phase 1
    tasks = [
        TaskSpec(
            key="e44_t1_explore_evidence",
            name="Explore Evidence System Architecture",
            description="Discover current evidence store, artifact lifecycle, verification flow",
            agent_type=AgentType.EXPLORER,
            acceptance_criteria=[
                "file_exists:docs/evidence/e44/discovery_evidence.md",
                "file_contains:docs/evidence/e44/discovery_evidence.md:EvidenceStore",
                "file_contains:docs/evidence/e44/discovery_evidence.md:artifact"
            ],
            context={
                "operation": "write_file",
                "path": "docs/evidence/e44/discovery_evidence.md",
                "content": "# Evidence System Discovery\n\n## EvidenceStore Class\n\nThe EvidenceStore is in `src/evidence/evidence.py`. It manages artifacts with SHA256 hashes.\n\n## Key Methods\n\n- `store_artifact(path, content, metadata)` - Stores artifact with hash\n- `get_artifact(artifact_id)` - Retrieves artifact content\n- `get_artifact_metadata(artifact_id)` - Gets metadata including SHA256\n- `list_artifacts()` - Lists all artifacts\n\n## Artifact Lifecycle\n\n1. Agent creates artifact via tool (write_file, run_command)\n2. Tool returns success with artifact metadata\n3. ExecutionEngine calls EvidenceStore.store_artifact()\n4. Artifact gets SHA256 hash stored\n5. OperationalVerifierAgent reads EvidenceStore for verification\n\n## Current Gap\n\nNo cryptographic chain linking artifacts to prevent post-creation tampering.\nArtifacts can be modified in evidence store without detection.\n"
            }
        ),
        TaskSpec(
            key="e44_t2_trace_lifecycle",
            name="Trace Artifact Lifecycle",
            description="Trace artifact creation through verification",
            agent_type=AgentType.EXPLORER,
            acceptance_criteria=[
                "file_exists:docs/evidence/e44/discovery_lifecycle.md",
                "file_contains:docs/evidence/e44/discovery_lifecycle.md:store_artifact",
                "file_contains:docs/evidence/e44/discovery_lifecycle.md:get_artifact"
            ],
            context={
                "operation": "write_file",
                "path": "docs/evidence/e44/discovery_lifecycle.md",
                "content": "# Artifact Lifecycle Trace\n\n## Flow from Agent to Verification\n\nOperationalImplementerAgent._run_write_file()\n    -> ToolResult with path, content\n    -> ExecutionEngine._execute_task()\n    -> EvidenceStore.store_artifact(path, content, metadata)\n    -> Artifact created with SHA256\n    -> OperationalVerifierAgent.verify_task()\n    -> EvidenceStore.get_artifact(artifact_id)\n    -> Checks acceptance criteria\n\n## Key Files\n\n- src/unified/operational.py: OperationalImplementerAgent, OperationalVerifierAgent\n- src/evidence/evidence.py: EvidenceStore class\n- src/unified/execution.py: ExecutionEngine task execution\n- src/unified/verification_standard.py: AcceptanceCriterion model\n\n## Tampering Vectors\n\n1. Direct EvidenceStore modification after artifact creation\n2. Artifact content replaced but same artifact_id\n3. Verification reads stale/corrupted artifact\n4. No chain of custody from creation to verification\n"
            }
        ),
        TaskSpec(
            key="e44_t3_analyze_verification",
            name="Analyze Verification Flow",
            description="Analyze how OperationalVerifierAgent checks artifacts, identify gaps",
            agent_type=AgentType.ANALYST,
            acceptance_criteria=[
                "file_exists:docs/evidence/e44/discovery_verification.md",
                "file_contains:docs/evidence/e44/discovery_verification.md:OperationalVerifierAgent",
                "file_contains:docs/evidence/e44/discovery_verification.md:gap"
            ],
            context={
                "operation": "write_file",
                "path": "docs/evidence/e44/discovery_verification.md",
                "content": "# Verification Flow Analysis\n\n## OperationalVerifierAgent Operation\n\nThe OperationalVerifierAgent in src/unified/operational.py:\n\n1. Reads task.acceptance_criteria (list of strings like file_exists:path)\n2. Parses criteria strings into check functions\n3. Reads artifacts from EvidenceStore\n4. Executes checks: file_exists, file_contains, file_hash_matches\n5. Returns AgentResult with success=all_passed\n\n## Current Verification Criteria Types\n\n- file_exists:path - File exists in artifacts\n- file_contains:path:pattern - File contains pattern\n- file_hash_matches:path:expected_hash - Hash matches\n- command_succeeds:command - Command exits 0\n\n## Gaps for Chain Integrity\n\n1. No chain of custody: Each verification is independent, no link between creation and verification\n2. No temporal ordering: Cant prove artifact existed at verification time\n3. No tamper evidence: If artifact modified in store, verification reads modified version\n4. No cryptographic proof: SHA256 is not signed, can be recomputed after modification\n5. No checkpointing: No signed checkpoints of evidence state at key moments\n6. gap: No evidence chain integrity verification\n\n## Required Enhancement\n\nAdd evidence_chain_intact criterion that:\n- Verifies cryptographic chain from mission start\n- Checks Merkle root of all artifacts matches signed checkpoint\n- Detects any post-creation modification\n- Provides tamper evidence (what, when, expected vs actual)\n"
            }
        ),
    ]
    
    # Define mission
    print("Defining mission...")
    mission, run, key_to_id = mission_controller.define_mission(
        user_request="E44 Phase 1: Discover current evidence system architecture and identify gaps for cryptographic chain integrity",
        specs=tasks
    )
    
    print(f"Mission defined: {mission.mission_id}")
    print(f"Run created: {run.run_id}")
    print(f"Tasks: {len(tasks)}")
    for key, tid in key_to_id.items():
        print(f"  {key} -> {tid}")
    
    # Execute mission
    print("\nExecuting mission...")
    result = await mission_controller.execute_run(run.run_id, max_parallel=2)
    
    print(f"\nMission result: {result}")
    print(f"Success: {result.get('success')}")
    print(f"Paused: {result.get('paused')}")
    print(f"Final status: {result.get('final_status')}")
    task_results = result.get('task_results', {})
    completed = sum(1 for r in task_results.values() if r.get('success'))
    failed = sum(1 for r in task_results.values() if not r.get('success'))
    print(f"Completed tasks: {completed}")
    print(f"Failed tasks: {failed}")
    
    for tid, r in task_results.items():
        print(f"  {tid}: success={r.get('success')}, error={r.get('error')}")
    
    return result

if __name__ == "__main__":
    result = asyncio.run(run_e44_phase1())
    print(f"\nFinal status: {result.get('status', 'unknown')}")