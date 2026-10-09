#!/usr/bin/env python3
"""E10-RP2 shared scenario — CANONICAL EXECUTION AUTHORIZATION &
VERIFICATION TRUTH.

All cycles go through CanonicalOrchestrator.execute_mission — the REAL
operational path: real MissionController, real ExecutionEngine, real
ToolExecutor governed execution (E9-R), and (new in RP2) the REAL EOE
grant authorization wired through eoe.engine_bridge.

DISCLOSED CONTROL INPUTS (decision boundaries only — same class as
E10-RP1, never claimed as independent planning):
  1. ScriptedDecomposerProvider — fixed decomposition at the planning
     boundary.
  2. The decision providers — replanning decision CONTENT at the
     decision boundary. The v2 decision deliberately carries a WRONG
     criteria correction for preserved task C (a realistic wrong
     decision); the verifier layer must CATCH it (this is the point of
     §4.2/§4.3 — the truth rule, not the decision, protects completion).
Everything else — deviation detection, classification, replan
application, review checks C1..C8, gate enforcement, continuation,
verification, per-task completion truth — is production code under test.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------- scenario

GOAL = ("E10-RP2 verification-truth proof: four-task mission, engine-level "
        "deviation at D, a WRONG criteria correction on preserved C at v2 "
        "caught by the verifier, then resolution with newer valid evidence")

A_OUTPUT = "RP2_A_OUTPUT"
C_REALITY = "RP2_C_REALITY_ACTUAL"        # what C ACTUALLY writes (v1 criteria match it)
C_WRONG_GUESS = "RP2_C_WRONG_GUESS"       # the v2 decision's WRONG tightening for C
D_PLAN_EXPECTED = "RP2_D_PLAN_EXPECTED"   # v1 plan assumption for D
D_REALITY = "RP2_D_REALITY_ACTUAL"        # what D ACTUALLY writes (engine deviation)
X_OUTPUT = "RP2_X_OUTPUT"
E_OUTPUT = "RP2_E_OUTPUT"

PLAN_JSON = """[
  {"key": "A", "name": "Foundation A", "description": "Foundation task",
   "depends_on": [],
   "acceptance_criteria": ["file_contains:task_a.txt:RP2_A_OUTPUT"],
   "context": {"content": "RP2_A_OUTPUT", "output_path": "task_a.txt", "sleep_s": 0.05}},

  {"key": "C", "name": "Right branch C", "description": "Right branch (v1 criteria match reality)",
   "depends_on": ["A"],
   "acceptance_criteria": ["file_contains:task_c.txt:""" + C_REALITY + """\"],
   "context": {"content": \"""" + C_REALITY + """\", "output_path": "task_c.txt", "sleep_s": 0.05}},

  {"key": "D", "name": "Merge D - controlled engine-level deviation",
   "description": "Merge built on the plan v1 expectation of C",
   "depends_on": ["C"],
   "acceptance_criteria": ["file_contains:task_d.txt:""" + D_PLAN_EXPECTED + """\"],
   "context": {"content": \"""" + D_REALITY + """\", "output_path": "task_d.txt", "sleep_s": 0.05}},

  {"key": "E", "name": "Report E", "description": "Final report",
   "depends_on": ["D"],
   "acceptance_criteria": ["file_contains:task_e.txt:RP2_E_OUTPUT"],
   "context": {"content": "RP2_E_OUTPUT", "output_path": "task_e.txt", "sleep_s": 0.05}}
]"""

CORRECTED_D_CRITERIA = ["file_contains:task_d.txt:" + D_REALITY]
WRONG_C_CRITERIA = ["file_contains:task_c.txt:" + C_WRONG_GUESS]
REALITY_C_CRITERIA = ["file_contains:task_c.txt:" + C_REALITY]

X_NAME = "X - remediation after engine deviation at D"

# Simple 2-task mission for the authorization / tool-failure cases.
PLAN_JSON_SIMPLE = """[
  {"key": "A", "name": "Write A", "description": "First write",
   "depends_on": [],
   "acceptance_criteria": ["file_contains:auth_a.txt:RP2_AUTH_A"],
   "context": {"content": "RP2_AUTH_A", "output_path": "auth_a.txt", "sleep_s": 0.02}},

  {"key": "B", "name": "Write B", "description": "Second write (depends on A)",
   "depends_on": ["A"],
   "acceptance_criteria": ["file_contains:auth_b.txt:RP2_AUTH_B"],
   "context": {"content": "RP2_AUTH_B", "output_path": "auth_b.txt", "sleep_s": 0.02}}
]"""

PLAN_JSON_TOOLFAIL = """[
  {"key": "A", "name": "Write A", "description": "First write",
   "depends_on": [],
   "acceptance_criteria": ["file_contains:tf_a.txt:RP2_TF_A"],
   "context": {"content": "RP2_TF_A", "output_path": "tf_a.txt", "sleep_s": 0.02}},

  {"key": "B", "name": "Write B with first-attempt tool failure",
   "description": "Real tool failure on attempt 1, engine retry recovers",
   "depends_on": ["A"],
   "acceptance_criteria": ["file_contains:tf_b.txt:RP2_TF_B"],
   "context": {"content": "RP2_TF_B", "output_path": "tf_b.txt", "sleep_s": 0.02,
               "fail_attempt_1": "tool_runtime"}}
]"""


# ------------------------------------------------- control input #1 (planning)

class ScriptedDecomposerProvider:
    """DISCLOSED control input #1 — planning boundary (same class as RP1)."""

    def __init__(self, plan_json: str = PLAN_JSON) -> None:
        self.calls = 0
        self._plan_json = plan_json

    async def complete(self, messages):
        self.calls += 1
        return SimpleNamespace(content=self._plan_json)


# ---------------------------------------- control input #2 (replan decisions)

class ResolutionDecisionProvider:
    """DISCLOSED control input #2 — decision boundary.

    stage="replan" (1st, engine deviation at D): v1->v2 — invalidate E,
    correct D's criteria to observed reality, and (deliberately WRONG)
    tighten preserved C's criteria to a guess that does NOT match C's
    artifact. The verifier layer must catch this wrong correction.
    stage="revision": recover D after the v2 review rejects (C6: D FAILED).
    stage="replan" (2nd, verifier failure at C): v2->v3 — correct C's
    criteria to the OBSERVED artifact content (reality)."""

    def __init__(self) -> None:
        self.replan_calls = 0
        self.revision_calls = 0
        self.verifier_replan_calls = 0
        self.log: list = []

    def __call__(self, stage, deviation=None, rejection=None,
                 controller=None, orchestrator=None, run_id=None):
        if stage == "replan":
            is_verifier_deviation = "orchestrator verifier" in str(
                getattr(deviation, "description", ""))
            if not is_verifier_deviation and self.replan_calls == 0:
                self.replan_calls += 1
                d_id = controller._key_to_task["D"]
                e_id = controller._key_to_task["E"]
                c_id = controller._key_to_task["C"]
                x_spec = {
                    "name": X_NAME,
                    "description": (
                        "Remediation task required by replan v2: covers the "
                        "report contract under OBSERVED REALITY, replacing "
                        "the invalidated E whose plan assumed D's v1 product."
                    ),
                    "agent_type": "implementer",
                    "depends_on": [d_id],
                    "acceptance_criteria": [
                        "file_exists:task_x.txt",
                        "file_contains:task_x.txt:" + X_OUTPUT,
                    ],
                    "context": {
                        "task_key": "X",
                        "content": X_OUTPUT + ": remediation report under observed reality",
                        "output_path": "task_x.txt",
                        "sleep_s": 0.05,
                    },
                }
                self.log.append({
                    "stage": "replan", "which": "engine-deviation-D",
                    "deviation": getattr(deviation, "failure_id", None),
                    "task_key": getattr(deviation, "task_key", None)})
                return {
                    "reason": (
                        f"Deviation {getattr(deviation, 'failure_id', '')} at task D: "
                        "verification against the plan v1 assumption failed; the "
                        "observed artifact defines the real contract. E (whose plan "
                        "assumed D's v1 product) is removed; remediation X covers "
                        "the report under reality; D's criteria are corrected to "
                        "observed reality; C's criteria are tightened to the "
                        "suspected contract (a deliberately WRONG guess — the "
                        "verifier layer must catch it if it does not match C's "
                        "actual artifact)."
                    ),
                    "next_version": "v2",
                    "invalidate_task_ids": [e_id],
                    "corrected_criteria": {
                        d_id: list(CORRECTED_D_CRITERIA),
                        c_id: list(WRONG_C_CRITERIA),
                    },
                    "add_specs": [x_spec],
                    "rewire": {},
                }
            # second replan: verifier-detected deviation at C
            self.verifier_replan_calls += 1
            c_id = controller._key_to_task["C"]
            self.log.append({
                "stage": "replan", "which": "verifier-deviation-C",
                "deviation": getattr(deviation, "failure_id", None),
                "task_key": getattr(deviation, "task_key", None)})
            return {
                "reason": (
                    "Verifier-detected deviation at task C: the v2 criteria "
                    "correction does not match C's observed artifact; the "
                    "criteria are corrected to the OBSERVED artifact content "
                    "(reality). No task invalidation: C's product is intact; "
                    "only its criteria contract was wrong."
                ),
                "next_version": "v3",
                "invalidate_task_ids": [],
                "corrected_criteria": {c_id: list(REALITY_C_CRITERIA)},
                "add_specs": [],
                "rewire": {},
            }
        if stage == "revision":
            self.revision_calls += 1
            self.log.append({"stage": "revision",
                             "rejected_checks": [c for c in (rejection.checks or []) if not c.get("passed")]})
            return {"recover_task_ids": [controller._key_to_task["D"]]}
        return None


class MixedBlockedDecisionProvider(ResolutionDecisionProvider):
    """Same first replan (v2 with the WRONG C correction), but the
    verifier-detected deviation at C receives NO second decision: the
    failure must stay unresolved and completion must FAIL (the §4.2 mixed
    case — no false success)."""

    def __call__(self, stage, deviation=None, rejection=None,
                 controller=None, orchestrator=None, run_id=None):
        if stage == "replan" and self.replan_calls >= 1:
            is_verifier_deviation = "orchestrator verifier" in str(
                getattr(deviation, "description", ""))
            if is_verifier_deviation:
                self.verifier_replan_calls += 1
                self.log.append({"stage": "replan", "which": "verifier-deviation-C",
                                 "decision": None})
                return None
        return super().__call__(stage, deviation=deviation, rejection=rejection,
                                 controller=controller, orchestrator=orchestrator,
                                 run_id=run_id)


# --------------------------------------------------- real EOE authorization

def build_real_authorization(artifacts_root: str, *, scope: str = "read_write",
                             revoke: bool = False, cover_other_dir: bool = False):
    """Real EOE authorization stack wired to the governed engine path.

    The OWNER side runs with a caller-supplied runtime key (the grants
    contract's prescribed injection — engineering never signs): propose ->
    (owner approval) -> approve -> ledger.register. The ENGINE side gets
    the bridge validator built on AccessAdmission (fail-closed).

    Returns (validator, grant_id, ledger, grantor, admission).
    """
    from eoe.access_gateway import AccessAdmission, AccessLedger, GrantorService
    from eoe.engine_bridge import build_engine_grant_validator
    from eoe.order_parser import AccessRequest, GrantKind

    key = os.urandom(32)  # grantor key — caller-supplied at runtime
    ledger = AccessLedger()
    grantor = GrantorService(key)
    admission = AccessAdmission(ledger, grantor, now=time.time)

    target = artifacts_root
    if cover_other_dir:
        target = tempfile.mkdtemp(prefix="rp2_uncovered_")
    request = AccessRequest(kind=GrantKind.PATH_GRANT, scope=scope, target=target)
    proposal = grantor.propose(request)          # PENDING — awaiting owner
    approved = grantor.approve(proposal)         # signed + APPROVED
    ledger.register(approved)
    if revoke:
        ledger.revoke(approved.grant_id)
    validator = build_engine_grant_validator(admission, artifacts_root)
    return validator, approved.grant_id, ledger, grantor, admission


# ------------------------------------------------------------ expectations

PRE_REGISTERED_EXPECTATIONS = {
    "written_before_any_cycle": True,
    "note": ("Fixed BEFORE observing any outcome (order §4 discipline). "
             "Success criteria are never changed after the fact."),
    "run_resolution_cycle": {
        "result": {"success": True},
        "reviews": ["approved", "rejected", "approved", "approved"],
        "replans": [
            {"from_version": "v1", "to_version": "v2", "invalidated": ["E"],
             "modified": ["C", "D"], "added": ["X"]},
            {"from_version": "v2", "to_version": "v3", "invalidated": [],
             "modified": ["C"], "added": []},
        ],
        "verifier_failure_recorded_for_C": True,
        "verifier_failure_resolved_by_newer_evidence": True,
        "mixed_state_seen": True,   # A evidenced while C not_evidenced (v2 round)
        "C_latest_verdict": "evidenced",
        "C_criteria_version": "v3",
        "historical_not_evidenced_preserved": True,
        "attempts_per_key": {"A": 1, "C": 1, "D": 4, "X": 1, "E": 0},
        "attempts_note": ("D=4 calibrated in diagnostic round #1 (a crashed run, "
                          "disclosed in the report): the engine retries the "
                          "verification-failed task (initial + 2 retries) then the "
                          "recovered re-execution completes — same observed "
                          "pattern as E10-RP1's C=4. Never relaxed after a "
                          "passing run."),
        "files": {"task_a.txt": "present", "task_c.txt": "present",
                  "task_d.txt": "present", "task_x.txt": "present",
                  "task_e.txt": "absent"},
        "duplicate_continuation": {"zero_new_attempts": True,
                                   "journal_unchanged": True},
    },
    "run_mixed_blocked_cycle": {
        "result": {"success": False},
        "reviews": ["approved", "rejected", "approved"],
        "replans": [
            {"from_version": "v1", "to_version": "v2", "invalidated": ["E"],
             "modified": ["C", "D"], "added": ["X"]},
        ],
        "verifier_failure_recorded_for_C": True,
        "verifier_failure_resolved_by_newer_evidence": False,
        "C_latest_verdict": "not_evidenced",
        "completion_check_failed_reason": "current_unresolved_verification_failure",
        "attempts_per_key": {"A": 1, "C": 1, "D": 4, "X": 1, "E": 0},
    },
    "auth_cases": {
        "allow": {"result_success": True, "files_written": True,
                  "grant_state": "APPROVED", "permission_errors": 0},
        "deny_revoked": {"result_success": False, "files_written": False,
                         "permission_errors_min": 1},
        "deny_read_only": {"result_success": False, "files_written": False,
                           "permission_errors_min": 1},
        "deny_path_uncovered": {"result_success": False, "files_written": False,
                                "permission_errors_min": 1},
        "missing_validator": {"result_success": False, "files_written": False,
                              "error_contains": "no validator available"},
        "missing_grants": {"result_success": False, "files_written": False,
                           "error_contains": "lacks required permission"},
    },
    "tool_fail_case": {
        "result_success": True,
        "B_attempts": 2,
        "replans": 0,
        "verifier_failures": 0,
        "no_unjustified_replan": True,
    },
}


# ---------------------------------------------------------------- helpers

def durable_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(__import__("json").dumps(obj, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _pv(payload, name, default=None):
    if hasattr(payload, "get"):
        return payload.get(name, default)
    return getattr(payload, name, default)


def dedup_attempts(events):
    """task_id -> [attempt_id, ...] (same rule as E10-RP1)."""
    out: dict = {}
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
    return out


def journal_records(state_dir: Path, mission_id: str) -> list:
    import json as _json
    p = Path(state_dir) / "side_effect_journal" / mission_id / "journal.jsonl"
    if not p.exists():
        return []
    return [_json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


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
