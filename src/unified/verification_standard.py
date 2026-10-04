"""
Verification Standard — Unified Engineering Agents System

The core principle: **No completion without verification.**

Every claim of completion must be backed by mechanically verifiable evidence.
This standard defines what counts as evidence, how it's verified, and the
decision flow for acceptance/rejection.

Based on: EAS v2 Verifier (evidence-based, file existence + hash matching)
         AgentFactory VerifierAgent (LLM-based verification)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Literal, Callable
from pydantic import BaseModel, Field, field_validator
from dataclasses import dataclass
import hashlib
import json


# ============================================================
# VERIFICATION PRINCIPLES
# ============================================================

"""
GOLDEN RULES OF VERIFICATION:

1. CLAIM ≠ COMPLETION
   An agent saying "done" is not completion. Only verified evidence is.

2. EVIDENCE OVER CLAIMS
   Verification checks file existence + content hash + criteria match.
   Agent output is advisory only.

3. MECHANICAL VERIFICATION
   Criteria must be mechanically checkable (file names, hashes, patterns).
   No "looks good" or "seems correct" — only objective checks.

4. EVIDENCE CHAIN
   Action → Artifact → sha256 → EvidenceRecord → Verification → Decision
   Every link must be traceable.

5. FAIL-CLOSED
   Missing evidence = NOT_EVIDENCED (not "maybe").
   Hash mismatch = NOT_EVIDENCED.
   Unverifiable criterion = documented as unverifiable, not passed.

6. SUB-VERDICTS DRIVE FLOW
   NOT_EVIDENCED → Arbiter (retry/escalate/terminate)
   STAGNANT → Escalation to human
   EVIDENCED → VERIFIED (user only)

7. HUMAN VERIFIES FINAL
   VERIFIED state only by actor="user" (golden rule).
   No agent, verifier, or arbiter can grant VERIFIED.
