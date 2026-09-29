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

        try:
            if criterion.type == CriterionType.FILE_EXISTS:
                return self._check_file_exists(criterion, artifacts)
            elif criterion.type == CriterionType.FILE_HASH_MATCHES:
                return self._check_file_hash(criterion, artifacts)
            elif criterion.type == CriterionType.FILE_CONTAINS:
                return self._check_file_contains(criterion, artifacts)
            elif criterion.type == CriterionType.FILE_MATCHES_SCHEMA:
                return self._check_file_schema(criterion, artifacts)
            elif criterion.type == CriterionType.COMMAND_SUCCEEDS:
                return self._check_command_succeeds(criterion, artifacts)
            elif criterion.type == CriterionType.COMMAND_OUTPUT_CONTAINS:
                return self._check_command_output(criterion, artifacts)
            elif criterion.type == CriterionType.TEST_PASSES:
                return self._check_test_passes(criterion, artifacts)
            elif criterion.type == CriterionType.TYPE_CHECK_PASSES:
                return self._check_type_check(criterion, artifacts)
            elif criterion.type == CriterionType.LINT_PASSES:
                return self._check_lint_passes(criterion, artifacts)
            elif criterion.type == CriterionType.BUILD_SUCCEEDS:
                return self._check_build_succeeds(criterion, artifacts)
            elif criterion.type == CriterionType.CUSTOM:
                return self._check_custom(criterion, artifacts)
            else:
                return CheckResult(
                    criterion_id=criterion.id,
                    criterion_type=criterion.type,
                    passed=False,
                    details=f"Unknown criterion type: {criterion.type}",
                )

        except Exception as e:
            return CheckResult(
                criterion_id=criterion.id,
                criterion_type=criterion.type,
                passed=False,
                details=f"Verification error: {e}",
            )
        finally:
            duration = int(
                (datetime.now(timezone.utc) - start).total_seconds() * 1000
            )

    def _check_file_exists(self, criterion: AcceptanceCriterion, artifacts: Dict) -> CheckResult:
        """Check if file exists in artifacts."""
        path = criterion.path
        if not path:
            return CheckResult(
                criterion_id=criterion.id,
                criterion_type=criterion.type,
                passed=False,
                details="No path specified",
            )

        # Find artifact by path
        found = False
        evidence = None
        for art_id, meta in artifacts.items():
            if meta.get("path") == path or meta.get("name") == path:
                found = True
                evidence = meta.get("sha256")
                break

        return CheckResult(
            criterion_id=criterion.id,
            criterion_type=criterion.type,
            passed=found,
            details=f"File {'found' if found else 'missing'}: {path}",
            evidence=evidence,
        )

    def _check_file_hash(self, criterion: AcceptanceCriterion, artifacts: Dict) -> CheckResult:
        """Check file hash matches expected."""
        path = criterion.path
        expected = criterion.expected_hash
        if not path or not expected:
            return CheckResult(
                criterion_id=criterion.id,
                criterion_type=criterion.type,
                passed=False,
                details="Missing path or expected_hash",
            )

        found = False
        evidence = None
        for art_id, meta in artifacts.items():
            if meta.get("path") == path or meta.get("name") == path:
                actual = meta.get("sha256")
                found = actual == expected
                evidence = actual
                break

        return CheckResult(
            criterion_id=criterion.id,
            criterion_type=criterion.type,
            passed=found,
            details=f"Hash {'matches' if found else 'mismatch'} for {path}",
            evidence=evidence,
        )

    def _check_file_contains(self, criterion: AcceptanceCriterion, artifacts: Dict) -> CheckResult:
        """Check file contains pattern."""
        path = criterion.path
        pattern = criterion.pattern
        if not path or not pattern:
            return CheckResult(
                criterion_id=criterion.id,
                criterion_type=criterion.type,
                passed=False,
                details="Missing path or pattern",
            )

        found = False
        evidence = None
        for art_id, meta in artifacts.items():
            if meta.get("path") == path or meta.get("name") == path:
                # Read content (bounded)
                content = self.evidence_store.get_artifact(art_id)
                if content:
                    try:
                        text = content.decode("utf-8", errors="replace")
                        found = pattern in text
                        evidence = meta.get("sha256")
                    except Exception:
                        pass
                break

        return CheckResult(
            criterion_id=criterion.id,
            criterion_type=criterion.type,
            passed=found,
            details=f"Pattern {'found' if found else 'not found'} in {path}",
            evidence=evidence,
        )

    def _check_file_schema(self, criterion: AcceptanceCriterion, artifacts: Dict) -> CheckResult:
        """Validate file against JSON/YAML schema."""
        # Simplified - would use jsonschema in real impl
        return CheckResult(
            criterion_id=criterion.id,
            criterion_type=criterion.type,
            passed=False,
            details="Schema validation not implemented",
        )

    def _check_command_succeeds(self, criterion: AcceptanceCriterion, artifacts: Dict) -> CheckResult:
        """Check if command succeeded (exit code 0)."""
        # Look for sandbox execution record
        cmd = criterion.command
        if not cmd:
            return CheckResult(
                criterion_id=criterion.id,
                criterion_type=criterion.type,
                passed=False,
                details="No command specified",
            )

        # In real implementation, check sandbox execution record
        return CheckResult(
            criterion_id=criterion.id,
            criterion_type=criterion.type,
            passed=False,
            details="Command verification requires sandbox execution record",
        )

    def _check_command_output(self, criterion: AcceptanceCriterion, artifacts: Dict) -> CheckResult:
        """Check command output contains pattern."""
        return CheckResult(
            criterion_id=criterion.id,
            criterion_type=criterion.type,
            passed=False,
            details="Command output verification requires sandbox execution record",
        )

    def _check_test_passes(self, criterion: AcceptanceCriterion, artifacts: Dict) -> CheckResult:
        """Check test suite passes."""
        return CheckResult(
            criterion_id=criterion.id,
            criterion_type=criterion.type,
            passed=False,
            details="Test verification requires test runner integration",
        )

    def _check_type_check(self, criterion: AcceptanceCriterion, artifacts: Dict) -> CheckResult:
        """Check static type check passes."""
        return CheckResult(
            criterion_id=criterion.id,
            criterion_type=criterion.type,
            passed=False,
            details="Type check verification requires type checker integration",
        )

    def _check_lint_passes(self, criterion: AcceptanceCriterion, artifacts: Dict) -> CheckResult:
        """Check linter passes."""
        return CheckResult(
            criterion_id=criterion.id,
            criterion_type=criterion.type,
            passed=False,
            details="Lint verification requires linter integration",
        )

    def _check_build_succeeds(self, criterion: AcceptanceCriterion, artifacts: Dict) -> CheckResult:
        """Check build succeeds."""
        return CheckResult(
            criterion_id=criterion.id,
            criterion_type=criterion.type,
            passed=False,
            details="Build verification requires build system integration",
        )

    def _check_custom(self, criterion: AcceptanceCriterion, artifacts: Dict) -> CheckResult:
        """Custom verification (would call registered function)."""
        return CheckResult(
            criterion_id=criterion.id,
            criterion_type=criterion.type,
            passed=False,
            details="Custom verification not implemented",
        )


