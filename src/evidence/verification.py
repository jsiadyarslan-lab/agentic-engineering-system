"""E1 verification records — owner decision D-08 (A: split authority).

The verification layer records **machine-checkable claims** about an
executed operation. Two rules are structural and never negotiable:

1. **Execution completed is not verified success.** A process exit
   code is EXECUTED-state evidence only; no check here converts an
   exit code into a verdict. The per-class checks below are the ones
   required by the Capability Gap Discovery §14.
2. **Engineering never issues the final verdict.** This module
   produces check records and a :class:`VerificationSummary`. The
   CALLER (JARVIS PRIME / the system owner) owns the final verdict —
   Engineering results therefore never claim ``final_status =
   VERIFIED`` on their own; that transition belongs to the caller
   side, which constructs it from the recorded evidence under the
   E0 result contract's constructor gate.

Per-class required checks (from the gap discovery §14):

- read/analyze — output artifact exists + deterministic re-run hash
  match (sampling);
- write — diff matches declared intent; targets exist with recorded
  hashes; scope containment; relevant tests pass (future);
- build — artifact exists + hash + PASSED status + manifest match
  (build is out of E1 scope; checks defined, marked NOT_APPLICABLE);
- test — runner report parsed; pass/fail counts; failures listed;
  runner exit code is evidence, the report is the claim source;
- artifact creation — hash + location + manifest entry; artifact
  readable after custody.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from enum import Enum

from contracts.result import VerificationState


class CheckKind(str, Enum):
    """Kinds of machine-checkable verification checks."""

    OUTPUT_HASH = "output_hash"
    RERUN_HASH_MATCH = "rerun_hash_match"
    ARTIFACT_CUSTODY = "artifact_custody"
    ARTIFACT_READABLE = "artifact_readable"
    TEST_REPORT_CONSISTENCY = "test_report_consistency"
    TEST_FAILURES_LISTED = "test_failures_listed"
    SCOPE_CONTAINMENT = "scope_containment"
    INTENT_MATCH = "intent_match"


@dataclass(frozen=True)
class VerificationCheck:
    """One machine-checkable claim about an executed operation."""

    check_id: str
    kind: CheckKind
    description: str
    passed: bool
    detail: str = ""
    evidence_reference: str = ""


@dataclass(frozen=True)
class VerificationSummary:
    """Aggregate of all recorded checks for one execution.

    ``state`` follows the E0 vocabulary: all checks passed →
    ``VERIFIED`` (the *checks* are verified — the final RESULT verdict
    remains with the caller); any check failed → ``FAILED``; no checks
    recorded → ``UNVERIFIED``. Engineering never converts this summary
    into a self-issued final result status.
    """

    checks: tuple[VerificationCheck, ...] = ()
    state: VerificationState = VerificationState.UNVERIFIED
    method: str = "e1-recorded-machine-checks"


def _result_state(checks: tuple[VerificationCheck, ...]) -> VerificationState:
    if not checks:
        return VerificationState.UNVERIFIED
    if all(check.passed for check in checks):
        return VerificationState.VERIFIED
    return VerificationState.FAILED


class VerificationRecorder:
    """Accumulates verification checks during one execution."""

    def __init__(self) -> None:
        self._checks: list[VerificationCheck] = []

    # -- generic ------------------------------------------------------------

    def add(self, check: VerificationCheck) -> VerificationCheck:
        if not isinstance(check, VerificationCheck):
            raise TypeError("only VerificationCheck instances can be added")
        self._checks.append(check)
        return check

    def checks(self) -> tuple[VerificationCheck, ...]:
        return tuple(self._checks)

    def summary(self) -> VerificationSummary:
        """Summarize recorded checks (never a final verdict)."""
        checks = tuple(self._checks)
        return VerificationSummary(
            checks=checks,
            state=_result_state(checks),
            method="e1-recorded-machine-checks",
        )

    # -- concrete checks -------------------------------------------------------

    def check_output_hash(
        self,
        *,
        reference: str,
        expected_sha256: str,
        observed_sha256: str,
    ) -> VerificationCheck:
        """Check that an output's recorded hash matches observation."""
        passed = hmac.compare_digest(expected_sha256, observed_sha256)
        return self.add(
            VerificationCheck(
                check_id=f"output-hash:{reference}",
                kind=CheckKind.OUTPUT_HASH,
                description=f"recorded output hash matches for {reference}",
                passed=passed,
                detail=(
                    f"expected={expected_sha256} observed={observed_sha256}"
                ),
                evidence_reference=reference,
            )
        )

    def check_rerun_hash(
        self,
        *,
        reference: str,
        first_sha256: str,
        second_sha256: str,
    ) -> VerificationCheck:
        """Check deterministic re-run: two independent hashes match."""
        passed = hmac.compare_digest(first_sha256, second_sha256)
        return self.add(
            VerificationCheck(
                check_id=f"rerun-hash:{reference}",
                kind=CheckKind.RERUN_HASH_MATCH,
                description=f"deterministic re-run hash match for {reference}",
                passed=passed,
                detail=f"first={first_sha256} second={second_sha256}",
                evidence_reference=reference,
            )
        )

    def check_artifact_custody(
        self,
        *,
        manifest_entries: tuple[tuple[str, str, int], ...],
        observed: tuple[tuple[str, str, int], ...],
    ) -> VerificationCheck:
        """Check custody manifest matches observed artifacts exactly."""
        passed = manifest_entries == observed
        return self.add(
            VerificationCheck(
                check_id="artifact-custody",
                kind=CheckKind.ARTIFACT_CUSTODY,
                description="custody manifest matches observed artifacts",
                passed=passed,
                detail=(
                    f"manifest={len(manifest_entries)} entries, "
                    f"observed={len(observed)} entries"
                ),
            )
        )

    def check_artifact_readable(
        self,
        *,
        reference: str,
        readable: bool,
    ) -> VerificationCheck:
        """Check an artifact remains readable after custody transfer."""
        return self.add(
            VerificationCheck(
                check_id=f"artifact-readable:{reference}",
                kind=CheckKind.ARTIFACT_READABLE,
                description=f"artifact readable after custody: {reference}",
                passed=bool(readable),
                evidence_reference=reference,
            )
        )

    def check_test_report(
        self,
        *,
        report_reference: str,
        total: int,
        passed: int,
        failed: int,
        errors: int,
        skipped: int,
        failure_names: tuple[str, ...],
    ) -> VerificationCheck:
        """Check parsed test-report arithmetic consistency.

        The runner's exit code is NEVER used here — the parsed report
        is the claim source (gap discovery §14: "runner exit ≠
        verdict; report is").
        """
        arithmetic_ok = total == passed + failed + errors + skipped
        failures_listed_ok = failed + errors <= 0 or len(failure_names) > 0
        consistency_ok = arithmetic_ok and failures_listed_ok
        detail = (
            f"total={total} passed={passed} failed={failed} "
            f"errors={errors} skipped={skipped}; "
            f"arithmetic={'ok' if arithmetic_ok else 'broken'}; "
            f"failures_listed={'ok' if failures_listed_ok else 'missing'}"
        )
        return self.add(
            VerificationCheck(
                check_id=f"test-report:{report_reference}",
                kind=CheckKind.TEST_REPORT_CONSISTENCY,
                description=f"test report consistent: {report_reference}",
                passed=consistency_ok,
                detail=detail,
                evidence_reference=report_reference,
            )
        )

    def check_scope_containment(
        self,
        *,
        requested_reference: str,
        contained: bool,
    ) -> VerificationCheck:
        """Check an operation stayed inside the granted scope."""
        return self.add(
            VerificationCheck(
                check_id=f"scope-containment:{requested_reference}",
                kind=CheckKind.SCOPE_CONTAINMENT,
                description=f"operation stayed in granted scope: {requested_reference}",
                passed=bool(contained),
                evidence_reference=requested_reference,
            )
        )

    def check_intent_match(
        self,
        *,
        declared_intent: str,
        observed_change: str,
        matches: bool,
    ) -> VerificationCheck:
        """Check an observed change matches the declared intent (write class)."""
        return self.add(
            VerificationCheck(
                check_id=f"intent-match:{declared_intent}",
                kind=CheckKind.INTENT_MATCH,
                description="observed change matches declared intent",
                passed=bool(matches),
                detail=f"intent={declared_intent} observed={observed_change}",
            )
        )


__all__ = [
    "CheckKind",
    "VerificationCheck",
    "VerificationRecorder",
    "VerificationSummary",
]
