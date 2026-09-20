"""E1 admission — enforceable admission for contract version 0.2.0.

The E0 gate (:func:`contracts.contract.admit_request`) remains the
0.1.0 structural contract, unchanged. This module is the E1 gate: it
re-validates the request structure, applies the E1 posture
(owner-authorized evolution), parses the operation payload, and
BINDS the request to a valid resource grant (D-06 = A) — the grant
is validated at admission time and re-validated at execution time
by the executor.

E1 posture (from the E1 authorization + closed decisions):

- ``READ`` × ``PASSIVE_ANALYSIS`` — admissible (E0-compatible
  analysis through the controlled pipeline, still grant-bound);
- ``READ`` × ``CONTROLLED_EXECUTION`` — admissible (bounded,
  evidenced analysis);
- ``CONTROLLED_WRITE`` × ``CONTROLLED_EXECUTION`` — admissible for
  workspace-confined operations and sandboxed execution operations;
- ``CONTROLLED_WRITE`` × ``PASSIVE_ANALYSIS`` — rejected (passive
  analysis performs no writes);
- ``HIGH_IMPACT`` — denied by default, at BOTH gates;
- ``CONTROLLED_WRITE`` × ``AUTONOMOUS_ENGINEERING_LOOP`` — the E2
  delegated loop mode (admits exactly one ``run_engineering_loop``
  operation; G4 order §3 additionally REQUIRES ``task_id`` — the
  loop mutates the delegated repository through applied patches, so
  task attribution is mandatory wherever mutation is possible);
- ``CONTROLLED_WRITE`` × ``MULTI_STEP_ENGINEERING_MISSION`` — the E3
  mission mode (admits exactly one ``run_engineering_mission``
  operation);
- every mode above ``MULTI_STEP_ENGINEERING_MISSION`` (E4) —
  rejected, not implemented.

Operation payload (request.input mapping):

```text
{
  "operations": [
    {"name": "repository_inspection", "target": "/abs/root"},
    {"name": "source_reading", "targets": ["/abs/file", ...]},
    {"name": "metadata_analysis", "target": "/abs/root"},
    {"name": "documentation_reading", "target": "/abs/root"},
    {"name": "static_analysis", "target": "/abs/root"},
    {"name": "import_graph", "target": "/abs/root"},
    {"name": "parse_test_report", "report_path": "/abs/report.xml"},
    {"name": "run_tests", "targets": ["tests/"], "image": "..."},
    {"name": "run_engineering_loop", "target": "/abs/root", ...},
    {"name": "run_engineering_mission", "target": "/abs/root", ...}
  ],
  "limits": {"timeout_seconds": 60}          # optional, may only lower
}
```

Fail-closed throughout: ``admit_controlled_request`` never raises;
every failure is a machine-readable :class:`E1RejectionReason`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from contracts.capability import CAPABILITY_IDENTITY
from contracts.contract import (
    AuthorizationContext,
    CapabilityRequest,
    CapabilityScope,
    ExecutionMode,
    PermissionClass,
    SUPPORTED_CAPABILITY_VERSIONS,
    identity_is_valid,
)
from contracts.domain import EngineeringDomain
from grants.grant import (
    GrantRejectionReason,
    GrantValidation,
    ResourceGrant,
    ScopeCoverage,
    ScopeMismatchReason,
    check_scope_coverage,
    validate_grant,
)
from contracts.implementation import E1_OPERATIONS, OperationSpec
from substrate.limits import (
    ExecutionLimits,
    E1_LIMITS_DEFAULTS,
    LimitsValidation,
    limits_from_mapping,
    validate_against_defaults,
)

#: Operations whose params carry a single absolute "target" root.
_SINGLE_TARGET_OPERATIONS: frozenset[str] = frozenset(
    {
        "repository_inspection",
        "metadata_analysis",
        "documentation_reading",
        "static_analysis",
        "import_graph",
        "run_engineering_loop",
        "run_engineering_mission",
    }
)

#: Operations whose params carry a list of absolute paths.
_MULTI_TARGET_OPERATIONS: frozenset[str] = frozenset({"source_reading"})

#: Operations whose params carry a single absolute report path.
_REPORT_PATH_OPERATIONS: frozenset[str] = frozenset({"parse_test_report"})

#: The sandboxed execution operation (relative targets + image).
_SANDBOX_EXECUTION_OPERATIONS: frozenset[str] = frozenset({"run_tests"})

#: The G3 controlled write operations (execution order v1 §4). These
#: carry the "separate authorization" E1.md recorded as required
#: before write-class domain operations could be registered — the
#: G3 owner order (2026-09-10) is that authorization. Registering
#: them here means the fail-closed machinery (class match, domain
#: scope, grant binding, task-identity attribution, workspace
#: confinement, custody exit, intent verification) applies to them
#: exactly as it does to every other E1 operation.
_G3_WRITE_OPERATIONS: frozenset[str] = frozenset(
    {"source_modification", "artifact_creation"}
)

#: The E2 autonomous-loop operation (delegated objective payload).
_LOOP_OPERATIONS: frozenset[str] = frozenset({"run_engineering_loop"})

#: The E3 engineering-mission operation (delegated mission payload).
_MISSION_OPERATIONS: frozenset[str] = frozenset({"run_engineering_mission"})

#: The E4 high-impact operation (approval-gated commit payload).
_HIGH_IMPACT_OPERATIONS: frozenset[str] = frozenset({"run_high_impact_commit"})


class E1RejectionReason(str, Enum):
    """Machine-readable E1 admission rejection reasons."""

    # structural (mirror of the E0 codes for the 0.2.0 gate)
    MISSING_REQUEST = "missing_request"
    INVALID_REQUEST = "invalid_request"
    MISSING_REQUEST_ID = "missing_request_id"
    CAPABILITY_IDENTITY_MISMATCH = "capability_identity_mismatch"
    UNSUPPORTED_CAPABILITY_VERSION = "unsupported_capability_version"
    MISSING_SCOPE = "missing_scope"
    INVALID_SCOPE = "invalid_scope"
    EMPTY_SCOPE = "empty_scope"
    UNDECLARED_DOMAIN = "undeclared_domain"
    MISSING_AUTHORIZATION_CONTEXT = "missing_authorization_context"
    INVALID_AUTHORIZATION_CONTEXT = "invalid_authorization_context"
    MISSING_SUBJECT = "missing_subject"
    UNKNOWN_PERMISSION_CLASS = "unknown_permission_class"
    HIGH_IMPACT_DENIED_BY_DEFAULT = "high_impact_denied_by_default"
    MISSING_EXECUTION_MODE = "missing_execution_mode"
    UNSUPPORTED_EXECUTION_MODE = "unsupported_execution_mode"
    INVALID_INPUT = "invalid_input"
    CONTRACT_EVALUATION_ERROR = "contract_evaluation_error"
    # E1 posture
    PASSIVE_ANALYSIS_CANNOT_WRITE = "passive_analysis_cannot_write"
    MODE_NOT_IMPLEMENTED_IN_E1 = "mode_not_implemented_in_e1"
    # E2 posture (autonomous engineering loop)
    LOOP_MODE_REQUIRES_CONTROLLED_WRITE = "loop_mode_requires_controlled_write"
    LOOP_OPERATION_REQUIRED = "loop_operation_required"
    LOOP_MODE_REQUIRED = "loop_mode_required"
    # E3 posture (multi-step engineering mission)
    MISSION_MODE_REQUIRES_CONTROLLED_WRITE = (
        "mission_mode_requires_controlled_write"
    )
    MISSION_OPERATION_REQUIRED = "mission_operation_required"
    MISSION_MODE_REQUIRED = "mission_mode_required"
    # E4 posture (high-impact operations, approval-gated)
    HIGH_IMPACT_MODE_REQUIRES_HIGH_IMPACT_CLASS = (
        "high_impact_mode_requires_high_impact_class"
    )
    HIGH_IMPACT_OPERATION_REQUIRED = "high_impact_operation_required"
    HIGH_IMPACT_MODE_REQUIRED = "high_impact_mode_required"
    # operation payload
    OPERATIONS_MISSING = "operations_missing"
    OPERATION_ENTRY_INVALID = "operation_entry_invalid"
    OPERATION_NAME_MISSING = "operation_name_missing"
    OPERATION_NOT_REGISTERED = "operation_not_registered"
    OPERATION_CLASS_MISMATCH = "operation_class_mismatch"
    OPERATION_DOMAIN_NOT_IN_SCOPE = "operation_domain_not_in_scope"
    OPERATION_PARAMS_INVALID = "operation_params_invalid"
    # G3 request identity (execution order v1 §2)
    TASK_IDENTITY_REQUIRED = "task_identity_required"
    MISSION_IDENTITY_INVALID = "mission_identity_invalid"
    TASK_IDENTITY_INVALID = "task_identity_invalid"
    # limits
    LIMITS_INVALID = "limits_invalid"
    LIMITS_EXCEED_DEFAULTS = "limits_exceed_defaults"
    # grants
    GRANT_REQUIRED = "grant_required"
    GRANT_REJECTED = "grant_rejected"
    GRANT_SCOPE_MISMATCH = "grant_scope_mismatch"


@dataclass(frozen=True)
class ParsedOperation:
    """One validated operation request within the payload."""

    name: str
    spec: OperationSpec
    params: dict[str, Any]

    def target_paths(self) -> tuple[str, ...]:
        """Absolute paths this operation will touch (for coverage checks)."""
        if self.name in _SINGLE_TARGET_OPERATIONS:
            target = self.params.get("target")
            return (target,) if isinstance(target, str) else ()
        if self.name in _MULTI_TARGET_OPERATIONS:
            targets = self.params.get("targets")
            if isinstance(targets, (list, tuple)):
                return tuple(
                    item for item in targets if isinstance(item, str)
                )
            return ()
        if self.name in _REPORT_PATH_OPERATIONS:
            report_path = self.params.get("report_path")
            return (report_path,) if isinstance(report_path, str) else ()
        if self.name == "source_modification":
            source = self.params.get("source")
            return (source,) if isinstance(source, str) else ()
        return ()


@dataclass(frozen=True)
class ControlledAdmission:
    """Outcome of the E1 admission gate (never an exception)."""

    accepted: bool
    reason: E1RejectionReason | None = None
    detail: str = ""
    bound_grant: ResourceGrant | None = None
    operations: tuple[ParsedOperation, ...] = ()
    limits: ExecutionLimits = E1_LIMITS_DEFAULTS

    @property
    def admissible(self) -> bool:
        return self.accepted


def _reject(
    reason: E1RejectionReason, detail: str = ""
) -> ControlledAdmission:
    return ControlledAdmission(accepted=False, reason=reason, detail=detail)


def admit_controlled_request(
    request: CapabilityRequest | None,
    *,
    grants: tuple[ResourceGrant, ...] | list[ResourceGrant],
    trusted_grantors: frozenset[str] | set[str],
    revocation: object,
    verifier: object,
    now: float,
) -> ControlledAdmission:
    """E1 admission gate — fail-closed, never raises.

    Validates structure (0.2.0), E1 posture, the operation payload,
    request limits against D-13, and binds the request to exactly one
    valid, scope-covering grant. Grant validation uses the same
    trusted-grantors / live-revocation / signature-verifier wiring the
    executor re-checks at execution time (D-06 = A).
    """
    try:
        return _admit(
            request,
            grants=grants,
            trusted_grantors=trusted_grantors,
            revocation=revocation,
            verifier=verifier,
            now=now,
        )
    except Exception:  # fail closed on any unexpected error
        return _reject(
            E1RejectionReason.CONTRACT_EVALUATION_ERROR,
            "unexpected error during E1 admission evaluation",
        )


def _admit(
    request: CapabilityRequest | None,
    *,
    grants: tuple[ResourceGrant, ...] | list[ResourceGrant],
    trusted_grantors: frozenset[str] | set[str],
    revocation: object,
    verifier: object,
    now: float,
) -> ControlledAdmission:
    # -- structure ---------------------------------------------------------
    if request is None:
        return _reject(E1RejectionReason.MISSING_REQUEST, "no request provided")
    if not isinstance(request, CapabilityRequest):
        return _reject(
            E1RejectionReason.INVALID_REQUEST,
            f"expected CapabilityRequest, got {type(request).__name__}",
        )
    if not isinstance(request.request_id, str) or not request.request_id:
        return _reject(
            E1RejectionReason.MISSING_REQUEST_ID,
            "request_id must be a non-empty string",
        )
    if request.capability != CAPABILITY_IDENTITY:
        return _reject(
            E1RejectionReason.CAPABILITY_IDENTITY_MISMATCH,
            f"expected {CAPABILITY_IDENTITY!r}, got {request.capability!r}",
        )
    if (
        not isinstance(request.capability_version, str)
        or request.capability_version not in SUPPORTED_CAPABILITY_VERSIONS
    ):
        return _reject(
            E1RejectionReason.UNSUPPORTED_CAPABILITY_VERSION,
            f"supported versions: {sorted(SUPPORTED_CAPABILITY_VERSIONS)}",
        )
    scope = request.scope
    if scope is None:
        return _reject(E1RejectionReason.MISSING_SCOPE, "capability scope is mandatory")
    if not isinstance(scope, CapabilityScope):
        return _reject(
            E1RejectionReason.INVALID_SCOPE,
            f"expected CapabilityScope, got {type(scope).__name__}",
        )
    if not scope.domains:
        return _reject(
            E1RejectionReason.EMPTY_SCOPE,
            "scope must declare at least one engineering domain",
        )
    for domain in scope.domains:
        if not isinstance(domain, EngineeringDomain):
            return _reject(
                E1RejectionReason.UNDECLARED_DOMAIN,
                f"undeclared engineering domain: {domain!r}",
            )
    authorization = request.authorization
    if authorization is None:
        return _reject(
            E1RejectionReason.MISSING_AUTHORIZATION_CONTEXT,
            "authorization context is mandatory",
        )
    if not isinstance(authorization, AuthorizationContext):
        return _reject(
            E1RejectionReason.INVALID_AUTHORIZATION_CONTEXT,
            f"expected AuthorizationContext, got {type(authorization).__name__}",
        )
    if not isinstance(authorization.subject, str) or not authorization.subject:
        return _reject(
            E1RejectionReason.MISSING_SUBJECT,
            "authorization subject must be a non-empty string",
        )
    permission_class = authorization.permission_class
    if not isinstance(permission_class, PermissionClass):
        return _reject(
            E1RejectionReason.UNKNOWN_PERMISSION_CLASS,
            "unknown permission class: rejected, never assumed (fail-closed)",
        )

    # -- G3 §2: mission/task identity ---------------------------------------
    # Structurally validated whenever present; task identity is
    # REQUIRED when the requested operations need task attribution
    # (the G3 controlled write surface). The identity is attribution,
    # never authority: it never widens scope, class, or grants.
    if request.mission_id != "" and not identity_is_valid(request.mission_id):
        return _reject(
            E1RejectionReason.MISSION_IDENTITY_INVALID,
            "mission_id must be a non-empty printable string of at most "
            "128 characters",
        )
    if request.task_id != "" and not identity_is_valid(request.task_id):
        return _reject(
            E1RejectionReason.TASK_IDENTITY_INVALID,
            "task_id must be a non-empty printable string of at most "
            "128 characters",
        )
    identity_input = request.input
    if (
        request.task_id == ""
        and isinstance(identity_input, Mapping)
        and any(
            isinstance(entry, dict) and entry.get("name") in _G3_WRITE_OPERATIONS
            for entry in (identity_input.get("operations") or ())
        )
    ):
        return _reject(
            E1RejectionReason.TASK_IDENTITY_REQUIRED,
            "G3 controlled write operations require an explicit task_id "
            "(attribution is mandatory wherever mutation is possible; the "
            "task never defines its own authority)",
        )

    mode = request.execution_mode
    if mode is None:
        return _reject(
            E1RejectionReason.MISSING_EXECUTION_MODE,
            "execution mode is mandatory",
        )
    if not isinstance(mode, ExecutionMode):
        return _reject(
            E1RejectionReason.UNSUPPORTED_EXECUTION_MODE,
            "unknown execution mode: rejected, never assumed (fail-closed)",
        )
    # -- HIGH_IMPACT default deny (E4 order §4): the ONLY admissible
    #    combination is HIGH_IMPACT class x HIGH_IMPACT_OPERATIONS mode,
    #    and it additionally requires a verified Owner approval at the
    #    engine (engineering.high_impact_engine). Every other
    #    HIGH_IMPACT combination stays denied by default.
    if (
        permission_class is PermissionClass.HIGH_IMPACT
        and mode is not ExecutionMode.HIGH_IMPACT_OPERATIONS
    ):
        return _reject(
            E1RejectionReason.HIGH_IMPACT_DENIED_BY_DEFAULT,
            "HIGH_IMPACT operations stay denied by default: the only "
            "admissible combination is the E4 HIGH_IMPACT_OPERATIONS mode "
            "with a HIGH_IMPACT grant AND a verified Owner approval",
        )

    # -- E1 posture ----------------------------------------------------------
    if mode is ExecutionMode.PASSIVE_ANALYSIS:
        if permission_class is PermissionClass.CONTROLLED_WRITE:
            return _reject(
                E1RejectionReason.PASSIVE_ANALYSIS_CANNOT_WRITE,
                "passive analysis performs no writes; controlled write "
                "requires CONTROLLED_EXECUTION mode",
            )
    elif mode is ExecutionMode.CONTROLLED_EXECUTION:
        if permission_class not in (
            PermissionClass.READ,
            PermissionClass.CONTROLLED_WRITE,
        ):
            return _reject(
                E1RejectionReason.UNSUPPORTED_EXECUTION_MODE,
                f"mode CONTROLLED_EXECUTION does not admit class {permission_class.value}",
            )
    elif mode is ExecutionMode.AUTONOMOUS_ENGINEERING_LOOP:
        if permission_class is not PermissionClass.CONTROLLED_WRITE:
            return _reject(
                E1RejectionReason.LOOP_MODE_REQUIRES_CONTROLLED_WRITE,
                (
                    "AUTONOMOUS_ENGINEERING_LOOP is a delegated write mode; it "
                    f"does not admit class {permission_class.value}"
                ),
            )
    elif mode is ExecutionMode.MULTI_STEP_ENGINEERING_MISSION:
        if permission_class is not PermissionClass.CONTROLLED_WRITE:
            return _reject(
                E1RejectionReason.MISSION_MODE_REQUIRES_CONTROLLED_WRITE,
                (
                    "MULTI_STEP_ENGINEERING_MISSION is a delegated write "
                    f"mode; it does not admit class {permission_class.value}"
                ),
            )
    elif mode is ExecutionMode.HIGH_IMPACT_OPERATIONS:
        if permission_class is not PermissionClass.HIGH_IMPACT:
            return _reject(
                E1RejectionReason.HIGH_IMPACT_MODE_REQUIRES_HIGH_IMPACT_CLASS,
                (
                    "HIGH_IMPACT_OPERATIONS is the E4 approval-gated mode; "
                    f"it does not admit class {permission_class.value}"
                ),
            )
    else:
        return _reject(
            E1RejectionReason.MODE_NOT_IMPLEMENTED_IN_E1,
            (
                f"execution mode {mode.value} is beyond E4 territory; not "
                "implemented (E4 high-impact operations with owner "
                "approval is the highest implemented autonomy)"
            ),
        )

    # -- input & operations -----------------------------------------------------
    request_input = request.input
    if request_input is not None and not isinstance(request_input, dict):
        return _reject(
            E1RejectionReason.INVALID_INPUT,
            "request input must be a mapping or None",
        )
    operations_payload = (request_input or {}).get("operations")
    if not isinstance(operations_payload, (list, tuple)) or not operations_payload:
        return _reject(
            E1RejectionReason.OPERATIONS_MISSING,
            "request input must carry a non-empty 'operations' list",
        )

    parsed: list[ParsedOperation] = []
    request_domains = frozenset(scope.domains)
    for index, entry in enumerate(operations_payload):
        if not isinstance(entry, dict):
            return _reject(
                E1RejectionReason.OPERATION_ENTRY_INVALID,
                f"operation #{index} must be a mapping",
            )
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            return _reject(
                E1RejectionReason.OPERATION_NAME_MISSING,
                f"operation #{index} has no 'name'",
            )
        spec = E1_OPERATIONS.get(name)
        if spec is None:
            return _reject(
                E1RejectionReason.OPERATION_NOT_REGISTERED,
                f"operation {name!r} is not registered in E1",
            )
        if spec.permission_class is not permission_class:
            return _reject(
                E1RejectionReason.OPERATION_CLASS_MISMATCH,
                (
                    f"operation {name!r} requires class "
                    f"{spec.permission_class.value}; request carries "
                    f"{permission_class.value}"
                ),
            )
        if spec.requires_domains is not None:
            missing = spec.requires_domains - request_domains
            if missing:
                return _reject(
                    E1RejectionReason.OPERATION_DOMAIN_NOT_IN_SCOPE,
                    (
                        f"operation {name!r} requires domains "
                        f"{sorted(domain.value for domain in missing)} in scope"
                    ),
                )
        params_error = _validate_operation_params(name, entry)
        if params_error is not None:
            return _reject(
                E1RejectionReason.OPERATION_PARAMS_INVALID,
                f"operation {name!r}: {params_error}",
            )
        params = {key: value for key, value in entry.items() if key != "name"}
        parsed.append(ParsedOperation(name=name, spec=spec, params=params))

    # -- E2 posture: the loop mode admits exactly one loop operation ------------
    if mode is ExecutionMode.AUTONOMOUS_ENGINEERING_LOOP:
        loop_operations = [
            operation for operation in parsed if operation.name in _LOOP_OPERATIONS
        ]
        if len(parsed) != 1 or len(loop_operations) != 1:
            return _reject(
                E1RejectionReason.LOOP_OPERATION_REQUIRED,
                (
                    "AUTONOMOUS_ENGINEERING_LOOP mode admits exactly one "
                    "'run_engineering_loop' operation"
                ),
            )
        # -- G4 order §3: task attribution is mandatory for the loop. The
        #    loop applies repair patches to the delegated repository, so
        #    mutation is possible and attribution must be explicit. The
        #    identity is attribution, never authority: a task_id never
        #    widens scope, class, or grants.
        if request.task_id == "":
            return _reject(
                E1RejectionReason.TASK_IDENTITY_REQUIRED,
                (
                    "run_engineering_loop requires an explicit task_id "
                    "(G4 order §3: the engineering loop mutates the "
                    "delegated repository through applied patches; "
                    "attribution is mandatory wherever mutation is "
                    "possible — the task never defines its own authority)"
                ),
            )
    # -- E3 posture: the mission mode admits exactly one mission op -------------
    elif mode is ExecutionMode.MULTI_STEP_ENGINEERING_MISSION:
        mission_operations = [
            operation
            for operation in parsed
            if operation.name in _MISSION_OPERATIONS
        ]
        if len(parsed) != 1 or len(mission_operations) != 1:
            return _reject(
                E1RejectionReason.MISSION_OPERATION_REQUIRED,
                (
                    "MULTI_STEP_ENGINEERING_MISSION mode admits exactly one "
                    "'run_engineering_mission' operation"
                ),
            )
    # -- E4 posture: the high-impact mode admits exactly one commit op ----------
    elif mode is ExecutionMode.HIGH_IMPACT_OPERATIONS:
        high_impact_operations = [
            operation
            for operation in parsed
            if operation.name in _HIGH_IMPACT_OPERATIONS
        ]
        if len(parsed) != 1 or len(high_impact_operations) != 1:
            return _reject(
                E1RejectionReason.HIGH_IMPACT_OPERATION_REQUIRED,
                (
                    "HIGH_IMPACT_OPERATIONS mode admits exactly one "
                    "'run_high_impact_commit' operation"
                ),
            )
    else:
        misplaced = [
            operation for operation in parsed if operation.name in _LOOP_OPERATIONS
        ]
        if misplaced:
            return _reject(
                E1RejectionReason.LOOP_MODE_REQUIRED,
                "run_engineering_loop requires AUTONOMOUS_ENGINEERING_LOOP mode",
            )
        misplaced_mission = [
            operation
            for operation in parsed
            if operation.name in _MISSION_OPERATIONS
        ]
        if misplaced_mission:
            return _reject(
                E1RejectionReason.MISSION_MODE_REQUIRED,
                (
                    "run_engineering_mission requires "
                    "MULTI_STEP_ENGINEERING_MISSION mode"
                ),
            )
        misplaced_high_impact = [
            operation
            for operation in parsed
            if operation.name in _HIGH_IMPACT_OPERATIONS
        ]
        if misplaced_high_impact:
            return _reject(
                E1RejectionReason.HIGH_IMPACT_MODE_REQUIRED,
                (
                    "run_high_impact_commit requires the "
                    "HIGH_IMPACT_OPERATIONS mode with a verified Owner "
                    "approval"
                ),
            )

    # -- limits -----------------------------------------------------------------
    limits_payload = (request_input or {}).get("limits")
    if "limits" not in (request_input or {}):
        resolved_limits: ExecutionLimits = E1_LIMITS_DEFAULTS
    else:
        candidate = limits_from_mapping(limits_payload)
        if isinstance(candidate, LimitsValidation):
            return _reject(
                E1RejectionReason.LIMITS_INVALID,
                candidate.detail,
            )
        policy_check: LimitsValidation = validate_against_defaults(candidate)
        if not policy_check.valid:
            return _reject(
                E1RejectionReason.LIMITS_EXCEED_DEFAULTS,
                policy_check.detail,
            )
        resolved_limits = candidate

    # -- grant binding (admission-time validation; executor re-checks) ----------
    target_paths: list[str] = []
    for operation in parsed:
        target_paths.extend(operation.target_paths())

    if not grants:
        return _reject(
            E1RejectionReason.GRANT_REQUIRED,
            "E1 controlled execution requires a resource grant (D-06=A)",
        )
    bound: ResourceGrant | None = None
    failures: list[str] = []
    for grant in grants:
        if not isinstance(grant, ResourceGrant):
            failures.append("non-grant object in the grant sequence")
            continue
        validation: GrantValidation = validate_grant(
            grant,
            trusted_grantors=trusted_grantors,
            revocation=revocation,  # type: ignore[arg-type]
            verifier=verifier,  # type: ignore[arg-type]
            now=now,
        )
        if not validation.valid:
            failures.append(
                f"grant {grant.grant_id!r}: {validation.reason.value}"
                if validation.reason
                else f"grant {grant.grant_id!r}: invalid"
            )
            continue
        coverage: ScopeCoverage = check_scope_coverage(
            grant,
            subject=authorization.subject,
            permission_class=permission_class,
            domains=tuple(scope.domains),
            target_paths=tuple(target_paths),
        )
        if not coverage.covered:
            failures.append(
                f"grant {grant.grant_id!r}: {coverage.reason.value}"
                if coverage.reason
                else f"grant {grant.grant_id!r}: scope mismatch"
            )
            continue
        bound = grant
        break
    if bound is None:
        if failures and all("grant" in failure for failure in failures):
            # distinguish pure validation failures from scope mismatches
            scope_mismatch = any(
                reason in failure
                for reason in (
                    ScopeMismatchReason.DOMAIN_NOT_COVERED.value,
                    ScopeMismatchReason.PERMISSION_CLASS_MISMATCH.value,
                    ScopeMismatchReason.SUBJECT_MISMATCH.value,
                    ScopeMismatchReason.RESOURCE_NOT_COVERED.value,
                )
                for failure in failures
            )
            reason = (
                E1RejectionReason.GRANT_SCOPE_MISMATCH
                if scope_mismatch
                else E1RejectionReason.GRANT_REJECTED
            )
            return _reject(reason, "; ".join(failures))
        return _reject(
            E1RejectionReason.GRANT_REJECTED,
            "no grant in the presented sequence is valid and covering",
        )

    return ControlledAdmission(
        accepted=True,
        reason=None,
        detail=(
            "admitted for controlled execution: structure valid, E1 "
            "posture satisfied, operations registered, limits within "
            "D-13, grant bound (admission-time validation)"
        ),
        bound_grant=bound,
        operations=tuple(parsed),
        limits=resolved_limits,
    )


def _validate_operation_params(name: str, entry: dict[str, Any]) -> str | None:
    """Validate one operation entry's parameters; None means valid."""
    if name in _SINGLE_TARGET_OPERATIONS:
        target = entry.get("target")
        if not isinstance(target, str) or not target.startswith("/"):
            return "'target' must be an absolute path string"
        return None
    if name in _MULTI_TARGET_OPERATIONS:
        targets = entry.get("targets")
        if not isinstance(targets, (list, tuple)) or not targets:
            return "'targets' must be a non-empty list of absolute paths"
        for item in targets:
            if not isinstance(item, str) or not item.startswith("/"):
                return "every target must be an absolute path string"
        return None
    if name in _REPORT_PATH_OPERATIONS:
        report_path = entry.get("report_path")
        if not isinstance(report_path, str) or not report_path.startswith("/"):
            return "'report_path' must be an absolute path string"
        return None
    if name in _SANDBOX_EXECUTION_OPERATIONS:
        targets = entry.get("targets")
        if not isinstance(targets, (list, tuple)) or not targets:
            return "'targets' must be a non-empty list of repository-relative paths"
        for item in targets:
            if not isinstance(item, str) or not item:
                return "every target must be a non-empty string"
            if item.startswith("/") or ".." in item.split("/"):
                return (
                    "targets must be repository-relative without escapes: "
                    f"{item!r}"
                )
        image = entry.get("image")
        if not isinstance(image, str) or not image:
            return "'image' must name an allowlisted sandbox image"
        return None
    if name == "source_modification":
        source = entry.get("source")
        if not isinstance(source, str) or not source.startswith("/"):
            return "'source' must be an absolute path string under a granted root"
        expected_sha256 = entry.get("expected_sha256")
        if not (
            isinstance(expected_sha256, str)
            and len(expected_sha256) == 64
            and all(character in "0123456789abcdef" for character in expected_sha256)
        ):
            return "'expected_sha256' must be a 64-character lowercase hex sha256"
        if not isinstance(entry.get("new_content"), str):
            return "'new_content' must be a UTF-8 text string"
        artifact_name = entry.get("artifact_name")
        if (
            not isinstance(artifact_name, str)
            or not artifact_name
            or artifact_name.startswith("/")
            or ".." in artifact_name.split("/")
            or "\\" in artifact_name
        ):
            return (
                "'artifact_name' must be a workspace-relative custody name "
                "without escapes"
            )
        return None
    if name == "artifact_creation":
        artifact_name = entry.get("artifact_name")
        if (
            not isinstance(artifact_name, str)
            or not artifact_name
            or artifact_name.startswith("/")
            or ".." in artifact_name.split("/")
            or "\\" in artifact_name
        ):
            return (
                "'artifact_name' must be a workspace-relative custody name "
                "without escapes"
            )
        if not isinstance(entry.get("content"), str):
            return "'content' must be a UTF-8 text string"
        content_sha256 = entry.get("content_sha256")
        if not (
            isinstance(content_sha256, str)
            and len(content_sha256) == 64
            and all(character in "0123456789abcdef" for character in content_sha256)
        ):
            return "'content_sha256' must be a 64-character lowercase hex sha256"
        return None
    if name in _LOOP_OPERATIONS:
        target = entry.get("target")
        if not isinstance(target, str) or not target.startswith("/"):
            return "'target' must be an absolute path string"
        raw_targets = entry.get("test_targets", ["tests/"])
        if not isinstance(raw_targets, (list, tuple)) or not raw_targets:
            return "'test_targets' must be a non-empty list"
        for item in raw_targets:
            if not isinstance(item, str) or not item:
                return "every test target must be a non-empty string"
            if item.startswith("/") or ".." in item.split("/"):
                return f"test targets must be repository-relative: {item!r}"
        image = entry.get("image")
        if not isinstance(image, str) or not image:
            return "'image' must name an allowlisted sandbox image"
        strategies = entry.get("strategies", [])
        if not isinstance(strategies, (list, tuple)):
            return "'strategies' must be a list (possibly empty)"
        for item in strategies:
            if not isinstance(item, dict):
                return "every strategy must be a mapping"
            patch = item.get("patch")
            if not isinstance(patch, dict):
                return "every strategy needs a 'patch' mapping"
            for key in ("path", "old_text", "new_text"):
                if not isinstance(patch.get(key), str):
                    return f"strategy patch {key!r} must be a string"
        limits = entry.get("limits")
        if limits is not None and not isinstance(limits, dict):
            return "'limits' must be a mapping or absent"
        return None
    if name in _MISSION_OPERATIONS:
        target = entry.get("target")
        if not isinstance(target, str) or not target.startswith("/"):
            return "'target' must be an absolute path string"
        image = entry.get("image")
        if not isinstance(image, str) or not image:
            return "'image' must name an allowlisted sandbox image"
        raw_workspace = entry.get("workspace_scope")
        if not isinstance(raw_workspace, (list, tuple)) or not raw_workspace:
            return "'workspace_scope' must be a non-empty list of prefixes"
        for item in raw_workspace:
            if not isinstance(item, str) or not item:
                return "every workspace scope prefix must be a non-empty string"
            if item.startswith("/") or ".." in item.split("/"):
                return (
                    "workspace scope prefixes must be repository-relative: "
                    f"{item!r}"
                )
        tasks = entry.get("tasks")
        if not isinstance(tasks, (list, tuple)) or not tasks:
            return "'tasks' must be a non-empty list of task mappings"
        for item in tasks:
            if not isinstance(item, dict):
                return "every task must be a mapping"
            if not isinstance(item.get("id"), str) or not item.get("id"):
                return "every task needs a non-empty string 'id'"
        limits = entry.get("limits")
        if limits is not None and not isinstance(limits, dict):
            return "'limits' must be a mapping or absent"
        return None
    if name in _HIGH_IMPACT_OPERATIONS:
        # shallow structural validation (E4 order §1 posture); the
        # deep fail-closed parse — ceilings, target existence, argv
        # safety — lives in engineering.high_impact.parse_high_impact_
        # payload and runs again inside the engine
        target = entry.get("target")
        if not isinstance(target, str) or not target.startswith("/"):
            return "'target' must be an absolute path string"
        message = entry.get("message")
        if not isinstance(message, str) or not message.strip():
            return "'message' must be a non-empty string"
        include = entry.get("include")
        if not isinstance(include, (list, tuple)) or not include:
            return "'include' must be a non-empty list of repository-relative prefixes"
        for item in include:
            if not isinstance(item, str) or not item:
                return "every include prefix must be a non-empty string"
            if item.startswith("/") or ".." in item.split("/"):
                return f"include prefixes must be repository-relative: {item!r}"
        author_name = entry.get("author_name", "engineering-e4")
        if not isinstance(author_name, str) or not author_name:
            return "'author_name' must be a non-empty string"
        author_email = entry.get("author_email", "engineering-e4@localhost")
        if not isinstance(author_email, str) or not author_email:
            return "'author_email' must be a non-empty string"
        rollback = entry.get("rollback", True)
        if not isinstance(rollback, bool):
            return "'rollback' must be a boolean"
        limits = entry.get("limits")
        if limits is not None and not isinstance(limits, dict):
            return "'limits' must be a mapping or absent"
        return None
    return None


__all__ = [
    "ControlledAdmission",
    "E1RejectionReason",
    "ParsedOperation",
    "admit_controlled_request",
]
