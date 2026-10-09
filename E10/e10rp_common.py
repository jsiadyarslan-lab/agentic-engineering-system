#!/usr/bin/env python3
"""E10-RP — EVIDENCE-BASED REPLANNING: shared scenario definition + PRE-REGISTERED
expected decisions (fixed BEFORE any run; success criteria are never changed
after observing outcomes — order §4).

Everything runs on the REAL production path:
MissionController.define_mission -> review_plan -> execute_run ->
ExecutionEngine.execute_task_graph -> agent reservation -> MissionTaskAgent
-> ToolExecutor("artifact_write") -> SandboxManager -> SideEffectJournal
(E9-R1 governed path + E10-CW1-R1 intent-first journal).

Main scenario graph (plan v1):

    A (foundation)
     |
    B ----------+
                 +-- D -- E
    C (DEVIATES) +

C is a CONTROLLED, KNOWN deviation INPUT: its agent durably writes observed
reality while plan v1's acceptance expects the plan's assumption. D's product
embeds that expectation ("built-on <plan-v1 assumption>"), so the deviation
invalidates D; remediation task X covers the contract under reality; E is
rewired onto X.
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

MISSION_REQUEST_MAIN = (
    "E10-RP evidence-based replanning proof: produce governed artifacts "
    "through a controlled plan deviation, an evidence-based replanning "
    "decision, plan v2 review, and verified continuation."
)

# ---- markers (main scenario) ---------------------------------------------
M = {
    "A": ("task_a.txt", "E10RP_A_OUTPUT"),
    "B": ("task_b.txt", "E10RP_B_OUTPUT"),
    # The deviation input: plan v1 expects C_PLAN_V1_EXPECTED, the agent
    # (observed reality) writes C_REALITY_ACTUAL.
    "C": ("task_c.txt", "E10RP_C_REALITY_ACTUAL"),
    "D": ("task_d.txt", "E10RP_D_OUTPUT built-on E10RP_C_PLAN_V1_EXPECTED"),
    "E": ("task_e.txt", "E10RP_E_FINAL"),
    # remediation task added by replan v2 (built on observed reality):
    "X": ("task_x.txt", "E10RP_X_OUTPUT built-on E10RP_C_REALITY_ACTUAL"),
}
C_PLAN_V1_EXPECTED = "E10RP_C_PLAN_V1_EXPECTED"


def main_specs_v1() -> List[TaskSpec]:
    """Plan v1. Acceptance criteria are the PLAN'S EXPECTATIONS:
      - C's criterion expects the plan v1 ASSUMPTION (the deviation input),
      - D's criterion embeds that assumption in its product contract."""
    def spec(key: str, depends: List[str], desc: str, crit_sub: str) -> TaskSpec:
        out_path, content_marker = M[key]
        return TaskSpec(
            key=key,
            name=f"{key} - {desc}",
            description=f"E10-RP main scenario task {key}: {desc}",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=depends,
            acceptance_criteria=[
                f"file_exists:{out_path}",
                f"file_contains:{out_path}:{crit_sub}",
            ],
            context={
                "task_key": key,
                "content": f"{content_marker}: {desc}",
                "output_path": out_path,
                "sleep_s": 0.05,
            },
        )

    return [
        spec("A", [], "foundation", "E10RP_A_OUTPUT"),
        spec("B", ["A"], "left branch", "E10RP_B_OUTPUT"),
        # plan v1 acceptance expects the PLAN'S ASSUMPTION, not reality:
        spec("C", ["A"], "right branch — CONTROLLED DEVIATION INPUT", C_PLAN_V1_EXPECTED),
        # D's product contract embeds the plan v1 expectation:
        spec("D", ["B", "C"], "merge — product embeds plan v1 expectation",
             "built-on E10RP_C_PLAN_V1_EXPECTED"),
        spec("E", ["D"], "final deliverable", "E10RP_E_FINAL"),
    ]


