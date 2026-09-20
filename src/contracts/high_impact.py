"""E4 high-impact engineering contracts, classification, and parser.

This module defines, fail-closed and deterministically:

- the impact classification of every capability operation this
  package declares (LOW_IMPACT / CONTROLLED / HIGH_IMPACT /
  FORBIDDEN) with the full §2 attribute matrix — scope, risk,
  required authority, approval requirement, resource limits, audit
  requirements, and verification requirements;
- the E4 high-impact request specification (``run_high_impact_commit``)
  and its fail-closed parser;
- the FROZEN high-impact capability contract (§3): identity,
  operation, target, scope, authority, policy, approval requirement,
  lease/lifetime requirement, resource limits, evidence requirements,
  verification requirements, and termination semantics.

Design rules (inherited from E0-E3):

- frozen: every contract dataclass is immutable; the executor can
  never mutate authority, approval state, scope, policy, or risk
  classification during execution;
- fail-closed: the parser never clamps, never guesses, never raises;
- default deny: nothing here grants anything — the admission gate
  (engineering.admission) admits exactly one high-impact operation,
  and the engine (engineering.high_impact_engine) additionally
  requires a verified Owner approval before any execution;
- bounded: file counts, byte budgets, and wall-clock ceilings are
  hard upper bounds; requests may only lower them, never raise them;
- honest: HIGH_IMPACT classification is *declared* by the E0
  contract; E4 implements exactly ONE high-impact operation
  (``run_high_impact_commit``). ``git_push``, ``release``,
  ``deployment``, ``production_modification``, and
  ``external_communication`` stay FORBIDDEN (never registered).

Process boundary: this module spawns no processes, opens no
sockets, and performs no filesystem access beyond pure data
validation (all execution lives in the sandbox substrate and in
engineering.high_impact_engine).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar

import hashlib

from contracts.contract import PermissionClass
from contracts.domain import EngineeringDomain
from substrate.limits import E1_LIMITS_DEFAULTS, ExecutionLimits


# ---------------------------------------------------------------------------
# §2 — impact classification matrix
# ---------------------------------------------------------------------------


class ImpactClassification(str, Enum):
    """Impact tier of a declared engineering capability operation."""

    #: Read-only, sandbox-free, no side effects on any resource.
    LOW_IMPACT = "LOW_IMPACT"
    #: Writes confined to a granted workspace; ephemeral or
    #: workspace-local effects only; no lasting external state.
    CONTROLLED = "CONTROLLED"
    #: Lasting repository-level effects (real commit objects) —
    #: admissible ONLY with Owner approval, lease, and policy.
    HIGH_IMPACT = "HIGH_IMPACT"
    #: Operations whose risk profile stays outside what this package
    #: is ever allowed to implement or execute autonomously.
    FORBIDDEN = "FORBIDDEN"


class ApprovalRequirement(str, Enum):
    """Approval semantics of a classified operation."""

    NOT_REQUIRED = "NOT_REQUIRED"
    OWNER_APPROVAL_REQUIRED = "OWNER_APPROVAL_REQUIRED"
    NEVER_APPROVABLE = "NEVER_APPROVABLE"


@dataclass(frozen=True)
class CapabilityClassificationEntry:
    """One row of the §2 capability classification matrix.

    Every attribute is declared once, here, and cross-checked by
    tests/contract/test_e4_boundary.py against the implementation
    registry — a row that lies about its registration is a structural
    failure, not a documentation issue.
    """

    capability_id: str
    operation: str
    permission_class: PermissionClass
    classification: ImpactClassification
    scope: str
    risk: str
    required_authority: str
    approval_requirement: ApprovalRequirement
    resource_limits: str
    audit_requirements: str
    verification_requirements: str
    implemented: bool = False


_READ_OPS_ROW = dict(
    permission_class=PermissionClass.READ,
    classification=ImpactClassification.LOW_IMPACT,
    scope="granted repository root, read-only",
    risk="negligible: no writes, no process spawning, no network",
    required_authority="READ-class resource grant, live-validated",
    approval_requirement=ApprovalRequirement.NOT_REQUIRED,
    resource_limits="D-13 ExecutionLimits (output ceiling, wall clock)",
    audit_requirements="evidence records with content digests per access",
    verification_requirements="deterministic re-read hash recheck (E1)",
    implemented=True,
)

_CONTROLLED_ROW = dict(
    permission_class=PermissionClass.CONTROLLED_WRITE,
    classification=ImpactClassification.CONTROLLED,
    scope="granted workspace copy; writes confined to task scope prefixes",
    risk="bounded: sandboxed execution, ephemeral effects, reversible by staging",
    required_authority="CONTROLLED_WRITE-class resource grant, live-validated",
    approval_requirement=ApprovalRequirement.NOT_REQUIRED,
    resource_limits=(
        "D-13 ExecutionLimits + loop/mission budgets (attempts, repairs, "
        "wall clock)"
    ),
    audit_requirements=(
        "per-attempt evidence trees: commands, artifacts, patches, verdicts"
    ),
    verification_requirements=(
        "independent fresh production re-run; change-ledger hash recheck"
    ),
    implemented=True,
)

_FORBIDDEN_ROW = dict(
    permission_class=PermissionClass.HIGH_IMPACT,
    classification=ImpactClassification.FORBIDDEN,
    scope="none — never implemented, never executed",
    risk="unbounded external or lasting impact outside this capability's authority",
    required_authority="none: no authority path exists or may be assumed",
    approval_requirement=ApprovalRequirement.NEVER_APPROVABLE,
    resource_limits="not applicable — no execution path",
    audit_requirements="structural AST guard: never registered in the operation registry",
    verification_requirements="structural AST guard: no handler, no engine call site",
    implemented=False,
)

#: The full §2 classification matrix. Every REGISTERED operation of
#: this package appears here with implemented=True; every operation
#: the E0 contract names under HIGH_IMPACT but E4 does not implement
#: appears with classification=FORBIDDEN and implemented=False.
CAPABILITY_CLASSIFICATION: tuple[CapabilityClassificationEntry, ...] = (
    CapabilityClassificationEntry(
        capability_id="repository_inspection",
        operation="list granted trees and file metadata",
        **_READ_OPS_ROW,
    ),
    CapabilityClassificationEntry(
        capability_id="source_reading",
        operation="read granted source files",
        **_READ_OPS_ROW,
    ),
    CapabilityClassificationEntry(
        capability_id="metadata_analysis",
        operation="read and hash file metadata",
        **_READ_OPS_ROW,
    ),
    CapabilityClassificationEntry(
        capability_id="documentation_reading",
        operation="read granted documentation files",
        **_READ_OPS_ROW,
    ),
    CapabilityClassificationEntry(
        capability_id="static_analysis",
        operation="AST-based module analysis",
        **_READ_OPS_ROW,
    ),
    CapabilityClassificationEntry(
        capability_id="import_graph",
        operation="intra-root import graph construction",
        **_READ_OPS_ROW,
    ),
    CapabilityClassificationEntry(
        capability_id="parse_test_report",
        operation="junit-xml report parsing",
        **_READ_OPS_ROW,
    ),
    CapabilityClassificationEntry(
        capability_id="run_tests",
        operation="sandboxed pytest execution through the isolation substrate",
        **_CONTROLLED_ROW,
    ),
    CapabilityClassificationEntry(
        capability_id="source_modification",
        operation=(
            "G3 controlled file modification inside the ephemeral "
            "workspace; custody-only exit"
        ),
        permission_class=PermissionClass.CONTROLLED_WRITE,
        classification=ImpactClassification.CONTROLLED,
        scope="granted source read + per-request ephemeral workspace",
        risk=(
            "bounded: exact-intent declared content, hash preconditions, "
            "ephemeral effects only, granted repository untouched"
        ),
        required_authority=(
            "CONTROLLED_WRITE-class resource grant + explicit task_id "
            "(G3 attribution), live-validated"
        ),
        approval_requirement=ApprovalRequirement.NOT_REQUIRED,
        resource_limits=(
            "D-13 workspace ceiling (pre-write) + G3 declaration ceiling"
        ),
        audit_requirements=(
            "access record + custody manifest + before/after change "
            "ledger + request-identity event"
        ),
        verification_requirements=(
            "intent-match + output-hash + artifact-readable + custody "
            "manifest match"
        ),
        implemented=True,
    ),
    CapabilityClassificationEntry(
        capability_id="artifact_creation",
        operation=(
            "G3 declared-content artifact generation in the custody "
            "boundary"
        ),
        permission_class=PermissionClass.CONTROLLED_WRITE,
        classification=ImpactClassification.CONTROLLED,
        scope="per-request ephemeral workspace custody directory only",
        risk=(
            "bounded: declared hash precondition, ephemeral effects "
            "only, no granted-repository access"
        ),
        required_authority=(
            "CONTROLLED_WRITE-class resource grant + explicit task_id "
            "(G3 attribution), live-validated"
        ),
        approval_requirement=ApprovalRequirement.NOT_REQUIRED,
        resource_limits=(
            "D-13 workspace ceiling (pre-write) + G3 declaration ceiling"
        ),
        audit_requirements=(
            "custody manifest + change ledger + request-identity event"
        ),
        verification_requirements=(
            "declared-hash precondition + output-hash + "
            "artifact-readable + custody manifest match"
        ),
        implemented=True,
    ),
    CapabilityClassificationEntry(
        capability_id="run_engineering_loop",
        operation="E2 bounded autonomous engineering loop (delegated objective)",
        **_CONTROLLED_ROW,
    ),
    CapabilityClassificationEntry(
        capability_id="run_engineering_mission",
        operation="E3 multi-step engineering mission (delegated task graph)",
        **_CONTROLLED_ROW,
    ),
    CapabilityClassificationEntry(
        capability_id="run_high_impact_commit",
        operation=(
            "E4 high-impact git commit: a REAL `git commit` executed by the "
            "real git binary inside the verified kernel-namespace sandbox, "
            "against a staged workspace repository, under a signed Owner "
            "approval, single-use lease, and frozen policy; verified by "
            "independent pure-Python reconstruction of the git object "
            "database; reversible via snapshot rollback"
        ),
        permission_class=PermissionClass.HIGH_IMPACT,
        classification=ImpactClassification.HIGH_IMPACT,
        scope=(
            "one staged repository copy under the execution workspace "
            "custody directory; the granted source root stays read-only"
        ),
        risk=(
            "high: creates lasting repository state (commit objects). "
            "Mitigations: Owner-signed single-use approval bound to the "
            "request digest, lease window, frozen policy, sandboxed "
            "execution, snapshot rollback, independent verification"
        ),
        required_authority=(
            "HIGH_IMPACT-class resource grant (owner-issued, APPROVED, "
            "live-validated) PLUS a signed Owner approval from a trusted "
            "approver (engineering.approval.ApprovalVerifier), PLUS the "
            "sandbox substrate with the local-git image"
        ),
        approval_requirement=ApprovalRequirement.OWNER_APPROVAL_REQUIRED,
        resource_limits=(
            "HighImpactLimits: max_files <= 64, max_total_bytes <= 1 MiB, "
            "timeout <= 60s wall clock, exactly 3 sandbox commands; D-13 "
            "ExecutionLimits apply to every sandbox run; requests may only "
            "lower ceilings"
        ),
        audit_requirements=(
            "HighImpactOutcome evidence: authorization trace (approval id, "
            "issuer, verifier decision), every sandbox command with exit "
            "code and bounded output digests, observed commit/tree SHA, "
            "verification checks, rollback attestation, resource usage"
        ),
        verification_requirements=(
            "independent host-side reconstruction of the git object "
            "database: ref -> commit -> tree -> blobs, SHA-1 verified "
            "against the staged manifest; rollback verified by fingerprint "
            "equality with the baseline; engine never self-verifies a "
            "failed reconstruction"
        ),
        implemented=True,
    ),
    CapabilityClassificationEntry(
        capability_id="git_push",
        operation="push repository state to a remote",
        **_FORBIDDEN_ROW,
    ),
    CapabilityClassificationEntry(
        capability_id="release",
        operation="cut a release of any artifact",
        **_FORBIDDEN_ROW,
    ),
    CapabilityClassificationEntry(
        capability_id="deployment",
        operation="deploy anything anywhere",
        **_FORBIDDEN_ROW,
    ),
    CapabilityClassificationEntry(
        capability_id="production_modification",
        operation="modify production state of any system",
        **_FORBIDDEN_ROW,
    ),
    CapabilityClassificationEntry(
        capability_id="external_communication",
        operation="communicate with any external system",
        **_FORBIDDEN_ROW,
    ),
)


# ---------------------------------------------------------------------------
# §3 — high-impact request specification (payload contract)
# ---------------------------------------------------------------------------


#: Hard ceilings for every high-impact execution. Requests may only
#: lower these values; raising any of them is a parse rejection.
HIGH_IMPACT_MAX_FILES_CEILING: int = 64
HIGH_IMPACT_MAX_TOTAL_BYTES_CEILING: int = 1024 * 1024  # 1 MiB
HIGH_IMPACT_TIMEOUT_SECONDS_CEILING: int = 60
HIGH_IMPACT_MESSAGE_MAX_CHARS: int = 200
HIGH_IMPACT_AUTHOR_NAME_MAX_CHARS: int = 64
HIGH_IMPACT_AUTHOR_EMAIL_MAX_CHARS: int = 128
HIGH_IMPACT_INCLUDE_PREFIX_MAX: int = 32

#: The one (and only) high-impact operation E4 implements.
HIGH_IMPACT_OPERATION_ID: str = "run_high_impact_commit"

#: The repository-relative paths the staging step always refuses to
#: include (the git metadata directory is CREATED by git inside the
#: sandbox, never staged from a source tree).
_STAGE_EXCLUDED_NAMES: frozenset[str] = frozenset({".git"})


class HighImpactRejection(str, Enum):
    """Machine-readable rejection reasons for high-impact payloads."""

    PAYLOAD_INVALID = "payload_invalid"
    PAYLOAD_NOT_MAPPING = "payload_not_mapping"
    TARGET_MISSING = "target_missing"
    TARGET_NOT_ABSOLUTE = "target_not_absolute"
    TARGET_NOT_DIRECTORY = "target_not_directory"
    MESSAGE_MISSING = "message_missing"
    MESSAGE_TOO_LONG = "message_too_long"
    MESSAGE_NOT_STRING = "message_not_string"
    AUTHOR_NAME_INVALID = "author_name_invalid"
    AUTHOR_EMAIL_INVALID = "author_email_invalid"
    INCLUDE_MISSING = "include_missing"
    INCLUDE_INVALID = "include_invalid"
    INCLUDE_ESCAPE = "include_escape"
    ROLLBACK_INVALID = "rollback_invalid"
    LIMITS_INVALID = "limits_invalid"
    LIMITS_EXCEED_CEILING = "limits_exceed_ceiling"
    LIMITS_BELOW_MINIMUM = "limits_below_minimum"


@dataclass(frozen=True)
class HighImpactLimits:
    """Resource and blast-radius budget of one high-impact execution.

    Structurally invalid values raise at construction (fail-closed);
    ceiling violations are rejected by the parser, never clamped.
    """

    max_files: int = HIGH_IMPACT_MAX_FILES_CEILING
    max_total_bytes: int = HIGH_IMPACT_MAX_TOTAL_BYTES_CEILING
    timeout_seconds: int = HIGH_IMPACT_TIMEOUT_SECONDS_CEILING

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_files, int)
            or isinstance(self.max_files, bool)
            or self.max_files < 1
        ):
            raise ValueError("max_files must be a positive integer")
        if (
            not isinstance(self.max_total_bytes, int)
            or isinstance(self.max_total_bytes, bool)
            or self.max_total_bytes < 1
        ):
            raise ValueError("max_total_bytes must be a positive integer")
        if (
            not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds < 1
        ):
            raise ValueError("timeout_seconds must be a positive integer")


@dataclass(frozen=True)
class HighImpactRequestSpec:
    """Parsed ``run_high_impact_commit`` payload (validated, frozen).

    ``target`` is the granted host repository root whose files are
    staged into the execution workspace. ``include`` holds
    repository-relative prefixes; only files under them are staged.
    ``rollback`` (default True) restores the staged repository to its
    pre-commit state after verification and proves reversibility.
    """

    target: str
    message: str
    author_name: str
    author_email: str
    include: tuple[str, ...]
    rollback: bool = True
    limits: HighImpactLimits = HighImpactLimits()


@dataclass(frozen=True)
class HighImpactParseResult:
    """Fail-closed parse outcome for a high-impact payload."""

    ok: bool
    spec: HighImpactRequestSpec | None = None
    reason: HighImpactRejection | None = None
    detail: str = ""


def _parse_limits(
    raw: object,
) -> tuple[HighImpactLimits | None, HighImpactRejection | None, str]:
    if raw is None:
        return HighImpactLimits(), None, ""
    if not isinstance(raw, dict):
        return None, HighImpactRejection.LIMITS_INVALID, (
            "'limits' must be a mapping or absent"
        )
    candidate: dict[str, int] = {}
    for key in ("max_files", "max_total_bytes", "timeout_seconds"):
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, int) or isinstance(value, bool):
            return None, HighImpactRejection.LIMITS_INVALID, (
                f"'limits.{key}' must be an integer"
            )
        if value < 1:
            return None, HighImpactRejection.LIMITS_BELOW_MINIMUM, (
                f"'limits.{key}' must be at least 1 (requests may only "
                "lower ceilings, never zero them)"
            )
        candidate[key] = value
    if candidate.get("max_files", 0) > HIGH_IMPACT_MAX_FILES_CEILING:
        return None, HighImpactRejection.LIMITS_EXCEED_CEILING, (
            f"'limits.max_files' exceeds the ceiling "
            f"{HIGH_IMPACT_MAX_FILES_CEILING}"
        )
    if candidate.get("max_total_bytes", 0) > HIGH_IMPACT_MAX_TOTAL_BYTES_CEILING:
        return None, HighImpactRejection.LIMITS_EXCEED_CEILING, (
            f"'limits.max_total_bytes' exceeds the ceiling "
            f"{HIGH_IMPACT_MAX_TOTAL_BYTES_CEILING}"
        )
    if candidate.get("timeout_seconds", 0) > HIGH_IMPACT_TIMEOUT_SECONDS_CEILING:
        return None, HighImpactRejection.LIMITS_EXCEED_CEILING, (
            f"'limits.timeout_seconds' exceeds the ceiling "
            f"{HIGH_IMPACT_TIMEOUT_SECONDS_CEILING}"
        )
    try:
        return HighImpactLimits(**candidate), None, ""  # type: ignore[arg-type]
    except ValueError as error:
        return None, HighImpactRejection.LIMITS_INVALID, str(error)


def parse_high_impact_payload(payload: object) -> HighImpactParseResult:
    """Parse and validate a ``run_high_impact_commit`` payload.

    Fail-closed: anything missing, mistyped, escaping, or exceeding a
    ceiling is rejected with a machine-readable reason. This function
    never raises and never clamps.
    """
    if not isinstance(payload, dict):
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.PAYLOAD_NOT_MAPPING,
            detail=f"expected a mapping, got {type(payload).__name__}",
        )

    target = payload.get("target")
    if not isinstance(target, str) or not target:
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.TARGET_MISSING,
            detail="'target' (granted repository root) is required",
        )
    if not target.startswith("/"):
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.TARGET_NOT_ABSOLUTE,
            detail="'target' must be an absolute path",
        )
    if not Path(target).is_dir():
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.TARGET_NOT_DIRECTORY,
            detail=f"'target' {target!r} is not an existing directory",
        )

    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.MESSAGE_MISSING,
            detail="'message' must be a non-empty string",
        )
    if any(ord(character) < 0x20 for character in message):
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.MESSAGE_MISSING,
            detail=(
                "'message' must be a single line without control characters "
                "(argv safety)"
            ),
        )
    if message.lstrip().startswith("-"):
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.MESSAGE_MISSING,
            detail="'message' must not start with a dash (argv safety)",
        )
    if len(message) > HIGH_IMPACT_MESSAGE_MAX_CHARS:
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.MESSAGE_TOO_LONG,
            detail=(
                f"'message' exceeds {HIGH_IMPACT_MESSAGE_MAX_CHARS} characters"
            ),
        )

    author_name = payload.get("author_name", "engineering-e4")
    if (
        not isinstance(author_name, str)
        or not author_name.strip()
        or any(ord(character) < 0x20 for character in author_name)
    ):
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.AUTHOR_NAME_INVALID,
            detail="'author_name' must be a non-empty string",
        )
    if len(author_name) > HIGH_IMPACT_AUTHOR_NAME_MAX_CHARS:
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.AUTHOR_NAME_INVALID,
            detail=(
                f"'author_name' exceeds {HIGH_IMPACT_AUTHOR_NAME_MAX_CHARS} "
                "characters"
            ),
        )
    author_email = payload.get("author_email", "engineering-e4@localhost")
    if (
        not isinstance(author_email, str)
        or not author_email.strip()
        or any(ord(character) < 0x20 for character in author_email)
    ):
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.AUTHOR_EMAIL_INVALID,
            detail="'author_email' must be a non-empty string",
        )
    if len(author_email) > HIGH_IMPACT_AUTHOR_EMAIL_MAX_CHARS:
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.AUTHOR_EMAIL_INVALID,
            detail=(
                f"'author_email' exceeds {HIGH_IMPACT_AUTHOR_EMAIL_MAX_CHARS} "
                "characters"
            ),
        )

    include = payload.get("include")
    if not isinstance(include, (list, tuple)) or not include:
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.INCLUDE_MISSING,
            detail="'include' must be a non-empty list of repository-relative prefixes",
        )
    if len(include) > HIGH_IMPACT_INCLUDE_PREFIX_MAX:
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.INCLUDE_INVALID,
            detail=f"'include' exceeds {HIGH_IMPACT_INCLUDE_PREFIX_MAX} prefixes",
        )
    normalized: list[str] = []
    for item in include:
        if not isinstance(item, str) or not item:
            return HighImpactParseResult(
                ok=False,
                reason=HighImpactRejection.INCLUDE_INVALID,
                detail="every include prefix must be a non-empty string",
            )
        if item.startswith("/") or ".." in item.split("/"):
            return HighImpactParseResult(
                ok=False,
                reason=HighImpactRejection.INCLUDE_ESCAPE,
                detail=(
                    "include prefixes must be repository-relative without "
                    f"escapes: {item!r}"
                ),
            )
        normalized.append(item.rstrip("/") + "/")

    rollback = payload.get("rollback", True)
    if not isinstance(rollback, bool):
        return HighImpactParseResult(
            ok=False,
            reason=HighImpactRejection.ROLLBACK_INVALID,
            detail="'rollback' must be a boolean",
        )

    limits, limits_reason, limits_detail = _parse_limits(payload.get("limits"))
    if limits is None or limits_reason is not None:
        return HighImpactParseResult(
            ok=False, reason=limits_reason, detail=limits_detail
        )

    return HighImpactParseResult(
        ok=True,
        spec=HighImpactRequestSpec(
            target=target,
            message=message,
            author_name=author_name,
            author_email=author_email,
            include=tuple(sorted(set(normalized))),
            rollback=rollback,
            limits=limits,
        ),
        detail="high-impact payload valid: target, message, author, "
        "include prefixes, rollback flag, limits within ceilings",
    )


# ---------------------------------------------------------------------------
# §3 — the frozen high-impact capability contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HighImpactContract:
    """The frozen §3 capability contract for ONE high-impact execution.

    Built by the engine from the admitted request AFTER approval
    verification and BEFORE any staging or sandbox command. Frozen:
    the executor can never mutate the authority, approval state,
    scope, policy, or risk classification of the operation it is
    executing. The lease window mirrors the verified approval (the
    engine copies the values; it cannot extend them).
    """

    operation_id: str
    operation: str
    risk_classification: ImpactClassification
    target: str
    scope_domains: tuple[str, ...]
    include_prefixes: tuple[str, ...]
    message: str
    author_name: str
    author_email: str
    rollback: bool
    limits: HighImpactLimits
    approval_required: bool
    approval_id: str
    approval_issued_by: str
    lease_not_before: float
    lease_not_after: float
    lease_single_use: bool
    request_digest: str
    sandbox_command_count: int

    #: Evidence requirements every high-impact execution must satisfy
    #: (class constants — not constructor parameters, not mutable).
    EVIDENCE_REQUIREMENTS: ClassVar[tuple[str, ...]] = (
        "authorization-trace: approval id, issuer, verifier decision",
        "execution-trace: every sandbox command with exit code and "
        "bounded output digests",
        "observation: commit SHA and tree SHA read back from the object db",
        "verification: independent reconstruction checks with pass flags",
        "rollback: snapshot fingerprint equality attestation",
        "resources: file count, byte total, wall-clock duration",
    )

    #: Verification requirements (independent of task results).
    VERIFICATION_REQUIREMENTS: ClassVar[tuple[str, ...]] = (
        "ref-present: refs/heads/main exists after the commit command",
        "commit-object-valid: zlib commit object parses with tree/author",
        "tree-parses: tree object decompresses into typed entries",
        "blob-manifest-match: every staged file's SHA-1 equals its blob id",
        "manifest-complete: no tree entry without a staged file and vice versa",
        "message-match: commit message equals the contract message",
        "author-match: commit author equals the contract author",
        "rollback-equality: restored manifest equals baseline fingerprint",
    )

    TERMINATION_SEMANTICS: ClassVar[str] = (
        "bounded single-pass sequence: validate -> authorize -> policy "
        "check -> stage -> 3 sandbox commands -> observe -> verify -> "
        "rollback -> attest; hard wall-clock deadline checked between "
        "phases; any failure fails closed with a machine-readable status; "
        "the engine never retries, never loops, and never re-executes a "
        "consumed approval"
    )


def high_impact_request_digest(
    *,
    operation_id: str,
    target: str,
    message: str,
    author_name: str,
    author_email: str,
    include: tuple[str, ...],
    rollback: bool,
    limits: HighImpactLimits,
) -> str:
    """Deterministic SHA-256 digest binding an approval to ONE request.

    The Owner approval authority computes this digest at issuance
    time; the engine recomputes it at verification time from the
    payload it actually received. A mutated request (any field)
    yields a different digest and the approval is rejected — replay
    against a different payload is impossible.
    """
    canonical = "|".join(
        (
            operation_id,
            target,
            message,
            author_name,
            author_email,
            ",".join(sorted(set(include))),
            "rollback=1" if rollback else "rollback=0",
            f"max_files={limits.max_files}",
            f"max_total_bytes={limits.max_total_bytes}",
            f"timeout_seconds={limits.timeout_seconds}",
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


#: Sandbox execution limits for high-impact git commands. Derived
#: from the D-13 defaults; the D-13 policy allows only lowering, and
#: the high-impact ceilings are stricter than D-13 where relevant.
def high_impact_sandbox_limits(spec_limits: HighImpactLimits) -> ExecutionLimits:
    """The D-13 sandbox limits for git commands under a spec budget.

    The wall-clock timeout of every sandbox command is bounded by the
    request's own timeout budget (never above the D-13 default).
    """
    timeout = min(
        spec_limits.timeout_seconds, E1_LIMITS_DEFAULTS.timeout_seconds
    )
    return ExecutionLimits(
        timeout_seconds=max(1, timeout),
        vcpu=E1_LIMITS_DEFAULTS.vcpu,
        memory_bytes=E1_LIMITS_DEFAULTS.memory_bytes,
        max_processes=E1_LIMITS_DEFAULTS.max_processes,
        max_output_bytes=E1_LIMITS_DEFAULTS.max_output_bytes,
        max_artifact_bytes=E1_LIMITS_DEFAULTS.max_artifact_bytes,
        max_workspace_bytes=E1_LIMITS_DEFAULTS.max_workspace_bytes,
    )


#: Domains the high-impact operation requires in the request scope.
HIGH_IMPACT_REQUIRED_DOMAINS: frozenset[EngineeringDomain] = frozenset(
    {EngineeringDomain.SOFTWARE_ENGINEERING}
)


def stage_excluded_names() -> frozenset[str]:
    """Repository-relative names the staging step always refuses."""
    return _STAGE_EXCLUDED_NAMES


def classification_entry(
    capability_id: str,
) -> CapabilityClassificationEntry | None:
    """Look up one classification matrix row (fail-closed: None)."""
    for entry in CAPABILITY_CLASSIFICATION:
        if entry.capability_id == capability_id:
            return entry
    return None


def implemented_high_impact_operations() -> tuple[str, ...]:
    """The high-impact operations E4 actually implements: exactly one."""
    return (
        HIGH_IMPACT_OPERATION_ID,
    )
