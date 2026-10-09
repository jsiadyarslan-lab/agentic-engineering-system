#!/usr/bin/env python3
"""E10-CW1-R1 shared helpers — intent-first pre-journal crash proof.

The previous CW1 proof killed at the ARTIFACT_CREATED emission — which fires
AFTER `_journal_performance` already fsynced the outcome record. It therefore
proved the (performed -> completion) window, never the (effect -> performed)
window. R1 injects the kill at the REAL boundaries:

  SCENARIO A  (A_pre_effect):  after the durable `intent` record, BEFORE the
      physical write. Journal: intent only. File: absent.
  SCENARIO B  (B_pre_journal): after the physical write completed (fsynced by
      the adapter), BEFORE `_journal_performance`. Journal: intent only.
      File: present. This is the gap the order targets (§2) — at baseline it
      made Process B re-perform the write because absence of a journal record
      was treated as a new operation.
  SCENARIO C  (C_post_journal): after the `performed` record, before the
      task completion records — re-proof of the CW1 window (order §4-C).
  SCENARIO D1 (B_pre_journal + torn trailing journal line): the partial
      FINAL record policy — ignored as never-durable-truth, resume must still
      reconcile against the intent that precedes it (order §4-D).
  SCENARIO D2a (B_pre_journal + corrupted trailing intent line): the intent
      record is destroyed (invalid JSON trailing) while the effect file
      exists — unreconcilable ambiguity must be REJECTED explicitly, not
      silently overwritten (order §4-D).
  SCENARIO D2b (C_post_journal + corrupted MIDDLE prior record): a prior
      performed record that may be the only proof of a proven effect is
      corrupt — the journal must FAIL CLOSED, never skip it silently
      (order §4-D).

Everything runs on the REAL production path (same as E10/CW1):
MissionController.define_mission -> execute_run -> ExecutionEngine
.execute_task_graph_parallel -> MissionTaskAgent.execute -> ToolExecutor
.execute_tool("artifact_write") -> engine._governed_artifact_write ->
SandboxManager -> adapter -> SideEffectJournal.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from e10_common import (  # noqa: F401
    MARKERS, TASK_KEYS, build_controller, build_engine, durable_write_json,
    e10_specs, fsync_file,
)

CRASH_WINDOW_TASK = "TASK_D"
D_REL_PATH = "task_d_output.txt"

SCENARIOS = ("A", "B", "C", "D1", "D2a", "D2b")

# scenario -> (injection point, corruption applied between A and B)
SCENARIO_INJECTION = {
    "A": "A_pre_effect",
    "B": "B_pre_journal",
    "C": "C_post_journal",
    "D1": "B_pre_journal",
    "D2a": "B_pre_journal",
    "D2b": "C_post_journal",
}
SCENARIO_CORRUPTION = {
    "A": None,
    "B": None,
    "C": None,
    "D1": "torn_trailing_line",
    "D2a": "corrupt_trailing_intent",
    "D2b": "corrupt_middle_record",
}


def journal_path(artifacts_dir: Path, mission_id: str) -> Path:
    return Path(artifacts_dir) / "side_effect_journal" / mission_id / "journal.jsonl"


def read_journal(artifacts_dir: Path, mission_id: str) -> List[dict]:
    """ALL parseable records (intent/performed/reconciled), file order.
    Torn/unparseable lines are counted separately by scan_journal()."""
    p = journal_path(artifacts_dir, mission_id)
    if not p.exists():
        return []
    out: List[dict] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def scan_journal(artifacts_dir: Path, mission_id: str) -> Dict[str, Any]:
    """Raw structural scan: valid records + per-line parse status + file hash."""
    p = journal_path(artifacts_dir, mission_id)
    if not p.exists():
        return {"exists": False, "records": [], "line_status": [], "sha256": None, "ends_with_newline": None}
    raw = p.read_bytes()
    lines = raw.decode("utf-8", errors="replace").splitlines()
    records: List[dict] = []
    status: List[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            status.append("empty")
            continue
        try:
            records.append(json.loads(s))
            status.append("valid")
        except json.JSONDecodeError:
            status.append("torn_or_corrupt")
    return {
        "exists": True,
        "records": records,
        "line_status": status,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "ends_with_newline": raw.endswith(b"\n"),
    }


def journal_records_for(records: List[dict], task_id: str, path: str) -> List[dict]:
    return [r for r in records
            if r.get("task_id") == task_id and r.get("path") == path]


def side_effect_file(artifacts_dir: Path, sandbox_id: str, path: str) -> Path:
    return Path(artifacts_dir) / sandbox_id / path


def stat_snapshot(path: Path) -> Optional[Dict[str, Any]]:
    """Independent OS-level observation of a side-effect file."""
    if not path.exists():
        return None
    st = path.stat()
    data = path.read_bytes()
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "inode": st.st_ino,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def fsync_journal(artifacts_dir: Path, mission_id: str) -> Optional[str]:
    p = journal_path(artifacts_dir, mission_id)
    if not p.exists():
        return None
    fsync_file(p)
    return str(p)
