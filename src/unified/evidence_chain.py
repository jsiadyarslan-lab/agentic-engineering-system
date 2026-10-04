# EvidenceChain - Cryptographic Evidence Chain Integrity

"""
Cryptographic evidence chain for mission artifact integrity.

Provides:
- Ed25519 signed checkpoints
- Merkle tree of artifact hashes
- Tamper detection with evidence
- Chain verification API
"""

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Any
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization


@dataclass
class Checkpoint:
    """Signed checkpoint of evidence state."""
    checkpoint_id: str
    mission_id: str
    run_id: str
    sequence: int
    prev_checkpoint_hash: str
    artifacts_merkle_root: str
    timestamp: str
    artifact_hashes: Dict[str, str] = field(default_factory=dict)  # artifact_id -> sha256 at checkpoint time
    signature: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Checkpoint':
        return cls(**data)
    
    def compute_hash(self) -> str:
        """Compute SHA256 of checkpoint (excluding signature)."""
        data = self.to_dict()
        data.pop('signature', None)
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


@dataclass
class VerificationResult:
    """Result of chain verification."""
    valid: bool
    tamper_evidence: Optional[Dict] = None
    verified_checkpoints: int = 0
    total_artifacts: int = 0
    details: str = ""


@dataclass 
class TamperEvidence:
    """Evidence of tampering."""
    artifact_id: str
    expected_hash: str
    actual_hash: str
    checkpoint_sequence: int
    details: str


class MerkleTree:
    """Merkle tree for artifact hash integrity."""
    
    def __init__(self, leaves: List[str]):
        self.leaves = leaves
        self.root = self._compute_root(leaves)
    
    def _compute_root(self, leaves: List[str]) -> str:
        if not leaves:
            return hashlib.sha256(b"empty").hexdigest()
        if len(leaves) == 1:
            return leaves[0]
        
        next_level = []
        for i in range(0, len(leaves), 2):
            left = leaves[i]
            right = leaves[i + 1] if i + 1 < len(leaves) else left
            combined = hashlib.sha256((left + right).encode()).hexdigest()
            next_level.append(combined)
        return self._compute_root(next_level)
    
    @classmethod
    def from_artifacts(cls, artifacts: Dict[str, str]) -> 'MerkleTree':
        """Create tree from artifact_id -> sha256 mapping."""
        # Sort by artifact_id for deterministic ordering
        sorted_items = sorted(artifacts.items())
        leaves = [sha256 for _, sha256 in sorted_items]
        return cls(leaves)
    
    def verify_inclusion(self, artifact_hash: str, artifacts: Dict[str, str]) -> bool:
        """Verify an artifact hash is included in the tree."""
        return artifact_hash in artifacts.values()


