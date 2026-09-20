"""Typed capability request contract and the E0 fail-closed admission gate.

The contract covers: capability identity and version, the request
itself, scope, authorization context, input, and execution mode.
Evidence, verification state, result, and failure are covered by the
result contract in :mod:`contracts.result`.

Design rules (E0):
- small, typed, deterministic where applicable, fail-closed, evolvable;
- ACCEPTED means "structurally valid and within the E0 posture" — it
  does NOT mean executed, successful, or verified;
- anything missing, unknown, not implemented, or high-impact is
  REJECTED — never assumed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from contracts.capability import CAPABILITY_IDENTITY, CAPABILITY_VERSION
from contracts.domain import EngineeringDomain


class PermissionClass(str, Enum):
    """Permission classes for engineering operations."""

    #: Read-only inspection of repositories and documentation.
    READ = "READ"
    #: Writes confined to an explicitly granted workspace.
    CONTROLLED_WRITE = "CONTROLLED_WRITE"
    #: Operations with lasting or external impact. DENIED by default in E0.
    HIGH_IMPACT = "HIGH_IMPACT"


#: Operations named by each permission class. Declarations only — naming
#: an operation here does NOT grant the capability the ability to
#: perform it.
PERMISSION_CLASS_OPERATIONS: Mapping[PermissionClass, frozenset[str]] = {
    PermissionClass.READ: frozenset(
        {
            "repository_inspection",
            "source_reading",
            "metadata_analysis",
            "documentation_reading",
        }
    ),
    PermissionClass.CONTROLLED_WRITE: frozenset(
        {
            "workspace_file_creation",
            "source_modification",
            "artifact_creation",
            "configuration_changes",
        }
    ),
    PermissionClass.HIGH_IMPACT: frozenset(
        {
            "git_commit",
            "git_push",
            "release",
            "deployment",
            "production_modification",
            "external_communication",
        }
    ),
}


class ExecutionMode(str, Enum):
    """Execution mode requested by a capability request.

    Only PASSIVE_ANALYSIS (E0) is admitted by the E0 contract. Every
    other mode is rejected — fail-closed — until its autonomy level is
    actually implemented and authorized.
    """

    PASSIVE_ANALYSIS = "PASSIVE_ANALYSIS"
    CONTROLLED_EXECUTION = "CONTROLLED_EXECUTION"
    AUTONOMOUS_ENGINEERING_LOOP = "AUTONOMOUS_ENGINEERING_LOOP"
    MULTI_STEP_ENGINEERING_MISSION = "MULTI_STEP_ENGINEERING_MISSION"
    HIGH_IMPACT_OPERATIONS = "HIGH_IMPACT_OPERATIONS"


#: Capability contract versions this package can admit. Evolvable: a
#: future version adds its string here after an owner decision.
#: 0.1.0 = E0 posture (READ + PASSIVE_ANALYSIS only, enforced below);
#: 0.2.0 = E1 posture with the sandbox gate blocked; 0.3.0 = E1
#: posture with the verified local substrate integrated (admitted by
#: the E1 gate in :mod:`engineering.admission`; this E0 gate still
#: rejects every non-passive request fail-closed); 0.4.0 = E2 posture
#: (bounded autonomous loop); 0.5.0 = E3 posture (multi-step
#: engineering mission); 0.6.0 = E4 posture (approval-gated
#: high-impact operations — exactly one operation, run_high_impact_
#: commit, admitted only through the E4 admission posture + a
#: verified Owner approval at the engine); 0.7.0 = G3 posture (owner
#: execution order v1, 2026-09-10 — the E1 controlled write surface:
#: source_modification + artifact_creation with mandatory task_id
#: attribution, hash preconditions, custody-only exit, and intent
#: verification); 0.8.0 = G4 posture (owner execution order v1,
#: 2026-09-10 — the E2 engineering intelligence loop contract: the
#: audited engineering-state machine, terminal-state categories,
#: mandatory task attribution for run_engineering_loop, and the
#: failure-chain bound; 0.7.0 remains explicitly supported).
SUPPORTED_CAPABILITY_VERSIONS: frozenset[str] = frozenset(
    {"0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.6.0", "0.7.0", CAPABILITY_VERSION}
)


class RejectionReason(str, Enum):
    """Machine-readable rejection reasons (fail-closed codes)."""

    MISSING_REQUEST = "missing_request"
    INVALID_REQUEST = "invalid_request"
    MISSING_REQUEST_ID = "missing_request_id"
    CAPABILITY_IDENTITY_MISMATCH = "capability_identity_mismatch"
    UNSUPPORTED_CAPABILITY_VERSION = "unsupported_capability_version"
    MISSION_IDENTITY_INVALID = "mission_identity_invalid"
    TASK_IDENTITY_INVALID = "task_identity_invalid"
    MISSING_SCOPE = "missing_scope"
    INVALID_SCOPE = "invalid_scope"
    EMPTY_SCOPE = "empty_scope"
    UNDECLARED_DOMAIN = "undeclared_domain"
    MISSING_AUTHORIZATION_CONTEXT = "missing_authorization_context"
    INVALID_AUTHORIZATION_CONTEXT = "invalid_authorization_context"
    MISSING_SUBJECT = "missing_subject"
    UNKNOWN_PERMISSION_CLASS = "unknown_permission_class"
    HIGH_IMPACT_DENIED_BY_DEFAULT = "high_impact_denied_by_default"
    CONTROLLED_WRITE_NOT_AVAILABLE_IN_E0 = "controlled_write_not_available_in_e0"
    MISSING_EXECUTION_MODE = "missing_execution_mode"
    UNSUPPORTED_EXECUTION_MODE = "unsupported_execution_mode"
    INVALID_INPUT = "invalid_input"
    CONTRACT_EVALUATION_ERROR = "contract_evaluation_error"


class AdmissionDecision(str, Enum):
    """Decision of the E0 admission gate."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class CapabilityScope:
    """Scope of a capability request: the engineering domains it touches.

    A request without scope is invalid (fail-closed). Scopes may only
    reference DECLARED engineering domains.
    """

    domains: tuple[EngineeringDomain, ...]


