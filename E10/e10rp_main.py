#!/usr/bin/env python3
"""E10-RP MAIN SCENARIO — the full replanning cycle on the REAL production
path, single process, every phase marked durably in the event log:

  MISSION -> PLAN V1 -> REVIEW v1 (approved) -> TASK EXECUTION (phase 1:
  A,B complete; C deviates -> verification not_evidenced) ->
  OBSERVED DEVIATION (TASK_FAILED) -> EVIDENCE ->
  [S1: claim WITHOUT record -> no classification, no replan] ->
  REPLANNING DECISION (PLAN_DEVIATION -> replan) ->
  PLAN V2 (invalidate D; add X; rewire E; correct C from observed reality) ->
  GATE REFUSAL (unapproved v2) -> REVIEW v2 REJECTED (C still FAILED) ->
  GATE REFUSAL (rejected review) -> RECOVER C -> REVIEW v2 APPROVED ->
  CONTINUATION (phase 2: C,X,E complete; A,B never re-executed; C's artifact
  adopted without rewrite) -> VERIFIED OUTCOME (verify_completion + finalize
  EVIDENCED + full checkpoint) -> DUPLICATE CONTINUATION (zero new effects).

Every assertion is checked against PRE_REGISTERED_EXPECTATIONS (fixed before
the run; success criteria never changed after observing outcomes).
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
    MISSION_REQUEST_MAIN, M, C_PLAN_V1_EXPECTED,
    PRE_REGISTERED_EXPECTATIONS, X_ADD_SPEC, main_specs_v1,
    build_engine, build_controller, durable_write_json,
    artifact_stat, journal_records,
)

EXP = PRE_REGISTERED_EXPECTATIONS["main"]
EXP_S1 = PRE_REGISTERED_EXPECTATIONS["s1_insufficient_evidence"]


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

    ev: Dict[str, Any] = {"pid": os.getpid(), "phases": []}
    evidence_dir = Path(args.evidence_dir)

    engine = build_engine(args.artifacts_dir, max_retries=0)
    controller = build_controller(engine, args.mc_state_dir, require_plan_review=True)
    from unified.contracts import EventType  # after engine build (path setup)

    def mark(trigger: str, detail: Dict[str, Any]) -> None:
        controller.emit_marker(ev["mission_id"], ev["run_id"], trigger, detail)

    # ================= MISSION + PLAN V1 =================
    mission, run, key_to_id = controller.define_mission(MISSION_REQUEST_MAIN, main_specs_v1())
    ev["mission_id"] = mission.mission_id
    ev["run_id"] = run.run_id
    ev["key_to_id"] = dict(key_to_id)
    mark("E10RP_PLAN_V1_DEFINED", {"tasks": ["A", "B", "C", "D", "E"], "plan_version": "v1"})
    plan_v1 = controller.record_plan_v1(run.run_id, mission.mission_id)
    ev["plan_v1"] = plan_v1

    a_id, b_id = key_to_id["A"], key_to_id["B"]
    c_id, d_id, e_id = key_to_id["C"], key_to_id["D"], key_to_id["E"]

    # The retry budget is per-TASK (execution.py:2146 uses task.max_retries,
    # default 2). The deviation must be terminal on its FIRST attempt so the
    # cycle is deterministic: 0 retries for every task in this scenario.
    for t in engine.tasks.values():
        t.max_retries = 0

    # ================= REVIEW v1 (before any execution) =================
    rv1 = controller.review_plan(run.run_id, reviewer="e10rp-reviewer",
                                 note="initial plan v1 review before phase 1")
    ev["review_v1"] = {
        "review_id": rv1.review_id, "verdict": rv1.verdict,
        "checks": [{k: c[k] for k in ("check", "passed")} for c in rv1.checks],
    }
    assert rv1.verdict == "approved", f"review v1 must approve: {rv1.reasons}"

    # ================= PHASE 1: execution under plan v1 =================
    result1 = await controller.execute_run(run.run_id, max_parallel=1)
    states_p1 = phase_states(controller, run.run_id)
    ev["phase1"] = {
        "states": states_p1,
        "task_results": {
            controller._task_to_key.get(tid, tid): {
                k: v for k, v in res.items() if k in ("success", "error", "terminal", "attempts")
            }
            for tid, res in result1.get("task_results", {}).items()
        },
    }
    exp1 = EXP["phase1_plan_v1"]
    assert states_p1.get("A") == "COMPLETED" == exp1["A"], states_p1
    assert states_p1.get("B") == "COMPLETED" == exp1["B"], states_p1
    assert states_p1.get("C") == "FAILED", f"C must fail verification: {states_p1}"
    assert states_p1.get("D") == "BLOCKED" and states_p1.get("E") == "BLOCKED", states_p1
    c_res = result1["task_results"][c_id]
    assert c_res.get("success") is False and "Verification failed" in str(c_res.get("error")), c_res
    ev["phase1"]["c_error"] = c_res.get("error")
    attempts_p1 = {k: attempts_len(controller, run.run_id, k) for k in ("A", "B", "C", "D", "E")}
    ev["phase1"]["attempts"] = attempts_p1

    # The deviation input is KNOWN; the verifier overturned the agent's
    # claimed success with the real file content (not_evidenced) — S1b.
    c_art = engine.evidence_store.get_artifact(
        [a for a in engine.evidence_store._artifacts.values()
         if getattr(a, "mission_id", "") == mission.mission_id and a.path == M["C"][0]][-1].artifact_id
    )
    assert c_art and b"E10RP_C_REALITY_ACTUAL" in c_art, "C must have durably written observed reality"
    assert EXP_S1["agent_claim_success_overturned_by_verification"] is True
    ev["phase1"]["agent_claim_overturned"] = {
        "agent_wrote_artifact": True,
        "artifact_content_has_reality_marker": True,
        "verifier_verdict": "not_evidenced",
        "task_result": "success=False error='Verification failed: not_evidenced'",
    }
    phase1_stats = {k: artifact_stat(engine, mission.mission_id, M[k][0]) for k in ("A", "B", "C")}
    ev["phase1"]["artifact_stats"] = phase1_stats

    # ================= OBSERVED DEVIATION -> EVIDENCE =================
    mark("E10RP_DEVIATION_OBSERVED", {"task": "C", "error": c_res.get("error")})
    history = list(engine.event_bus.history)
    events_all = history

    # ---- S1: a deviation CLAIM without the failure RECORD --------------
    # (drop C's TASK_FAILED from the stream: an unevidenced claim must not
    # be classified, must not change the plan, must not replan)
    events_no_record = [
        e for e in events_all
        if not (e.event_type == EventType.TASK_FAILED and e.correlation_id == c_id)
    ]
    failures_no_record = controller.scan_failures(events_no_record, result1["task_results"])
    deviation_claim_no_record = [
        f for f in failures_no_record
        if f.kind.value == "plan_deviation" and f.task_id == c_id
    ]
    assert not deviation_claim_no_record, "claim WITHOUT record was classified!"
    assert controller.plan_version == "v1" and not controller.replans
    ev["s1_insufficient_evidence"] = {
        "claim_without_failure_record_is_classified": False,
        "claim_without_failure_record_triggers_replan": False,
        "scan_failures_without_the_record_returns_for_C": [],
        "note": "no FailureRecord -> no classification -> no replan decision possible",
    }

    # ---- the REAL deviation record (from the durable event stream) ------
    failures = controller.scan_failures(events_all, result1["task_results"])
    deviation = next(
        (f for f in failures if f.kind.value == "plan_deviation" and f.task_id == c_id), None
    )
    assert deviation is not None, f"plan deviation not detected: {[(f.kind.value, f.task_key) for f in failures]}"
    assert deviation.recovery_action.value == "replan", deviation.recovery_action
    assert deviation.evidence, "deviation record must carry evidence"
    ev["deviation_record"] = {
        "failure_id": deviation.failure_id,
        "kind": deviation.kind.value,
        "task": deviation.task_key,
        "task_id": deviation.task_id,
        "recovery_action": deviation.recovery_action.value,
        "evidence": deviation.evidence,
        "classification_reason": deviation.classification_reason,
        "resolved": deviation.resolved,
    }
    assert EXP["classification"]["C_kind"] == deviation.kind.value
    assert EXP["classification"]["C_recovery"] == deviation.recovery_action.value

    # ================= REPLANNING DECISION -> PLAN V2 =================
    # Data-driven correction: derive C's real contract from its OWN artifact
    # (observed reality), exactly as the e33 pattern.
    text = c_art.decode("utf-8")
    corrected_marker = text.strip().splitlines()[0].split(":")[0].strip()
    assert corrected_marker == "E10RP_C_REALITY_ACTUAL", corrected_marker
    corrected_criteria = [
        f"file_exists:{M['C'][0]}",
        f"file_contains:{M['C'][0]}:{corrected_marker}",
    ]
    x_spec = dict(X_ADD_SPEC)
    x_spec["depends_on"] = [c_id]  # X covers the merge under reality, after C
    mark("E10RP_REPLAN_DECISION", {
        "from": "v1", "to": "v2",
        "invalidated": ["D"], "added": ["X"], "rewired": {"E": ["NEW:X"]},
        "corrected": {"C": corrected_criteria},
    })
    replan = controller.replan_mission(
        run_id=run.run_id,
        deviation=deviation,
        invalidate_task_ids=[d_id],
        corrected_criteria={c_id: corrected_criteria},
        add_specs=[x_spec],
        rewire={e_id: ["NEW:X"]},
        reason=(
            f"Deviation {deviation.failure_id} at task C: verification against plan v1 "
            f"assumption ('{C_PLAN_V1_EXPECTED}') failed with verdict not_evidenced; "
            f"the observed artifact defines the real contract ('{corrected_marker}'). "
            "D (whose product embeds the invalidated expectation) is removed; "
            "remediation task X covers the merge contract under reality; "
            "E is rewired onto X; C's criteria are corrected to observed reality."
        ),
        plan_version="v2",
    )
    ev["replan_v1_to_v2"] = {
        "from_version": replan.from_version, "to_version": replan.to_version,
        "reason": replan.reason, "evidence": replan.evidence,
        "invalidated": replan.invalidated_tasks, "preserved": replan.preserved_tasks,
        "added": replan.added_tasks, "rewired": replan.rewired_dependencies,
        "modified": replan.modified_tasks,
    }
    exp_r = EXP["replan_v1_to_v2"]
    assert replan.invalidated_tasks == exp_r["invalidated"], replan.invalidated_tasks
    assert replan.preserved_tasks == exp_r["preserved"], replan.preserved_tasks
    assert [a["task_key"] for a in replan.added_tasks] == ["X"], replan.added_tasks
    assert [r["task_key"] for r in replan.rewired_dependencies] == ["E"], replan.rewired_dependencies
    assert replan.rewired_dependencies[0]["new_depends_on"] == ["X"], replan.rewired_dependencies
    assert [m["task_key"] for m in replan.modified_tasks] == ["C"], replan.modified_tasks
    assert deviation.resolved and deviation.resolved_by == "replan->v2"
    states_after_replan = phase_states(controller, run.run_id)
    ev["states_after_replan"] = states_after_replan
    x_id = controller._key_to_task["X"]
    assert controller.engine.task_graph.get(run.run_id, {}).get(d_id) is None, "D must be removed"
    assert states_after_replan.get("E") == "BLOCKED", states_after_replan  # rewired onto incomplete X

    # ================= GATE: unapproved v2 must REFUSE =================
    def snap():
        return (
            len(engine.event_bus.history),
            {k: attempts_len(controller, run.run_id, k) for k in ("A", "B", "C", "E", "X")},
        )

    gate_refusals: List[Dict[str, Any]] = []
    s0 = snap()
    try:
        await controller.execute_run(run.run_id, max_parallel=1)
        raise AssertionError("continuation must be REFUSED before v2 approval")
    except RuntimeError as ex:
        assert "PLAN_REVIEW_GATE" in str(ex) and "REFUSED" in str(ex), str(ex)
        gate_refusals.append({"when": "after replan, before any v2 review", "error": str(ex)})
    assert snap() == s0, "refusal must execute NOTHING"

    # ================= REVIEW v2 #1 -> REJECTED (real failure) ===========
    rv2a = controller.review_plan(run.run_id, reviewer="e10rp-reviewer",
                                  note="review v2 while C is still FAILED")
    ev["review_v2_first"] = {
        "review_id": rv2a.review_id, "verdict": rv2a.verdict,
        "reasons": rv2a.reasons,
        "checks": [{k: c[k] for k in ("check", "passed")} for c in rv2a.checks],
    }
    assert rv2a.verdict == "rejected", "review v2 #1 must REJECT (C is FAILED — plan not executable)"
    failing = [c["check"] for c in rv2a.checks if not c["passed"]]
    assert failing == [EXP["review_v2"]["first_failing_check"]], failing

    # ================= GATE: rejected review must REFUSE =================
    s1 = snap()
    try:
        await controller.execute_run(run.run_id, max_parallel=1)
        raise AssertionError("continuation must be REFUSED after rejected review")
    except RuntimeError as ex:
        assert "PLAN_REVIEW_GATE" in str(ex) and "REJECTED" in str(ex).upper(), str(ex)
        gate_refusals.append({"when": "after review v2 REJECTED", "error": str(ex)})
    assert snap() == s1, "refusal must execute NOTHING (only the review event was added)"
    ev["gate_refusals"] = gate_refusals
    ev["gate_zero_execution"] = {
        "snapshot_before_first_refusal": s0,
        "snapshot_after_first_refusal": s0,
        "snapshot_before_second_refusal": s1,
        "snapshot_after_second_refusal_equals_before": True,
    }

    # ================= RECOVER C -> REVIEW v2 #2 -> APPROVED =============
    controller.recover_failed_task(run.run_id, c_id, reason="Plan corrected: C re-verified against observed contract")
    states_mid = phase_states(controller, run.run_id)
    assert states_mid.get("C") == "READY", states_mid
    rv2b = controller.review_plan(run.run_id, reviewer="e10rp-reviewer",
                                  note="review v2 after C recovered under corrected criteria")
    ev["review_v2_second"] = {
        "review_id": rv2b.review_id, "verdict": rv2b.verdict,
        "checks": [{k: c[k] for k in ("check", "passed")} for c in rv2b.checks],
    }
    assert rv2b.verdict == "approved", f"review v2 #2 must approve: {rv2b.reasons}"
    assert all(c["passed"] for c in rv2b.checks)
    mark("E10RP_CONTINUATION_APPROVED", {"plan_version": "v2", "review_id": rv2b.review_id})

    # ================= CONTINUATION (phase 2 under plan v2) ==============
    result2 = await controller.execute_run(run.run_id, max_parallel=1)
    states_p2 = phase_states(controller, run.run_id)
    ev["phase2"] = {
        "states": states_p2,
        "task_results": {
            controller._task_to_key.get(tid, tid): {
                k: v for k, v in res.items() if k in ("success", "error", "attempts")
            }
            for tid, res in result2.get("task_results", {}).items()
        },
    }
    assert states_p2.get("C") == "COMPLETED" and states_p2.get("X") == "COMPLETED" \
        and states_p2.get("E") == "COMPLETED", states_p2
    assert result2["task_results"][c_id]["success"] is True, "C passes under corrected criteria"
    assert result2["task_results"][x_id]["success"] is True
    assert result2["task_results"][e_id]["success"] is True

    # ---- preservation: A,B never re-executed; C's side effect not repeated
    attempts_after = {k: attempts_len(controller, run.run_id, k) for k in ("A", "B", "C", "X", "E")}
    ev["preservation"] = {
        "attempts_after_phase2": attempts_after,
        "phase1_attempts": attempts_p1,
    }
    assert attempts_after["A"] == 1 and attempts_after["B"] == 1, attempts_after
    assert attempts_after["C"] == 2, "C re-executed exactly once under v2"  # 1 failed + 1 corrected
    assert attempts_after["X"] == 1 and attempts_after["E"] == 1, attempts_after

    journal_c = journal_records(engine, mission.mission_id, M["C"][0])
    ev["journal_task_c"] = journal_c
    assert [r["record_type"] for r in journal_c] == ["intent", "performed", "reconciled"], journal_c
    perf = next(r for r in journal_c if r["record_type"] == "performed")
    recon = next(r for r in journal_c if r["record_type"] == "reconciled")
    assert recon["mtime_ns"] == perf["mtime_ns"] and recon["inode"] == perf["inode"] \
        and recon["artifact_id"] == perf["artifact_id"], "C's re-execution must ADOPT (no rewrite)"
    final_stats = {k: artifact_stat(engine, mission.mission_id, M[k][0]) for k in ("A", "B", "C")}
    ev["artifact_stats_final"] = final_stats
    assert final_stats["A"] == phase1_stats["A"] and final_stats["B"] == phase1_stats["B"], \
        "A/B artifacts must be untouched by continuation"
    assert final_stats["C"]["mtime_ns"] == phase1_stats["C"]["mtime_ns"], \
        "C's artifact must not be rewritten on re-execution"
    assert final_stats["C"]["sha256"] == phase1_stats["C"]["sha256"]

    # ================= VERIFIED OUTCOME =================
    ok, report = controller.verify_completion(run.run_id, required_keys=["A", "B", "C", "X", "E"])
    ev["verify_completion"] = {"passed": ok, "report": report}
    assert ok, report
    fin = controller.finalize_mission(mission.mission_id, run.run_id)
    fin = fin if isinstance(fin, dict) else {"raw": str(fin)}
    ev["finalize"] = {"mission_state": str(fin.get("mission_state", fin.get("state", ""))),
                      "raw": str(fin)[:400]}
    cp = controller.create_full_checkpoint(mission.mission_id, run.run_id, step=2)
    ev["final_checkpoint"] = {"checkpoint_id": cp.checkpoint_id, "hash": cp.hash}
    assert cp.verify(), "final checkpoint integrity"

    # ================= DUPLICATE CONTINUATION (S5) =================
    # E10 lesson: this engine's execution-start marker is TASK_ASSIGNED
    # (task.started is never emitted).
    task_started_before = sum(
        1 for e in engine.event_bus.history if e.event_type == EventType.TASK_ASSIGNED
    )
    journal_counts_before = {
        p: len(journal_records(engine, mission.mission_id, p))
        for p in (M["A"][0], M["B"][0], M["C"][0], M["X"][0], M["E"][0])
    }
    stats_before_dup = {k: artifact_stat(engine, mission.mission_id, M[k][0])
                        for k in ("A", "B", "C", "X", "E")}
    result3 = await controller.execute_run(run.run_id, max_parallel=1)
    task_started_after = sum(
        1 for e in engine.event_bus.history if e.event_type == EventType.TASK_ASSIGNED
    )
    journal_counts_after = {
        p: len(journal_records(engine, mission.mission_id, p))
        for p in (M["A"][0], M["B"][0], M["C"][0], M["X"][0], M["E"][0])
    }
    stats_after_dup = {k: artifact_stat(engine, mission.mission_id, M[k][0])
                       for k in ("A", "B", "C", "X", "E")}
    ev["duplicate_continuation"] = {
        "result_keys": sorted(result3.get("task_results", {}).keys()),
        "task_started_before": task_started_before,
        "task_started_after": task_started_after,
        "journal_counts_before": journal_counts_before,
        "journal_counts_after": journal_counts_after,
        "stats_identical": stats_before_dup == stats_after_dup,
    }
    assert task_started_after == task_started_before, "duplicate continuation must start NOTHING"
    assert journal_counts_after == journal_counts_before, "no new journal records"
    assert stats_before_dup == stats_after_dup, "no artifact may change"

    # ================= durable ledger + final event log =================
    ev["ledger_final"] = controller.ledger_snapshot()
    engine._save_events_to_disk(mission.mission_id)

    durable_write_json(evidence_dir / "main_scenario.json", ev)
    print("E10RP_MAIN_SCENARIO_COMPLETE")
    print(json.dumps({
        "mission_id": mission.mission_id, "run_id": run.run_id,
        "plan_version": controller.plan_version,
        "reviews": [(r.plan_version, r.verdict) for r in controller.plan_reviews],
        "replans": [(r.from_version, r.to_version) for r in controller.replans],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
