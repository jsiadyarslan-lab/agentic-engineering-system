#!/usr/bin/env python3
"""E10-CW1-R1 BASELINE GAP DEMONSTRATION — the order §2 target gap, shown
EMPIRICALLY against the code at the R1 baseline (d8b0620) via a detached
git worktree, and (as a sanity control) against the FIXED tree.

The scenario is the EXACT R1-B boundary: the production adapter completes
the physical write; the process dies by REAL SIGKILL BEFORE the engine
records the outcome (`performed`). Then a NEW process performs the SAME
logical governed write (same mission_id/task_id/path/content).

  BASELINE (d8b0620): SideEffectJournal has NO record for the operation ->
  absence of a record is treated as a NEW operation -> the physical write is
  RE-PERFORMED (mtime_ns changes, a fresh artifact id, the effect happens
  twice). This is the pre-existing failure the order targets. It is never a
  pass of any acceptance criterion.

  FIXED (this tree): the durable `intent` record (written BEFORE the effect)
  lets the resuming process recognize the SAME logical operation -> ADOPT
  without rewriting (mtime_ns/inode/sha256 unchanged, planned identity kept).

Usage:
  python3 e10cw1r1_baseline_gap.py <workdir> <mode:process_a|process_b>
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from e10_common import build_engine, durable_write_json  # noqa: E402

MISSION = "m-gap-demo"
TASK = "task-gap-demo"
SANDBOX = "sandbox-task-gap-demo"
PATH = "gap_demo.txt"
CONTENT = "GAP-DEMO-PAYLOAD-0123456789"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def journal_scan(artifacts_dir: Path) -> dict:
    p = artifacts_dir / "side_effect_journal" / MISSION / "journal.jsonl"
    if not p.exists():
        return {"exists": False, "records": []}
    recs = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return {"exists": True, "records": recs}


def file_stat(f: Path):
    if not f.exists():
        return None
    import hashlib
    st = f.stat()
    return {"mtime_ns": st.st_mtime_ns, "inode": st.st_ino,
            "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}


async def process_a(workdir: str) -> None:
    """Die by SIGKILL at the exact R1-B boundary: write completed, outcome
    never journaled. The durable marker proves the boundary state."""
    work = Path(workdir)
    artifacts_dir = work / "artifacts"
    evidence_dir = work / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    print(f"[GAP_DEMO_A] pid={pid} start={utcnow()}")

    engine = build_engine(artifacts_dir)
    from unified.contracts import new_attempt_id
    from unified.agent_role import AgentType
    from unified.execution import ExecutionContext
    context = ExecutionContext(
        mission_id=MISSION, run_id="r-gap", task_id=TASK,
        attempt_id=new_attempt_id(), agent_id="", agent_type=AgentType.IMPLEMENTER,
        sandbox_id=SANDBOX,
    )
    f = artifacts_dir / SANDBOX / PATH
    real_write = engine.sandbox_manager.write_artifact

    async def wrapped(sandbox_id, path, content, artifact_id=None):
        if sandbox_id == SANDBOX and path == PATH:
            # the REAL production adapter performs the physical write
            if artifact_id is not None:
                artifact = await real_write(sandbox_id, path, content, artifact_id=artifact_id)
            else:
                artifact = await real_write(sandbox_id, path, content)
            scan = journal_scan(artifacts_dir)
            marker = {
                "injection_point": "B_pre_journal (R1-B boundary)",
                "reached_at_utc": utcnow(),
                "process_pid": pid,
                "kill_signal": "SIGKILL",
                "boundary_state": {
                    "file": file_stat(f),
                    "journal_exists": scan["exists"],
                    "journal_records_for_this_operation": [
                        r for r in scan["records"]
                        if r.get("task_id") == TASK and r.get("path") == PATH
                    ],
                    "artifact_id_from_adapter": artifact.artifact_id,
                },
                "lifecycle_position": (
                    "the physical write COMPLETED (real adapter); the engine "
                    "has NOT written any outcome record for this operation"
                ),
            }
            durable_write_json(evidence_dir / "injection.json", marker)
            print(f"[GAP_DEMO_A] boundary reached: file written, journal records for op = "
                  f"{len(marker['boundary_state']['journal_records_for_this_operation'])}; killing")
            os.kill(pid, signal.SIGKILL)
        return await real_write(sandbox_id, path, content)

    engine.sandbox_manager.write_artifact = wrapped
    await engine.execute_tool(context, "artifact_write",
                              {"sandbox_id": SANDBOX, "path": PATH, "content": CONTENT})
    raise SystemExit("FATAL: injection never fired")


async def process_b(workdir: str) -> None:
    """A NEW OS process performs the SAME logical governed write. What happens
    to the physical file reveals whether the pre-performed window is closed."""
    work = Path(workdir)
    artifacts_dir = work / "artifacts"
    evidence_dir = work / "evidence"
    pid = os.getpid()
    injection = json.loads((evidence_dir / "injection.json").read_text())
    pre = injection["boundary_state"]["file"]
    f = artifacts_dir / SANDBOX / PATH

    engine = build_engine(artifacts_dir)
    from unified.contracts import new_attempt_id
    from unified.agent_role import AgentType
    from unified.execution import ExecutionContext
    context = ExecutionContext(
        mission_id=MISSION, run_id="r-gap", task_id=TASK,
        attempt_id=new_attempt_id(), agent_id="", agent_type=AgentType.IMPLEMENTER,
        sandbox_id=SANDBOX,
    )
    result = await engine.execute_tool(context, "artifact_write",
                                       {"sandbox_id": SANDBOX, "path": PATH, "content": CONTENT})
    post = file_stat(f)
    scan = journal_scan(artifacts_dir)
    op_records = [r for r in scan["records"] if r.get("task_id") == TASK and r.get("path") == PATH]
    outcome = {
        "process_b_pid": pid,
        "process_a_pid": injection["process_pid"],
        "pid_difference": pid != injection["process_pid"],
        "tool_success": result.success,
        "result_artifact_id": result.output.get("artifact_id") if result.success else None,
        "adapter_artifact_id_at_crash": injection["boundary_state"]["artifact_id_from_adapter"],
        "file_mtime_ns_before_resume": pre["mtime_ns"],
        "file_mtime_ns_after_resume": post["mtime_ns"],
        "file_inode_before_resume": pre["inode"],
        "file_inode_after_resume": post["inode"],
        "PHYSICAL_WRITE_RE_PERFORMED": (
            post["mtime_ns"] != pre["mtime_ns"] or post["inode"] != pre["inode"]
        ),
        "identity_preserved": bool(
            result.success
            and result.output.get("artifact_id") == injection["boundary_state"]["artifact_id_from_adapter"]
        ),
        "journal_records_for_op_after_resume": [
            {"record_type": r.get("record_type"), "performed_via": r.get("performed_via"),
             "artifact_id": r.get("artifact_id"), "process_pid": r.get("process_pid")}
            for r in op_records
        ],
        "verdict": None,  # filled by the caller
    }
    # BASELINE behaviour = the write is re-performed (the gap).
    # FIXED behaviour = adoption without rewrite.
    if outcome["PHYSICAL_WRITE_RE_PERFORMED"]:
        outcome["verdict"] = "GAP_DEMONSTRATED__SIDE_EFFECT_EXECUTED_TWICE"
    else:
        outcome["verdict"] = "WINDOW_CLOSED__ADOPTED_WITHOUT_REWRITE"
    durable_write_json(evidence_dir / "process_b_gap_demo.json", outcome)
    print(f"[GAP_DEMO_B] pid={pid}: {outcome['verdict']}")
    print(f"[GAP_DEMO_B]   mtime before={pre['mtime_ns']} after={post['mtime_ns']}")
    print(f"[GAP_DEMO_B]   journal records for op: {outcome['journal_records_for_op_after_resume']}")


if __name__ == "__main__":
    asyncio.run(process_a(sys.argv[1]) if sys.argv[2] == "process_a" else process_b(sys.argv[1]))