@dataclass(frozen=True)
class AuthorizationContext:
    """Who is requesting, under which permission class.

    E0 authorization is a *contract*: it records the subject and the
    permission class the request claims. Granting and decision logic
    belongs to JARVIS PRIME's admission/authorization layer — not to
    Engineering. The E0 gate simply refuses anything it cannot fully
    verify (fail-closed).
    """

    subject: str
    permission_class: PermissionClass
    trace_id: str = ""


@dataclass(frozen=True)
class CapabilityRequest:
    """A request addressed to the Engineering capability.

    Required fields are validated by :func:`admit_request`:
    ``request_id`` (non-empty), ``capability`` (must equal the
    Engineering identity), ``capability_version`` (must be supported),
    ``scope`` (present, non-empty, declared domains only),
    ``authorization`` (present, with a non-empty subject and a known
    permission class), and ``execution_mode`` (known and admitted by
    E0). ``input`` is an optional payload mapping.

    G3 execution order §2 (2026-09-10) adds the mission/task identity
    fields: ``mission_id`` (the optional grouping identity — a task
    may belong to a mission) and ``task_id`` (the engineering task
    the request serves). Both are structurally validated whenever
    present at BOTH gates; the E1 gate additionally REQUIRES
    ``task_id`` for requests whose operations need task attribution
    (the G3 controlled write surface). The request never defines its
    own authority — identity is attribution, not authorization.
    """

    request_id: str
    capability: str
    capability_version: str
    scope: CapabilityScope | None
    authorization: AuthorizationContext | None
    execution_mode: ExecutionMode | None
    input: Mapping[str, Any] | None = None
    mission_id: str = ""
    task_id: str = ""


@dataclass(frozen=True)
class Admission:
    """Outcome of the E0 admission gate."""

    decision: AdmissionDecision
    reason: RejectionReason | None = None
    detail: str = ""

    @property
    def accepted(self) -> bool:
        """True only when the decision is ACCEPTED."""
        return self.decision is AdmissionDecision.ACCEPTED


def _reject(reason: RejectionReason, detail: str = "") -> Admission:
    return Admission(
        decision=AdmissionDecision.REJECTED,
        reason=reason,
        detail=detail,
    )


def admit_request(request: CapabilityRequest | None) -> Admission:
    """Fail-closed admission gate for the E0 capability contract.

    This function never raises. Anything missing, unknown, not
    implemented, or high-impact yields REJECTED with a machine-readable
    reason. ACCEPTED means the request is structurally valid and within
    the E0 posture (READ + PASSIVE_ANALYSIS); it does NOT mean
    execution, success, or verification.
    """
    try:
        return _admit(request)
    except Exception:  # fail closed on any unexpected error
        return _reject(
            RejectionReason.CONTRACT_EVALUATION_ERROR,
            "unexpected error during contract evaluation",
        )


#: Maximum length and character rule for mission/task identity
#: strings (G3 §2): printable, bounded, non-empty when present.
IDENTITY_MAX_LENGTH: int = 128


def identity_is_valid(value: object) -> bool:
    """Structural rule for mission/task identity strings (G3 §2).

    A present identity must be a non-empty string of at most
    :data:`IDENTITY_MAX_LENGTH` characters containing no ASCII
    control characters. Empty strings mean "absent" and are handled
    by the gates (absence is never coerced into a fabricated
    identity).
    """
    if not isinstance(value, str) or not value:
        return False
    if len(value) > IDENTITY_MAX_LENGTH:
        return False
    return not any(ord(character) < 32 or ord(character) == 127 for character in value)


