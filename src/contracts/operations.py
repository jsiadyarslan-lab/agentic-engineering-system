"""E1 READ operations — Repository Understanding (owner decision D-02 = C).

The four READ-class operations declared by the E0 permission contract
are implemented here as deterministic, pure-Python machinery:

- ``repository_inspection`` — file inventory with hashes, structure,
  and git metadata (refs, HEAD, commit walk over LOOSE objects);
- ``source_reading`` — scoped file reads with path policy;
- ``metadata_analysis`` — file metadata, line counts, language
  distribution;
- ``documentation_reading`` — documentation-file enumeration + reads.

Boundaries (fail-closed):

- **Path policy**: every access resolves through :class:`PathPolicy`,
  which enforces grant-root containment AFTER full symlink
  resolution, rejects absolute paths outside the roots, relative
  path escapes, and over-size reads. No read ever happens outside a
  granted root.
- **No process spawning**: git metadata is read by a pure-Python
  reader (:class:`GitReader`) that parses ``.git`` text files and
  zlib-decompresses LOOSE objects. Packed objects and exotic layouts
  are reported as unsupported with a truthful diagnostic — never
  guessed, never shell-ed out to.
- **No mutation**: these operations only read; evidence is recorded
  as references + hashes by the executor.
- **Determinism**: outputs are sorted and stable so verification can
  re-run and compare hashes.
"""

from __future__ import annotations

import hashlib
import stat
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from substrate.limits import DEFAULT_MAX_OUTPUT_BYTES


class PathPolicyViolation(Exception):
    """A path failed the read path policy (containment/size)."""


class ReadSizeExceeded(PathPolicyViolation):
    """The requested read exceeds the per-read byte ceiling."""


class GitUnsupported(Exception):
    """A git-metadata feature is unsupported (fail-closed diagnostic)."""


@dataclass(frozen=True)
class FileAccessEvidence:
    """Reference-based evidence for one read access."""

    path: str
    sha256: str
    size: int
    mode: str = ""