"""


# ============================================================
# ACCEPTANCE CRITERIA TYPES
# ============================================================

class CriterionType(str, Enum):
    """Types of mechanically verifiable acceptance criteria."""

    FILE_EXISTS = "file_exists"                    # File exists at path
    FILE_HASH_MATCHES = "file_hash_matches"        # File hash matches expected
    FILE_CONTAINS = "file_contains"                # File contains pattern
    FILE_MATCHES_SCHEMA = "file_matches_schema"    # File matches JSON/YAML schema
    COMMAND_SUCCEEDS = "command_succeeds"          # Command exits with 0
    COMMAND_OUTPUT_CONTAINS = "command_output_contains"  # Command stdout contains
    TEST_PASSES = "test_passes"                    # Test suite passes
    TYPE_CHECK_PASSES = "type_check_passes"        # Static type check passes
    LINT_PASSES = "lint_passes"                    # Linter passes
    BUILD_SUCCEEDS = "build_succeeds"              # Build command succeeds
    CUSTOM = "custom"                              # Custom verifier function
    EVIDENCE_CHAIN_INTACT = "evidence_chain_intact"  # Cryptographic evidence chain verified


class VerificationMethod(str, Enum):
    """How verification is performed."""
    AUTOMATED = "automated"      # Machine-checkable
    MANUAL = "manual"            # Human review required
    HYBRID = "hybrid"            # Automated checks + human review


# ============================================================
# CRITERION DEFINITION
# ============================================================

class AcceptanceCriterion(BaseModel):
    """
    Single mechanically verifiable acceptance criterion.
    Must be specific enough for automated verification.
    """
    id: str
    type: CriterionType
    description: str

    # Parameters per type
    path: Optional[str] = None                    # For file_* types
    expected_hash: Optional[str] = None           # For file_hash_matches
    pattern: Optional[str] = None                 # For file_contains
    schema_path: Optional[str] = None             # For file_matches_schema
    command: Optional[List[str]] = None           # For command_* types
    expected_output_pattern: Optional[str] = None # For command_output_contains
    test_command: Optional[List[str]] = None      # For test_passes
    type_check_command: Optional[List[str]] = None
    lint_command: Optional[List[str]] = None
    build_command: Optional[List[str]] = None

    # Verification
    method: VerificationMethod = VerificationMethod.AUTOMATED
    weight: float = 1.0                           # For partial credit scoring

    # E44: Cryptographic evidence chain verification
    tamper_evidence: Optional[Dict[str, Any]] = None      # Tamper evidence if detected
    chain_verification: Optional[Dict[str, Any]] = None   # Chain verification result

    @field_validator("weight")
    @classmethod
    def validate_weight(cls, v: float) -> float:
        if not 0 < v <= 10:
            raise ValueError("Weight must be in (0, 10]")
        return v


# ============================================================
# VERIFICATION RESULT
# ============================================================

class CheckResult(BaseModel):
    """Result of a single criterion check."""
    criterion_id: str
    criterion_type: CriterionType
    passed: bool
    details: str
    evidence: Optional[str] = None  # sha256 or path
    duration_ms: int = 0
    tamper_evidence: Optional[Dict[str, Any]] = None  # E44: Tamper evidence


class VerificationReport(BaseModel):
    """Complete verification report for a task."""
    task_id: str
    attempt_id: str
    verifier_id: str

    # Overall
    verdict: Literal["evidenced", "not_evidenced"]
    confidence: float = Field(ge=0.0, le=1.0)

    # Checks
    checks: List[CheckResult] = Field(default_factory=list)
    passed_count: int = 0
    total_count: int = 0
    total_weight: float = 0.0
    passed_weight: float = 0.0

    # Missing evidence
    missing_evidence: List[str] = Field(default_factory=list)

    # Sub-verdict for flow control
    sub_verdict: Optional[str] = None  # "NOT_EVIDENCED" or None

    # E44: Chain verification summary
    chain_verified: bool = False
    chain_verification_details: Optional[str] = None

    # Timing
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: int = 0

    @property
    def score(self) -> float:
        """Weighted score (0.0 to 1.0)."""
        if self.total_weight == 0:
            return 0.0
        return self.passed_weight / self.total_weight


# ============================================================
# VERIFIER IMPLEMENTATION
# ============================================================

class EvidenceStore:
    """Interface for evidence storage/retrieval."""

    def get_artifact(self, artifact_id: str) -> Optional[bytes]:
        """Get artifact content by ID."""
        raise NotImplementedError

    def get_artifact_path(self, artifact_id: str) -> Optional[str]:
        """Get artifact filesystem path."""
        raise NotImplementedError

    def get_artifact_hash(self, artifact_id: str) -> Optional[str]:
        """Get artifact sha256."""
        raise NotImplementedError

    def artifact_exists(self, artifact_id: str) -> bool:
        """Check if artifact exists."""
        raise NotImplementedError

    # E44: Evidence chain methods
    def get_evidence_chain(self) -> Optional[Any]:
        """Get the evidence chain for this mission."""
        return None

    def create_checkpoint(self) -> Optional[Any]:
        """Create a checkpoint of current evidence state."""
        return None

    def verify_evidence_chain(self) -> Optional[Dict[str, Any]]:
        """Verify the evidence chain integrity."""
        return None


class Verifier:
    """
    Mechanical verifier - checks acceptance criteria against evidence.
    No LLM calls - pure deterministic verification.
    """

    def __init__(self, evidence_store: EvidenceStore):
        self.evidence_store = evidence_store

    def verify(
        self,
        task_id: str,
        attempt_id: str,
        criteria: List[AcceptanceCriterion],
        artifacts: Dict[str, Any],  # artifact_id -> metadata
    ) -> VerificationReport:
        """
        Verify all criteria against available evidence.

        Args:
            task_id: Task being verified
            attempt_id: Attempt that produced artifacts
            criteria: Acceptance criteria from plan
            artifacts: Map of artifact_id -> {path, sha256, size, ...}

        Returns:
            VerificationReport with verdict and details
        """
        report = VerificationReport(
            task_id=task_id,
            attempt_id=attempt_id,
            verifier_id="verifier",
            verdict="evidenced",
            confidence=1.0,
        )

        for criterion in criteria:
            check = self._check_criterion(criterion, artifacts)
            report.checks.append(check)

            if check.passed:
                report.passed_count += 1
                report.passed_weight += criterion.weight
            else:
                report.missing_evidence.append(
                    f"{criterion.id}: {check.details}"
                )

            report.total_count += 1
            report.total_weight += criterion.weight

        # Determine verdict
        if report.passed_count == report.total_count:
            report.verdict = "evidenced"
            report.confidence = 1.0
        else:
            report.verdict = "not_evidenced"
            report.confidence = report.score
            report.sub_verdict = "NOT_EVIDENCED"

        report.completed_at = datetime.now(timezone.utc)
        report.duration_ms = int(
            (report.completed_at - report.started_at).total_seconds() * 1000
        )

        return report

    def _check_criterion(
        self,
        criterion: AcceptanceCriterion,
        artifacts: Dict[str, Any],
    ) -> CheckResult:
        """Check a single criterion."""
        start = datetime.now(timezone.utc)

        if criterion.type == CriterionType.FILE_EXISTS:
            passed, details, evidence = self._check_file_exists(criterion.path, artifacts)
            tamper = None
        elif criterion.type == CriterionType.FILE_HASH_MATCHES:
            passed, details, evidence = self._check_file_hash(criterion.path, criterion.expected_hash, artifacts)
            tamper = None
        elif criterion.type == CriterionType.FILE_CONTAINS:
            passed, details, evidence = self._check_file_contains(criterion.path, criterion.pattern, artifacts)
            tamper = None
        elif criterion.type == CriterionType.EVIDENCE_CHAIN_INTACT:
            passed, details, evidence, tamper = self._check_evidence_chain_intact(criterion, artifacts)
        else:
            passed, details, evidence = False, f"Unsupported criterion type: {criterion.type}", None
            tamper = None

        duration = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        result = CheckResult(
            criterion_id=criterion.id,
            criterion_type=criterion.type,
            passed=passed,
            details=details,
            evidence=evidence,
            duration_ms=duration,
            tamper_evidence=tamper,
        )

        # Store tamper evidence in criterion for later inspection
        if tamper:
            criterion.tamper_evidence = tamper

        return result

    def _check_file_exists(self, path: str, artifacts: Dict[str, Any]) -> tuple:
        if not path:
            return False, "No path specified", None

        found = False
        evidence = None
        for art_id, meta in artifacts.items():
            if meta.get("path") == path or meta.get("name") == path:
                found = True
                evidence = meta.get("sha256")
                break

        return found, f"File {'found' if found else 'missing'}: {path}", evidence

    def _check_file_hash(self, path: str, expected_hash: str, artifacts: Dict[str, Any]) -> tuple:
        if not path or not expected_hash:
            return False, "Missing path or expected_hash", None

        found = False
        evidence = None
        for art_id, meta in artifacts.items():
            if meta.get("path") == path or meta.get("name") == path:
                actual = meta.get("sha256")
                found = actual == expected_hash
                evidence = actual
                break

        return found, f"Hash {'matches' if found else 'mismatch'} for {path}", evidence

    def _check_file_contains(self, path: str, pattern: str, artifacts: Dict[str, Any]) -> tuple:
        if not path or not pattern:
            return False, "Missing path or pattern", None

        found = False
        evidence = None
        for art_id, meta in artifacts.items():
            if meta.get("path") == path or meta.get("name") == path:
                content = self.evidence_store.get_artifact(art_id)
                if content:
                    try:
                        text = content.decode("utf-8", errors="replace")
                        found = pattern in text
                        evidence = meta.get("sha256")
                    except Exception:
                        pass
                break

        return found, f"Pattern {'found' if found else 'not found'} in {path}", evidence

    def _check_evidence_chain_intact(self, criterion: AcceptanceCriterion, artifacts: Dict[str, Any]) -> tuple:
        """Check cryptographic evidence chain integrity."""
        try:
            evidence_chain = self.evidence_store.get_evidence_chain()
            if not evidence_chain:
                return False, "No evidence chain available", None, {"type": "no_chain", "details": "Evidence chain not initialized"}

            result = evidence_chain.verify_chain(artifacts)
            if result.valid:
                criterion.chain_verification = {
                    "verified_checkpoints": result.verified_checkpoints,
                    "total_artifacts": result.total_artifacts,
                    "details": result.details
                }
                return True, f"Evidence chain verified: {result.details}", result.details, None
            else:
                return False, f"Evidence chain tampered: {result.details}", None, result.tamper_evidence
        except Exception as e:
            return False, f"Chain verification error: {e}", None, {"type": "verification_error", "details": str(e)}


# ============================================================
# FILE EVIDENCE STORE (Concrete Implementation)
# ============================================================

class FileEvidenceStore(EvidenceStore):
    """
    File-based evidence store implementation.
    Stores artifacts on disk with SHA256 hashing.
    """

    def __init__(self, base_path: str):
        self.base_path = base_path
        self._artifacts: Dict[str, Any] = {}
        self._evidence_chain: Optional[Any] = None

    def store_artifact(self, artifact) -> None:
        """Store artifact with hash."""
        import os
        os.makedirs(self.base_path, exist_ok=True)

        # Write content to file
        file_path = os.path.join(self.base_path, artifact.name)
        with open(file_path, "wb") as f:
            f.write(artifact.content)

        # Store metadata
        self._artifacts[artifact.artifact_id] = {
            "artifact_id": artifact.artifact_id,
            "path": artifact.name,
            "name": artifact.name,
            "sha256": artifact.sha256,
            "size": len(artifact.content),
            "mission_id": artifact.mission_id,
        }

        # Add to evidence chain if available
        if self._evidence_chain:
            self._evidence_chain.add_artifact(artifact.artifact_id, artifact.sha256)

    def get_artifact(self, artifact_id: str) -> Optional[bytes]:
        """Get artifact content by ID."""
        if artifact_id not in self._artifacts:
            return None
        meta = self._artifacts[artifact_id]
        file_path = os.path.join(self.base_path, meta["path"])
        try:
            with open(file_path, "rb") as f:
                return f.read()
        except Exception:
            return None

    def get_artifact_path(self, artifact_id: str) -> Optional[str]:
        if artifact_id not in self._artifacts:
            return None
        return os.path.join(self.base_path, self._artifacts[artifact_id]["path"])

    def get_artifact_hash(self, artifact_id: str) -> Optional[str]:
        if artifact_id not in self._artifacts:
            return None
        return self._artifacts[artifact_id].get("sha256")

    def artifact_exists(self, artifact_id: str) -> bool:
        return artifact_id in self._artifacts

    # E44: Evidence chain methods
    def set_evidence_chain(self, evidence_chain) -> None:
        """Set the evidence chain for this store."""
        self._evidence_chain = evidence_chain

    def get_evidence_chain(self):
        """Get the evidence chain for this mission."""
        return self._evidence_chain

    def create_checkpoint(self):
        """Create a checkpoint of current evidence state."""
        if self._evidence_chain:
            return self._evidence_chain.create_checkpoint()
        return None

    def verify_evidence_chain(self):
        """Verify the evidence chain integrity."""
        if self._evidence_chain:
            return self._evidence_chain.verify_chain({
                art_id: meta.get("sha256", "") for art_id, meta in self._artifacts.items()
            })
        return None


# ============================================================
# UTILITY FUNCTIONS (for backward compatibility)
# ============================================================

def compute_sha256(data: bytes) -> str:
    """Compute SHA256 hash of bytes."""
    import hashlib
    return hashlib.sha256(data).hexdigest()


def compute_file_sha256(file_path: str) -> str:
    """Compute SHA256 hash of a file."""
    import hashlib
    with open(file_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def create_evidence_record(
    task_id: str,
    attempt_id: str,
    artifact_id: str,
    sha256: str,
    criterion_type: CriterionType,
    passed: bool,
    details: str,
) -> dict:
    """Create an evidence record dictionary."""
    return {
        "task_id": task_id,
        "attempt_id": attempt_id,
        "artifact_id": artifact_id,
        "sha256": sha256,
        "criterion_type": criterion_type.value if hasattr(criterion_type, "value") else str(criterion_type),
        "passed": passed,
        "details": details,
    }


# E44: Verification checklist for self-hosting missions
VERIFICATION_CHECKLIST = [
    "All tasks have acceptance criteria defined",
    "All artifacts have SHA256 hashes recorded",
    "Evidence chain checkpoints created at mission milestones",
    "Independent verification performed by OperationalVerifierAgent",
    "No verification weakening (criteria match agent output)",
    "No mock agents or fake artifacts",
    "Failure detection and recovery demonstrated",
    "Interruption and resume demonstrated",
    "LOCAL == REMOTE git state verified",
    "false_success_rate = 0",
]