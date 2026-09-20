"""E1 resource grants — owner decision D-06 (A: signed typed grants).

Authority model (fail-closed, from the Capability Gap Discovery §8):

- Grants are issued by a **grantor** (the system owner or a
  PRIME-delegated resolver). Engineering **validates** grants — it
  never issues, signs, or self-grants them. No signing code exists
  anywhere in this package; only verification code does, and the
  verification key is always supplied by the caller at runtime.
  Nothing in this repository stores a key.
- A grant is a typed, expirable, revocable, scope-bounded
  authorization for ONE permission class over declared domains and
  explicit resource references, issued to ONE subject.
- Grant validity is checked at **admission time** AND re-checked at
  **execution time** (live expiry + revocation). Revocation is a
  contract with the grantor side: a registered revocation channel
  answers "is this grant revoked?" — without a channel, grants are
  rejected (fail-closed), never assumed valid.
- Signatures: a grant carries a hex signature over its canonical
  payload. Verification goes through a registered
  :class:`GrantVerifier`. No verifier registered → every grant is
  rejected. The provided :class:`HMACGrantVerifier` performs an
  HMAC-SHA256 comparison using a caller-supplied key; an
  :class:`AlwaysFailGrantVerifier` is available for closed
  installations that want an explicit, auditable deny-all posture.

Rejection is always machine-readable; ``validate_grant`` never raises.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any

from contracts.contract import PermissionClass
from contracts.domain import EngineeringDomain

#: Resource reference kinds known to the E1 contract.
RESOURCE_KINDS: frozenset[str] = frozenset({"filesystem_root", "repository_root"})


class GrantApprovalState(str, Enum):
    """Approval state of a grant (write/execution classes need APPROVED)."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


@dataclass(frozen=True)
class ResourceReference:
    """A concrete resource covered by a grant.

    ``kind`` is one of :data:`RESOURCE_KINDS`; ``path`` is an absolute,
    normalized filesystem path owned by the resource's owner. Access
    is only ever resolved *within* the granted reference (path policy).
    """

    kind: str
    path: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in RESOURCE_KINDS:
            raise ValueError(f"unknown resource kind: {self.kind!r}")
        if not isinstance(self.path, str) or not self.path.startswith("/"):
            raise ValueError(f"resource path must be absolute: {self.path!r}")


@dataclass(frozen=True)
class ResourceGrant:
    """A typed authorization issued by a grantor to a subject.

    Field semantics:

    - ``grant_id`` — non-empty unique identifier chosen by the grantor;
    - ``grantor`` — identity of the issuing authority (must be a
      registered trusted grantor on the validating side);
    - ``subject`` — the identity the grant is issued to; it must match
      the request's authorization subject;
    - ``permission_class`` — exactly one E0 permission class;
    - ``domains`` — the declared engineering domains the grant covers;
    - ``resources`` — the concrete resource references covered;
    - ``issued_at`` / ``expires_at`` — epoch seconds; a grant is valid
      only for ``issued_at <= now < expires_at``;
    - ``approval_state`` — only ``APPROVED`` grants pass validation;
    - ``revocable`` — marks grants that participate in the live
      revocation contract (still checked either way);
    - ``signature`` — hex HMAC-SHA256 over :func:`canonical_grant_payload`
      produced by the GRANTOR side; verified here, never produced here.
    """

    grant_id: str
    grantor: str
    subject: str
    permission_class: PermissionClass
    domains: tuple[EngineeringDomain, ...]
    resources: tuple[ResourceReference, ...]
    issued_at: float
    expires_at: float
    approval_state: GrantApprovalState
    revocable: bool = True
    signature: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.grant_id, str) or not self.grant_id:
            raise ValueError("grant_id must be a non-empty string")
        if not isinstance(self.grantor, str) or not self.grantor:
            raise ValueError("grantor must be a non-empty string")
        if not isinstance(self.subject, str) or not self.subject:
            raise ValueError("subject must be a non-empty string")
        if not isinstance(self.permission_class, PermissionClass):
            raise ValueError("permission_class must be a PermissionClass")
        if (
            not isinstance(self.domains, tuple)
            or not self.domains
            or not all(isinstance(domain, EngineeringDomain) for domain in self.domains)
        ):
            raise ValueError("domains must be a non-empty tuple of EngineeringDomain")
        if (
            not isinstance(self.resources, tuple)
            or not self.resources
            or not all(isinstance(resource, ResourceReference) for resource in self.resources)
        ):
            raise ValueError("resources must be a non-empty tuple of ResourceReference")
        if not isinstance(self.issued_at, (int, float)) or isinstance(self.issued_at, bool):
            raise ValueError("issued_at must be numeric")
        if not isinstance(self.expires_at, (int, float)) or isinstance(self.expires_at, bool):
            raise ValueError("expires_at must be numeric")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if not isinstance(self.approval_state, GrantApprovalState):
            raise ValueError("approval_state must be a GrantApprovalState")
        if not isinstance(self.signature, str):
            raise ValueError("signature must be a string")


