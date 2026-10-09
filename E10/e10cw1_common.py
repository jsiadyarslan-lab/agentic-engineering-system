#!/usr/bin/env python3
"""E10-CW1 shared helpers — crash-window idempotency proof.

Scenario (E10-CW1 order sections 3-6): the SAME production 5-task graph as
E10 (A -> (B, C) -> D -> E), but Process A is SIGKILLed at a REAL lifecycle
boundary INSIDE the crash window: after TASK_D's governed artifact write
(the side effect + its durable side-effect journal record) and BEFORE the
task/attempt completion is durably recorded (no checkpoint may cover the
gap). Process B (new OS process, different PID) restores from durable
storage only and resumes: TASK_D must NOT re-perform the physical write —
it must reconcile with the journaled outcome (original artifact identity,
unchanged file mtime/inode), then TASK_E completes normally.

Everything runs on the REAL production path:
MissionController.define_mission -> execute_run -> ExecutionEngine
.execute_task_graph_parallel -> agent reservation -> MissionTaskAgent.execute
-> ToolExecutor.execute_tool("artifact_write") -> SandboxManager -> journal.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

# reuse the proven E10 scenario building blocks (same graph, same agents)
from e10_common import (  # noqa: F401
    MARKERS, TASK_KEYS, build_controller, build_engine, durable_write_json,
    e10_specs, fsync_file,
)

# The crash-window task: its side effect happens, then the process dies
# before its completion is durably recorded.
CRASH_WINDOW_TASK = "TASK_D"


def journal_path(artifacts_dir: Path, mission_id: str) -> Path:
    return Path(artifacts_dir) / "side_effect_journal" / mission_id / "journal.jsonl"


def read_journal(artifacts_dir: Path, mission_id: str) -> list:
    p = journal_path(artifacts_dir, mission_id)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # torn trailing line — never durable truth
    return out


def journal_index(records: list) -> Dict[tuple, list]:
    """{(task_id, path): [records...]} preserving file order."""
    idx: Dict[tuple, list] = {}
    for rec in records:
        if rec.get("record_type") in ("performed", "reconciled"):
            idx.setdefault((rec.get("task_id", ""), rec.get("path", "")), []).append(rec)
    return idx


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
    """fsync the journal file like every other engine durable record."""
    p = journal_path(artifacts_dir, mission_id)
    if not p.exists():
        return None
    fsync_file(p)
    return str(p)
