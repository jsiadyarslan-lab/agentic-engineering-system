"""E1 controlled write operations (G3 execution order v1, 2026-09-10).

The two write-class engineering operations admitted into E1 by the G3
owner execution order — the "separate authorization" that
``docs/E1.md`` recorded as required before any write-class domain
operation could be registered:

- ``source_modification`` — exact-intent controlled modification of a
  file read from the granted scope, executed INSIDE the per-request
  ephemeral workspace (D-07 = A); the modified content exits only
  through the custody boundary (D-05 = A). The granted repository is
  never mutated: reads go through the granted-scope path policy and
  writes land only in the workspace.
- ``artifact_creation`` — declared-content artifact generated directly
  in the custody boundary.

Contract properties (G3 order §4, fail-closed throughout):

- both handlers are pure functions over ``(params, policy,
  workspace)`` — no process creation, no network, no host access;
- the DECLARED intent is exact: the source precondition hash and the
  declared output content/hash are binding preconditions checked
  before and after the write;
- the workspace ceiling is enforced BEFORE any byte is written (no
  partial writes — D-07);
- every outcome carries the structured facts the executor needs to
  record evidence (access + custody entries) and machine-checkable
  verification (output hash, intent match, artifact readability);
- execution completed is NOT verified success: the outcome is
  EXECUTED-state evidence only; the verdict belongs to the caller
  (D-08 = A).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from contracts.operations import FileAccessEvidence, PathPolicy
from substrate.workspace import ArtifactCustodyEntry, Workspace

#: Maximum accepted length of the declared ``new_content`` / ``content``
#: payload (checked before the workspace write so oversized requests
#: fail at admission/handler time, not at the byte ceiling only).
MAX_DECLARED_CONTENT_BYTES: int = 1_048_576

_HEX_DIGITS = frozenset("0123456789abcdef")


def _is_sha256_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _HEX_DIGITS for character in value)
    )


def _valid_artifact_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not value.startswith("/")
        and ".." not in value.split("/")
        and "\\" not in value
    )


def _encode_declared_content(value: object) -> bytes | None:
    """UTF-8-encode a declared str payload; None when not a plain str.

    G3 admits TEXT content declarations only (source code, manifests,
    reports). Binary content declarations are deliberately out of the
    G3 scope and fail closed here rather than being smuggled through
    encodings.
    """
    if not isinstance(value, str):
        return None
    return value.encode("utf-8")


@dataclass(frozen=True)
class WriteOperationOutcome:
    """Structured outcome of one controlled write operation.

    ``state`` is ``EXECUTED`` only when the declared intent was fully
    carried out (precondition held, write landed, read-back verified);
    every other path is ``FAILED`` with a truthful ``detail``. The
    executor maps this onto E0 ``OutcomeState`` records and the
    verification checks — this type never claims a final verdict.
    """

    state: str
    detail: str
    #: the granted-scope read access backing the modification
    access: FileAccessEvidence | None = None
    #: the custody entry for the written artifact
    artifact: ArtifactCustodyEntry | None = None
    #: declared intent, reference-encoded (never the content itself)
    declared_intent: str = ""
    #: observed change, reference-encoded (never the content itself)
    observed_change: str = ""
    #: hash of the declared content (computed, for intent checks)
    declared_sha256: str = ""
    #: hash observed by reading the artifact back after the write
    observed_sha256: str = ""
    #: artifact was readable after the write (custody precondition)
    readable: bool = False

    @property
    def executed(self) -> bool:
        return self.state == "EXECUTED"

    @property
    def intent_verified(self) -> bool:
        """True only when declared intent and observation coincide."""
        return (
            self.executed
            and self.readable
            and bool(self.declared_sha256)
            and self.declared_sha256 == self.observed_sha256
        )


def source_modification(
    params: dict,
    policy: PathPolicy,
    workspace: Workspace,
) -> WriteOperationOutcome:
    """Execute one controlled file modification inside the workspace.

    Input contract (admission-validated, G3 order §4):

    - ``source`` — absolute path under a granted root (read through
      the path policy; escapes are rejected fail-closed);
    - ``expected_sha256`` — the declared precondition: the sha256 of
      the source file as the caller observed it. A mismatch means the
      source changed (or the expectation is wrong) — nothing is
      written;
    - ``new_content`` — the declared full replacement content (UTF-8
      text; binary declarations fail closed);
    - ``artifact_name`` — the workspace-relative custody exit name for
      the modified file (no escapes).

    The granted repository is never mutated: the write lands in the
    per-request ephemeral workspace and exits through the custody
    manifest only.
    """
    source = params["source"]
    expected_sha256 = params["expected_sha256"]
    new_content = params["new_content"]
    artifact_name = params["artifact_name"]

    payload = _encode_declared_content(new_content)
    if payload is None:
        return WriteOperationOutcome(
            state="FAILED",
            detail="new_content must be a UTF-8 text string (binary "
            "declarations are outside the G3 scope)",
        )
    if len(payload) > MAX_DECLARED_CONTENT_BYTES:
        return WriteOperationOutcome(
            state="FAILED",
            detail=(
                "declared new_content exceeds the G3 declaration ceiling "
                f"({len(payload)} > {MAX_DECLARED_CONTENT_BYTES} bytes)"
            ),
        )

    # 1. read the source through the granted-scope policy (fail-closed
    #    on escapes, missing files, and read-size ceilings)
    data, access = policy.read_file(source)
    declared_intent = f"{access.path}@{expected_sha256} -> {artifact_name}"

    # 2. intent precondition: the observed source hash must equal the
    #    declared expectation — no write happens otherwise
    if access.sha256 != expected_sha256:
        return WriteOperationOutcome(
            state="FAILED",
            detail=(
                "source precondition failed: declared expected_sha256 "
                f"{expected_sha256} != observed {access.sha256} "
                f"({access.path}); nothing was written"
            ),
            access=access,
            declared_intent=declared_intent,
            observed_change=f"{access.path}@{access.sha256} (unchanged)",
        )

    # 3. write the declared content into the custody boundary (the
    #    workspace enforces the size ceiling BEFORE writing bytes)
    try:
        entry = workspace.create_artifact(artifact_name, payload)
    except Exception as error:  # workspace limit / name violations
        return WriteOperationOutcome(
            state="FAILED",
            detail=(
                f"workspace rejected the write fail-closed: "
                f"{type(error).__name__}: {error}"
            ),
            access=access,
            declared_intent=declared_intent,
            observed_change=f"{access.path}@{access.sha256} (no write)",
        )

    # 4. read the artifact back: custody requires readability and an
    #    exact hash match against the declared content
    try:
        observed_bytes = workspace.read_file(Path("artifacts") / artifact_name)
        observed_sha256 = hashlib.sha256(observed_bytes).hexdigest()
        readable = True
    except Exception as error:  # pragma: no cover - defensive
        observed_sha256 = ""
        readable = False
        detail_hint = f"read-back failed: {type(error).__name__}: {error}"
    declared_sha256 = hashlib.sha256(payload).hexdigest()
    observed_change = (
        f"{access.path}@{access.sha256} -> artifacts/{artifact_name}"
        f"@{observed_sha256 or 'unreadable'}"
    )
    if not readable:
        return WriteOperationOutcome(
            state="FAILED",
            detail=f"artifact not readable after the write: {detail_hint}",
            access=access,
            artifact=entry,
            declared_intent=declared_intent,
            observed_change=observed_change,
            declared_sha256=declared_sha256,
            observed_sha256=observed_sha256,
            readable=False,
        )
    if observed_sha256 != declared_sha256:  # pragma: no cover - defensive
        return WriteOperationOutcome(
            state="FAILED",
            detail=(
                "written artifact hash does not match the declared "
                f"content: declared={declared_sha256} "
                f"observed={observed_sha256}"
            ),
            access=access,
            artifact=entry,
            declared_intent=declared_intent,
            observed_change=observed_change,
            declared_sha256=declared_sha256,
            observed_sha256=observed_sha256,
            readable=True,
        )

    return WriteOperationOutcome(
        state="EXECUTED",
        detail=(
            f"controlled modification executed: {access.path} "
            f"(sha256 {access.sha256[:12]}) -> artifacts/{artifact_name} "
            f"(sha256 {declared_sha256[:12]}); granted source untouched"
        ),
        access=access,
        artifact=entry,
        declared_intent=declared_intent,
        observed_change=observed_change,
        declared_sha256=declared_sha256,
        observed_sha256=observed_sha256,
        readable=True,
    )


def artifact_creation(
    params: dict,
    workspace: Workspace,
) -> WriteOperationOutcome:
    """Generate one declared-content artifact in the custody boundary.

    Input contract (admission-validated, G3 order §4):

    - ``artifact_name`` — workspace-relative custody exit name (no
      escapes);
    - ``content`` — the declared artifact content (UTF-8 text);
    - ``content_sha256`` — the declared sha256 of the content. The
      handler refuses to create an artifact whose content does not
      hash exactly to the declaration (fail-closed intent contract).
    """
    artifact_name = params["artifact_name"]
    content = params["content"]
    content_sha256 = params["content_sha256"]

    payload = _encode_declared_content(content)
    if payload is None:
        return WriteOperationOutcome(
            state="FAILED",
            detail="content must be a UTF-8 text string (binary "
            "declarations are outside the G3 scope)",
        )
    if len(payload) > MAX_DECLARED_CONTENT_BYTES:
        return WriteOperationOutcome(
            state="FAILED",
            detail=(
                "declared content exceeds the G3 declaration ceiling "
                f"({len(payload)} > {MAX_DECLARED_CONTENT_BYTES} bytes)"
            ),
        )
    declared_sha256 = hashlib.sha256(payload).hexdigest()
    declared_intent = f"{artifact_name}@{content_sha256}"

    # 1. intent precondition: declared hash must match the declared
    #    content — nothing is written otherwise
    if declared_sha256 != content_sha256:
        return WriteOperationOutcome(
            state="FAILED",
            detail=(
                "declared content_sha256 does not match the declared "
                f"content: declared={content_sha256} "
                f"computed={declared_sha256}; nothing was written"
            ),
            declared_intent=declared_intent,
            observed_change="no write",
            declared_sha256=declared_sha256,
        )

    # 2. write into the custody boundary (ceiling checked BEFORE bytes)
    try:
        entry = workspace.create_artifact(artifact_name, payload)
    except Exception as error:  # workspace limit / name violations
        return WriteOperationOutcome(
            state="FAILED",
            detail=(
                f"workspace rejected the write fail-closed: "
                f"{type(error).__name__}: {error}"
            ),
            declared_intent=declared_intent,
            observed_change="no write",
            declared_sha256=declared_sha256,
        )

    # 3. read back: readability + exact hash match
    try:
        observed_bytes = workspace.read_file(Path("artifacts") / artifact_name)
        observed_sha256 = hashlib.sha256(observed_bytes).hexdigest()
        readable = True
    except Exception as error:  # pragma: no cover - defensive
        observed_sha256 = ""
        readable = False
        detail_hint = f"read-back failed: {type(error).__name__}: {error}"
    observed_change = f"artifacts/{artifact_name}@{observed_sha256 or 'unreadable'}"
    if not readable:  # pragma: no cover - defensive
        return WriteOperationOutcome(
            state="FAILED",
            detail=f"artifact not readable after the write: {detail_hint}",
            artifact=entry,
            declared_intent=declared_intent,
            observed_change=observed_change,
            declared_sha256=declared_sha256,
            observed_sha256=observed_sha256,
            readable=False,
        )
    if observed_sha256 != declared_sha256:  # pragma: no cover - defensive
        return WriteOperationOutcome(
            state="FAILED",
            detail=(
                "written artifact hash does not match the declared "
                f"content: declared={declared_sha256} "
                f"observed={observed_sha256}"
            ),
            artifact=entry,
            declared_intent=declared_intent,
            observed_change=observed_change,
            declared_sha256=declared_sha256,
            observed_sha256=observed_sha256,
            readable=True,
        )

    return WriteOperationOutcome(
        state="EXECUTED",
        detail=(
            f"artifact generated: artifacts/{artifact_name} "
            f"(sha256 {declared_sha256[:12]}, {len(payload)} bytes) "
            "inside the custody boundary"
        ),
        artifact=entry,
        declared_intent=declared_intent,
        observed_change=observed_change,
        declared_sha256=declared_sha256,
        observed_sha256=observed_sha256,
        readable=True,
    )


__all__ = [
    "MAX_DECLARED_CONTENT_BYTES",
    "WriteOperationOutcome",
    "artifact_creation",
    "source_modification",
]