X_ADD_SPEC = {
    "name": "X - remediation after deviation at C",
    "description": (
        "Remediation task required by replan v2: covers the merge contract "
        "under OBSERVED REALITY (built on C's actual output), replacing the "
        "invalidated D whose product embedded the plan v1 expectation."
    ),
    "agent_type": "implementer",
    "depends_on": [],  # resolved by replan_mission onto C's real task_id
    "acceptance_criteria": [
        f"file_exists:{M['X'][0]}",
        f"file_contains:{M['X'][0]}:E10RP_X_OUTPUT",
    ],
    "context": {
        "task_key": "X",
        "content": f"{M['X'][1]}: remediation merge under observed reality",
        "output_path": M["X"][0],
        "sleep_s": 0.05,
    },
}

# ---- S2 scenario (minimal scope + non-plan failure) ------------------------
S2 = {
    "A": ("task_s2_a.txt", "E10RP_S2_A_OUTPUT"),
    "B": ("task_s2_b.txt", "E10RP_S2_B_OUTPUT"),
    "C": ("task_s2_c.txt", "E10RP_S2_C_OUTPUT"),
    "D": ("task_s2_d.txt", "E10RP_S2_D_OUTPUT"),
    "E": ("task_s2_e.txt", "E10RP_S2_E_REALITY_ACTUAL"),
}
S2_E_PLAN_V1_EXPECTED = "E10RP_S2_E_PLAN_V1_EXPECTED"


def s2_specs_v1() -> List[TaskSpec]:
    def spec(key: str, depends: List[str], desc: str) -> TaskSpec:
        out_path, content_marker = S2[key]
        if key == "E":
            crit = [
                f"file_exists:{out_path}",
                f"file_contains:{out_path}:{S2_E_PLAN_V1_EXPECTED}",
            ]
        else:
            crit = [
                f"file_exists:{out_path}",
                f"file_contains:{out_path}:{content_marker}",
            ]
        ctx: Dict[str, Any] = {
            "task_key": key,
            "content": f"{content_marker}: {desc}",
            "output_path": out_path,
            "sleep_s": 0.05,
        }
        if key == "B":
            # REAL deterministic first-attempt tool failure (the agent's
            # built-in injection through the real sandbox layer), recovered
            # by the engine retry loop — a failure IRRELEVANT to the plan.
            ctx["fail_attempt_1"] = "tool_runtime"
        return TaskSpec(
            key=key,
            name=f"S2-{key} - {desc}",
            description=f"E10-RP S2 scenario task {key}: {desc}",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=depends,
            acceptance_criteria=crit,
            context=ctx,
        )

    return [
        spec("A", [], "foundation"),
        spec("B", ["A"], "second — real tool failure then retry"),
        spec("C", ["B"], "third"),
        spec("D", ["C"], "fourth"),
        spec("E", ["D"], "terminal — CONTROLLED DEVIATION INPUT (minimal scope)"),
    ]


