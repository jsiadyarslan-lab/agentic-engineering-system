"""Test artifact containment for the canonical-path test suites (E2-R2 §3).

THE RULE (E2-R2 executive order §3):
    No test may write to, modify, or delete canonical evidence
    (docs/evidence/**) or any other fixed canonical path.

Every test run gets an ISOLATED set of roots:

    TEST_ROOT            one fresh temporary directory per test session/run
    TEMP_EVIDENCE_ROOT   where tests dump their evidence JSON artifacts
    TEMP_ARTIFACT_ROOT   where engines persist state (checkpoints, events,
                         evidence store, mission-controller ledgers, sandbox
                         artifacts)

Override (used by E2-R2 verification tooling to inspect a run's outputs):
    UNIFIED_TEST_ROOT=<dir>   — reuse a fixed location instead of a new
                                mkdtemp (still fully outside docs/evidence).

This module is the single authority for those roots; the E32e/E32f/E33
suites import it and are forbidden from deriving their own repo-relative
evidence paths.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

__all__ = [
    "TEST_ROOT",
    "TEMP_EVIDENCE_ROOT",
    "TEMP_ARTIFACT_ROOT",
    "evidence_dir",
    "state_dir",
    "new_isolated_test_root",
]

_OVERRIDE = os.environ.get("UNIFIED_TEST_ROOT")
if _OVERRIDE:
    TEST_ROOT = Path(_OVERRIDE).resolve()
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    _owned = False  # caller-managed lifetime
else:
    TEST_ROOT = Path(tempfile.mkdtemp(prefix="unified-test-"))
    _owned = True

TEMP_EVIDENCE_ROOT = TEST_ROOT / "evidence"
TEMP_ARTIFACT_ROOT = TEST_ROOT / "state"
TEMP_EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
TEMP_ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)


def _cleanup() -> None:
    if _owned and TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT, ignore_errors=True)


atexit.register(_cleanup)


def evidence_dir(phase: str) -> Path:
    """Isolated evidence directory for a test phase (e.g. 'e32e', 'e33')."""
    d = TEMP_EVIDENCE_ROOT / phase
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_dir(phase: str) -> Path:
    """Isolated engine-state directory for a test phase (e.g. 'e33')."""
    d = TEMP_ARTIFACT_ROOT / phase / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_isolated_test_root() -> Path:
    """A brand-new isolated root (for suites that must not share state)."""
    root = Path(tempfile.mkdtemp(prefix="unified-test-"))
    return root
