"""
E41-R2 Tamper Test for OperationalVerifierAgent

Tests that the independent verifier correctly:
- Case A: Valid artifact -> VERIFIED
- Case B: Tampered artifact -> FAILED  
- Case C: Tampered evidence/hash -> FAILED
- Case D: Missing artifact -> FAILED
"""
import asyncio
import json
import tempfile
import hashlib
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from unified.operational import OperationalVerifierAgent
from unified.contracts import AgentType
from unified.execution import FileEvidenceStore
from unified.agent_role import AgentContext, AgentTask
from unified.domain_model import Artifact, new_artifact_id, new_attempt_id


async def test_verifier_tamper():
    """Run tamper tests for OperationalVerifierAgent."""
    
    artifacts_dir = tempfile.mkdtemp(prefix="e41_tamper_")
    print(f"Artifacts dir: {artifacts_dir}")
    
    # Create evidence store
    evidence_store = FileEvidenceStore(artifacts_dir)
    
    def create_artifact(path: str, content: bytes, mission_id: str = "test-mission") -> Artifact:
        """Create an artifact and store it in evidence store with file on disk."""
        sha256 = hashlib.sha256(content).hexdigest()
        artifact = Artifact(
            artifact_id=new_artifact_id(),
            name=os.path.basename(path),
            path=path,
            sha256=sha256,
            size_bytes=len(content),
            created_by="test-sandbox",
            mission_id=mission_id,
        )
        # Write content to disk
        full_path = os.path.join(artifacts_dir, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'wb') as f:
            f.write(content)
        # Store in evidence store
        evidence_store.store_artifact(artifact)
        return artifact
    
    async def run_verification(task_id: str, criteria: list, context_dict: dict = None) -> dict:
        """Helper to run verification."""
        context = AgentContext(
            mission_id="test-mission",
            run_id="test-run",
            task_id=task_id,
            attempt_id=new_attempt_id(),
            agent_id="test-verifier-001",
            agent_type=AgentType.VERIFIER,
            sandbox_id="test-sandbox",
            sandbox_manager=None,  # Not needed for read-only verification
            evidence_store=evidence_store,
        )
        
        task = AgentTask(
            task_id=task_id,
            mission_id="test-mission",
            run_id="test-run",
            name=f"Verification {task_id}",
            description=f"Test verification for {task_id}",
            agent_type=AgentType.VERIFIER,
            acceptance_criteria=criteria,
            context=context_dict or {},
        )
        
        verifier = OperationalVerifierAgent()
        result = await verifier.execute(context, task)
        return {"success": result.success, "output": result.output}
    
    results = {}
    
    # ===== CASE A: Valid artifact -> VERIFIED =====
    print("\n=== CASE A: Valid artifact ===")
    valid_content = b"Hello, World! This is a valid artifact."
    create_artifact("test_valid.txt", valid_content)
    
    result = await run_verification("test-task-a", [
        "file_exists:test_valid.txt",
        "file_contains:test_valid.txt:Hello, World!",
    ])
    
    print(f"Result: success={result['success']}, output={result['output']}")
    results["case_a"] = {
        "expected": "VERIFIED",
        "actual": "VERIFIED" if result['success'] else "FAILED",
        "passed": result['success'],
        "details": result['output']
    }
    
    # ===== CASE B: Tampered artifact -> FAILED =====
    print("\n=== CASE B: Tampered artifact ===")
    tampered_content = b"TAMPERED: This content has been modified!"
    create_artifact("test_tampered.txt", tampered_content)
    
    result_b = await run_verification("test-task-b", [
        "file_exists:test_tampered.txt",
        "file_contains:test_tampered.txt:Hello, World!",  # Expects original content
    ])
    
    print(f"Result: success={result_b['success']}, output={result_b['output']}")
    results["case_b"] = {
        "expected": "FAILED",
        "actual": "FAILED" if not result_b['success'] else "VERIFIED",
        "passed": not result_b['success'],
        "details": result_b['output']
    }
    
    # ===== CASE C: Tampered evidence/hash -> FAILED =====
    print("\n=== CASE C: Tampered evidence/hash ===")
    hash_content = b"Content for hash test"
    hash_artifact = create_artifact("test_hash.txt", hash_content)
    real_hash = hash_artifact.sha256
    wrong_hash = "0" * 64  # Wrong hash
    
    result_c = await run_verification("test-task-c", [
        f"file_hash_matches:test_hash.txt:{wrong_hash}",  # Wrong expected hash
    ])
    
    print(f"Result: success={result_c['success']}, output={result_c['output']}")
    print(f"  Real hash: {real_hash}")
    print(f"  Expected (wrong): {wrong_hash}")
    results["case_c"] = {
        "expected": "FAILED",
        "actual": "FAILED" if not result_c['success'] else "VERIFIED",
        "passed": not result_c['success'],
        "details": result_c['output']
    }
    
    # ===== CASE D: Missing artifact -> FAILED =====
    print("\n=== CASE D: Missing artifact ===")
    result_d = await run_verification("test-task-d", [
        "file_exists:nonexistent.txt",
    ])
    
    print(f"Result: success={result_d['success']}, output={result_d['output']}")
    results["case_d"] = {
        "expected": "FAILED",
        "actual": "FAILED" if not result_d['success'] else "VERIFIED",
        "passed": not result_d['success'],
        "details": result_d['output']
    }
    
    # Summary
    print("\n" + "="*60)
    print("TAMPER TEST SUMMARY")
    print("="*60)
    all_passed = True
    for case, result in results.items():
        status = "PASS" if result["passed"] else "FAIL"
        print(f"  {case}: {status} (expected {result['expected']}, got {result['actual']})")
        if not result["passed"]:
            all_passed = False
    
    # Save results
    output_file = Path(artifacts_dir) / "verifier_tamper_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {output_file}")
    
    return all_passed, results


if __name__ == "__main__":
    success, results = asyncio.run(test_verifier_tamper())
    sys.exit(0 if success else 1)