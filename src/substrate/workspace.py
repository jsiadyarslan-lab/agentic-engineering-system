"""E1 workspace model — owner decision D-07 (A: ephemeral per-request).

The workspace is the ONLY place Engineering-controlled execution may
write. Its contract:

- **Ephemeral**: one workspace per request, created when the executor
  needs write capacity, destroyed — guaranteed, via the context
  manager — after evidence custody, on success, failure, timeout, or
  revocation. Cleanup is best-effort with an attestation record when
  removal fails (never silent).
- **Path-scoped**: every write/read resolves through
  :meth:`Workspace.resolve`, which enforces absolute containment
  under the workspace root and rejects symlink escapes (resolve +
  containment re-check). Escapes raise :class:`WorkspaceAccessError`.
- **Bounded**: total written bytes are tracked against the D-13
  workspace ceiling; exceeding the cap raises
  :class:`WorkspaceLimitExceeded` BEFORE any bytes are written — no
  partial writes, no silent truncation.
- **Custody boundary**: artifacts leave the workspace only through a
  sealed :class:`CustodyManifest` of (path, sha256, size, kind)
  entries. The manifest is the artifact boundary (D-05 = A:
  reference-based evidence).
- **Observable**: every file mutation is recorded as an E0
  ``ChangedResource`` with before/after hashes so results can carry
  a truthful change ledger.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from substrate.limits import DEFAULT_MAX_WORKSPACE_BYTES
from contracts.result import ChangedResource


class WorkspaceLifecycle(str, Enum):
    """Lifecycle states of a per-request workspace."""

    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    SEALED = "SEALED"
    DESTROYED = "DESTROYED"
    FAILED = "FAILED"


class WorkspaceError(Exception):
    """Base class for workspace contract violations."""


class WorkspaceAccessError(WorkspaceError):
    """A path escaped (or attempted to escape) the workspace root."""


class WorkspaceLimitExceeded(WorkspaceError):
    """The workspace size ceiling would be exceeded (no partial write)."""


class WorkspaceStateError(WorkspaceError):
    """The workspace is not in a state that allows this operation."""


@dataclass(frozen=True)
class WorkspaceSpec:
    """Specification for creating a per-request workspace.

    ``base_dir`` is an optional caller-provided parent directory (the
    caller may locate workspaces on a volume it controls); when it is
    ``None`` the platform temporary directory is used. ``prefix``
    namespaces the created directory. ``max_total_bytes`` is the D-13
    workspace ceiling (may only be lowered).
    """

    base_dir: Path | None = None
    prefix: str = "e1-workspace-"
    max_total_bytes: int = DEFAULT_MAX_WORKSPACE_BYTES


@dataclass(frozen=True)
class ArtifactCustodyEntry:
    """One artifact handed out of the workspace (reference + hash)."""

    path: str
    sha256: str
    size: int
    kind: str


@dataclass(frozen=True)
class CustodyManifest:
    """The sealed artifact manifest — the only artifact exit path."""

    entries: tuple[ArtifactCustodyEntry, ...] = ()

    @property
    def total_bytes(self) -> int:
        return sum(entry.size for entry in self.entries)

    def references(self) -> tuple[str, ...]:
        return tuple(entry.path for entry in self.entries)


@dataclass(frozen=True)
class CleanupAttestation:
    """Attestation of workspace destruction (mandatory cleanup)."""

    destroyed: bool
    state: WorkspaceLifecycle
    detail: str = ""
    destroyed_at: float = 0.0


@dataclass
class _FileLedger:
    """Internal per-file tracking (path → sha256 before/after)."""

    before: dict[str, str] = field(default_factory=dict)
    after: dict[str, str] = field(default_factory=dict)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Workspace:
    """A per-request ephemeral workspace (create → use → seal → destroy).

    Use as a context manager to guarantee destruction::

        with Workspace(WorkspaceSpec()) as workspace:
            record = workspace.write_file("out/report.json", payload)
            manifest = workspace.seal()
        # root removed here; attestation available via workspace.attestation

    Direct use is allowed for the executor, which MUST call
    :meth:`destroy` in a ``finally`` block — the context manager is
    the reference implementation of that guarantee.
    """

    def __init__(self, spec: WorkspaceSpec | None = None) -> None:
        self._spec = spec if spec is not None else WorkspaceSpec()
        self._root = Path(
            tempfile.mkdtemp(prefix=self._spec.prefix, dir=self._spec.base_dir)
        ).resolve()
        self._artifacts_dir = self._root / "artifacts"
        self._artifacts_dir.mkdir()
        self._state = WorkspaceLifecycle.CREATED
        self._total_bytes = 0
        self._ledger = _FileLedger()
        self._custody: CustodyManifest | None = None
        self._attestation: CleanupAttestation | None = None
        self._activate()

    # -- lifecycle ---------------------------------------------------------

    def _activate(self) -> None:
        if self._state is WorkspaceLifecycle.CREATED:
            self._state = WorkspaceLifecycle.ACTIVE

    @property
    def state(self) -> WorkspaceLifecycle:
        return self._state

    @property
    def root(self) -> Path:
        return self._root

    @property
    def artifacts_dir(self) -> Path:
        return self._artifacts_dir

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def attestation(self) -> CleanupAttestation | None:
        return self._attestation

    def __enter__(self) -> Workspace:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.destroy()

    # -- path policy -------------------------------------------------------

    def resolve(self, relative_path: str | Path) -> Path:
        """Resolve ``relative_path`` inside the root, fail-closed.

        Rules: the input must be relative (workspace-internal
        addressing only — absolute paths are rejected because the
        workspace never addresses the outside world); no ``..``
        segment may survive resolution; every symlink along the path
        must resolve back under the root. Violations raise
        :class:`WorkspaceAccessError`.
        """
        candidate_input = str(relative_path)
        if candidate_input.startswith("/"):
            raise WorkspaceAccessError(
                f"absolute paths are not workspace-addressable: {candidate_input!r}"
            )
        candidate = self._root / candidate_input
        resolved = candidate.resolve()
        root_resolved = self._root.resolve()
        if resolved == root_resolved or not resolved.is_relative_to(root_resolved):
            raise WorkspaceAccessError(
                f"path escapes the workspace root: {candidate_input!r} -> {str(resolved)!r}"
            )
        return resolved

    # -- reads -------------------------------------------------------------

    def read_file(self, relative_path: str | Path) -> bytes:
        """Read a file inside the workspace (containment enforced)."""
        target = self.resolve(relative_path)
        if not target.is_file():
            raise WorkspaceAccessError(f"not a file: {relative_path!r}")
        return target.read_bytes()

    # -- writes ------------------------------------------------------------

    def _require_active(self) -> None:
        if self._state is not WorkspaceLifecycle.ACTIVE:
            raise WorkspaceStateError(
                f"workspace is {self._state.value}; writes require ACTIVE"
            )

    def write_file(self, relative_path: str | Path, data: bytes) -> ArtifactCustodyEntry:
        """Write ``data`` to a workspace-relative path (atomic policy).

        The size ceiling is checked BEFORE any byte is written; on
        breach nothing is written and :class:`WorkspaceLimitExceeded`
        is raised. The write is recorded with before/after hashes.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("workspace writes accept bytes only")
        payload = bytes(data)
        self._require_active()
        target = self.resolve(relative_path)
        before_hash: str | None = self._ledger.after.get(str(target))
        if before_hash is None and target.exists():
            before_hash = _sha256_bytes(target.read_bytes())
        if self._total_bytes + len(payload) > self._spec.max_total_bytes:
            raise WorkspaceLimitExceeded(
                f"workspace ceiling {self._spec.max_total_bytes} bytes would be "
                f"exceeded ({self._total_bytes} + {len(payload)})"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        digest = _sha256_bytes(payload)
        key = str(target)
        if before_hash is not None:
            self._ledger.before[key] = before_hash
        else:
            self._ledger.before.setdefault(key, "")
        self._ledger.after[key] = digest
        self._total_bytes += len(payload)
        return ArtifactCustodyEntry(
            path=str(target.relative_to(self._root)),
            sha256=digest,
            size=len(payload),
            kind="file",
        )

    def create_artifact(
        self, artifact_name: str, data: bytes
    ) -> ArtifactCustodyEntry:
        """Write an artifact into the bounded artifacts directory."""
        if artifact_name.startswith("/") or ".." in artifact_name.split("/"):
            raise WorkspaceAccessError(f"invalid artifact name: {artifact_name!r}")
        return self.write_file(Path("artifacts") / artifact_name, data)

    def modify_file(self, relative_path: str | Path, data: bytes) -> ArtifactCustodyEntry:
        """Modify an existing workspace file (records before-hash)."""
        target = self.resolve(relative_path)
        if not target.exists():
            raise WorkspaceAccessError(
                f"modification target does not exist: {str(relative_path)!r}"
            )
        return self.write_file(relative_path, data)

    # -- sealing / custody --------------------------------------------------

    def seal(self) -> CustodyManifest:
        """Seal the workspace: stop writes, build the custody manifest.

        The manifest enumerates every file currently under the
        artifacts directory with its hash and size. After sealing,
        any further write raises :class:`WorkspaceStateError`.
        """
        self._require_active()
        entries: list[ArtifactCustodyEntry] = []
        if self._artifacts_dir.exists():
            for path in sorted(self._artifacts_dir.rglob("*")):
                if path.is_file():
                    data = path.read_bytes()
                    entries.append(
                        ArtifactCustodyEntry(
                            path=str(path.relative_to(self._root)),
                            sha256=_sha256_bytes(data),
                            size=len(data),
                            kind="artifact",
                        )
                    )
        self._custody = CustodyManifest(entries=tuple(entries))
        self._state = WorkspaceLifecycle.SEALED
        return self._custody

    @property
    def custody_manifest(self) -> CustodyManifest | None:
        return self._custody

    # -- teardown ------------------------------------------------------------

    def destroy(self) -> CleanupAttestation:
        """Destroy the workspace root (mandatory cleanup).

        Best-effort with attestation: if removal fails, the failure is
        recorded and the state becomes FAILED — never silently kept.
        Idempotent: destroying twice returns the first attestation.
        """
        if self._state is WorkspaceLifecycle.DESTROYED:
            assert self._attestation is not None
            return self._attestation
        try:
            shutil.rmtree(self._root)
            self._state = WorkspaceLifecycle.DESTROYED
            self._attestation = CleanupAttestation(
                destroyed=True,
                state=self._state,
                detail="workspace root removed",
                destroyed_at=time.time(),
            )
        except OSError as error:
            self._state = WorkspaceLifecycle.FAILED
            self._attestation = CleanupAttestation(
                destroyed=False,
                state=self._state,
                detail=f"cleanup failed: {error}",
                destroyed_at=time.time(),
            )
        return self._attestation

    # -- E0 result mapping ---------------------------------------------------

    def changed_resources(self) -> tuple[ChangedResource, ...]:
        """Map the write ledger to E0 ``ChangedResource`` records."""
        records: list[ChangedResource] = []
        for path, after_hash in self._ledger.after.items():
            before_hash = self._ledger.before.get(path, "")
            relpath = str(Path(path).relative_to(self._root))
            if before_hash and before_hash != after_hash:
                change = f"modified (sha256 {before_hash[:12]} -> {after_hash[:12]})"
            else:
                change = f"created (sha256 {after_hash[:12]})"
            records.append(ChangedResource(resource=relpath, change=change))
        return tuple(records)