class PathPolicy:
    """Grant-root-scoped read policy.

    ``granted_roots`` are absolute directories from the bound grant's
    resource references. An access is permitted only when the
    fully-resolved target stays under a fully-resolved root — symlink
    chains that leave the root are rejected. Reads are additionally
    capped by ``max_read_bytes`` (default: the D-13 output ceiling).
    """

    def __init__(
        self,
        granted_roots: tuple[Path, ...] | list[Path],
        *,
        max_read_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        if not granted_roots:
            raise ValueError("path policy requires at least one granted root")
        resolved: list[Path] = []
        for root in granted_roots:
            if not isinstance(root, Path):
                raise TypeError("granted roots must be Path instances")
            resolved.append(root.resolve())
        self._roots = tuple(resolved)
        self._max_read_bytes = max_read_bytes

    @property
    def roots(self) -> tuple[Path, ...]:
        return self._roots

    @property
    def max_read_bytes(self) -> int:
        return self._max_read_bytes

    def check_path(self, target: str | Path) -> Path:
        """Resolve and validate ``target``; return the resolved Path.

        Raises :class:`PathPolicyViolation` on any escape or
        non-absolute input. The returned path is what MAY be read —
        callers still use :meth:`read_file` for the actual bytes.
        """
        raw = str(target)
        if not raw.startswith("/"):
            raise PathPolicyViolation(
                f"read targets must be absolute paths: {raw!r}"
            )
        resolved = Path(raw).resolve()
        for root in self._roots:
            if resolved == root or resolved.is_relative_to(root):
                return resolved
        raise PathPolicyViolation(
            f"target {raw!r} resolves outside every granted root"
        )

    def read_file(self, target: str | Path) -> tuple[bytes, FileAccessEvidence]:
        """Read one file under the policy; return bytes + evidence."""
        resolved = self.check_path(target)
        if not resolved.exists():
            raise PathPolicyViolation(f"target does not exist: {str(target)!r}")
        if not resolved.is_file():
            raise PathPolicyViolation(f"target is not a file: {str(target)!r}")
        size = resolved.stat().st_size
        if size > self._max_read_bytes:
            raise ReadSizeExceeded(
                f"target {str(target)!r} is {size} bytes; read ceiling is "
                f"{self._max_read_bytes}"
            )
        data = resolved.read_bytes()
        mode_bits = stat.S_IMODE(resolved.stat().st_mode)
        evidence = FileAccessEvidence(
            path=str(resolved),
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
            mode=oct(mode_bits),
        )
        return data, evidence

    def list_tree(self, root: str | Path) -> tuple[Path, ...]:
        """List all files under a granted root (deterministic order)."""
        resolved_root = self.check_path(root)
        if not resolved_root.is_dir():
            raise PathPolicyViolation(f"root is not a directory: {str(root)!r}")
        files: list[Path] = []
        stack = [resolved_root]
        while stack:
            current = stack.pop()
            try:
                entries = sorted(current.iterdir(), key=lambda p: p.name)
            except OSError as error:
                raise PathPolicyViolation(
                    f"cannot list directory {str(current)!r}: {error}"
                ) from error
            for entry in entries:
                if entry.name == ".git":
                    continue
                if entry.is_symlink():
                    # never follow directory symlinks during enumeration;
                    # reads through the policy re-validate containment
                    files.append(entry)
                elif entry.is_dir():
                    stack.append(entry)
                elif entry.is_file():
                    files.append(entry)
        return tuple(sorted(files, key=lambda p: str(p.relative_to(resolved_root))))


# ---------------------------------------------------------------------------
# Pure-Python git metadata reader (loose objects only; fail-closed otherwise)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommitInfo:
    """Parsed commit object (loose)."""

    sha: str
    tree: str
    parents: tuple[str, ...]
    author: str
    committer: str
    message: str


@dataclass(frozen=True)
class GitSummary:
    """Repository git metadata summary (loose-object based)."""

    head_reference: str
    head_sha: str
    branch: str
    branches: tuple[str, ...]
    tags: tuple[str, ...]
    commit_count: int
    recent_commits: tuple[CommitInfo, ...]
    warnings: tuple[str, ...] = ()


def _parse_commit(payload: bytes, sha: str) -> CommitInfo:
    header, _, message = payload.partition(b"\n\n")
    tree = ""
    parents: list[str] = []
    author = ""
    committer = ""
    for line in header.decode("utf-8", errors="replace").splitlines():
        if line.startswith("tree "):
            tree = line[5:].strip()
        elif line.startswith("parent "):
            parents.append(line[7:].strip())
        elif line.startswith("author "):
            author = line[7:].strip()
        elif line.startswith("committer "):
            committer = line[10:].strip()
    return CommitInfo(
        sha=sha,
        tree=tree,
        parents=tuple(parents),
        author=author,
        committer=committer,
        message=message.decode("utf-8", errors="replace").strip(),
    )


class GitReader:
    """Read git metadata from a working tree WITHOUT any subprocess.

    Supported (fail-closed on everything else):

    - ``.git`` as a directory (not a worktree/submodule ``gitdir``
      file — those raise :class:`GitUnsupported`);
    - HEAD resolution (symbolic ref or detached SHA);
    - refs under ``refs/heads`` and ``refs/tags`` plus
      ``packed-refs`` (text parsing);
    - LOOSE objects (zlib) of type ``commit``;
    - commit-history walking following parents while objects are
      loose — the first packed or missing object stops the walk with
      a truthful warning.

    The reader never writes, never spawns processes, and never
    guesses: unsupported shapes are reported, not emulated.
    """

    MAX_WALK = 512

    def __init__(self, repo_root: Path) -> None:
        self._root = Path(repo_root)
        git_dir = self._root / ".git"
        if git_dir.is_file():
            raise GitUnsupported(
                ".git is a file (linked worktree/submodule); unsupported"
            )
        if not git_dir.is_dir():
            raise GitUnsupported("no .git directory found at repository root")
        self._git_dir = git_dir

    # -- refs -----------------------------------------------------------

    def head(self) -> tuple[str, str, str]:
        """Return (head_reference, sha, branch).

        ``head_reference`` is the raw HEAD content (trimmed);
        ``branch`` is the branch name or ``""`` when detached.
        """
        head_path = self._git_dir / "HEAD"
        if not head_path.is_file():
            raise GitUnsupported("HEAD file missing")
        raw = head_path.read_text(encoding="utf-8").strip()
        if raw.startswith("ref: "):
            ref = raw[5:].strip()
            sha = self._resolve_ref(ref)
            if sha is None:
                raise GitUnsupported(f"HEAD points at unreadable ref {ref!r}")
            branch = ref[len("refs/heads/") :] if ref.startswith("refs/heads/") else ""
            return raw, sha, branch
        if len(raw) == 40 and all(ch in "0123456789abcdef" for ch in raw.lower()):
            return raw, raw.lower(), ""
        raise GitUnsupported(f"unrecognized HEAD content: {raw!r}")

    def _resolve_ref(self, ref: str) -> str | None:
        loose = self._git_dir / Path(*ref.split("/"))
        if loose.is_file():
            content = loose.read_text(encoding="utf-8").strip()
            if content.startswith("ref: "):
                return self._resolve_ref(content[5:].strip())
            return content or None
        packed = self._packed_refs()
        return packed.get(ref)

    def _packed_refs(self) -> dict[str, str]:
        packed_path = self._git_dir / "packed-refs"
        refs: dict[str, str] = {}
        if not packed_path.is_file():
            return refs
        for line in packed_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("^"):
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2 and parts[0] and parts[1]:
                refs[parts[1].strip()] = parts[0].strip()
        return refs

    def branches(self) -> tuple[str, ...]:
        heads_dir = self._git_dir / "refs" / "heads"
        names: list[str] = []
        if heads_dir.is_dir():
            for path in heads_dir.rglob("*"):
                if path.is_file():
                    names.append(str(path.relative_to(heads_dir)))
        for ref in self._packed_refs():
            if ref.startswith("refs/heads/"):
                name = ref[len("refs/heads/") :]
                if name not in names:
                    names.append(name)
        return tuple(sorted(names))

    def tags(self) -> tuple[str, ...]:
        tags_dir = self._git_dir / "refs" / "tags"
        names: list[str] = []
        if tags_dir.is_dir():
            for path in tags_dir.rglob("*"):
                if path.is_file():
                    names.append(str(path.relative_to(tags_dir)))
        for ref in self._packed_refs():
            if ref.startswith("refs/tags/"):
                name = ref[len("refs/tags/") :]
                if name not in names:
                    names.append(name)
        return tuple(sorted(names))

    # -- objects ---------------------------------------------------------

    def _loose_object_path(self, sha: str) -> Path:
        return self._git_dir / "objects" / sha[:2] / sha[2:]

    def read_loose_object(self, sha: str) -> tuple[str, bytes]:
        """Return (type, payload) for a LOOSE object; fail-closed."""
        if not isinstance(sha, str) or len(sha) != 40 or not all(
            ch in "0123456789abcdef" for ch in sha.lower()
        ):
            raise GitUnsupported(f"not a SHA-1 string: {sha!r}")
        path = self._loose_object_path(sha.lower())
        if not path.is_file():
            raise GitUnsupported(
                f"object {sha!r} is not loose (packed or missing); "
                "packfile reading is unsupported"
            )
        raw = zlib.decompress(path.read_bytes())
        header, _, payload = raw.partition(b"\x00")
        parts = header.decode("utf-8", errors="replace").split(" ", 1)
        if len(parts) != 2 or not parts[0]:
            raise GitUnsupported(f"malformed object header for {sha!r}")
        return parts[0], payload

    def commit(self, sha: str) -> CommitInfo:
        kind, payload = self.read_loose_object(sha)
        if kind != "commit":
            raise GitUnsupported(
                f"object {sha!r} is {kind!r}, not a commit (e.g. annotated tag)"
            )
        return _parse_commit(payload, sha.lower())

    def walk_history(self, start_sha: str) -> tuple[tuple[CommitInfo, ...], tuple[str, ...]]:
        """Walk parents from ``start_sha`` while objects are loose.

        Returns (commits, warnings). The walk stops at the first
        packed/missing/malformed object with a truthful warning —
        it never fabricates history.
        """
        commits: list[CommitInfo] = []
        warnings: list[str] = []
        seen: set[str] = set()
        queue: list[str] = [start_sha]
        while queue and len(commits) < self.MAX_WALK:
            sha = queue.pop(0)
            if sha in seen:
                continue
            seen.add(sha)
            try:
                info = self.commit(sha)
            except GitUnsupported as error:
                warnings.append(f"history walk stopped: {error}")
                continue
            commits.append(info)
            queue.extend(info.parents)
        return tuple(commits), tuple(warnings)

    def summary(self, *, recent: int = 5) -> GitSummary:
        head_reference, head_sha, branch = self.head()
        commits, warnings = self.walk_history(head_sha)
        return GitSummary(
            head_reference=head_reference,
            head_sha=head_sha,
            branch=branch,
            branches=self.branches(),
            tags=self.tags(),
            commit_count=len(commits),
            recent_commits=tuple(commits[:recent]),
            warnings=warnings,
        )


# ---------------------------------------------------------------------------
# READ operation payloads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileInventoryEntry:
    """One file in a repository inventory."""

    relative_path: str
    size: int
    sha256: str
    is_binary: bool
    extension: str


@dataclass(frozen=True)
class RepositoryInventory:
    """Result payload of ``repository_inspection``."""

    root: str
    file_count: int
    total_bytes: int
    files: tuple[FileInventoryEntry, ...]
    directory_count: int
    git: GitSummary | None
    git_warnings: tuple[str, ...] = ()

    def to_plain(self) -> dict[str, Any]:
        """Deterministic plain projection (for evidence references)."""
        return {
            "root": self.root,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "directory_count": self.directory_count,
            "files": [
                {
                    "path": entry.relative_path,
                    "size": entry.size,
                    "sha256": entry.sha256,
                    "binary": entry.is_binary,
                    "ext": entry.extension,
                }
                for entry in self.files
            ],
            "git": {
                "head": self.git.head_sha,
                "branch": self.git.branch,
                "commit_count": self.git.commit_count,
            }
            if self.git
            else None,
        }


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _extension(path: Path) -> str:
    return path.suffix.lower()


def repository_inspection(
    root: Path, policy: PathPolicy
) -> tuple[RepositoryInventory, tuple[FileAccessEvidence, ...]]:
    """Inventory a granted repository root (deterministic).

    Walks the tree under the path policy, hashes every file, detects
    binary files, and attaches the git metadata summary when the
    loose-object reader supports the layout (otherwise the inventory
    carries the truthful warning).
    """
    files = policy.list_tree(root)
    entries: list[FileInventoryEntry] = []
    evidence: list[FileAccessEvidence] = []
    parent_dirs: set[str] = set()
    for path in files:
        data, access = policy.read_file(path)
        rel = str(path.relative_to(Path(root).resolve()))
        parent_dirs.add(str(Path(rel).parent))
        entries.append(
            FileInventoryEntry(
                relative_path=rel,
                size=len(data),
                sha256=access.sha256,
                is_binary=_is_binary(data),
                extension=_extension(path),
            )
        )
        evidence.append(access)
    directory_count = len(
        {directory for directory in parent_dirs if directory not in (".", "")}
    )
    git_summary: GitSummary | None = None
    git_warnings: tuple[str, ...] = ()
    try:
        git_summary = GitReader(Path(root)).summary()
        git_warnings = git_summary.warnings
    except GitUnsupported as error:
        git_warnings = (f"git metadata unavailable: {error}",)
    inventory = RepositoryInventory(
        root=str(Path(root).resolve()),
        file_count=len(entries),
        total_bytes=sum(entry.size for entry in entries),
        files=tuple(entries),
        directory_count=directory_count,
        git=git_summary,
        git_warnings=git_warnings,
    )
    return inventory, tuple(evidence)


@dataclass(frozen=True)
class FileReadResult:
    """Result payload of one scoped file read."""

    path: str
    size: int
    sha256: str
    is_binary: bool
    content: bytes


def source_reading(
    targets: tuple[str, ...], policy: PathPolicy
) -> tuple[tuple[FileReadResult, ...], tuple[FileAccessEvidence, ...]]:
    """Read explicitly requested files under the path policy."""
    if not targets:
        raise ValueError("source_reading requires at least one target path")
    results: list[FileReadResult] = []
    evidence: list[FileAccessEvidence] = []
    for target in targets:
        data, access = policy.read_file(target)
        results.append(
            FileReadResult(
                path=access.path,
                size=access.size,
                sha256=access.sha256,
                is_binary=_is_binary(data),
                content=data,
            )
        )
        evidence.append(access)
    return tuple(results), tuple(evidence)


@dataclass(frozen=True)
class RepositoryMetadata:
    """Result payload of ``metadata_analysis``."""

    root: str
    file_count: int
    total_bytes: int
    total_lines: int
    by_extension: tuple[tuple[str, int, int], ...]
    largest_files: tuple[tuple[str, int], ...]

    def to_plain(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "total_lines": self.total_lines,
            "by_extension": [
                {"ext": ext, "files": count, "bytes": total}
                for ext, count, total in self.by_extension
            ],
            "largest_files": [
                {"path": path, "size": size} for path, size in self.largest_files
            ],
        }


def metadata_analysis(
    root: Path, policy: PathPolicy
) -> tuple[RepositoryMetadata, tuple[FileAccessEvidence, ...]]:
    """Analyze file metadata: sizes, lines, extension distribution."""
    files = policy.list_tree(root)
    total_lines = 0
    by_extension: dict[str, tuple[int, int]] = {}
    largest: list[tuple[str, int]] = []
    evidence: list[FileAccessEvidence] = []
    resolved_root = Path(root).resolve()
    for path in files:
        data, access = policy.read_file(path)
        evidence.append(access)
        rel = str(path.relative_to(resolved_root))
        ext = _extension(path)
        count, total = by_extension.get(ext, (0, 0))
        by_extension[ext] = (count + 1, total + len(data))
        largest.append((rel, len(data)))
        if not _is_binary(data):
            total_lines += data.count(b"\n")
    largest.sort(key=lambda item: (-item[1], item[0]))
    metadata = RepositoryMetadata(
        root=str(resolved_root),
        file_count=len(files),
        total_bytes=sum(size for _, size in largest),
        total_lines=total_lines,
        by_extension=tuple(
            (ext, count, total)
            for ext, (count, total) in sorted(by_extension.items())
        ),
        largest_files=tuple(largest[:10]),
    )
    return metadata, tuple(evidence)


#: Documentation file extensions read by ``documentation_reading``.
DOCUMENTATION_EXTENSIONS: frozenset[str] = frozenset({".md", ".rst", ".txt"})


@dataclass(frozen=True)
class DocumentationBundle:
    """Result payload of ``documentation_reading``."""

    root: str
    documents: tuple[FileReadResult, ...]


def documentation_reading(
    root: Path, policy: PathPolicy
) -> tuple[DocumentationBundle, tuple[FileAccessEvidence, ...]]:
    """Enumerate and read documentation files under a granted root."""
    files = policy.list_tree(root)
    resolved_root = Path(root).resolve()
    doc_files = [
        path
        for path in files
        if _extension(path) in DOCUMENTATION_EXTENSIONS
        or path.name.upper().startswith("README")
    ]
    documents: list[FileReadResult] = []
    evidence: list[FileAccessEvidence] = []
    for path in doc_files:
        data, access = policy.read_file(path)
        documents.append(
            FileReadResult(
                path=access.path,
                size=access.size,
                sha256=access.sha256,
                is_binary=_is_binary(data),
                content=data,
            )
        )
        evidence.append(access)
    bundle = DocumentationBundle(
        root=str(resolved_root),
        documents=tuple(documents),
    )
    return bundle, tuple(evidence)


__all__ = [
    "DOCUMENTATION_EXTENSIONS",
    "CommitInfo",
    "DocumentationBundle",
    "FileAccessEvidence",
    "FileInventoryEntry",
    "FileReadResult",
    "GitReader",
    "GitSummary",
    "GitUnsupported",
    "PathPolicy",
    "PathPolicyViolation",
    "ReadSizeExceeded",
    "RepositoryInventory",
    "RepositoryMetadata",
    "documentation_reading",
    "metadata_analysis",
    "repository_inspection",
    "source_reading",
]