_GRANT_SIGNATURE_FIELDS = ("signature",)


def canonical_grant_payload(grant: ResourceGrant) -> bytes:
    """Canonical byte serialization of a grant, excluding the signature.

    Deterministic: dataclass field order, JSON with sorted keys and
    compact separators. The grantor side signs exactly these bytes;
    the verifier recomputes them from the received grant. Any field
    tampering therefore changes the payload and invalidates the
    signature.
    """
    payload: dict[str, Any] = {}
    for field in fields(ResourceGrant):
        if field.name in _GRANT_SIGNATURE_FIELDS:
            continue
        value = getattr(grant, field.name)
        if field.name == "permission_class":
            value = value.value
        elif field.name == "approval_state":
            value = value.value
        elif field.name == "domains":
            value = [domain.value for domain in value]
        elif field.name == "resources":
            value = [{"kind": resource.kind, "path": resource.path} for resource in value]
        payload[field.name] = value
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


class GrantVerifier(ABC):
    """Caller-side signature verification contract for grants.

    The caller (PRIME or the system owner) registers a verifier with
    the shared verification material it controls. Engineering invokes
    ``verify``; it never sees, stores, or derives the key.
    """

    @abstractmethod
    def verify(self, grant: ResourceGrant) -> bool:
        """Return True only when the grant's signature is valid."""


class HMACGrantVerifier(GrantVerifier):
    """HMAC-SHA256 verifier with a caller-supplied key.

    The key enters through the constructor at RUNTIME from caller
    memory and is never persisted by this package. This class only
    *verifies*; the signing side lives with the grantor.
    """

    def __init__(self, key: bytes) -> None:
        if not isinstance(key, bytes) or not key:
            raise ValueError("verification key must be non-empty bytes")
        self._key = key

    def verify(self, grant: ResourceGrant) -> bool:
        if not isinstance(grant, ResourceGrant) or not grant.signature:
            return False
        expected = hmac.new(self._key, canonical_grant_payload(grant), hashlib.sha256)
        return hmac.compare_digest(expected.hexdigest(), grant.signature)


class AlwaysFailGrantVerifier(GrantVerifier):
    """A verifier that rejects every grant (closed installations)."""

    def verify(self, grant: ResourceGrant) -> bool:  # noqa: ARG002
        return False


class RevocationChannel(ABC):
    """Live revocation contract with the grantor side (D-06 = A).

    The channel answers "has this grant been revoked?" at validation
    time. Implementations belong to the caller/grantor side. No
    registered channel → grants are rejected (fail-closed).
    """

    @abstractmethod
    def is_revoked(self, grant_id: str) -> bool:
        """Return True when ``grant_id`` has been revoked."""


class GrantLedger:
    """Caller-side store of issued grants.

    The ledger is owned by the caller (PRIME / owner tooling) — it is
    the bag of grants the caller presents to Engineering for
    validation. Engineering holds no issuance power: this class can
    only register grants that ALREADY exist (signed by the grantor)
    and look them up. It cannot create, sign, or modify one.
    """

    def __init__(self) -> None:
        self._grants: dict[str, ResourceGrant] = {}

    def register(self, grant: ResourceGrant) -> None:
        if not isinstance(grant, ResourceGrant):
            raise TypeError("ledger entries must be ResourceGrant instances")
        if grant.grant_id in self._grants:
            raise ValueError(f"duplicate grant_id: {grant.grant_id!r}")
        self._grants[grant.grant_id] = grant

    def lookup(self, grant_id: str) -> ResourceGrant | None:
        return self._grants.get(grant_id)

    def all(self) -> tuple[ResourceGrant, ...]:
        return tuple(self._grants.values())

    def __len__(self) -> int:
        return len(self._grants)


