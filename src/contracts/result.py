"""Result, evidence, and verification contract (E0).

Core rule: EXECUTION COMPLETED IS NOT VERIFIED SUCCESS. There is no
SUCCESS terminal status in this contract. The only success-equivalent
terminal is VERIFIED, and a result is only constructible with that
status when it carries a passing verification record plus at least one
evidence record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from contracts.capability import CAPABILITY_IDENTITY
from contracts.contract import CapabilityScope


class OutcomeState(str, Enum):
    """Contract states for recorded actions and final statuses.

    - EXECUTED: the action ran to completion (says nothing about truth).
    - OBSERVED: something was observed without acting.
    - EVIDENCED: a claim is backed by evidence records.
    - VERIFIED: a claim passed explicit verification (the only
      success-equivalent terminal).
    - FAILED: the action or result failed.
    - INCOMPLETE: not finished; the fail-closed default.
    """

    EXECUTED = "EXECUTED"
    OBSERVED = "OBSERVED"
    EVIDENCED = "EVIDENCED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"


class VerificationState(str, Enum):
    """State of the verification record attached to a result."""

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class BuildStatus(str, Enum):
    """Build status attached to a result (E0: not applicable)."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    PASSED = "PASSED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ActionRecord:
    """One action recorded during capability work."""

    name: str
    state: OutcomeState


@dataclass(frozen=True)
class ArtifactRecord:
    """An artifact produced by the capability.

    ``reference`` is a reference (path, URI, or identifier) — content
    is never embedded in the result object.
    """

    kind: str
    reference: str


@dataclass(frozen=True)
class ChangedResource:
    """A resource changed by the capability. E0 expects none."""

    resource: str
    change: str


@dataclass(frozen=True)
class TestRecord:
    """A single test outcome.

    ``message`` (E2, 0.4.0) carries the bounded failure/error text
    parsed from the report — absent for passing tests and for reports
    that predate the field. It is diagnostic detail, never a verdict.
    """

    name: str
    passed: bool
    message: str = ""


@dataclass(frozen=True)
class Evidence:
    """Evidence backing a claim: a reference, never an embedded blob."""

    kind: str
    reference: str


@dataclass(frozen=True)
class Verification:
    """Verification record. Fail-closed default: UNVERIFIED."""

    state: VerificationState = VerificationState.UNVERIFIED
    method: str = ""
    checks: tuple[str, ...] = ()


@dataclass(frozen=True)
class Diagnostic:
    """A diagnostic entry attached to a result."""

    severity: str
    message: str


@dataclass(frozen=True)
class Risk:
    """A risk attached to a result, with an optional mitigation."""

    description: str
    mitigation: str = ""


@dataclass(frozen=True)
class CapabilityResult:
    """Result contract for the Engineering capability.

    Invariants (fail-closed, enforced in ``__post_init__``):

    - ``final_status`` has no SUCCESS member — the only success
      terminal is VERIFIED;
    - ``final_status is VERIFIED`` requires ``verification.state`` to be
      VERIFIED and at least one evidence record to exist.

    Execution completed is not verified success.
    """

    request_id: str
    capability: str = CAPABILITY_IDENTITY
    scope: CapabilityScope | None = None
    actions: tuple[ActionRecord, ...] = ()
    artifacts: tuple[ArtifactRecord, ...] = ()
    changed_resources: tuple[ChangedResource, ...] = ()
    tests: tuple[TestRecord, ...] = ()
    build_status: BuildStatus = BuildStatus.NOT_APPLICABLE
    diagnostics: tuple[Diagnostic, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    verification: Verification = field(default_factory=Verification)
    risks: tuple[Risk, ...] = ()
    final_status: OutcomeState = OutcomeState.INCOMPLETE

    def __post_init__(self) -> None:
        if self.final_status is OutcomeState.VERIFIED:
            if self.verification.state is not VerificationState.VERIFIED:
                raise ValueError(
                    "final_status=VERIFIED requires verification.state=VERIFIED "
                    "(execution completed is not verified success — fail-closed)"
                )
            if not self.evidence:
                raise ValueError(
                    "final_status=VERIFIED requires at least one evidence record"
                )
