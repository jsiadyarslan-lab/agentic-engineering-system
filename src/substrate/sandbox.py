"""E1 sandbox contract and substrate port — owner decision D-01 (A).

The E1 isolation architecture is a **port**: this module defines the
sandbox request contract, the execution record contract, and the
abstract :class:`SubstrateAdapter` interface that a real isolation
substrate must implement. The owner decision D-01 = A fixes the
substrate class to **container-based isolation**; D-04 = A fixes the
network posture to **NONE**; D-13 fixes the limit ceiling.

Substrate status (E1, superseded gate): the local kernel substrate
of this execution environment — user/mount/pid/uts/network
namespaces, pivot_root, read-only binds, capability drop, seccomp,
and rlimits — was proven experimentally (LOCAL-D01-A-SUPPORTED:
21/21 capability probes, 23/23 real-sandbox-lifecycle proofs) and
accepted by the owner as the E1 execution substrate. The production
adapter is :class:`substrate.local_substrate.LocalSubstrateAdapter`
(registered by the caller; see
:func:`substrate.local_substrate.local_sandbox_manager`). A
provisioned remote container substrate would satisfy the same port.

Fail-closed rules enforced here (none may be weakened):

- **No substrate, no execution.** :class:`SandboxManager` holds at
  most one registered adapter. With no adapter registered, every
  execution request returns a BLOCKED outcome naming the exact
  missing dependency — it NEVER falls back to running code on the
  host. Process-creating machinery exists ONLY inside the substrate
  adapter module; every other module in this package is typed
  contracts (structurally enforced by tests).
- **Single execute per sandbox id.** A sandbox executes exactly one
  command; a second execute with the same id is rejected.
- **Network is NONE.** The only permitted network mode is
  ``NetworkMode.NONE``; anything else is rejected (D-04 = A:
  enforcement, not documentation).
- **Images come from a caller-registered allowlist.** No allowlist
  entry, no execution.
- **Environment variables come from a minimal allowlist.**
  Requests may only shrink the permitted set; unknown names are
  rejected. Values are supplied by the substrate, never by callers.
- **Limits may only be lowered** from the D-13 defaults
  (:mod:`substrate.limits`).
- **Exit codes are EXECUTED-state evidence, never verdicts.**
  :class:`SandboxExecutionRecord` records the exit code; the
  verification layer decides what it means (D-08 split).
- **Teardown always.** The manager attempts teardown after every
  execute, including failures, and records the teardown evidence.

ACCEPTANCE GATE STATUS (honest state of this repository): the local
substrate adapter is implemented and its sandboxed execution is
proven by the integration test suite (real sandboxes, real targets,
no mocks in the acceptance evidence). The gate OPENS when the caller
registers the adapter; with no adapter registered the gate stays
BLOCKED — by design, fail-closed, with no host-execution fallback.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from substrate.limits import (
    ExecutionLimits,
    LimitsRejectionReason,
    LimitsValidation,
    validate_against_defaults,
)
from substrate.workspace import ArtifactCustodyEntry


class NetworkMode(str, Enum):
    """Sandbox network posture. E1 admits exactly one mode: NONE."""

    NONE = "NONE"


#: Minimal environment variable names permitted inside a sandbox
#: (from the Capability Gap Discovery §7 — the request may only
#: shrink this set, never extend it).
PERMITTED_ENV_NAMES: frozenset[str] = frozenset(
    {"PATH", "HOME", "PYTHONDONTWRITEBYTECODE"}
)

#: The exact dependency behind the BLOCKED gate when no substrate
#: adapter is registered (fail-closed; never a host fallback).
MISSING_SUBSTRATE_DEPENDENCY: str = (
    "no isolation substrate adapter is registered with the sandbox "
    "manager. The verified LOCAL substrate (D-01=A container-class "
    "isolation via kernel namespaces — substrate.local_substrate."
    "LocalSubstrateAdapter) is implemented and proven in this "
    "repository; a provisioned remote container substrate would also "
    "satisfy the port. Until an adapter is registered, sandboxed "
    "execution is BLOCKED: host execution fallback is forbidden and "
    "does not exist (fail-closed)."
)

#: The gate identifier used in reports and diagnostics. With the
#: local substrate implemented, the gate opens on adapter
#: registration; the BLOCKED state remains the registered-adapter-less
#: default.
SANDBOX_GATE_ID = "E1_SANDBOX_EXECUTION_ACCEPTANCE_GATE"


class SandboxRejectionReason(str, Enum):
    """Machine-readable reasons a sandbox request is rejected/blocked."""

    #: No substrate adapter registered — the BLOCKED gate.
    SUBSTRATE_UNAVAILABLE = "sandbox_substrate_unavailable"
    #: Image not on the caller-registered allowlist.
    IMAGE_NOT_ALLOWED = "sandbox_image_not_allowed"
    #: Requested limits exceed the D-13 defaults.
    LIMITS_EXCEED_DEFAULTS = "sandbox_limits_exceed_defaults"
    #: Limits object structurally invalid.
    LIMITS_INVALID = "sandbox_limits_invalid"
    #: Any network mode other than NONE.
    NETWORK_NOT_PERMITTED = "sandbox_network_not_permitted"
    #: Environment variable outside the permitted set.
    ENV_NOT_PERMITTED = "sandbox_env_not_permitted"
    #: Structurally invalid request (fields, types, emptiness).
    INVALID_REQUEST = "sandbox_invalid_request"
    #: The sandbox id was already executed (single-execute rule).
    ALREADY_EXECUTED = "sandbox_already_executed"
    #: The registered adapter rejected the request (adapter-side
    #: contract enforcement).
    SUBSTRATE_REJECTED = "sandbox_substrate_rejected"
    #: The adapter failed while executing (fail-closed failure).
    SUBSTRATE_FAILED = "sandbox_substrate_failed"


class SandboxTermination(str, Enum):
    """How a sandbox execution ended (termination, not verdict)."""

    COMPLETED = "COMPLETED"
    TIMEOUT = "TIMEOUT"
    LIMIT_BREACH = "LIMIT_BREACH"
    KILLED = "KILLED"
    FAILED_TO_START = "FAILED_TO_START"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class SandboxRequest:
    """A request to execute one command inside the isolation substrate.

    ``command`` is the full argv (non-empty). ``limits`` must satisfy
    :func:`substrate.limits.validate_against_defaults`. ``env_names``
    must be a subset of :data:`PERMITTED_ENV_NAMES` — values are
    supplied by the substrate, never by this package.
    ``workspace_root`` and ``artifacts_dir`` reference the per-request
    workspace the substrate should use: the workspace stays the
    artifact custody boundary — the substrate binds the custody
    directory as the ONLY artifact exit path. ``sources_root``, when
    non-empty, is the granted host repository root the substrate
    mounts READ-ONLY as the in-sandbox working tree.
    """

    sandbox_id: str
    image: str
    command: tuple[str, ...]
    limits: ExecutionLimits
    env_names: frozenset[str] = frozenset()
    network: NetworkMode = NetworkMode.NONE
    workspace_root: str = ""
    artifacts_dir: str = ""
    sources_root: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.sandbox_id, str) or not self.sandbox_id:
            raise ValueError("sandbox_id must be a non-empty string")
        if not isinstance(self.image, str) or not self.image:
            raise ValueError("image must be a non-empty string")
        if (
            not isinstance(self.command, tuple)
            or not self.command
            or not all(isinstance(part, str) and part for part in self.command)
        ):
            raise ValueError("command must be a non-empty tuple of non-empty strings")
        if not isinstance(self.limits, ExecutionLimits):
            raise ValueError("limits must be ExecutionLimits")
        if self.network is not NetworkMode.NONE:
            raise ValueError("E1 sandbox network mode must be NONE (D-04=A)")
        if not isinstance(self.sources_root, str):
            raise ValueError("sources_root must be a string")


@dataclass(frozen=True)
class SandboxExecutionRecord:
    """Evidence-shaped record of one sandbox execution.

    ``exit_code`` is recorded as EXECUTED-state evidence ONLY — it is
    never interpreted as success or verification (D-08). Output
    references point at bounded, persisted evidence artifacts; the
    bytes themselves are never embedded here.
    """

    sandbox_id: str
    executed: bool
    exit_code: int | None
    termination: SandboxTermination
    duration_ms: int
    stdout_reference: str = ""
    stderr_reference: str = ""
    limits_applied: ExecutionLimits | None = None
    artifacts: tuple[ArtifactCustodyEntry, ...] = ()
    started_at: float = 0.0
    finished_at: float = 0.0


@dataclass(frozen=True)
class TeardownEvidence:
    """Attestation that a sandbox was torn down (always attempted)."""

    sandbox_id: str
    torn_down: bool
    detail: str = ""


@dataclass(frozen=True)
class SubstrateDescriptor:
    """Identity card of a registered substrate adapter."""

    name: str
    isolation_class: str = "container"
    network_support: str = "none"


class SubstrateAdapter(ABC):
    """The port a real container substrate must implement (D-01=A).

    Contract obligations for any implementation:

    - enforce the request's limits server-side (wall-clock kill,
      resource ceilings) — the manager validates the POLICY, the
      substrate enforces the MECHANISM;
    - execute at most once per sandbox id;
    - bound stdout/stderr to the D-13 output ceiling and persist them
      as referenceable artifacts;
    - hand artifacts out only through hash-manifested custody entries;
    - tear down on completion, failure, or kill — always;
    - fail closed: on any internal error, return a record with
      ``termination=FAILED_TO_START`` / ``KILLED`` and a truthful
      reason — never a fabricated success.
    """

    @abstractmethod
    def descriptor(self) -> SubstrateDescriptor: ...

    @abstractmethod
    def execute(self, request: SandboxRequest) -> SandboxExecutionRecord: ...

    @abstractmethod
    def teardown(self, sandbox_id: str) -> TeardownEvidence: ...


class SandboxOutcomeKind(str, Enum):
    """Coarse outcome of :meth:`SandboxManager.execute`."""

    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class SandboxOutcome:
    """Result of a sandbox manager execute call (never an exception)."""

    outcome: SandboxOutcomeKind
    reason: SandboxRejectionReason | None = None
    detail: str = ""
    record: SandboxExecutionRecord | None = None
    teardown: TeardownEvidence | None = None

    @property
    def blocked(self) -> bool:
        return self.outcome is SandboxOutcomeKind.BLOCKED


class SandboxManager:
    """Owns the substrate port and the request-side contract.

    The manager is the only path to sandboxed execution. With no
    adapter registered it cannot execute anything — that is the
    BLOCKED acceptance gate, and it stays BLOCKED (fail-closed) until
    the caller registers a substrate adapter (the verified local
    substrate or a provisioned remote one). There is no host-execution
    fallback, and process-creating machinery is structurally confined
    to the substrate adapter module.
    """

    def __init__(
        self,
        *,
        substrate: SubstrateAdapter | None = None,
        image_allowlist: frozenset[str] | None = None,
        permitted_env_names: frozenset[str] = PERMITTED_ENV_NAMES,
    ) -> None:
        self._substrate = substrate
        self._image_allowlist = (
            image_allowlist if image_allowlist is not None else frozenset()
        )
        self._permitted_env = frozenset(permitted_env_names)
        self._executed_ids: set[str] = set()

    # -- caller-side wiring --------------------------------------------------

    @property
    def substrate_registered(self) -> bool:
        return self._substrate is not None

    @property
    def substrate(self) -> SubstrateAdapter | None:
        """Read-only view of the registered adapter (None if absent)."""
        return self._substrate

    def register_substrate(self, substrate: SubstrateAdapter) -> None:
        """Register the (single) substrate adapter — caller action."""
        if not isinstance(substrate, SubstrateAdapter):
            raise TypeError("substrate must implement SubstrateAdapter")
        if self._substrate is not None:
            raise RuntimeError("a substrate adapter is already registered")
        self._substrate = substrate

    def allow_images(self, images: frozenset[str] | set[str]) -> None:
        """Extend the image allowlist — caller action."""
        self._image_allowlist = self._image_allowlist | frozenset(images)

    @property
    def image_allowlist(self) -> frozenset[str]:
        return self._image_allowlist

    @property
    def executed_sandbox_ids(self) -> frozenset[str]:
        return frozenset(self._executed_ids)

    # -- execution ------------------------------------------------------------

    def execute(self, request: object) -> SandboxOutcome:
        """Execute one sandbox request — fail-closed, never raises."""
        try:
            return self._execute(request)
        except Exception as error:  # fail closed on any unexpected error
            return SandboxOutcome(
                outcome=SandboxOutcomeKind.FAILED,
                reason=SandboxRejectionReason.SUBSTRATE_FAILED,
                detail=f"sandbox manager internal error: {error}",
            )

    def _execute(self, request: object) -> SandboxOutcome:
        if self._substrate is None:
            return SandboxOutcome(
                outcome=SandboxOutcomeKind.BLOCKED,
                reason=SandboxRejectionReason.SUBSTRATE_UNAVAILABLE,
                detail=(
                    f"{SANDBOX_GATE_ID}: {MISSING_SUBSTRATE_DEPENDENCY}"
                ),
            )

        if not isinstance(request, SandboxRequest):
            return SandboxOutcome(
                outcome=SandboxOutcomeKind.REJECTED,
                reason=SandboxRejectionReason.INVALID_REQUEST,
                detail=f"expected SandboxRequest, got {type(request).__name__}",
            )
        try:
            request.__post_init__()
        except ValueError as error:
            return SandboxOutcome(
                outcome=SandboxOutcomeKind.REJECTED,
                reason=SandboxRejectionReason.INVALID_REQUEST,
                detail=str(error),
            )

        if request.network is not NetworkMode.NONE:
            return SandboxOutcome(
                outcome=SandboxOutcomeKind.REJECTED,
                reason=SandboxRejectionReason.NETWORK_NOT_PERMITTED,
                detail="E1 network posture is DENY (D-04=A); only NONE is admitted",
            )

        if request.image not in self._image_allowlist:
            return SandboxOutcome(
                outcome=SandboxOutcomeKind.REJECTED,
                reason=SandboxRejectionReason.IMAGE_NOT_ALLOWED,
                detail=(
                    f"image {request.image!r} is not on the registered allowlist"
                ),
            )

        limits_check: LimitsValidation = validate_against_defaults(request.limits)
        if not limits_check.valid:
            reason = (
                SandboxRejectionReason.LIMITS_EXCEED_DEFAULTS
                if limits_check.reason is LimitsRejectionReason.EXCEEDS_DEFAULTS
                else SandboxRejectionReason.LIMITS_INVALID
            )
            return SandboxOutcome(
                outcome=SandboxOutcomeKind.REJECTED,
                reason=reason,
                detail=limits_check.detail,
            )

        unknown_env = sorted(request.env_names - self._permitted_env)
        if unknown_env:
            return SandboxOutcome(
                outcome=SandboxOutcomeKind.REJECTED,
                reason=SandboxRejectionReason.ENV_NOT_PERMITTED,
                detail=f"environment names outside the permitted set: {unknown_env}",
            )

        if request.sandbox_id in self._executed_ids:
            return SandboxOutcome(
                outcome=SandboxOutcomeKind.REJECTED,
                reason=SandboxRejectionReason.ALREADY_EXECUTED,
                detail=(
                    f"sandbox {request.sandbox_id!r} already executed "
                    "(single-execute-per-id rule)"
                ),
            )

        self._executed_ids.add(request.sandbox_id)
        started = time.time()
        try:
            record = self._substrate.execute(request)
        except Exception as error:
            teardown = self._safe_teardown(request.sandbox_id)
            return SandboxOutcome(
                outcome=SandboxOutcomeKind.FAILED,
                reason=SandboxRejectionReason.SUBSTRATE_FAILED,
                detail=f"adapter raised during execution: {error}",
                teardown=teardown,
            )
        if not isinstance(record, SandboxExecutionRecord):
            teardown = self._safe_teardown(request.sandbox_id)
            return SandboxOutcome(
                outcome=SandboxOutcomeKind.FAILED,
                reason=SandboxRejectionReason.SUBSTRATE_FAILED,
                detail=(
                    "adapter returned a non-record object "
                    f"({type(record).__name__}); fail-closed"
                ),
                teardown=teardown,
            )
        teardown = self._safe_teardown(request.sandbox_id)
        duration_ms = int(max(0.0, (time.time() - started) * 1000))
        normalized = SandboxExecutionRecord(
            sandbox_id=record.sandbox_id,
            executed=record.executed,
            exit_code=record.exit_code,
            termination=record.termination,
            duration_ms=duration_ms or record.duration_ms,
            stdout_reference=record.stdout_reference,
            stderr_reference=record.stderr_reference,
            limits_applied=record.limits_applied or request.limits,
            artifacts=tuple(record.artifacts),
            started_at=record.started_at or started,
            finished_at=record.finished_at or time.time(),
        )
        if not record.executed:
            return SandboxOutcome(
                outcome=SandboxOutcomeKind.FAILED,
                reason=SandboxRejectionReason.SUBSTRATE_FAILED,
                detail=f"adapter reported failed execution ({record.termination.value})",
                record=normalized,
                teardown=teardown,
            )
        return SandboxOutcome(
            outcome=SandboxOutcomeKind.EXECUTED,
            record=normalized,
            teardown=teardown,
        )

    def _safe_teardown(self, sandbox_id: str) -> TeardownEvidence:
        """Teardown that never raises (attested on failure)."""
        try:
            assert self._substrate is not None
            return self._substrate.teardown(sandbox_id)
        except Exception as error:
            return TeardownEvidence(
                sandbox_id=sandbox_id,
                torn_down=False,
                detail=f"teardown failed: {error}",
            )


__all__ = [
    "MISSING_SUBSTRATE_DEPENDENCY",
    "NetworkMode",
    "PERMITTED_ENV_NAMES",
    "SANDBOX_GATE_ID",
    "SandboxExecutionRecord",
    "SandboxManager",
    "SandboxOutcome",
    "SandboxOutcomeKind",
    "SandboxRejectionReason",
    "SandboxRequest",
    "SandboxTermination",
    "SubstrateAdapter",
    "SubstrateDescriptor",
    "TeardownEvidence",
]