# ---- PRE-REGISTERED EXPECTATIONS (order §4: fixed before any run) ----------
PRE_REGISTERED_EXPECTATIONS: Dict[str, Any] = {
    "main": {
        "phase1_plan_v1": {
            "A": "COMPLETED",
            "B": "COMPLETED",
            "C": "FAILED_VERIFICATION_NOT_EVIDENCED",
            "D": "BLOCKED_NEVER_STARTED",
            "E": "BLOCKED_NEVER_STARTED",
            "agent_claim_overturned_by_verifier": True,
        },
        "classification": {
            "C_kind": "plan_deviation",
            "C_recovery": "replan",
        },
        "replan_v1_to_v2": {
            "invalidated": ["D"],
            "preserved": ["A", "B"],
            "added": [{"key": "X", "depends_on": ["C"]}],
            "rewired": [{"key": "E", "depends_on": ["X"]}],
            "modified": {"C": "criteria_derived_from_observed_artifact"},
        },
        "gate": {
            "unapproved_v2_refused_before_execution": True,
            "rejected_review_refused_before_execution": True,
            "refusals_leave_zero_execution": True,
        },
        "review_v2": {
            "first_verdict": "REJECTED",
            "first_failing_check": "C6_plan_executable_no_failed_tasks",
            "after_recovery_verdict": "APPROVED",
        },
        "phase2_continuation": {
            "C": "COMPLETED_UNDER_CORRECTED_CRITERIA",
            "X": "COMPLETED",
            "E": "COMPLETED",
            "A_B_not_reexecuted": True,
            "C_artifact_adopted_without_rewrite": True,
        },
        "final_outcome": "VERIFY_COMPLETION_PASS__FINALIZE_EVIDENCED__FULL_CHECKPOINT",
        "duplicate_continuation": "ZERO_NEW_SIDE_EFFECTS",
    },
    "s1_insufficient_evidence": {
        "claim_without_failure_record_is_classified": False,
        "claim_without_failure_record_triggers_replan": False,
        "agent_claim_success_overturned_by_verification": True,
    },
    "s2_minimal_scope": {
        "phase1": {
            "A": "COMPLETED", "B": "COMPLETED_after_real_tool_retry",
            "C": "COMPLETED", "D": "COMPLETED",
            "E": "FAILED_VERIFICATION_NOT_EVIDENCED",
        },
        "classification": {
            "E_kind": "plan_deviation",
            "E_recovery": "replan",
            "B_first_attempt_kind": "tool_runtime_failure",
            "B_first_attempt_recovery": "retry",
            "B_failure_resolved_by": "engine_retry_then_completed",
            "B_failure_never_replans": True,
        },
        "replan_v1_to_v2": {
            "invalidated": [],
            "preserved": ["A", "B", "C", "D"],
            "added": [],
            "rewired": [],
            "modified": {"E": "criteria_derived_from_observed_artifact"},
            "scope_exactly_affected_task_only": True,
        },
        "phase2": {
            "E": "COMPLETED_UNDER_CORRECTED_CRITERIA",
            "A_B_C_D_not_reexecuted": True,
        },
    },
}


def build_engine(artifacts_dir: str, max_retries: int = 0):
    """Production-contract engine (E9-R1: governed tool execution requires a
    grant validator — same pattern as E9-R/test_production_integration.py)."""
    from unified.execution import ExecutionEngine
    from unified.mission_controller import register_mission_agent

    engine = ExecutionEngine(
        artifacts_base_dir=str(artifacts_dir),
        max_retries=max_retries,
        grant_validator=lambda grant_id, permission: True,
    )
    register_mission_agent(engine.agent_registry, pool_size=4)
    return engine


def build_controller(engine, state_dir: str, require_plan_review: bool = True):
    from unified.mission_controller import MissionController
    return MissionController(engine, state_dir=str(state_dir),
                             require_plan_review=require_plan_review)


def durable_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write JSON durably: flush + fsync file, then fsync the directory
    (same contract as the E10 harness)."""
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


def artifact_stat(engine, mission_id: str, out_path: str):
    """(mtime_ns, inode, sha256) of a governed artifact file on disk, or None."""
    import hashlib

    base = Path(engine.artifacts_base_dir)
    hits = []
    for sandbox_dir in base.glob("sandbox-task-*"):
        cand = sandbox_dir / out_path
        if cand.exists():
            hits.append(cand)
    if not hits:
        return None
    p = hits[0]
    st = p.stat()
    return {
        "mtime_ns": st.st_mtime_ns,
        "inode": st.st_ino,
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "size": st.st_size,
    }


def journal_records(engine, mission_id: str, out_path: str) -> List[Dict[str, Any]]:
    """All journal records for a given artifact path (any task)."""
    p = Path(engine.artifacts_base_dir) / "side_effect_journal" / mission_id / "journal.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("path") == out_path:
            out.append(rec)
    return out