class GrantRejectionReason(str, Enum):
    """Machine-readable grant rejection reasons (fail-closed codes)."""

    STRUCTURALLY_INVALID = "grant_structurally_invalid"
    UNKNOWN_GRANTOR = "grant_unknown_grantor"
    APPROVAL_PENDING = "grant_approval_pending"
    APPROVAL_DENIED = "grant_approval_denied"
    NOT_YET_VALID = "grant_not_yet_valid"
    EXPIRED = "grant_expired"
    REVOKED = "grant_revoked"
    NO_REVOCATION_CHANNEL = "grant_no_revocation_channel"
    NO_VERIFIER = "grant_no_verifier"
    INVALID_SIGNATURE = "grant_invalid_signature"
    EVALUATION_ERROR = "grant_evaluation_error"


@dataclass(frozen=True)
class GrantValidation:
    """Outcome of a full grant validation (never an exception)."""

    valid: bool
    reason: GrantRejectionReason | None = None
    detail: str = ""

    @property
    def accepted(self) -> bool:
        return self.valid


def _invalid(reason: GrantRejectionReason, detail: str) -> GrantValidation:
    return GrantValidation(valid=False, reason=reason, detail=detail)


def validate_grant(
    grant: object,
    *,
    trusted_grantors: frozenset[str] | set[str] | None,
    revocation: RevocationChannel | None,
    verifier: GrantVerifier | None,
    now: float | None = None,
) -> GrantValidation:
    """Validate one grant fail-closed; never raises.

    Check order (each failure short-circuits with its reason):

    1. structural validity (typed fields, sane timestamps);
    2. grantor is registered as trusted (``trusted_grantors``);
    3. approval state is ``APPROVED``;
    4. time window: ``issued_at <= now < expires_at``;
    5. live revocation check through the registered channel
       (no channel → reject);
    6. signature verification through the registered verifier
       (no verifier → reject).
    """
    try:
        return _validate_grant(
            grant,
            trusted_grantors=trusted_grantors,
            revocation=revocation,
            verifier=verifier,
            now=time.time() if now is None else now,
        )
    except Exception:  # fail closed on any unexpected error
        return _invalid(
            GrantRejectionReason.EVALUATION_ERROR,
            "unexpected error during grant evaluation",
        )


def _validate_grant(
    grant: object,
    *,
    trusted_grantors: frozenset[str] | set[str] | None,
    revocation: RevocationChannel | None,
    verifier: GrantVerifier | None,
    now: float,
) -> GrantValidation:
    if not isinstance(grant, ResourceGrant):
        return _invalid(
            GrantRejectionReason.STRUCTURALLY_INVALID,
            f"expected ResourceGrant, got {type(grant).__name__}",
        )
    try:
        grant.__post_init__()
    except ValueError as error:
        return _invalid(GrantRejectionReason.STRUCTURALLY_INVALID, str(error))

    if trusted_grantors is None or grant.grantor not in trusted_grantors:
        return _invalid(
            GrantRejectionReason.UNKNOWN_GRANTOR,
            f"grantor not registered as trusted: {grant.grantor!r}",
        )

    if grant.approval_state is GrantApprovalState.PENDING:
        return _invalid(
            GrantRejectionReason.APPROVAL_PENDING,
            "grant awaits grantor approval",
        )
    if grant.approval_state is GrantApprovalState.DENIED:
        return _invalid(
            GrantRejectionReason.APPROVAL_DENIED,
            "grantor explicitly denied this grant",
        )

    if now < grant.issued_at:
        return _invalid(
            GrantRejectionReason.NOT_YET_VALID,
            f"grant becomes valid at {grant.issued_at}; now={now}",
        )
    if now >= grant.expires_at:
        return _invalid(
            GrantRejectionReason.EXPIRED,
            f"grant expired at {grant.expires_at}; now={now}",
        )

    if revocation is None:
        return _invalid(
            GrantRejectionReason.NO_REVOCATION_CHANNEL,
            "no live revocation channel registered (D-06=A: live check mandatory)",
        )
    try:
        if revocation.is_revoked(grant.grant_id):
            return _invalid(
                GrantRejectionReason.REVOKED,
                f"grant {grant.grant_id!r} was revoked by the grantor",
            )
    except Exception:
        return _invalid(
            GrantRejectionReason.EVALUATION_ERROR,
            "revocation channel failed; assuming revoked (fail-closed)",
        )

    if verifier is None:
        return _invalid(
            GrantRejectionReason.NO_VERIFIER,
            "no grant verifier registered (D-06=A: signed grants mandatory)",
        )
    try:
        if not verifier.verify(grant):
            return _invalid(
                GrantRejectionReason.INVALID_SIGNATURE,
                "grant signature failed verification",
            )
    except Exception:
        return _invalid(
            GrantRejectionReason.EVALUATION_ERROR,
            "verifier raised during verification (fail-closed)",
        )

    return GrantValidation(
        valid=True,
        detail=(
            "grant valid: trusted grantor, approved, within validity "
            "window, not revoked, signature verified"
        ),
    )


