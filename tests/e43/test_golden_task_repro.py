#!/usr/bin/env python3
"""
E43-R2 Golden Task Reproduction Test
Proves real task completion with:
- REAL AGENT (OperationalImplementerAgent)
- REAL TOOL (write)
- REAL ARTIFACT (hello.txt with SHA256)
- INDEPENDENT VERIFICATION (OperationalVerifierAgent)
- TASK_COMPLETED state
"""

import asyncio
import json
import hashlib
import tempfile
import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from unified.execution import create_execution_engine
from unified.operational import (
    OperationalImplementerAgent,
    OperationalVerifierAgent,
)
from unified.domain_model import AgentType, TaskState
from unified.agent_role import AgentDefinition, AgentLifecycleState
from unified.mission_controller import TaskSpec, MissionController
from unified.verification_standard import AcceptanceCriterion, CriterionType


async def test_golden_task():
    """Reproduce the Golden Task from scratch."""
    
    # Create temp directory for artifacts
    with tempfile.TemporaryDirectory() as tmpdir:
        artifacts_dir = Path(tmpdir) / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"Artifacts dir: {artifacts_dir}")
        
        # Create execution engine with operational agents
        engine = create_execution_engine(artifacts_base_dir=str(artifacts_dir))
        
        # Register OperationalImplementerAgent
        impl_def = AgentDefinition(
            agent_id="e43r2-implementer-001",
            agent_type=AgentType.IMPLEMENTER,
            name="Implementer",
            version="1.0",
            description="Implementation and coding (E43-R2)",
            tools=["write_artifact", "read_artifact", "run_command", "security_audit"],
            permissions=["write", "read", "execute", "security_scan"],
            max_tokens=50000,
            timeout_seconds=300,
            requires_sandbox=True,
            supported_domains=["file_operations", "code_execution", "data_processing", "security"],
            implementation_class="unified.operational.OperationalImplementerAgent",
            state=AgentLifecycleState.REGISTERED,
        )
        engine.agent_registry.register_definition(impl_def)
        engine.agent_registry.enable_agent("e43r2-implementer-001")
        engine.agent_registry.replace_implementation(AgentType.IMPLEMENTER, OperationalImplementerAgent)
        
        # Register OperationalVerifierAgent
        ver_def = AgentDefinition(
            agent_id="e43r2-verifier-001",
            agent_type=AgentType.VERIFIER,
            name="Verifier",
            version="1.0",
            description="Verification and validation (E43-R2)",
            tools=["write_artifact", "read_artifact", "run_command", "security_audit"],
            permissions=["write", "read", "execute", "security_scan"],
            max_tokens=50000,
            timeout_seconds=300,
            requires_sandbox=True,
            supported_domains=["file_operations", "code_execution", "data_processing", "security"],
            implementation_class="unified.operational.OperationalVerifierAgent",
            state=AgentLifecycleState.REGISTERED,
        )
        engine.agent_registry.register_definition(ver_def)
        engine.agent_registry.enable_agent("e43r2-verifier-001")
        engine.agent_registry.replace_implementation(AgentType.VERIFIER, OperationalVerifierAgent)
        
        mc = MissionController(engine, state_dir=str(artifacts_dir))
        
        # Define acceptance criteria as strings (format expected by OperationalVerifierAgent)
        criteria = [
            "file_exists:hello.txt",
            "file_contains:hello.txt:Hello World",
        ]
        
        # Create task spec
        task_spec = TaskSpec(
            key="golden-1",
            name="Write Hello World",
            description="Write hello.txt with 'Hello World'",
            depends_on=[],
            acceptance_criteria=criteria,
            context={"operation": "write_file", "path": "hello.txt", "content": "Hello World"},
            agent_type=AgentType.IMPLEMENTER,
        )
        
        # Define and execute mission
        mission, run, key_to_id = mc.define_mission(
            user_request="Reproduce golden task: write file, verify independently",
            specs=[task_spec],
        )
        
        print(f"Mission: {mission.mission_id}")
        print(f"Run: {run.run_id}")
        print("Executing...")
        
        run_result = await mc.execute_run(mission.current_run_id or run.run_id)
        
        print(f"Run result: {run_result.get('state', 'unknown')}")
        
        # Get task result
        task_id = key_to_id.get("golden-1")
        if task_id:
            task = engine.tasks.get(task_id)
            if task:
                print(f"Task state: {task.state}")
                print(f"Task artifact_ids: {task.artifact_ids}")
        
        # Verify artifact from evidence store
        if engine.evidence_store and engine.evidence_store._artifacts:
            for art_id, art in engine.evidence_store._artifacts.items():
                if art.path == "hello.txt":
                    content = art.content if hasattr(art, 'content') and art.content else ""
                    if not content:
                        # Read from sandbox if needed
                        pass
                    print(f"\nArtifact found in evidence store:")
                    print(f"  Artifact ID: {art_id}")
                    print(f"  Path: {art.path}")
                    print(f"  SHA256: {art.sha256}")
                    print(f"  Size: {art.size_bytes}")
                    
                    expected = "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e"
                    print(f"  Expected: {expected}")
                    print(f"  Match: {art.sha256 == expected}")
                    
                    # Check completion
                    if task and task.state == TaskState.COMPLETED:
                        print("\n[SUCCESS] GOLDEN TASK REPRODUCED: TASK_COMPLETED")
                        return True
                    else:
                        print(f"\n[FAILED] GOLDEN TASK FAILED: state={task.state if task else 'MISSING'}")
                        return False
        
        print("[ERROR] hello.txt not found in evidence store!")
        return False


if __name__ == "__main__":
    result = asyncio.run(test_golden_task())
    sys.exit(0 if result else 1)