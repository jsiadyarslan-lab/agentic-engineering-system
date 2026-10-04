#!/usr/bin/env python3
"""
E44 Self-Hosting Mission Execution Script - Phase 2: Architecture/Design
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

async def run_e44_phase2():
    """Execute E44 Phase 2: Architecture/Design."""
    
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
    
    # Define Phase 2 tasks
    tasks = [
        TaskSpec(
            key="e44_t4_threat_model",
            name="Threat Model for Evidence Tampering",
            description="STRIDE analysis of evidence store, artifact creation, verification, storage",
            agent_type=AgentType.ANALYST,
            acceptance_criteria=[
                "file_exists:docs/evidence/e44/design_threat_model.md",
                "file_contains:docs/evidence/e44/design_threat_model.md:STRIDE",
                "file_contains:docs/evidence/e44/design_threat_model.md:EvidenceStore"
            ],
            context={
                "operation": "write_file",
                "path": "docs/evidence/e44/design_threat_model.md",
                "content": "# Threat Model: Evidence Tampering (STRIDE Analysis)\n\n## System: Evidence Store and Artifact Chain\n\n## STRIDE Analysis\n\n### Spoofing\n- Attacker creates fake artifact with valid SHA256 (collision unlikely)\n- Attacker impersonates legitimate agent writing to EvidenceStore\n- Mitigation: Agent identity verification, signed artifacts\n\n### Tampering\n- **HIGH RISK**: Direct EvidenceStore modification after artifact creation\n- Artifact content replaced but same artifact_id retained\n- Verification reads modified version, passes if pattern still matches\n- Merkle root not verified against signed checkpoint\n- Mitigation: Signed checkpoints, Merkle tree verification\n\n### Repudiation\n- Agent denies creating artifact\n- No non-repudiation proof (no signatures)\n- Mitigation: Ed25519 signatures on artifact creation\n\n### Information Disclosure\n- EvidenceStore accessible, artifacts readable\n- Low risk - artifacts are development artifacts\n- Mitigation: Access controls if needed\n\n### Denial of Service\n- EvidenceStore corruption blocks verification\n- Large artifact count slows verification\n- Mitigation: Integrity checks, bounded reads\n\n### Elevation of Privilege\n- Malicious agent gains write access to EvidenceStore\n- Could insert fake verification results\n- Mitigation: Agent capability validation, signed checkpoints\n\n## Critical Tampering Vectors\n\n1. **Post-creation artifact modification** - EvidenceStore has no integrity protection\n2. **No chain of custody** - Cannot prove artifact state at verification time\n3. **No temporal ordering** - Artifacts have no sequence proof\n4. **Verification trusts store** - Verifier reads whatever is in store\n\n## Required Countermeasures\n\n1. Cryptographic evidence chain with signed checkpoints\n2. Merkle tree of all artifact hashes per checkpoint\n3. Ed25519 signatures on checkpoints\n4. Verification API that validates chain integrity\n5. Tamper evidence: what changed, when, expected vs actual\n"
            }
        ),
        TaskSpec(
            key="e44_t5_evidence_chain_design",
            name="Cryptographic Evidence Chain Design",
            description="Design Ed25519 key generation, checkpoint structure, Merkle tree, verification API",
            agent_type=AgentType.DESIGNER,
            acceptance_criteria=[
                "file_exists:docs/evidence/e44/design_evidence_chain.md",
                "file_contains:docs/evidence/e44/design_evidence_chain.md:Ed25519",
                "file_contains:docs/evidence/e44/design_evidence_chain.md:Merkle"
            ],
            context={
                "operation": "write_file",
                "path": "docs/evidence/e44/design_evidence_chain.md",
                "content": "# Cryptographic Evidence Chain Design\n\n## Overview\n\nImplement a cryptographic evidence chain that provides:\n- Tamper detection for all mission artifacts\n- Non-repudiation of artifact creation\n- Verifiable chain of custody from creation to verification\n\n## Cryptographic Primitives\n\n### Ed25519 Key Pair\n- Private key: Used to sign checkpoints (held by factory operator)\n- Public key: Distributed for verification\n- Key generation: `cryptography.hazmat.primitives.asymmetric.ed25519`\n\n### Checkpoint Structure\n```json\n{\n  \"checkpoint_id\": \"uuid\",\n  \"mission_id\": \"mission-xxx\",\n  \"run_id\": \"run-xxx\",\n  \"sequence\": 1,\n  \"prev_checkpoint_hash\": \"sha256_of_prev\",\n  \"artifacts_merkle_root\": \"sha256_merkle_root\",\n  \"timestamp\": \"ISO8601\",\n  \"signature\": \"ed25519_signature\"\n}\n```\n\n### Merkle Tree of Artifact Hashes\n- Leaf nodes: SHA256 of each artifact content\n- Internal nodes: SHA256(left_child + right_child)\n- Root: Single hash representing all artifacts at checkpoint\n- Verification: Recompute tree, compare root to checkpoint\n\n### EvidenceChain Class API\n```python\nclass EvidenceChain:\n    def __init__(self, private_key: Ed25519PrivateKey, mission_id: str, run_id: str)\n    def add_artifact(self, artifact_id: str, sha256: str) -> None\n    def create_checkpoint(self) -> Checkpoint\n    def verify_chain(self, checkpoints: List[Checkpoint], artifacts: Dict) -> VerificationResult\n    def detect_tampering(self, checkpoint: Checkpoint, artifacts: Dict) -> TamperEvidence\n```\n\n### VerificationResult\n```python\n@dataclass\nclass VerificationResult:\n    valid: bool\n    tamper_evidence: Optional[TamperEvidence]\n    verified_checkpoints: int\n    total_artifacts: int\n```\n\n### TamperEvidence\n```python\n@dataclass\nclass TamperEvidence:\n    artifact_id: str\n    expected_hash: str\n    actual_hash: str\n    checkpoint_sequence: int\n    details: str\n```\n\n## Integration Points\n\n1. **EvidenceStore**: Maintain EvidenceChain instance, auto-add artifacts\n2. **MissionController**: Create checkpoints at phase transitions\n3. **OperationalVerifierAgent**: Add `evidence_chain_intact` criterion\n4. **Checkpoint triggers**: Mission start, task completion, phase end, mission end\n"
            }
        ),
        TaskSpec(
            key="e44_t6_integration_design",
            name="Integration Points Design",
            description="Design integration with EvidenceStore, OperationalVerifierAgent, mission lifecycle",
            agent_type=AgentType.DESIGNER,
            acceptance_criteria=[
                "file_exists:docs/evidence/e44/design_integration.md",
                "file_contains:docs/evidence/e44/design_integration.md:EvidenceStore",
                "file_contains:docs/evidence/e44/design_integration.md:OperationalVerifierAgent"
            ],
            context={
                "operation": "write_file",
                "path": "docs/evidence/e44/design_integration.md",
                "content": "# Integration Points Design\n\n## EvidenceStore Integration\n\n### Modified EvidenceStore\n- Add `evidence_chain: EvidenceChain` attribute\n- Override `store_artifact()` to call `evidence_chain.add_artifact()`\n- Add `create_checkpoint()` method\n- Add `verify_evidence_chain()` method\n\n### Backward Compatibility\n- EvidenceChain is optional (None = no chain)\n- Existing missions without chain continue to work\n- New missions enable chain via config\n\n## OperationalVerifierAgent Integration\n\n### New Criterion: `evidence_chain_intact`\n```\nevidence_chain_intact:mission_id:run_id\n```\n\n### Verification Logic\n1. Parse criterion to extract mission_id, run_id\n2. Load all checkpoints for mission/run\n3. Load all artifacts from EvidenceStore\n4. Call `EvidenceChain.verify_chain()`\n5. Return success/failure with tamper evidence\n\n### Acceptance Criterion Registration\n- Add to `verification_standard.py` criterion types\n- Map to new check function in OperationalVerifierAgent\n\n## Mission Lifecycle Integration\n\n### Checkpoint Triggers\n1. **Mission START**: Initial checkpoint (empty Merkle root)\n2. **Task COMPLETED**: Checkpoint after each task\n3. **Phase END**: Checkpoint at phase boundary\n4. **Mission END**: Final checkpoint\n\n### MissionController Changes\n- In `execute_run()`: Create checkpoint after each task batch\n- In `define_mission()`: Initialize EvidenceChain for new missions\n- Store checkpoints in mission artifacts\n\n## Artifact Manifest\n\nEach mission produces:\n- `evidence_chain_checkpoints.json`: All signed checkpoints\n- `evidence_chain_manifest.json`: Artifact list with hashes\n- `evidence_chain_verification.json`: Final verification result\n\n## Configuration\n\n```python\n# Enable evidence chain for mission\nmission_config = {\n    \"evidence_chain_enabled\": True,\n    \"checkpoint_frequency\": \"per_task\",  # per_task, per_phase, manual\n    \"key_management\": \"file_based\",  # file_based, env_var, hsm\n}\n```\n"
            }
        ),
    ]
    
    # Define mission
    print("Defining Phase 2 mission...")
    mission, run, key_to_id = mission_controller.define_mission(
        user_request="E44 Phase 2: Design cryptographic evidence chain with threat model and integration points",
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
    task_results = result.get('task_results', {})
    completed = sum(1 for r in task_results.values() if r.get('success'))
    failed = sum(1 for r in task_results.values() if not r.get('success'))
    print(f"Completed tasks: {completed}")
    print(f"Failed tasks: {failed}")
    
    for tid, r in task_results.items():
        print(f"  {tid}: success={r.get('success')}, error={r.get('error')}")
    
    return result

if __name__ == "__main__":
    result = asyncio.run(run_e44_phase2())
    print(f"\nFinal status: {result.get('success', False)}")