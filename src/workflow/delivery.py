"""Byte snapshots staged before the SQLite acceptance transaction."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

_CHUNK = 1024 * 1024
_PREVIEW_LIMIT = 262144


def _inside(root: Path, name: str) -> Path:
    """Resolve one manifest name within its artifact root."""
    target = (root / name).resolve()
    if root not in target.parents or not target.is_file():
        raise FileNotFoundError(name)
    return target


def _copy(source: Path, target: Path, expected: str) -> None:
    digest = hashlib.sha256()
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        for chunk in iter(lambda: incoming.read(_CHUNK), b""):
            outgoing.write(chunk)
            digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError("candidate bytes changed after audit")
        outgoing.flush()
        os.fsync(outgoing.fileno())


def stage(workspace: Path, files: dict, evidence_path: str,
          evidence_sha256: str) -> str:
    """Copy the exact audited bytes beside, never into, the work directory.

    A rejected or interrupted attempt remains private: the public projection
    requires a committed acceptance, not simply the existence of these files.
    """
    root = workspace.resolve()
    source = _inside(root, "evidence.json")
    if source != Path(evidence_path).resolve():
        raise ValueError("candidate evidence is not from the active workspace")
    snapshot = root.parent / "delivery"
    snapshot.mkdir()
    for name, meta in files.items():
        target = (snapshot / "files" / name).resolve()
        if snapshot / "files" not in target.parents:
            raise ValueError("invalid candidate artifact name")
        _copy(_inside(root, name), target, meta["sha256"])
    record = snapshot / "evidence.json"
    _copy(source, record, evidence_sha256)
    return str(record)


def preview(evidence: dict, name: str) -> bytes:
    """Verify the bytes behind this preview, even for accepted old records."""
    files = evidence["files"]
    if name not in files:
        raise FileNotFoundError(name)
    metadata = files[name]
    if evidence["verification"].get("delivery_format") == "attempt-snapshot-v1":
        root = Path(evidence["evidence_path"]).parent / "files"
    else:
        # Pre-fix successful records still point at their original workspace.
        # Never substitute new attempt bytes for this historical evidence.
        root = Path(evidence["workspace"])
    target = _inside(root.resolve(), name)
    digest = hashlib.sha256()
    head = bytearray()
    size = 0
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
            head.extend(chunk[:_PREVIEW_LIMIT - len(head)])
    if digest.hexdigest() != metadata["sha256"] or size != metadata["bytes"]:
        raise ValueError("artifact does not match accepted evidence")
    return bytes(head)
