#!/usr/bin/env python3
"""Tamper Detection Tests for EvidenceChain."""
import sys
sys.path.insert(0, 'src')

import tempfile
from unified.evidence_chain import EvidenceChain, VerificationResult, TamperEvidence

def test_evidence_chain_basic():
    """Test basic EvidenceChain functionality."""
    private_key, public_key = EvidenceChain.generate_key_pair()
    
    chain = EvidenceChain(private_key=private_key, mission_id="test-mission", run_id="test-run")
    
    # Add artifacts
    chain.add_artifact("artifact-1", "abc123")
    chain.add_artifact("artifact-2", "def456")
    
    # Create checkpoint
    checkpoint = chain.create_checkpoint()
    
    assert checkpoint.sequence == 1
    assert checkpoint.mission_id == "test-mission"
    assert checkpoint.run_id == "test-run"
    assert checkpoint.signature != ""
    
    # Verify chain
    artifacts = {"artifact-1": "abc123", "artifact-2": "def456"}
    result = chain.verify_chain(artifacts)
    
    assert result.valid == True
    assert result.verified_checkpoints == 1
    assert result.total_artifacts == 2
    
    print("PASS: test_evidence_chain_basic")

def test_tamper_detection():
    """Test tamper detection when artifact is modified."""
    private_key, public_key = EvidenceChain.generate_key_pair()
    
    chain = EvidenceChain(private_key=private_key, mission_id="test-mission", run_id="test-run")
    
    # Add original artifacts
    chain.add_artifact("artifact-1", "abc123")
    chain.add_artifact("artifact-2", "def456")
    
    # Create checkpoint with original state
    chain.create_checkpoint()
    
    # Simulate tampering - modify artifact hash
    tampered_artifacts = {"artifact-1": "abc123", "artifact-2": "TAMPERED_HASH"}
    
    # Verify should detect tampering
    result = chain.verify_chain(tampered_artifacts)
    
    assert result.valid == False
    assert result.tamper_evidence is not None
    assert result.tamper_evidence["type"] == "artifact_modified"
    
    print("PASS: test_tamper_detection")

def test_chain_linkage_verification():
    """Test chain linkage verification across multiple checkpoints."""
    private_key, public_key = EvidenceChain.generate_key_pair()
    
    chain = EvidenceChain(private_key=private_key, mission_id="test-mission", run_id="test-run")
    
    # Add artifacts and create first checkpoint
    chain.add_artifact("artifact-1", "abc123")
    cp1 = chain.create_checkpoint()
    
    # Add more artifacts and create second checkpoint
    chain.add_artifact("artifact-2", "def456")
    cp2 = chain.create_checkpoint()
    
    # Verify chain linkage
    assert cp2.prev_checkpoint_hash == cp1.compute_hash()
    
    # Verify full chain
    artifacts = {"artifact-1": "abc123", "artifact-2": "def456"}
    result = chain.verify_chain(artifacts)
    
    assert result.valid == True
    assert result.verified_checkpoints == 2
    
    print("PASS: test_chain_linkage_verification")

def test_signature_verification():
    """Test Ed25519 signature verification."""
    private_key, public_key = EvidenceChain.generate_key_pair()
    
    chain = EvidenceChain(private_key=private_key, mission_id="test-mission", run_id="test-run")
    
    chain.add_artifact("artifact-1", "abc123")
    checkpoint = chain.create_checkpoint()
    
    # Verify with correct public key
    result = chain.verify_chain({"artifact-1": "abc123"})
    assert result.valid == True
    
    # Create chain with wrong key - should fail signature verification
    wrong_private_key, wrong_public_key = EvidenceChain.generate_key_pair()
    wrong_chain = EvidenceChain(private_key=wrong_private_key, mission_id="test-mission", run_id="test-run")
    wrong_chain.add_artifact("artifact-1", "abc123")
    wrong_checkpoint = wrong_chain.create_checkpoint()
    
    # Verify with original public key - should fail
    wrong_chain.public_key = public_key
    result = wrong_chain.verify_chain({"artifact-1": "abc123"})
    assert result.valid == False
    assert result.tamper_evidence["type"] == "invalid_signature"
    
    print("PASS: test_signature_verification")

def test_persistence_roundtrip():
    """Test export/import of checkpoints."""
    private_key, public_key = EvidenceChain.generate_key_pair()
    
    chain = EvidenceChain(private_key=private_key, mission_id="test-mission", run_id="test-run")
    
    chain.add_artifact("artifact-1", "abc123")
    chain.add_artifact("artifact-2", "def456")
    chain.create_checkpoint()
    chain.add_artifact("artifact-3", "ghi789")
    chain.create_checkpoint()
    
    # Export checkpoints
    exported = chain.export_checkpoints()
    assert len(exported) == 2
    
    # Import into new chain
    loaded_chain = EvidenceChain.load_checkpoints(exported, public_key)
    
    assert len(loaded_chain.checkpoints) == 2
    assert loaded_chain._sequence == 2
    assert loaded_chain.checkpoints[0].mission_id == "test-mission"
    assert loaded_chain.checkpoints[1].prev_checkpoint_hash == loaded_chain.checkpoints[0].compute_hash()
    
    # Verify with loaded chain
    artifacts = {"artifact-1": "abc123", "artifact-2": "def456", "artifact-3": "ghi789"}
    result = loaded_chain.verify_chain(artifacts)
    assert result.valid == True
    assert result.verified_checkpoints == 2
    
    print("PASS: test_persistence_roundtrip")

if __name__ == "__main__":
    test_evidence_chain_basic()
    test_tamper_detection()
    test_chain_linkage_verification()
    test_signature_verification()
    test_persistence_roundtrip()
    print("\nAll tamper detection tests PASSED!")
