#!/usr/bin/env python3
"""E10 — Durable Execution & Cross-Process Resume Proof: shared scenario definition.

Mission shape (E10 section 9 — multi-task graph with explicit dependencies):

    TASK_A (independent foundation)
       |
    TASK_B ------+
                +--- TASK_D --- TASK_E
    TASK_C ------+

Process A executes A, B, C to completion, stops at a safe scheduling boundary
(D READY, E BLOCKED), writes a durable checkpoint, and is SIGKILLed.
Process B (a real separate OS process) restores from the checkpoint on disk
and completes D and E without re-executing A, B, C.

Everything here runs on the REAL production path:
MissionController.define_mission -> execute_run -> ExecutionEngine
.execute_task_graph_parallel -> _execute_single_task -> agent reservation ->
MissionTaskAgent.execute -> ToolExecutor.execute_tool("artifact_write") ->
SandboxManager -> Artifact -> Evidence (E9-R governed path).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from unified.agent_role import AgentType  # noqa: E402
from unified.mission_controller import TaskSpec  # noqa: E402

MISSION_REQUEST = (
    "E10 durable execution proof: produce five governed artifacts "
    "(foundation, two branches, merge, final) with a durable checkpoint "
    "boundary between the branches and the merge."
)

TASK_KEYS = ["TASK_A", "TASK_B", "TASK_C", "TASK_D", "TASK_E"]

EXPECTED_STATES_AT_PAUSE = {
    "TASK_A": "COMPLETED",
    "TASK_B": "COMPLETED",
    "TASK_C": "COMPLETED",
    "TASK_D": "READY",     # unblocked (B and C completed) but never started
    "TASK_E": "BLOCKED",   # depends on D which never ran in Process A
}

MARKERS = {
    "TASK_A": ("task_a_output.txt", "E10_TASK_A_COMPLETE"),
    "TASK_B": ("task_b_output.txt", "E10_TASK_B_COMPLETE"),
    "TASK_C": ("task_c_output.txt", "E10_TASK_C_COMPLETE"),
    "TASK_D": ("task_d_output.txt", "E10_TASK_D_COMPLETE"),
    "TASK_E": ("task_e_output.txt", "E10_TASK_E_COMPLETE"),
}


def e10_specs() -> List[TaskSpec]:
    """Five interlocked tasks per the E10 section 9 graph."""
    def spec(key: str, depends: List[str], desc: str) -> TaskSpec:
        out_path, marker = MARKERS[key]
        return TaskSpec(
            key=key,
            name=f"{key} - {desc}",
            description=f"E10 scenario task {key}: {desc}",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=depends,
            acceptance_criteria=[
                f"file_exists:{out_path}",
                f"file_contains:{out_path}:{marker}",
            ],
            context={
                "task_key": key,
                "content": f"{marker}: {desc}",
                "output_path": out_path,
                "sleep_s": 0.15,
            },
        )

    return [
        spec("TASK_A", [], "foundation"),
        spec("TASK_B", ["TASK_A"], "left branch"),
        spec("TASK_C", ["TASK_A"], "right branch"),
        spec("TASK_D", ["TASK_B", "TASK_C"], "merge"),
        spec("TASK_E", ["TASK_D"], "final"),
    ]


def build_engine(artifacts_dir: str):
    """Build a production-contract engine (E9-R1: governed tool execution
    requires a grant validator — same pattern as E9-R/test_production_integration.py)."""
    from unified.execution import ExecutionEngine
    from unified.mission_controller import register_mission_agent

    engine = ExecutionEngine(
        artifacts_base_dir=str(artifacts_dir),
        grant_validator=lambda grant_id, permission: True,
    )
    register_mission_agent(engine.agent_registry, pool_size=4)
    return engine


def build_controller(engine, state_dir: str):
    from unified.mission_controller import MissionController
    return MissionController(engine, state_dir=str(state_dir))


def durable_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write JSON durably: flush + fsync file, then fsync the directory.

    The engine's own persistence uses atomic temp+replace but does not fsync;
    the scenario harness fsyncs every durable record so the SIGKILL that
    follows cannot lose acknowledged state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_file(path: Path) -> None:
    """fsync an engine-written durable file (checkpoint/events/evidence)."""
    with open(path, "rb") as f:
        os.fsync(f.fileno())
    fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def artifacts_snapshot(engine, mission_id: str) -> Dict[str, Any]:
    """Per-task artifact identity snapshot: {artifact_id, path, sha256, sandbox}."""
    tasks_by_sandbox = {}
    for tid, task in engine.tasks.items():
        tasks_by_sandbox[f"sandbox-{tid}"] = tid
    snap: Dict[str, Any] = {}
    for aid, art in engine.evidence_store._artifacts.items():
        if getattr(art, "mission_id", "") != mission_id:
            continue
        tid = tasks_by_sandbox.get(art.created_by, art.created_by)
        snap.setdefault(tid, []).append({
            "artifact_id": art.artifact_id,
            "name": art.name,
            "path": art.path,
            "sha256": art.sha256,
            "sandbox": art.created_by,
            "size_bytes": art.size_bytes,
        })
    return snap


def attempts_snapshot(engine) -> Dict[str, List[Dict[str, Any]]]:
    """Attempt ledger snapshot per task (E10 section 19 fields)."""
    snap: Dict[str, List[Dict[str, Any]]] = {}
    for att in engine.attempts.values():
        snap.setdefault(att.task_id, []).append({
            "attempt_id": att.attempt_id,
            "task_id": att.task_id,
            "agent_id": att.agent_id,
            "state": att.state.value if hasattr(att.state, "value") else str(att.state),
            "success": att.success,
            "error": att.error,
            "started_at": att.started_at.isoformat() if att.started_at else None,
            "completed_at": att.completed_at.isoformat() if att.completed_at else None,
        })
    for lst in snap.values():
        lst.sort(key=lambda a: (a["started_at"] or "", a["attempt_id"]))
    return snap


def evidence_snapshot(engine, mission_id: str) -> List[Dict[str, Any]]:
    out = []
    for ev in engine.evidence_store._evidence.values():
        if getattr(ev, "mission_id", "") != mission_id:
            continue
        out.append({
            "evidence_id": ev.evidence_id,
            "evidence_hash": ev.evidence_hash,
            "source_id": ev.source_id,
            "task_id": getattr(ev, "task_id", ""),
            "run_id": getattr(ev, "run_id", ""),
        })
    out.sort(key=lambda e: e["evidence_id"])
    return out
