"""E1 evidence collection — owner decision D-05 (A: reference-based only).

The evidence collector records WHAT happened during controlled
execution, as *references* — paths, identifiers, hashes — never as
embedded content blobs. The reference rule is structural: every
record method takes strings and integers; none accepts bytes, so
content cannot leak into the evidence stream by construction.

Records collected per the Capability Gap Discovery §13:

- **command records** — argv, cwd, exit code, duration (for sandbox
  executions; the exit code is EXECUTED-state evidence only);
- **access records** — path, sha256, size, mode for every file read
  through the path policy;
- **artifact records** — path, sha256, size, kind for every artifact
  in a custody manifest;
- **environment identity** — runtime version, sandbox id, and the
  NAMES of the permitted environment variables (values are never
  recorded; secrets cannot enter evidence);
- **test records** — name + outcome per parsed test;
- **events** — named lifecycle moments with references.

The collector maps everything onto the E0 result-contract types
(``ActionRecord``, ``ArtifactRecord``, ``Evidence``, ``TestRecord``,
``ChangedResource``) so the executor can assemble a truthful
``CapabilityResult``. Ownership of the evidence stays with the
caller; Engineering is custodian during execution only.
"""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass
from enum import Enum

from contracts.result import (
    ActionRecord,
    ArtifactRecord,
    ChangedResource,
    Evidence,
    OutcomeState,
    TestRecord,
)


class EvidenceKind(str, Enum):
    """Kinds of evidence records (reference-based only)."""

    COMMAND = "command"
    ACCESS = "access"
    ARTIFACT = "artifact"
    ENVIRONMENT = "environment"
    TEST = "test"
    EVENT = "event"


@dataclass(frozen=True)
class EvidenceEntry:
    """One reference-based evidence entry (no content by construction)."""

    kind: EvidenceKind
    reference: str
    recorded_at: float
    detail: str = ""


def _require_reference(reference: object, what: str) -> str:
    if not isinstance(reference, str) or not reference:
        raise TypeError(f"{what} reference must be a non-empty string")
    return reference


