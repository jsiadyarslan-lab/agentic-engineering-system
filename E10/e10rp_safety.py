#!/usr/bin/env python3
"""E10-RP SAFETY SCENARIO S2 — minimal replanning scope + non-plan failure.

Mission (plan v1): A -> B(tool failure, retry) -> C -> D -> E(deviates).
E is TERMINAL: nothing depends on E's output, so the only justified change
is E's own criteria (derived from E's observed artifact). Pre-registered
decision: NO invalidation, NO added tasks, NO rewiring — scope exactly the
affected task; A,B,C,D preserved and never re-executed.

B's first attempt is a REAL tool-layer failure (the production agent's
deterministic injection through the real sandbox filesystem). The engine
retry loop recovers it; scan_failures must classify it TOOL_RUNTIME_FAILURE
with recovery RETRY (resolved by engine retry) — a failure irrelevant to the
plan NEVER becomes a replanning decision.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from e10rp_common import (  # noqa: E402
    PRE_REGISTERED_EXPECTATIONS, S2, S2_E_PLAN_V1_EXPECTED, s2_specs_v1,
    build_engine, build_controller, durable_write_json,
    artifact_stat, journal_records,
)

EXP = PRE_REGISTERED_EXPECTATIONS["s2_minimal_scope"]


def phase_states(controller, run_id: str) -> Dict[str, str]:
    graph = controller.engine.task_graph.get(run_id, {})
    return {
        controller._task_to_key.get(tid, tid): (
            node["state"].value if hasattr(node["state"], "value") else str(node["state"])
        )
        for tid, node in graph.items()
    }


def attempts_len(controller, run_id: str, key: str) -> int:
    """Attempts for a task from the engine's live attempt ledger
    (engine._attempts is keyed by attempt_id; group by task_id — same
    grouping the full checkpoint persists as attempt_history)."""
    tid = controller._key_to_task.get(key, "")
    if not tid:
        return 0
    return sum(1 for a in controller.engine._attempts.values() if a.task_id == tid)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts-dir", required=True)
    ap.add_argument("--mc-state-dir", required=True)
    ap.add_argument("--evidence-dir", required=True)
    args = ap.parse_args()

    ev: Dict[str, Any] = {"pid": os.getpid()}
    evidence_dir = Path(args.evidence_dir)

    engine = build_engine(args.artifacts_dir, max_retries=1)  # retry enabled for the REAL tool failure
    controller = build_controller(engine, args.mc_state_dir, require_plan_review=True)
    from unified.contracts import EventType  # after engine build (path setup)

    mission, run, key_to_id = controller.define_mission(
        "E10-RP S2: minimal-scope replanning + non-plan failure classification", s2_specs_v1()
    )
    ev["mission_id"] = mission.mission_id
    ev["run_id"] = run.run_id
    a_id, b_id, c_id, d_id, e_id = (key_to_id[k] for k in "ABCDE")
    # Per-TASK retry budgets (execution.py:2146): B gets ONE real retry for
    # the injected tool failure; E gets ONE retry of the verification failure
    # (terminal at retry_count=1); A/C/D pass first try.
    engine.tasks[a_id].max_retries = 0
    engine.tasks[b_id].max_retries = 1
    engine.tasks[c_id].max_retries = 0
    engine.tasks[d_id].max_retries = 0
    engine.tasks[e_id].max_retries = 1
    controller.emit_marker(mission.mission_id, run.run_id, "E10RP_S2_PLAN_V1_DEFINED", {"plan_version": "v1"})

    rv1 = controller.review_plan(run.run_id, reviewer="e10rp-reviewer",
                                 note="S2 initial plan v1 review")
    assert rv1.verdict == "approved", rv1.reasons
    ev["review_v1"] = {"verdict": rv1.verdict}

    # ================= PHASE 1 =================
    result1 = await controller.execute_run(run.run_id, max_parallel=1)
    states_p1 = phase_states(controller, run.run_id)
    ev["phase1"] = {
        "states": states_p1,
        "task_results": {
            controller._task_to_key.get(tid, tid): {
                k: v for k, v in res.items() if k in ("success", "error", "attempts")
            }
            for tid, res in result1.get("task_results", {}).items()
        },
    }
    assert states_p1.get("A") == "COMPLETED" and states_p1.get("B") == "COMPLETED"
    assert states_p1.get("C") == "COMPLETED" and states_p1.get("D") == "COMPLETED"
    assert states_p1.get("E") == "FAILED", states_p1
    e_res = result1["task_results"][e_id]
    assert e_res.get("success") is False and "Verification failed" in str(e_res.get("error")), e_res
    ev["phase1"]["e_error"] = e_res.get("error")
    phase1_stats = {k: artifact_stat(engine, mission.mission_id, S2[k][0]) for k in "ABCDE"}
    ev["phase1"]["artifact_stats"] = phase1_stats
    attempts_p1 = {k: attempts_len(controller, run.run_id, k) for k in "ABCDE"}
    ev["phase1"]["attempts"] = attempts_p1
    # B failed ONCE for a real tool reason, then the engine retry recovered it:
    assert attempts_p1["B"] == 2, attempts_p1  # 1 failed (tool) + 1 success
    assert attempts_p1["E"] == 2, attempts_p1  # verification failure retried once, then terminal

    # ================= DETECT + CLASSIFY =================
    controller.emit_marker(mission.mission_id, run.run_id, "E10RP_S2_DEVIATION_OBSERVED",
                           {"task": "E", "error": e_res.get("error")})
    events_all = list(engine.event_bus.history)
    failures = controller.scan_failures(events_all, result1["task_results"])
    dev_E = next((f for f in failures if f.kind.value == "plan_deviation" and f.task_id == e_id), None)
    fail_B = next((f for f in failures if f.task_id == b_id), None)
    assert dev_E is not None, "E's plan deviation not detected"
    assert fail_B is not None, "B's first-attempt failure not detected"
    ev["classification"] = {
        "E": {"kind": dev_E.kind.value, "recovery": dev_E.recovery_action.value,
              "resolved": dev_E.resolved, "evidence": dev_E.evidence,
              "classification_reason": dev_E.classification_reason},
        "B": {"kind": fail_B.kind.value, "recovery": fail_B.recovery_action.value,
              "resolved": fail_B.resolved, "resolved_by": fail_B.resolved_by,
              "evidence": fail_B.evidence,
              "classification_reason": fail_B.classification_reason},
    }
    assert EXP["classification"]["E_kind"] == dev_E.kind.value
    assert EXP["classification"]["E_recovery"] == dev_E.recovery_action.value
    assert EXP["classification"]["B_first_attempt_kind"] == fail_B.kind.value
    assert EXP["classification"]["B_first_attempt_recovery"] == fail_B.recovery_action.value
    assert fail_B.kind.value == "tool_runtime_failure" and fail_B.recovery_action.value == "retry"
    assert fail_B.resolved and fail_B.resolved_by == "engine_retry_then_completed"
    assert not dev_E.resolved, "terminal deviation stays unresolved until replan"

    # ================= data-driven correction + minimal replan ===========
    e_art = engine.evidence_store.get_artifact(
        [a for a in engine.evidence_store._artifacts.values()
         if getattr(a, "mission_id", "") == mission.mission_id and a.path == S2["E"][0]][-1].artifact_id
    )
    text = e_art.decode("utf-8")
    corrected_marker = text.strip().splitlines()[0].split(":")[0].strip()
    assert corrected_marker == "E10RP_S2_E_REALITY_ACTUAL", corrected_marker
    corrected = [f"file_exists:{S2['E'][0]}", f"file_contains:{S2['E'][0]}:{corrected_marker}"]

    controller.emit_marker(mission.mission_id, run.run_id, "E10RP_S2_REPLAN_DECISION",
                           {"from": "v1", "to": "v2", "modified": {"E": corrected},
                            "invalidated": [], "added": [], "rewired": []})
    replan = controller.replan_mission(
        run_id=run.run_id,
        deviation=dev_E,
        invalidate_task_ids=[],           # nothing depends on E's output
        corrected_criteria={e_id: corrected},
        add_specs=[],                     # no remediation needed
        rewire={},                        # no dependents to rewire
        reason=(
            f"Deviation {dev_E.failure_id} at terminal task E: verification against "
            f"plan v1 assumption ('{S2_E_PLAN_V1_EXPECTED}') failed not_evidenced; E's "
            f"observed artifact defines the real contract ('{corrected_marker}'). "
            "E is terminal with no dependents: the minimal correct change is E's own "
            "criteria — nothing else in the plan is affected."
        ),
        plan_version="v2",
    )
    ev["replan_v1_to_v2"] = {
        "from_version": replan.from_version, "to_version": replan.to_version,
        "invalidated": replan.invalidated_tasks, "preserved": replan.preserved_tasks,
        "added": replan.added_tasks, "rewired": replan.rewired_dependencies,
        "modified": replan.modified_tasks, "reason": replan.reason,
        "evidence": replan.evidence,
    }
    assert replan.invalidated_tasks == EXP["replan_v1_to_v2"]["invalidated"] == []
    assert replan.added_tasks == [] and replan.rewired_dependencies == []
    assert replan.preserved_tasks == EXP["replan_v1_to_v2"]["preserved"], replan.preserved_tasks
    assert [m["task_key"] for m in replan.modified_tasks] == ["E"]

    # ================= gate refusals + rejected review =================
    def snap():
        return (
            len(engine.event_bus.history),
            {k: attempts_len(controller, run.run_id, k) for k in "ABCDE"},
        )

    gate_refusals: List[Dict[str, Any]] = []
    s0 = snap()
    try:
        await controller.execute_run(run.run_id, max_parallel=1)
        raise AssertionError("must REFUSE before v2 review")
    except RuntimeError as ex:
        assert "PLAN_REVIEW_GATE" in str(ex), str(ex)
        gate_refusals.append({"when": "unapproved v2", "error": str(ex)})
    assert snap() == s0

    rv2a = controller.review_plan(run.run_id, reviewer="e10rp-reviewer",
                                  note="review v2 while E is still FAILED")
    assert rv2a.verdict == "rejected"
    failing = [c["check"] for c in rv2a.checks if not c["passed"]]
    assert failing == ["C6_plan_executable_no_failed_tasks"], failing
    ev["review_v2_first"] = {"verdict": rv2a.verdict, "reasons": rv2a.reasons}
    s1 = snap()
    try:
        await controller.execute_run(run.run_id, max_parallel=1)
        raise AssertionError("must REFUSE after rejected review")
    except RuntimeError as ex:
        assert "PLAN_REVIEW_GATE" in str(ex), str(ex)
        gate_refusals.append({"when": "rejected review", "error": str(ex)})
    assert snap() == s1
    ev["gate_refusals"] = gate_refusals

    # ================= recover -> approve -> continuation ===============
    controller.recover_failed_task(run.run_id, e_id, reason="Plan corrected: E re-verified against observed contract")
    rv2b = controller.review_plan(run.run_id, reviewer="e10rp-reviewer",
                                  note="review v2 after E recovered")
    assert rv2b.verdict == "approved", rv2b.reasons
    ev["review_v2_second"] = {"verdict": rv2b.verdict}

    result2 = await controller.execute_run(run.run_id, max_parallel=1)
    states_p2 = phase_states(controller, run.run_id)
    ev["phase2"] = {"states": states_p2}
    assert states_p2.get("E") == "COMPLETED", states_p2
    assert result2["task_results"][e_id]["success"] is True

    attempts_after = {k: attempts_len(controller, run.run_id, k) for k in "ABCDE"}
    ev["preservation"] = {"attempts_after": attempts_after, "attempts_phase1": attempts_p1}
    # scope exactly the affected task: A,B,C,D untouched by the replan cycle
    assert attempts_after["A"] == attempts_p1["A"] == 1
    assert attempts_after["B"] == attempts_p1["B"] == 2
    assert attempts_after["C"] == attempts_p1["C"] == 1
    assert attempts_after["D"] == attempts_p1["D"] == 1
    assert attempts_after["E"] == attempts_p1["E"] + 1 == 3  # one corrected re-execution only

    journal_e = journal_records(engine, mission.mission_id, S2["E"][0])
    ev["journal_task_e"] = journal_e
    types = [r["record_type"] for r in journal_e]
    assert types[0] == "intent" and types[1] == "performed", types
    assert all(t == "reconciled" for t in types[2:]), types  # every re-execution adopts
    perf = journal_e[1]
    for r in journal_e[2:]:
        assert r["mtime_ns"] == perf["mtime_ns"] and r["inode"] == perf["inode"], "no rewrite ever"

    final_stats = {k: artifact_stat(engine, mission.mission_id, S2[k][0]) for k in "ABCDE"}
    ev["artifact_stats_final"] = final_stats
    for k in "ABCD":
        assert final_stats[k] == phase1_stats[k], f"{k} untouched"

    ok, report = controller.verify_completion(run.run_id, required_keys=["A", "B", "C", "D", "E"])
    assert ok, report
    fin = controller.finalize_mission(mission.mission_id, run.run_id)
    fin = fin if isinstance(fin, dict) else {"raw": str(fin)}
    ev["finalize"] = fin
    cp = controller.create_full_checkpoint(mission.mission_id, run.run_id, step=2)
    assert cp.verify()
    ev["final_checkpoint"] = {"checkpoint_id": cp.checkpoint_id, "hash": cp.hash}
    ev["finalize"] = fin

    ev["ledger_final"] = controller.ledger_snapshot()
    engine._save_events_to_disk(mission.mission_id)

    durable_write_json(evidence_dir / "s2_scenario.json", ev)
    print("E10RP_S2_SCENARIO_COMPLETE")
    print(json.dumps({
        "mission_id": mission.mission_id, "plan_version": controller.plan_version,
        "reviews": [(r.plan_version, r.verdict) for r in controller.plan_reviews],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