# ============================================================
# EVIDENCE HELPERS
# ============================================================

def compute_sha256(content: bytes) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content).hexdigest()


def compute_file_sha256(path: str) -> str:
    """Compute SHA256 hash of file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def create_evidence_record(
    content: bytes,
    content_type: str,
    source_id: str,
    mission_id: str,
    run_id: str,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create evidence record dict."""
    from unified.domain_model import new_evidence_id

    return {
        "evidence_id": new_evidence_id(),
        "evidence_hash": compute_sha256(content),
        "content_type": content_type,
        "source_id": source_id,
        "mission_id": mission_id,
        "run_id": run_id,
        "task_id": task_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================
# VERIFICATION STANDARD CHECKLIST
# ============================================================

VERIFICATION_CHECKLIST = """
VERIFICATION STANDARD CHECKLIST
===============================

For each task, the following MUST be true for VERIFIED:

1. PLAN PHASE
   □ Task has acceptance_criteria with at least 1 CriterionType.FILE_EXISTS
   □ Each criterion has unique id, type, and required parameters
   □ Criteria are mechanically verifiable (no "looks good")

2. EXECUTION PHASE
   □ Implementer runs in sandbox (not host)
   □ All write operations go through sandbox /artifacts
   □ Each artifact has sha256 recorded in EvidenceRecord
   □ Artifact custody log tracks: path, hash, size, creator

3. VERIFICATION PHASE
   □ Verifier checks EACH criterion mechanically
   □ File existence checked via artifact custody (not filesystem glob)
   □ Hash matching uses recorded sha256 (not recomputed from host)
   □ Missing evidence documented specifically (which file, which criterion)
   □ Confidence score reflects weighted pass rate

4. DECISION PHASE
   □ EVIDENCED → VERIFIED only by human (actor="user")
   □ NOT_EVIDENCED → Arbiter with specific missing evidence
   □ Arbiter sees: checks_performed, missing_evidence, confidence
   □ Arbiter decision: retry_with_constraints / terminate_stagnant / escalate_to_human

5. AUDIT TRAIL
   □ Every verification produces VerificationReport
   □ Report linked to task, attempt, verifier
   □ Checks include pass/fail, details, evidence reference
   □ Missing evidence list is actionable for retry

VIOLATIONS (AUTO-REJECT):
- Agent claims DONE without verification
- Verifier passes criterion without mechanical check
- Hash mismatch ignored
- Missing file marked as "assumed created"
- Human not required for VERIFIED transition
- Evidence chain broken (artifact → hash → record → verification)
"""


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Principles
    "VERIFICATION_CHECKLIST",
    # Types
    "CriterionType",
    "VerificationMethod",
    # Models
    "AcceptanceCriterion",
    "CheckResult",
    "VerificationReport",
    # Verifier
    "EvidenceStore",
    "Verifier",
    # Helpers
    "compute_sha256",
    "compute_file_sha256",
    "create_evidence_record",
]