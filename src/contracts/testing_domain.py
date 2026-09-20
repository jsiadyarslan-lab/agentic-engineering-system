"""E1 testing domain — owner decisions D-11 = A (pytest only) and D-02 = C.

The testing domain has three real, tested components:

- :class:`TestRunSpec` — the typed specification of a sandboxed
  pytest run (approved runner only, explicit targets, junit-xml
  report). The argv shape is FIXED by the contract — callers cannot
  smuggle arbitrary runner flags.
- :func:`parse_junit_report` — deterministic parsing of a junit-xml
  report into typed records (the runner's exit code is never the
  verdict; the parsed report is the claim source — gap discovery
  §14).
- :func:`build_sandbox_request` — construction of the sandbox request
  that executes the run through the isolation substrate.

EXECUTION STATUS (0.3.0): the verified local substrate
(:mod:`substrate.local_substrate`) executes run_tests for real —
the granted repository is mounted read-only as the in-sandbox
working tree, pytest runs as sandbox pid 1, and the junit report
exits through the custody-directory bind at ``/artifacts/report.xml``
(the in-sandbox artifact exit path). The substrate must be
registered by the caller (reference wiring:
:func:`substrate.local_substrate.local_sandbox_manager`); with no
adapter registered the run is BLOCKED fail-closed (no host fallback).
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from enum import Enum

from substrate.limits import E1_LIMITS_DEFAULTS, ExecutionLimits
from contracts.result import TestRecord
from substrate.sandbox import (
    NetworkMode,
    SandboxRequest,
)


#: The single approved runner (D-11 = A: pytest only, version pinned
#: by the caller within the project's test extra constraint).
APPROVED_RUNNER: str = "pytest"
APPROVED_RUNNER_CONSTRAINT: str = "pytest>=7.2"

#: The only supported report format (built into pytest; no plugins).
APPROVED_REPORT_FORMAT: str = "junit-xml"

#: The in-sandbox artifact exit path: the substrate binds the
#: workspace custody directory (the only artifact exit boundary)
#: at this path, so the report leaves the sandbox through custody.
SANDBOX_REPORT_PATH = "/artifacts/report.xml"


class TestRunRejectionReason(str, Enum):
    """Machine-readable reasons a test-run specification is rejected."""

    UNSUPPORTED_RUNNER = "test_run_unsupported_runner"
    MISSING_TARGETS = "test_run_missing_targets"
    INVALID_TARGETS = "test_run_invalid_targets"
    UNSUPPORTED_REPORT_FORMAT = "test_run_unsupported_report_format"
    INVALID_IMAGE = "test_run_invalid_image"


@dataclass(frozen=True)
class TestRunSpec:
    """Typed specification of one sandboxed pytest run.

    ``image`` must be on the caller's sandbox image allowlist at
    execution time. ``targets`` are paths inside the granted
    repository root (the sandbox mounts the workspace copy). The
    report is written to the workspace artifacts directory and leaves
    through custody only.
    """

    runner: str = APPROVED_RUNNER
    runner_constraint: str = APPROVED_RUNNER_CONSTRAINT
    targets: tuple[str, ...] = ()
    report_format: str = APPROVED_REPORT_FORMAT
    image: str = ""

    def __post_init__(self) -> None:
        if self.runner != APPROVED_RUNNER:
            raise ValueError(
                f"only the approved runner {APPROVED_RUNNER!r} is permitted (D-11=A)"
            )
        if not isinstance(self.targets, tuple) or not self.targets:
            raise ValueError("targets must be a non-empty tuple of paths")
        for target in self.targets:
            if not isinstance(target, str) or not target:
                raise ValueError("each target must be a non-empty string")
            if target.startswith("/") or ".." in target.split("/"):
                raise ValueError(
                    f"targets must be repository-relative without escapes: {target!r}"
                )
        if self.report_format != APPROVED_REPORT_FORMAT:
            raise ValueError(
                f"only the {APPROVED_REPORT_FORMAT!r} report format is supported"
            )
        if not isinstance(self.image, str):
            raise ValueError("image must be a string")

    def command(
        self, report_path: str = SANDBOX_REPORT_PATH
    ) -> tuple[str, ...]:
        """The FIXED argv the sandbox must run (no caller-supplied flags).

        ``report_path`` is the in-sandbox artifact exit path — the
        substrate binds the workspace custody directory there; the
        report leaves the sandbox ONLY through that boundary.
        """
        return (
            "python",
            "-m",
            "pytest",
            f"--junitxml={report_path}",
            *self.targets,
        )


def validate_run_spec(
    spec: object,
) -> tuple[bool, TestRunRejectionReason | None, str]:
    """Fail-closed validation of a test-run specification."""
    if not isinstance(spec, TestRunSpec):
        return False, TestRunRejectionReason.UNSUPPORTED_RUNNER, (
            f"expected TestRunSpec, got {type(spec).__name__}"
        )
    try:
        spec.__post_init__()
    except ValueError as error:
        message = str(error)
        if "approved runner" in message:
            return False, TestRunRejectionReason.UNSUPPORTED_RUNNER, message
        if "targets must be a non-empty tuple" in message:
            return False, TestRunRejectionReason.MISSING_TARGETS, message
        if "each target must be" in message or "repository-relative" in message:
            return False, TestRunRejectionReason.INVALID_TARGETS, message
        if "report format" in message:
            return False, TestRunRejectionReason.UNSUPPORTED_REPORT_FORMAT, message
        return False, TestRunRejectionReason.INVALID_IMAGE, message
    if not spec.image:
        return False, TestRunRejectionReason.INVALID_IMAGE, (
            "image must name an allowlisted sandbox image"
        )
    return True, None, "spec valid: approved runner, targets, report format, image"


def build_sandbox_request(
    spec: TestRunSpec,
    *,
    sandbox_id: str,
    workspace_root: str,
    artifacts_dir: str,
    sources_root: str = "",
    limits: ExecutionLimits | None = None,
) -> SandboxRequest:
    """Build the sandbox request for a sandboxed pytest run.

    The command comes from the spec's fixed argv shape; the network
    mode is always NONE (D-04 = A); limits default to the D-13
    defaults and may only be lowered by the caller.
    ``sources_root`` is the granted repository root the substrate
    mounts read-only as the in-sandbox working tree (``targets`` are
    relative to it).
    """
    ok, reason, detail = validate_run_spec(spec)
    if not ok:
        raise ValueError(f"invalid TestRunSpec ({reason.value}): {detail}")
    return SandboxRequest(
        sandbox_id=sandbox_id,
        image=spec.image,
        command=spec.command(),
        limits=limits if limits is not None else E1_LIMITS_DEFAULTS,
        env_names=frozenset({"PATH", "HOME", "PYTHONDONTWRITEBYTECODE"}),
        network=NetworkMode.NONE,
        workspace_root=workspace_root,
        artifacts_dir=artifacts_dir,
        sources_root=sources_root,
    )


# ---------------------------------------------------------------------------
# JUnit XML report parsing (deterministic; exit codes are never verdicts)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TestReportSummary:
    """Parsed summary of one pytest junit-xml report."""

    report_reference: str
    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    records: tuple[TestRecord, ...]
    failure_names: tuple[str, ...]
    parse_warnings: tuple[str, ...] = ()

    @property
    def consistent(self) -> bool:
        return self.total == self.passed + self.failed + self.errors + self.skipped


@dataclass(frozen=True)
class ReportParseResult:
    """Fail-closed parse outcome for a junit-xml payload."""

    ok: bool
    summary: TestReportSummary | None = None
    error: str = ""


#: Maximum failure text kept per test record (bounded evidence detail).
_FAILURE_TEXT_LIMIT: int = 600


def _failure_text(element: ElementTree.Element) -> str:
    """Extract the bounded failure/error text from a junit element."""
    message = element.get("message", "")
    body = (element.text or "").strip()
    combined = message if message else body
    if message and body and body not in message:
        combined = f"{message}: {body}"
    combined = " ".join(combined.split())
    return combined[:_FAILURE_TEXT_LIMIT]


def parse_junit_report(data: bytes | str, *, report_reference: str) -> ReportParseResult:
    """Parse a junit-xml report into a typed summary.

    Malformed XML yields ``ok=False`` with the parser error — never
    a guessed summary. Testcase outcomes follow the junit schema:
    a ``<failure>``/``<error>``/``<skipped>`` child decides the
    outcome; absence means passed.
    """
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        return ReportParseResult(ok=False, error=f"malformed junit xml: {error}")
    if root.tag != "testsuites" and root.tag != "testsuite":
        return ReportParseResult(ok=False, error=f"unexpected root element: {root.tag!r}")

    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    passed = failed = errors = skipped = 0
    records: list[TestRecord] = []
    failure_names: list[str] = []
    warnings: list[str] = []
    for suite in suites:
        for case in suite.findall("testcase"):
            name = case.get("name", "<unnamed>")
            classname = case.get("classname", "")
            full_name = f"{classname}::{name}" if classname else name
            failure_element = case.find("failure")
            error_element = case.find("error")
            if failure_element is not None:
                failed += 1
                failure_names.append(full_name)
                records.append(
                    TestRecord(
                        name=full_name,
                        passed=False,
                        message=_failure_text(failure_element),
                    )
                )
            elif error_element is not None:
                errors += 1
                failure_names.append(full_name)
                records.append(
                    TestRecord(
                        name=full_name,
                        passed=False,
                        message=_failure_text(error_element),
                    )
                )
            elif case.find("skipped") is not None:
                skipped += 1
                records.append(TestRecord(name=full_name, passed=False))
            else:
                passed += 1
                records.append(TestRecord(name=full_name, passed=True))
        suite_total = suite.get("tests")
        if suite_total is not None:
            try:
                declared = int(suite_total)
                actual = len(suite.findall("testcase"))
                if declared != actual:
                    warnings.append(
                        f"suite {suite.get('name', '<unnamed>')!r} declares "
                        f"{declared} tests but contains {actual} testcases"
                    )
            except ValueError:
                warnings.append(
                    f"suite {suite.get('name', '<unnamed>')!r} has non-integer tests count"
                )
    total = passed + failed + errors + skipped
    summary = TestReportSummary(
        report_reference=report_reference,
        total=total,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        records=tuple(records),
        failure_names=tuple(sorted(failure_names)),
        parse_warnings=tuple(warnings),
    )
    return ReportParseResult(ok=True, summary=summary)


__all__ = [
    "APPROVED_REPORT_FORMAT",
    "APPROVED_RUNNER",
    "APPROVED_RUNNER_CONSTRAINT",
    "SANDBOX_REPORT_PATH",
    "ReportParseResult",
    "TestReportSummary",
    "TestRunRejectionReason",
    "TestRunSpec",
    "build_sandbox_request",
    "parse_junit_report",
    "validate_run_spec",
]