class ScopeMismatchReason(str, Enum):
    """Reasons a grant does not cover a request's scope."""

    SUBJECT_MISMATCH = "grant_subject_mismatch"
    PERMISSION_CLASS_MISMATCH = "grant_permission_class_mismatch"
    DOMAIN_NOT_COVERED = "grant_domain_not_covered"
    RESOURCE_NOT_COVERED = "grant_resource_not_covered"


@dataclass(frozen=True)
class ScopeCoverage:
    """Outcome of checking grant coverage over a request's scope."""

    covered: bool
    reason: ScopeMismatchReason | None = None
    detail: str = ""

    @property
    def covered_scope(self) -> bool:
        return self.covered


def check_scope_coverage(
    grant: ResourceGrant,
    *,
    subject: str,
    permission_class: PermissionClass,
    domains: tuple[EngineeringDomain, ...],
    target_paths: tuple[str, ...] = (),
) -> ScopeCoverage:
    """Check that ``grant`` covers the request's subject, class, and scope.

    ``target_paths`` (optional, absolute paths requested by the
    operations) must each fall under one of the grant's resource
    references. Path containment here is a prefix check on normalized
    absolute paths; the executor's path policy re-checks it with full
    symlink resolution at read time (defense in depth).
    """
    if not isinstance(grant, ResourceGrant):
        return ScopeCoverage(
            covered=False,
            reason=ScopeMismatchReason.SUBJECT_MISMATCH,
            detail="grant is not a ResourceGrant",
        )
    if subject != grant.subject:
        return ScopeCoverage(
            covered=False,
            reason=ScopeMismatchReason.SUBJECT_MISMATCH,
            detail=f"grant issued to {grant.subject!r}, request subject {subject!r}",
        )
    if permission_class is not grant.permission_class:
        return ScopeCoverage(
            covered=False,
            reason=ScopeMismatchReason.PERMISSION_CLASS_MISMATCH,
            detail=(
                f"grant covers {grant.permission_class.value}, request "
                f"needs {permission_class.value}"
            ),
        )
    granted_domains = frozenset(grant.domains)
    for domain in domains:
        if domain not in granted_domains:
            return ScopeCoverage(
                covered=False,
                reason=ScopeMismatchReason.DOMAIN_NOT_COVERED,
                detail=f"domain {domain.value} not covered by the grant",
            )
    for target in target_paths:
        if not _path_covered(target, grant.resources):
            return ScopeCoverage(
                covered=False,
                reason=ScopeMismatchReason.RESOURCE_NOT_COVERED,
                detail=f"target {target!r} not under any granted resource",
            )
    return ScopeCoverage(covered=True, detail="grant covers subject, class, domains, and targets")


def _path_covered(target: str, resources: tuple[ResourceReference, ...]) -> bool:
    if not isinstance(target, str) or not target.startswith("/"):
        return False
    normalized = _normalize(target)
    for resource in resources:
        root = _normalize(resource.path)
        if normalized == root or normalized.startswith(root + "/"):
            return True
    return False


def _normalize(path: str) -> str:
    parts: list[str] = []
    for segment in path.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts:
                parts.pop()
            else:
                return ""  # escapes the filesystem root — never covered
        else:
            parts.append(segment)
    return "/" + "/".join(parts)
