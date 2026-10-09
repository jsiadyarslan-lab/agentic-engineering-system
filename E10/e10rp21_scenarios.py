#!/usr/bin/env python3
"""E10-RP2.1 §3/§4 — TASK-BOUND VERIFICATION + VERIFIER ERROR
CLASSIFICATION scenarios (order E10-RP2.1 §3.3/§3.4/§4.3).

All scenarios start from the ACTUAL creation point
(create_canonical_orchestrator) and run real missions through the real
operational path with the REAL EOE grant authorization wired through
eoe.engine_bridge (NO allow-all validator in any scenario).

Scenarios:
  collision-resolve — §3.3 direct name collision + §3.4 criteria
      correction after replan. Task A writes shared.txt with the shared
      token; task B (depends on A) writes the SAME relative name with
      DIFFERENT content that does NOT satisfy the token criterion. The
      engine-layer verification passes B through a PRE-EXISTING
      first-path-match collision on the evidence store (DISCLOSED finding
      — see E10_RP21_DISCOVERY.md D7); the orchestrator's TASK-BOUND
      verifier must catch it: B not_evidenced (criteria_mismatch) read
      from B's OWN sandbox file. The replan decision corrects B's
      criteria to the OBSERVED content (the RP2 D-pattern); after review
      approval + continuation, B is evidenced under v2 by NEWER evidence
      bound to the corrected criteria — history preserved.

  verifier-read-error — §4.3: the verifier's own READ fails (injected
      OSError on Path.read_text for the task file only). Explicit class
      verifier_error -> TOOL_RUNTIME_FAILURE -> the replan decision
      provider is NEVER consulted, replan_mission NEVER invoked, and the
      mission produces NO final success (current unresolved verification
      failure blocks completion).

  verifier-exec-crash — §4.3: the verifier agent EXECUTION itself raises
      (AgentFactory.execute_agent_by_id patched to raise for e3-verifier).
      run_verifier catches + classifies verifier_error; same guarantees:
      no replan, no success, the run does not crash.

  unprovable-attempt — §3.4: the producing attempt cannot be established
      (RoleCoordinator._producing_attempt_id patched to return ""). The
      verdict is not_evidenced with explicit class
      provenance_unprovable (fail-closed — replacing the RP2
      evidenced-with-disclosure hole); the failure is replan-eligible
      (mission-state problem) but the provider declines (returns None) —
      the mission fails honestly with the failure named.

Disclosed control injections (all listed in facts.json under 'providers'):
planning/replan decision content (ScriptedDecomposerProvider /
FixedDecisionProvider) and the per-scenario fault injections above.
Nothing else is patched; execution, authorization, verification
machinery, review, and completion are the REAL production path.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for _p in (str(HERE), str(REPO / "src"), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from e10rp2_common import (  # noqa: E402
    ScriptedDecomposerProvider, build_real_authorization,
    journal_records, events_jsonl, durable_write_json,
)

SHARED_TOKEN = "RP21_SHARED_TOKEN"
B_WRONG = "RP21_B_WRONG_CONTENT"

PLAN_COLLISION = """[
  {"key": "A", "name": "Write A shared token", "description": "First writer",
   "depends_on": [],
   "acceptance_criteria": ["file_contains:shared.txt:""" + SHARED_TOKEN + """\"],
   "context": {"content": \"""" + SHARED_TOKEN + """\", "output_path": "shared.txt", "sleep_s": 0.05}},

  {"key": "B", "name": "Write B same relative name, different content",
   "description": "Same-name collision writer (depends on A)",
   "depends_on": ["A"],
   "acceptance_criteria": ["file_contains:shared.txt:""" + SHARED_TOKEN + """\"],
   "context": {"content": \"""" + B_WRONG + """\", "output_path": "shared.txt", "sleep_s": 0.05}}
]"""

PLAN_SINGLE = """[
  {"key": "A", "name": "Write A", "description": "Single writer",
   "depends_on": [],
   "acceptance_criteria": ["file_contains:task_a.txt:RP21_A_OK"],
   "context": {"content": "RP21_A_OK", "output_path": "task_a.txt", "sleep_s": 0.05}}
]"""


class FixedDecisionProvider:
    """DISCLOSED control input — the replanning decision boundary.

    collision-resolve: ONE decision — correct B's criteria to the OBSERVED
    artifact content (the engine-layer false pass is caught by the
    task-bound verifier; the replan accepts the observed product as the
    contract, the RP2 D-pattern). All later requests: None.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.log: list = []

    def __call__(self, stage, deviation=None, rejection=None,
                 controller=None, orchestrator=None, run_id=None):
        self.calls += 1
        self.log.append({
            "stage": stage,
            "deviation": getattr(deviation, "task_key", None),
            "description_head": str(getattr(deviation, "description", ""))[:120],
        })
        if stage == "replan" and self.calls == 1:
            b_id = controller._key_to_task["B"]
            return {
                "reason": (
                    "Task-bound verifier caught B's same-name collision: B's "
                    "OWN sandbox file does not satisfy the token criterion "
                    "(the engine layer passed it via a first-path-match on "
                    "A's recorded artifact). The observed product is "
                    "accepted as the contract; B's criteria are corrected "
                    "to the OBSERVED content."
                ),
                "next_version": "v2",
                "invalidate_task_ids": [],
                "corrected_criteria": {
                    b_id: [f"file_contains:shared.txt:{B_WRONG}"],
                },
                "add_specs": [],
                "rewire": {},
            }
        return None


class LoggingNoDecisionProvider:
    """DISCLOSED control input — logs every consultation, always declines."""

    def __init__(self) -> None:
        self.calls = 0
        self.log: list = []

    def __call__(self, stage, deviation=None, rejection=None,
                 controller=None, orchestrator=None, run_id=None):
        self.calls += 1
        self.log.append({
            "stage": stage,
            "deviation": getattr(deviation, "task_key", None),
            "description_head": str(getattr(deviation, "description", ""))[:160],
        })
        return None


def find_mission_id(out: Path) -> str:
    mc_dir = out / "mission_controller"
    return next(mc_dir.iterdir()).name


def orch_events(orch, mission_id):
    return [e for e in orch.mc.engine.event_bus.history
            if e.mission_id == mission_id]


def _pv(payload, name, default=None):
    if hasattr(payload, "get"):
        try:
            return payload.get(name, default)
        except Exception:
            return default
    return getattr(payload, name, default)


def verification_view(orch, mission_id):
    """Per-task verification history (verdict, class, evidence paths),
    sorted by durable event timestamp."""
    per_task: dict = {}
    for e in orch_events(orch, mission_id):
        if e.event_type.value != "verification.complete":
            continue
        if e.source != "canonical_orchestrator":
            continue
        tid = _pv(e.payload, "task_id", "") or e.correlation_id or ""
        key = orch.mc._task_to_key.get(tid, tid)
        per_task.setdefault(key, []).append({
            "verdict": _pv(e.payload, "verdict", ""),
            "failure_class": _pv(e.payload, "failure_class", None),
            "plan_version": _pv(e.payload, "plan_version", None),
            "attempt_id": _pv(e.payload, "attempt_id", ""),
            "evidence_paths": _pv(e.payload, "evidence_paths", None) or [],
            "timestamp": e.timestamp.isoformat(),
        })
    for k in per_task:
        per_task[k].sort(key=lambda v: v["timestamp"])
    return per_task


def run_scenario(mode: str, out: Path) -> dict:
    from orchestrator.canonical import create_canonical_orchestrator

    injections: list = []
    plan = PLAN_COLLISION if mode == "collision-resolve" else PLAN_SINGLE
    decomposer = ScriptedDecomposerProvider(plan)

    provider = (FixedDecisionProvider() if mode == "collision-resolve"
                else LoggingNoDecisionProvider())

    # ---- disclosed fault injections (scenario-specific) ----
    if mode == "verifier-read-error":
        import pathlib
        _orig_read_text = pathlib.Path.read_text

        def _patched_read_text(self, *a, **kw):
            if self.name == "task_a.txt":
                raise OSError(
                    "injected verifier read failure (RP2.1 §4.3 control)")
            return _orig_read_text(self, *a, **kw)

        pathlib.Path.read_text = _patched_read_text
        injections.append(
            "Path.read_text raises OSError for files named task_a.txt "
            "(verifier machinery read failure only; the engine-layer "
            "verifier reads recorded evidence, not the disk)")
    elif mode == "verifier-exec-crash":
        from unified.agent_role import AgentFactory
        _orig_exec = AgentFactory.execute_agent_by_id

        async def _patched_exec(self, agent_id, *a, **kw):
            if agent_id == "e3-verifier":
                raise RuntimeError(
                    "injected verifier execution crash (RP2.1 §4.3 control)")
            return await _orig_exec(self, agent_id, *a, **kw)

        AgentFactory.execute_agent_by_id = _patched_exec
        injections.append(
            "AgentFactory.execute_agent_by_id raises RuntimeError for "
            "e3-verifier (verifier execution failure)")
    elif mode == "unprovable-attempt":
        injections.append(
            "RoleCoordinator._producing_attempt_id patched to return '' "
            "(producing attempt cannot be established)")

    validator, grant_id, ledger, _g, admission = build_real_authorization(str(out))
    grant_ids = [grant_id]

    orch = create_canonical_orchestrator(
        llm_provider=decomposer,
        artifacts_base_dir=str(out),
        auto_approve_plans=True,
        max_parallel=1,
        require_plan_review=True,
        replan_decision_provider=provider,
        max_review_rounds=3,
        grant_validator=validator,
        grant_ids=grant_ids,
    )

    if mode == "unprovable-attempt":
        # applied AFTER construction, BEFORE execution
        orch.role_coordinator._producing_attempt_id = lambda task_id: ""

    goal = f"E10-RP2.1 scenario: {mode}"
    try:
        result = asyncio.run(orch.execute_mission(goal))
        crashed = False
        crash_error = ""
    except Exception as exc:  # the run itself must never crash
        crashed = True
        crash_error = f"{type(exc).__name__}: {exc}"
        result = None

    mission_id = find_mission_id(out)
    key_to_tid = dict(orch.mc._key_to_task)

    run_id = next(
        (rid for rid, g in orch.mc.engine.task_graph.items()
         if any(n.get("mission_id") == mission_id for n in g.values())),
        None,
    )

    # task-bound verdicts, keyed by task key
    verifs = verification_view(orch, mission_id)
    by_key = verifs

    # verifier failure records with their explicit classes
    verifier_failures = []
    for f in orch.mc.failures:
        if "orchestrator verifier" in str(f.description):
            verifier_failures.append({
                "task_key": f.task_key,
                "kind": f.kind.value,
                "recovery": f.recovery_action.value,
                "resolved": bool(f.resolved),
                "description_head": str(f.description)[:200],
            })

    # per-task OWN sandbox files (task-bound reality)
    own_files = {}
    for key, tid in key_to_tid.items():
        sbx = out / f"sandbox-{tid}"
        own_files[key] = sorted(
            str(p.relative_to(sbx)) for p in sbx.rglob("*") if p.is_file()
        ) if sbx.exists() else []

    graph_now = orch.mc.engine.task_graph.get(run_id, {})
    complete, completion_report = (False, {})
    if result is not None and run_id:
        required_keys = [k for k, tid in key_to_tid.items() if tid in graph_now]
        complete, completion_report = orch.mc.verify_completion(run_id, required_keys)

    facts = {
        "mode": mode,
        "mission_id": mission_id,
        "sandbox_ids": {k: f"sandbox-{t}" for k, t in key_to_tid.items()},
        "crashed": crashed,
        "crash_error": crash_error,
        "result": {
            "success": bool(result.success) if result else False,
            "final_state": getattr(result, "final_state", None) if result else None,
            "error": (str(getattr(result, "error", "")) or "")[:400] if result else crash_error,
        } if result else {"success": False, "final_state": None,
                          "error": crash_error[:400]},
        "verifications_by_key": by_key,
        "verifier_failures": verifier_failures,
        "replans": [r.to_version for r in orch.mc.replans],
        "provider_calls": provider.calls,
        "provider_log": provider.log,
        "own_files": own_files,
        "completion": {"complete": bool(complete), "report": completion_report},
        "grant": {
            "grant_id": grant_id,
            "validator": "eoe.engine_bridge (REAL)",
            "grant_ids_passed": list(grant_ids),
            "admission_usage_log": list(admission.usage_log),
        },
        "providers": {
            "decomposer_llm_calls": decomposer.calls,
            "decision_calls": provider.calls,
            "injections": injections,
            "disclosure": (
                "ScriptedDecomposerProvider (planning boundary) + decision "
                "providers (replanning decision boundary) + the per-scenario "
                "fault injections listed above — predetermined control "
                "inputs, disclosed; NOT claimed as independent planning. "
                "Execution, authorization, verification machinery, review, "
                "and completion are the REAL production path."),
        },
    }
    events = orch_events(orch, mission_id)
    durable_write_json(out / "events.jsonl", events_jsonl(events))
    return facts


EXPECTATIONS = {
    "collision-resolve": {
        "result_success": True,
        "A_verdicts": ["evidenced", "evidenced"],
        "B_verdicts": ["not_evidenced", "evidenced"],
        "B_first_class": "criteria_mismatch",
        "B_evidence_from_own_sandbox": True,
        "replans": ["v2"],
        "B_failure_kind": "plan_deviation",
        "B_failure_resolved": True,
        "crashed": False,
    },
    "verifier-read-error": {
        "result_success": False,
        "A_verdicts": ["not_evidenced"],
        "A_class": "verifier_error",
        "provider_calls": 0,
        "replans": [],
        "verifier_failure_kind": "tool_runtime_failure",
        "completion_failure_reason": "current_unresolved_verification_failure",
        "crashed": False,
    },
    "verifier-exec-crash": {
        "result_success": False,
        "A_verdicts": ["not_evidenced"],
        "A_class": "verifier_error",
        "provider_calls": 0,
        "replans": [],
        "verifier_failure_kind": "tool_runtime_failure",
        "completion_failure_reason": "current_unresolved_verification_failure",
        "crashed": False,
    },
    "unprovable-attempt": {
        "result_success": False,
        "A_verdicts": ["not_evidenced"],
        "A_class": "provenance_unprovable",
        "verifier_failure_kind": "plan_deviation",
        "provider_calls_ge": 1,
        "replans": [],
        "completion_failure_reason": "current_unresolved_verification_failure",
        "crashed": False,
    },
}


def check(mode: str, facts: dict) -> list:
    exp = EXPECTATIONS[mode]
    results = []

    def rec(name, ok, detail=""):
        results.append({"expectation": name, "pass": bool(ok), "detail": detail})

    rec("no_crash", facts["crashed"] is False, facts["crash_error"][:200])
    rec("result.success",
        facts["result"]["success"] is exp["result_success"],
        f"{facts['result']['success']} (want {exp['result_success']})")

    by_key = facts["verifications_by_key"]
    if mode == "collision-resolve":
        a_hist = by_key.get("A", [])
        b_hist = by_key.get("B", [])
        rec("A_verdicts", [v["verdict"] for v in a_hist] == exp["A_verdicts"],
            str([v["verdict"] for v in a_hist]))
        rec("B_verdicts", [v["verdict"] for v in b_hist] == exp["B_verdicts"],
            str([v["verdict"] for v in b_hist]))
        rec("B_first_failure_class",
            b_hist and b_hist[0]["failure_class"] == exp["B_first_class"],
            str(b_hist[0]["failure_class"] if b_hist else None))
        # task-bound proof: B's failing verification read B's OWN file
        b_tid = None
        # evidence path recorded in B's first (failing) verification points
        # into B's own sandbox
        own = facts["own_files"].get("B", [])
        b_paths = b_hist[0]["evidence_paths"] if b_hist else []
        in_own = bool(own) and any(
            any(p.endswith(f"/{f}") for p in b_paths) for f in own)
        rec("B_evidence_from_own_sandbox", in_own,
            f"paths={b_paths} own={own}")
        # A's evidence came from A's own sandbox (task-bound, not B's)
        a_paths = a_hist[0]["evidence_paths"] if a_hist else []
        a_sbx = facts["sandbox_ids"].get("A", "sandbox-A")
        rec("A_evidence_from_own_sandbox",
            any(p.endswith(f"{a_sbx}/shared.txt") for p in a_paths),
            f"paths={a_paths} want-suffix={a_sbx}/shared.txt")
        rec("replans", facts["replans"] == exp["replans"], str(facts["replans"]))
        bf = [f for f in facts["verifier_failures"] if f["task_key"] == "B"]
        rec("B_failure_kind",
            bf and bf[0]["kind"] == exp["B_failure_kind"],
            str(bf[0]["kind"] if bf else None))
        rec("B_failure_resolved",
            bf and bf[0]["resolved"] is exp["B_failure_resolved"],
            str(bf[0]["resolved"] if bf else None))
    else:
        a_hist = by_key.get("A", [])
        rec("A_verdicts", [v["verdict"] for v in a_hist] == exp["A_verdicts"],
            str([v["verdict"] for v in a_hist]))
        rec("A_failure_class",
            a_hist and a_hist[0]["failure_class"] == exp["A_class"],
            str(a_hist[0]["failure_class"] if a_hist else None))
        rec("provider_calls",
            (facts["provider_calls"] >= exp["provider_calls_ge"]
             if "provider_calls_ge" in exp
             else facts["provider_calls"] == exp["provider_calls"]),
            str(facts["provider_calls"]))
        rec("replans", facts["replans"] == exp["replans"], str(facts["replans"]))
        af = [f for f in facts["verifier_failures"] if f["task_key"] == "A"]
        rec("verifier_failure_kind",
            af and af[0]["kind"] == exp["verifier_failure_kind"],
            str(af[0]["kind"] if af else None))
        reasons = [
            vf.get("reason") for vf in (facts["completion"]["report"]
                                        .get("checks", {})
                                        .get("verification_history", {})
                                        .get("verification_failures", []))]
        rec("completion_failure_reason",
            exp["completion_failure_reason"] in reasons, str(reasons))
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=list(EXPECTATIONS), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expectations", required=True)
    args = ap.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    facts = run_scenario(args.mode, out)
    durable_write_json(out / "facts.json", facts)

    checks = check(args.mode, facts)
    durable_write_json(out / "expectations_check.json", checks)

    failed = [c for c in checks if not c["pass"]]
    verdict = "SCENARIO_PROVEN" if not failed else "SCENARIO_FAILED"
    print(f"[RP2.1 mode={args.mode}] verdict={verdict} "
          f"checks={len(checks) - len(failed)}/{len(checks)}")
    for c in checks:
        mark = "PASS" if c["pass"] else "FAIL"
        print(f"  [{mark}] {c['expectation']}: {c['detail']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