class EvidenceChain:
    """Cryptographic evidence chain for mission artifacts."""
    
    def __init__(
        self,
        private_key: Optional[ed25519.Ed25519PrivateKey] = None,
        mission_id: str = "",
        run_id: str = "",
    ):
        self.mission_id = mission_id
        self.run_id = run_id
        self.artifacts: Dict[str, str] = {}  # artifact_id -> sha256
        self.checkpoints: List[Checkpoint] = []
        self.private_key = private_key
        self.public_key = private_key.public_key() if private_key else None
        self._sequence = 0
    
    def add_artifact(self, artifact_id: str, sha256: str) -> None:
        """Add artifact to the chain."""
        self.artifacts[artifact_id] = sha256
    
    def create_checkpoint(self) -> Checkpoint:
        """Create a signed checkpoint of current state."""
        self._sequence += 1
        
        # Compute Merkle root of current artifacts
        merkle_tree = MerkleTree.from_artifacts(self.artifacts)
        merkle_root = merkle_tree.root
        
        # Previous checkpoint hash
        prev_hash = self.checkpoints[-1].compute_hash() if self.checkpoints else "0" * 64
        
        # Create checkpoint
        checkpoint = Checkpoint(
            checkpoint_id=str(uuid.uuid4()),
            mission_id=self.mission_id,
            run_id=self.run_id,
            sequence=self._sequence,
            prev_checkpoint_hash=prev_hash,
            artifacts_merkle_root=merkle_root,
            artifact_hashes=dict(self.artifacts),  # Store snapshot of artifact hashes
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        
        # Sign checkpoint (excluding signature field)
        if self.private_key:
            checkpoint_data = json.dumps({
                k: v for k, v in checkpoint.to_dict().items() if k != "signature"
            }, sort_keys=True).encode()
            signature = self.private_key.sign(checkpoint_data)
            checkpoint.signature = signature.hex()
        
        self.checkpoints.append(checkpoint)
        return checkpoint
    
    def verify_chain(self, artifacts: Dict[str, str]) -> VerificationResult:
        """Verify the entire evidence chain against current artifacts."""
        if not self.checkpoints:
            return VerificationResult(
                valid=True,
                details="No checkpoints to verify"
            )
        
        verified = 0
        tamper_evidence = None
        
        for checkpoint in self.checkpoints:
            # Verify signature
            if self.public_key and checkpoint.signature:
                try:
                    checkpoint_data = json.dumps({
                        k: v for k, v in checkpoint.to_dict().items() if k != "signature"
                    }, sort_keys=True).encode()
                    self.public_key.verify(bytes.fromhex(checkpoint.signature), checkpoint_data)
                except Exception as e:
                    tamper_evidence = {
                        "type": "invalid_signature",
                        "checkpoint_sequence": checkpoint.sequence,
                        "details": f"Signature verification failed: {e}"
                    }
                    break
            
            # Verify artifacts at checkpoint time match stored hashes
            checkpoint_artifacts = checkpoint.artifact_hashes
            for art_id, expected_hash in checkpoint_artifacts.items():
                actual_hash = artifacts.get(art_id)
                if actual_hash is None:
                    tamper_evidence = {
                        "type": "artifact_missing",
                        "artifact_id": art_id,
                        "expected_hash": expected_hash,
                        "actual_hash": "missing",
                        "checkpoint_sequence": checkpoint.sequence,
                        "details": f"Artifact {art_id} missing at verification (was present at checkpoint {checkpoint.sequence})"
                    }
                    break
                if actual_hash != expected_hash:
                    tamper_evidence = {
                        "type": "artifact_modified",
                        "artifact_id": art_id,
                        "expected_hash": expected_hash,
                        "actual_hash": actual_hash,
                        "checkpoint_sequence": checkpoint.sequence,
                        "details": f"Artifact {art_id} hash mismatch at checkpoint {checkpoint.sequence}"
                    }
                    break
            if tamper_evidence:
                break
            
            # Verify Merkle root matches checkpoint's artifact_hashes
            merkle_tree = MerkleTree.from_artifacts(checkpoint_artifacts)
            if merkle_tree.root != checkpoint.artifacts_merkle_root:
                tamper_evidence = {
                    "type": "merkle_root_mismatch",
                    "checkpoint_sequence": checkpoint.sequence,
                    "expected_root": checkpoint.artifacts_merkle_root,
                    "actual_root": merkle_tree.root,
                    "details": f"Merkle root mismatch at checkpoint {checkpoint.sequence}"
                }
                break
            
            # Verify chain linkage
            if checkpoint.sequence > 1:
                prev_checkpoint = self.checkpoints[checkpoint.sequence - 2]
                if checkpoint.prev_checkpoint_hash != prev_checkpoint.compute_hash():
                    tamper_evidence = {
                        "type": "chain_broken",
                        "checkpoint_sequence": checkpoint.sequence,
                        "details": f"Checkpoint {checkpoint.sequence} prev_hash doesn't match checkpoint {checkpoint.sequence - 1}"
                    }
                    break
            
            verified += 1
        
        return VerificationResult(
            valid=tamper_evidence is None,
            tamper_evidence=tamper_evidence,
            verified_checkpoints=verified,
            total_artifacts=len(artifacts),
            details="Chain verified" if tamper_evidence is None else f"Tamper detected: {tamper_evidence}"
        )
    
    def detect_tampering(self, artifacts: Dict[str, str]) -> Optional[TamperEvidence]:
        """Quick tamper detection - returns first tamper evidence found."""
        result = self.verify_chain(artifacts)
        if result.tamper_evidence:
            return TamperEvidence(**result.tamper_evidence)
        return None
    
    def export_checkpoints(self) -> List[Dict]:
        """Export checkpoints for persistence."""
        return [cp.to_dict() for cp in self.checkpoints]
    
    @classmethod
    def load_checkpoints(cls, checkpoints_data: List[Dict], public_key: ed25519.Ed25519PublicKey) -> 'EvidenceChain':
        """Load chain from exported checkpoints."""
        chain = cls(private_key=None)  # No private key for loaded chain
        chain.public_key = public_key
        chain.checkpoints = [Checkpoint.from_dict(cp) for cp in checkpoints_data]
        if chain.checkpoints:
            chain._sequence = chain.checkpoints[-1].sequence
        return chain
    
    @staticmethod
    def generate_key_pair() -> tuple:
        """Generate Ed25519 key pair."""
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        return private_key, public_key
    
    @staticmethod
    def serialize_private_key(private_key: ed25519.Ed25519PrivateKey) -> str:
        """Serialize private key to PEM."""
        return private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode()
    
    @staticmethod
    def serialize_public_key(public_key: ed25519.Ed25519PublicKey) -> str:
        """Serialize public key to PEM."""
        return public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()
    
    @staticmethod
    def load_private_key(pem: str) -> ed25519.Ed25519PrivateKey:
        """Load private key from PEM."""
        return serialization.load_pem_private_key(pem.encode(), password=None)
    
    @staticmethod
    def load_public_key(pem: str) -> ed25519.Ed25519PublicKey:
        """Load public key from PEM."""
        return serialization.load_pem_public_key(pem.encode())