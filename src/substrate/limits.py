"""E1 execution limits — owner decision D-13 (recorded, closed).

The values below are the owner-recorded E1 defaults from the Owner
Decision Gate Register (D-13, ACCEPTED):

    timeout = 300 seconds | CPU = 2 vCPU | memory = 4 GiB
    processes = 32 | stdout/stderr = 10 MiB | artifacts = 100 MiB
    workspace = 1 GiB

Rules (fail-closed):
- The defaults are an upper ceiling. Requests may only ask for limits
  that are equal to or LOWER than the defaults; anything that exceeds
  a default is REJECTED — never silently clamped.
- Structurally invalid limits (non-positive, non-integer) raise at
  construction time, mirroring the E0 result-contract discipline.
- These limits are POLICY. Their enforcement mechanism depends on the
  isolation substrate (D-01 = A: container controls). In this
  repository the substrate adapter is a port; until a real container
  substrate is provisioned, execution-class operations that require
  the substrate are BLOCKED (never weakened, never emulated).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

_MIB = 1024 * 1024
_GIB = 1024 * 1024 * 1024

#: Owner-recorded default: wall-clock timeout per execution (seconds).
DEFAULT_TIMEOUT_SECONDS = 300

#: Owner-recorded default: CPU allocation (vCPU).
DEFAULT_VCPU = 2

#: Owner-recorded default: memory ceiling (bytes; 4 GiB).
DEFAULT_MEMORY_BYTES = 4 * _GIB

#: Owner-recorded default: maximum process count inside the sandbox.
DEFAULT_MAX_PROCESSES = 32

#: Owner-recorded default: combined stdout/stderr ceiling (bytes; 10 MiB).
DEFAULT_MAX_OUTPUT_BYTES = 10 * _MIB

#: Owner-recorded default: per-execution artifact ceiling (bytes; 100 MiB).
DEFAULT_MAX_ARTIFACT_BYTES = 100 * _MIB

#: Owner-recorded default: workspace size ceiling (bytes; 1 GiB).
DEFAULT_MAX_WORKSPACE_BYTES = 1 * _GIB


@dataclass(frozen=True)
class ExecutionLimits:
    """Typed execution-limit policy bound to a request or grant.

    A structurally invalid value (non-positive integer, non-int type)
    raises ``ValueError`` at construction — the same fail-closed
    discipline the E0 result contract applies. Limit *policy* checks
    against the D-13 defaults are performed by
    :func:`validate_against_defaults`, which never clamps and never
    raises.
    """

    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    vcpu: int = DEFAULT_VCPU
    memory_bytes: int = DEFAULT_MEMORY_BYTES
    max_processes: int = DEFAULT_MAX_PROCESSES
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES
    max_workspace_bytes: int = DEFAULT_MAX_WORKSPACE_BYTES

    def __post_init__(self) -> None:
        integer_fields = (
            "timeout_seconds",
            "vcpu",
            "memory_bytes",
            "max_processes",
            "max_output_bytes",
            "max_artifact_bytes",
            "max_workspace_bytes",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} must be an integer, got {value!r}")
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value!r}")


#: The frozen owner-recorded D-13 default limits (never mutated).
E1_LIMITS_DEFAULTS: ExecutionLimits = ExecutionLimits()


class LimitsRejectionReason(str, Enum):
    """Machine-readable reasons a limits request is rejected."""

    #: A requested limit exceeds the D-13 default (never clamped).
    EXCEEDS_DEFAULTS = "exceeds_defaults"
    #: The limits object is structurally invalid.
    INVALID = "invalid"


@dataclass(frozen=True)
class LimitsValidation:
    """Outcome of validating requested limits against D-13 defaults."""

    valid: bool
    reason: LimitsRejectionReason | None = None
    violations: tuple[str, ...] = ()

    @property
    def detail(self) -> str:
        if self.valid:
            return "requested limits are within the D-13 defaults"
        if self.reason is LimitsRejectionReason.EXCEEDS_DEFAULTS:
            return "exceeds owner defaults (D-13): " + ", ".join(self.violations)
        return "invalid limits"


def validate_against_defaults(
    limits: ExecutionLimits | None,
) -> LimitsValidation:
    """Validate ``limits`` against the frozen D-13 defaults.

    Fail-closed: a ``None`` candidate, a non-``ExecutionLimits`` object,
    or any field above the default yields an invalid result with the
    offending field names. Requests may only LOWER limits — never
    exceed them. This function never raises and never clamps.
    """
    if not isinstance(limits, ExecutionLimits):
        return LimitsValidation(
            valid=False,
            reason=LimitsRejectionReason.INVALID,
            violations=("limits must be an ExecutionLimits instance",),
        )
    violations: list[str] = []
    if limits.timeout_seconds > E1_LIMITS_DEFAULTS.timeout_seconds:
        violations.append("timeout_seconds")
    if limits.vcpu > E1_LIMITS_DEFAULTS.vcpu:
        violations.append("vcpu")
    if limits.memory_bytes > E1_LIMITS_DEFAULTS.memory_bytes:
        violations.append("memory_bytes")
    if limits.max_processes > E1_LIMITS_DEFAULTS.max_processes:
        violations.append("max_processes")
    if limits.max_output_bytes > E1_LIMITS_DEFAULTS.max_output_bytes:
        violations.append("max_output_bytes")
    if limits.max_artifact_bytes > E1_LIMITS_DEFAULTS.max_artifact_bytes:
        violations.append("max_artifact_bytes")
    if limits.max_workspace_bytes > E1_LIMITS_DEFAULTS.max_workspace_bytes:
        violations.append("max_workspace_bytes")
    if violations:
        return LimitsValidation(
            valid=False,
            reason=LimitsRejectionReason.EXCEEDS_DEFAULTS,
            violations=tuple(sorted(violations)),
        )
    return LimitsValidation(valid=True)


def limits_from_mapping(
    values: object,
) -> ExecutionLimits | LimitsValidation:
    """Parse an optional limits mapping from request input.

    Accepts ``None`` (→ the D-13 defaults), or a mapping whose keys are
    a subset of the ``ExecutionLimits`` field names with integer
    values. Unknown keys, non-mapping input, or non-integer values
    return a fail-closed :class:`LimitsValidation` instead of raising.
    Field values are still structurally validated by the
    ``ExecutionLimits`` constructor and policy-checked by the caller
    through :func:`validate_against_defaults`.
    """
    if values is None:
        return E1_LIMITS_DEFAULTS
    if not isinstance(values, dict):
        return LimitsValidation(
            valid=False,
            reason=LimitsRejectionReason.INVALID,
            violations=("limits must be a mapping or None",),
        )
    allowed = {
        "timeout_seconds",
        "vcpu",
        "memory_bytes",
        "max_processes",
        "max_output_bytes",
        "max_artifact_bytes",
        "max_workspace_bytes",
    }
    unknown = sorted(set(values) - allowed)
    if unknown:
        return LimitsValidation(
            valid=False,
            reason=LimitsRejectionReason.INVALID,
            violations=(f"unknown limit fields: {unknown}",),
        )
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int):
            return LimitsValidation(
                valid=False,
                reason=LimitsRejectionReason.INVALID,
                violations=(f"{key} must be an integer",),
            )
    try:
        return ExecutionLimits(**values)
    except ValueError as error:
        return LimitsValidation(
            valid=False,
            reason=LimitsRejectionReason.INVALID,
            violations=(str(error),),
        )