def _require_positive_int(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError(f"{what} must be a non-negative integer")
    return value


def _require_hash(value: object, what: str = "hash") -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{what} must be a non-empty string")
    return value


class EvidenceCollector:
    """Collects reference-based evidence during controlled execution.

    All record methods validate their inputs and reject content
    payloads (bytes) structurally. Timestamps default to wall-clock
    time; tests inject ``now`` for determinism.
    """

    def __init__(self, *, now: float | None = None) -> None:
        self._entries: list[EvidenceEntry] = []
        self._actions: list[ActionRecord] = []
        self._artifacts: list[ArtifactRecord] = []
        self._tests: list[TestRecord] = []
        self._changed: list[ChangedResource] = []
        self._clock: list[float] = [] if now is None else [now]

    # -- clock ---------------------------------------------------------------

    def _stamp(self) -> float:
        if self._clock:
            # deterministic mode: fixed injected timestamp
            return self._clock[-1]
        return time.time()

    # -- records ---------------------------------------------------------------

    def record_command(
        self,
        *,
        argv: tuple[str, ...],
        cwd: str,
        exit_code: int | None,
        duration_ms: int,
        started_at: float | None = None,
    ) -> EvidenceEntry:
        """Record one executed command (sandbox executions)."""
        if (
            not isinstance(argv, tuple)
            or not argv
            or not all(isinstance(part, str) and part for part in argv)
        ):
            raise TypeError("argv must be a non-empty tuple of non-empty strings")
        cwd_ref = _require_reference(cwd, "cwd")
        duration = _require_positive_int(duration_ms, "duration_ms")
        if exit_code is not None and (
            isinstance(exit_code, bool) or not isinstance(exit_code, int)
        ):
            raise TypeError("exit_code must be an integer or None")
        joined = " ".join(argv)
        detail = (
            f"exit={exit_code if exit_code is not None else 'n/a'} "
            f"duration_ms={duration}"
        )
        entry = EvidenceEntry(
            kind=EvidenceKind.COMMAND,
            reference=f"cmd:{joined}",
            recorded_at=self._stamp(),
            detail=detail,
        )
        self._entries.append(entry)
        self._actions.append(ActionRecord(name=joined, state=OutcomeState.EXECUTED))
        return entry

    def record_access(
        self,
        *,
        path: str,
        sha256: str,
        size: int,
        mode: str = "",
    ) -> EvidenceEntry:
        """Record one file access through the path policy."""
        path_ref = _require_reference(path, "access path")
        digest = _require_hash(sha256)
        file_size = _require_positive_int(size, "size")
        detail = f"sha256={digest} size={file_size}"
        if mode:
            detail += f" mode={mode}"
        entry = EvidenceEntry(
            kind=EvidenceKind.ACCESS,
            reference=path_ref,
            recorded_at=self._stamp(),
            detail=detail,
        )
        self._entries.append(entry)
        return entry

    def record_artifact(
        self,
        *,
        path: str,
        sha256: str,
        size: int,
        kind: str,
    ) -> EvidenceEntry:
        """Record one artifact leaving the workspace via custody."""
        path_ref = _require_reference(path, "artifact path")
        digest = _require_hash(sha256)
        file_size = _require_positive_int(size, "size")
        kind_ref = _require_reference(kind, "artifact kind")
        entry = EvidenceEntry(
            kind=EvidenceKind.ARTIFACT,
            reference=path_ref,
            recorded_at=self._stamp(),
            detail=f"kind={kind_ref} sha256={digest} size={file_size}",
        )
        self._entries.append(entry)
        self._artifacts.append(ArtifactRecord(kind=kind_ref, reference=path_ref))
        return entry

    def record_environment(
        self,
        *,
        sandbox_id: str = "",
        env_names: frozenset[str] | set[str] = frozenset(),
    ) -> EvidenceEntry:
        """Record the execution environment identity (scrubbed).

        Only the NAMES of permitted environment variables are
        recorded — never their values. Runtime version and sandbox id
        are references, not content.
        """
        names = sorted(frozenset(env_names))
        detail = f"env_names={names}"
        if sandbox_id:
            detail = f"sandbox_id={sandbox_id} " + detail
        entry = EvidenceEntry(
            kind=EvidenceKind.ENVIRONMENT,
            reference=f"runtime:{platform.python_implementation()}-{platform.python_version()}",
            recorded_at=self._stamp(),
            detail=detail,
        )
        self._entries.append(entry)
        return entry

    def record_test(
        self, *, name: str, passed: bool, message: str = ""
    ) -> EvidenceEntry:
        """Record one parsed test outcome (``message`` = bounded failure text)."""
        name_ref = _require_reference(name, "test name")
        if not isinstance(passed, bool):
            raise TypeError("passed must be a boolean")
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        detail = "passed" if passed else "failed"
        if message:
            excerpt = message[:240].replace("\n", " ")
            detail = f"failed: {excerpt}"
        entry = EvidenceEntry(
            kind=EvidenceKind.TEST,
            reference=f"test:{name_ref}",
            recorded_at=self._stamp(),
            detail=detail,
        )
        self._entries.append(entry)
        self._tests.append(
            TestRecord(name=name_ref, passed=passed, message=message)
        )
        return entry

    def record_event(self, *, name: str, reference: str, detail: str = "") -> EvidenceEntry:
        """Record a named lifecycle event (workspace, teardown, gates)."""
        name_ref = _require_reference(name, "event name")
        reference_ref = _require_reference(reference, "event reference")
        entry = EvidenceEntry(
            kind=EvidenceKind.EVENT,
            reference=reference_ref,
            recorded_at=self._stamp(),
            detail=detail or name_ref,
        )
        self._entries.append(entry)
        self._actions.append(ActionRecord(name=name_ref, state=OutcomeState.OBSERVED))
        return entry

    def record_action(self, *, name: str, state: OutcomeState) -> None:
        """Record an operation action outcome directly."""
        name_ref = _require_reference(name, "action name")
        if not isinstance(state, OutcomeState):
            raise TypeError("state must be an OutcomeState")
        self._actions.append(ActionRecord(name=name_ref, state=state))

    def record_changed_resources(
        self, changed: tuple[ChangedResource, ...]
    ) -> None:
        """Adopt workspace changed-resource records into the evidence."""
        if not isinstance(changed, tuple) or not all(
            isinstance(item, ChangedResource) for item in changed
        ):
            raise TypeError("changed must be a tuple of ChangedResource")
        self._changed.extend(changed)

    # -- projection to the E0 result contract ----------------------------------

    def entries(self) -> tuple[EvidenceEntry, ...]:
        return tuple(self._entries)

    def to_result_fields(
        self,
    ) -> tuple[
        tuple[ActionRecord, ...],
        tuple[ArtifactRecord, ...],
        tuple[ChangedResource, ...],
        tuple[TestRecord, ...],
        tuple[Evidence, ...],
    ]:
        """Project collected records onto the E0 result-contract types."""
        evidence = tuple(
            Evidence(kind=entry.kind.value, reference=entry.reference)
            for entry in self._entries
        )
        return (
            tuple(self._actions),
            tuple(self._artifacts),
            tuple(self._changed),
            tuple(self._tests),
            evidence,
        )

    def __len__(self) -> int:
        return len(self._entries)
