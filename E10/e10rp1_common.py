#!/usr/bin/env python3
"""E10-RP1 shared scenario — canonical replanning path & review-gate
integration.

All cycles go through CanonicalOrchestrator.execute_mission — the REAL
operational path: real MissionController, real ExecutionEngine, real
ToolExecutor governed execution (E9-R). No mocks of production decision
logic.

TWO DISCLOSED CONTROL INPUTS (order §3 allowance — decision boundaries
only; neither is claimed to be independent planning, untested
self-intelligence, or a general replanning engine):
  1. ScriptedDecomposerProvider — a fixed, predetermined decomposition at
     the goal-decomposition (planning) boundary.
  2. The decision providers — the E10-RP-proven decision CONTENT at the
     replanning decision boundary:
       FullCycleDecisionProvider  — stage "replan" (v1->v2 decision) and
                                    stage "revision" (post-rejection
                                    recovery), the E10-RP sequence.
       BlockedDecisionProvider    — same replan decision, but NO revision:
                                    proves a rejected review blocks.
Everything else — deviation detection, classification, replan application,
review checks C1..C8, gate enforcement, continuation, verification — is
production code under test.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------- scenario

GOAL = ("E10-RP1 canonical integration proof: five-task mission with a "
        "controlled deviation at C, evidence-based replanning, review gate, "
        "and verified continuation")

C_PLAN_EXPECTED = "RP1_C_PLAN_EXPECTED"      # plan v1 assumption for C
C_REALITY = "RP1_C_REALITY_ACTUAL"           # what the agent ACTUALLY writes

PLAN_JSON = """[
  {"key": "A", "name": "Foundation A", "description": "Foundation task",
   "depends_on": [],
   "acceptance_criteria": ["file_contains:task_a.txt:RP1_A_OUTPUT"],
   "context": {"content": "RP1_A_OUTPUT", "output_path": "task_a.txt", "sleep_s": 0.05}},

  {"key": "B", "name": "Left branch B", "description": "Left branch",
   "depends_on": ["A"],
   "acceptance_criteria": ["file_contains:task_b.txt:RP1_B_OUTPUT"],
   "context": {"content": "RP1_B_OUTPUT", "output_path": "task_b.txt", "sleep_s": 0.05}},

  {"key": "C", "name": "Right branch C - controlled deviation",
   "description": "Right branch: writes observed reality that deviates from the plan v1 expectation",
   "depends_on": ["A"],
   "acceptance_criteria": ["file_contains:task_c.txt:""" + C_PLAN_EXPECTED + """\"],
   "context": {"content": \"""" + C_REALITY + """\", "output_path": "task_c.txt", "sleep_s": 0.05}},

  {"key": "D", "name": "Merge D", "description": "Merge built on the plan v1 expectation of C",
   "depends_on": ["B", "C"],
   "acceptance_criteria": ["file_contains:task_d.txt:RP1_D_OUTPUT"],
   "context": {"content": "RP1_D_OUTPUT", "output_path": "task_d.txt", "sleep_s": 0.05}},

  {"key": "E", "name": "Report E", "description": "Final report",
   "depends_on": ["D"],
   "acceptance_criteria": ["file_contains:task_e.txt:RP1_E_OUTPUT"],
   "context": {"content": "RP1_E_OUTPUT", "output_path": "task_e.txt", "sleep_s": 0.05}}
]"""

CORRECTED_C_CRITERIA = ["file_exists:task_c.txt",
                         "file_contains:task_c.txt:" + C_REALITY]

X_NAME = "X - remediation after deviation at C"


# ------------------------------------------------- control input #1 (planning)

class ScriptedDecomposerProvider:
    """DISCLOSED control input #1 — planning boundary.

    Returns a fixed, predetermined decomposition for GoalDecomposer's LLM
    call. Deterministic; no network; no claimed independent planning."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages):
        self.calls += 1
        return SimpleNamespace(content=PLAN_JSON)


# ---------------------------------------- control input #2 (replan decisions)

class FullCycleDecisionProvider:
    """DISCLOSED control input #2 — replanning decision boundary.

    stage="replan":  the E10-RP-proven decision content for the C-deviation
                     (invalidate D; correct C from its observed artifact; add
                     X after C; rewire E onto X; v1 -> v2).
    stage="revision": the post-rejection recovery of the corrected task —
                     exactly the E10-RP sequence (review #1 rejects because
                     C is still FAILED; only after recovery does review #2
                     approve)."""

    def __init__(self) -> None:
        self.replan_calls = 0
        self.revision_calls = 0
        self.log: list = []

    def __call__(self, stage, deviation=None, rejection=None,
                 controller=None, orchestrator=None, run_id=None):
        if stage == "replan":
            self.replan_calls += 1
            c_id = controller._key_to_task["C"]
            d_id = controller._key_to_task["D"]
            e_id = controller._key_to_task["E"]
            x_spec = {
                "name": X_NAME,
                "description": (
                    "Remediation task required by replan v2: covers the merge "
                    "contract under OBSERVED REALITY (built on C's actual "
                    "output), replacing the invalidated D whose product "
                    "embedded the plan v1 expectation."
                ),
                "agent_type": "implementer",
                "depends_on": [c_id],
                "acceptance_criteria": [
                    "file_exists:task_x.txt",
                    "file_contains:task_x.txt:RP1_X_OUTPUT",
                ],
                "context": {
                    "task_key": "X",
                    "content": "RP1_X_OUTPUT: remediation merge under observed reality",
                    "output_path": "task_x.txt",
                    "sleep_s": 0.05,
                },
            }
            self.log.append({"stage": "replan", "deviation": deviation.failure_id,
                             "task_key": deviation.task_key})
            return {
                "reason": (
                    f"Deviation {deviation.failure_id} at task C: verification "
                    f"against the plan v1 assumption ('{C_PLAN_EXPECTED}') "
                    "failed with verdict not_evidenced; the observed artifact "
                    f"defines the real contract ('{C_REALITY}'). D (whose "
                    "product embeds the invalidated expectation) is removed; "
                    "remediation X covers the merge under reality; E is "
                    "rewired onto X; C's criteria are corrected to observed "
                    "reality."
                ),
                "next_version": "v2",
                "invalidate_task_ids": [d_id],
                "corrected_criteria": {c_id: list(CORRECTED_C_CRITERIA)},
                "add_specs": [x_spec],
                "rewire": {e_id: ["NEW:X"]},
            }
        if stage == "revision":
            self.revision_calls += 1
            self.log.append({"stage": "revision",
                             "rejected_checks": [c for c in (rejection.checks or []) if not c.get("passed")]})
            return {"recover_task_ids": [controller._key_to_task["C"]]}
        return None


class BlockedDecisionProvider(FullCycleDecisionProvider):
    """Same replan decision, but stage="revision" returns None — after the
    first v2 review rejection there is no correction: the plan must stay
    blocked (proves rejected review blocks continuation)."""

    def __call__(self, stage, deviation=None, rejection=None,
                 controller=None, orchestrator=None, run_id=None):
        if stage == "revision":
            self.revision_calls += 1
            self.log.append({"stage": "revision", "decision": None})
            return None
        return super().__call__(stage, deviation=deviation, rejection=rejection,
                                 controller=controller, orchestrator=orchestrator,
                                 run_id=run_id)


# ------------------------------------------------------------ expectations

PRE_REGISTERED_EXPECTATIONS = {
    "written_before_any_cycle": True,
    "note": ("Fixed BEFORE observing any outcome (order §4 discipline). "
             "Success criteria are never changed after the fact."),
    "run_a_full_cycle": {
        "result": {"success": True, "final_state": "EVIDENCED"},
        "reviews": ["approved", "rejected", "approved"],
        "review_v2_first_failing_check": "C6_plan_executable_no_failed_tasks",
        "replan": {"from_version": "v1", "to_version": "v2",
                   "invalidated": ["D"], "preserved": ["A", "B"],
                   "added": ["X"], "rewired": {"E": ["X"]}, "modified": ["C"]},
        "attempts_per_key": {"A": 1, "B": 1, "C": 4, "X": 1, "E": 1, "D": 0},
        "journal_performed_per_path": {
            "task_a.txt": 1, "task_b.txt": 1, "task_c.txt": 1,
            "task_x.txt": 1, "task_e.txt": 1},
        "journal_reconciled_task_c": 3,
        "files": {"task_d.txt": "absent", "task_c.txt": "contains " + C_REALITY,
                  "task_x.txt": "present", "task_e.txt": "present"},
        "ordering_invariants": {
            "no_attempt_before_v1_review": True,
            "no_attempt_between_replan_and_v2_approval": True,
            "first_continuation_attempt_after_v2_approval": True,
            "replan_lt_reject_lt_recover_lt_approve": True,
        },
        "duplicate_continuation": {"zero_new_attempts": True,
                                   "journal_unchanged": True,
                                   "result_success": True},
    },
    "run_b_blocked_cycle": {
        "result": {"success": False, "final_state": "PLAN_REVIEW_REJECTED"},
        "reviews": ["approved", "rejected"],
        "review_v2_failing_check": "C6_plan_executable_no_failed_tasks",
        "attempts_per_key": {"A": 1, "B": 1, "C": 3, "X": 0, "E": 0, "D": 0},
        "c_final_state": "FAILED",
        "zero_attempts_after_rejection": True,
        "files": {"task_d.txt": "absent", "task_x.txt": "absent",
                  "task_e.txt": "absent"},
    },
}


# ---------------------------------------------------------------- helpers

def durable_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _pv(payload, name, default=None):
    if hasattr(payload, "get"):
        return payload.get(name, default)
    return getattr(payload, name, default)


def dedup_attempts(events):
    """task_id -> [attempt_id, ...] — TASK_ASSIGNED is emitted twice per
    attempt; dedup by attempt_id (same rule as build_reexecution_ledger)."""
    out: dict = {}
    first_ts: dict = {}
    for e in events:
        if getattr(e, "event_type", None) is None or e.event_type.value != "task.assigned":
            continue
        tid = _pv(e.payload, "task_id", "")
        aid = _pv(e.payload, "attempt_id", "")
        if not tid:
            continue
        bucket = out.setdefault(tid, [])
        if aid not in bucket:
            bucket.append(aid)
            first_ts[aid] = e.timestamp
    return out, first_ts


def journal_records(state_dir: Path, mission_id: str) -> list:
    p = Path(state_dir) / "side_effect_journal" / mission_id / "journal.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def payload_out(payload):
    if hasattr(payload, "model_dump"):
        return payload.model_dump(mode="json")
    if isinstance(payload, dict):
        return payload
    return str(payload)


def events_jsonl(events) -> list:
    return [{
        "event_type": e.event_type.value,
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        "correlation_id": e.correlation_id,
        "source": e.source,
        "payload": payload_out(e.payload),
    } for e in events]