def _admit(request: CapabilityRequest | None) -> Admission:
    if request is None:
        return _reject(RejectionReason.MISSING_REQUEST, "no request provided")
    if not isinstance(request, CapabilityRequest):
        return _reject(
            RejectionReason.INVALID_REQUEST,
            f"expected CapabilityRequest, got {type(request).__name__}",
        )

    if not isinstance(request.request_id, str) or not request.request_id:
        return _reject(
            RejectionReason.MISSING_REQUEST_ID,
            "request_id must be a non-empty string",
        )
    if request.capability != CAPABILITY_IDENTITY:
        return _reject(
            RejectionReason.CAPABILITY_IDENTITY_MISMATCH,
            f"expected {CAPABILITY_IDENTITY!r}, got {request.capability!r}",
        )
    if (
        not isinstance(request.capability_version, str)
        or request.capability_version not in SUPPORTED_CAPABILITY_VERSIONS
    ):
        return _reject(
            RejectionReason.UNSUPPORTED_CAPABILITY_VERSION,
            f"supported versions: {sorted(SUPPORTED_CAPABILITY_VERSIONS)}",
        )

    scope = request.scope
    if scope is None:
        return _reject(RejectionReason.MISSING_SCOPE, "capability scope is mandatory")
    if not isinstance(scope, CapabilityScope):
        return _reject(
            RejectionReason.INVALID_SCOPE,
            f"expected CapabilityScope, got {type(scope).__name__}",
        )
    domains = scope.domains
    if not domains:
        return _reject(
            RejectionReason.EMPTY_SCOPE,
            "scope must declare at least one engineering domain",
        )
    for domain in domains:
        if not isinstance(domain, EngineeringDomain):
            return _reject(
                RejectionReason.UNDECLARED_DOMAIN,
                f"undeclared engineering domain: {domain!r}",
            )

    authorization = request.authorization
    if authorization is None:
        return _reject(
            RejectionReason.MISSING_AUTHORIZATION_CONTEXT,
            "authorization context is mandatory",
        )
    if not isinstance(authorization, AuthorizationContext):
        return _reject(
            RejectionReason.INVALID_AUTHORIZATION_CONTEXT,
            f"expected AuthorizationContext, got {type(authorization).__name__}",
        )
    if not isinstance(authorization.subject, str) or not authorization.subject:
        return _reject(
            RejectionReason.MISSING_SUBJECT,
            "authorization subject must be a non-empty string",
        )
    permission_class = authorization.permission_class
    if not isinstance(permission_class, PermissionClass):
        return _reject(
            RejectionReason.UNKNOWN_PERMISSION_CLASS,
            "unknown permission class: rejected, never assumed (fail-closed)",
        )
    if permission_class is PermissionClass.HIGH_IMPACT:
        return _reject(
            RejectionReason.HIGH_IMPACT_DENIED_BY_DEFAULT,
            "E0 denies git_commit, git_push, release, deployment, "
            "production_modification and external_communication by default",
        )
    if permission_class is PermissionClass.CONTROLLED_WRITE:
        return _reject(
            RejectionReason.CONTROLLED_WRITE_NOT_AVAILABLE_IN_E0,
            "E0 is passive analysis only; controlled execution is E1 "
            "(NOT_IMPLEMENTED)",
        )

    mode = request.execution_mode
    if mode is None:
        return _reject(
            RejectionReason.MISSING_EXECUTION_MODE,
            "execution mode is mandatory",
        )
    if not isinstance(mode, ExecutionMode):
        return _reject(
            RejectionReason.UNSUPPORTED_EXECUTION_MODE,
            "unknown execution mode: rejected, never assumed (fail-closed)",
        )
    if mode is not ExecutionMode.PASSIVE_ANALYSIS:
        return _reject(
            RejectionReason.UNSUPPORTED_EXECUTION_MODE,
            f"E0 admits PASSIVE_ANALYSIS only; {mode.value} is not implemented",
        )

    request_input = request.input
    if request_input is not None and not isinstance(request_input, Mapping):
        return _reject(
            RejectionReason.INVALID_INPUT,
            "request input must be a mapping or None",
        )

    # -- G3 §2: mission/task identity (structural, when present) --------
    if request.mission_id != "" and not identity_is_valid(request.mission_id):
        return _reject(
            RejectionReason.MISSION_IDENTITY_INVALID,
            "mission_id must be a non-empty printable string of at most "
            f"{IDENTITY_MAX_LENGTH} characters",
        )
    if request.task_id != "" and not identity_is_valid(request.task_id):
        return _reject(
            RejectionReason.TASK_IDENTITY_INVALID,
            "task_id must be a non-empty printable string of at most "
            f"{IDENTITY_MAX_LENGTH} characters",
        )

    return Admission(
        decision=AdmissionDecision.ACCEPTED,
        reason=None,
        detail=(
            "structurally valid and within the E0 passive-analysis posture; "
            "acceptance is not execution, success, or verification"
        ),
    )
