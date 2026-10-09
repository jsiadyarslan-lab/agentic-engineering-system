#!/usr/bin/env python3
"""E10-RP REQUIRED TEST MATRIX — RP-T01..RP-T23.

A session-scoped fixture runs the COMPLETE replanning proof chain as real
OS subprocesses (main scenario + S2 safety scenario + independent verifier).
Every test asserts its criterion against the recorded durable evidence.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def rp_session(tmp_path_factory):
    proc = subprocess.run(
        [sys.executable, str(HERE / "run_e10rp.py")],
        capture_output=True, text=True, timeout=900, cwd=str(REPO),
    )
    assert proc.returncode == 0, f"RP session failed:\n{proc.stdout[-6000:]}\n{proc.stderr[-2000:]}"
    line = [l for l in proc.stdout.splitlines() if l.startswith("[RUNNER] session=")][0]
    session = Path(line.split("=", 1)[1].strip())
    return {
        "session": session,
        "runner": _load(session / "evidence" / "runner.json"),
        "expectations": _load(session / "evidence" / "pre_registered_expectations.json"),
        "main": _load(session / "evidence" / "main_scenario.json"),
        "s2": _load(session / "evidence" / "s2_scenario.json"),
        "verifier": _load(session / "evidence" / "verifier.json"),
    }


# ---------------------------------------------------------------- T01..T16 (main)
def test_RP_T01_full_cycle_proven(rp_session):
    assert rp_session["runner"]["verdict"] == "E10RP_CHAIN_PROVEN"
    assert all(st["rc_as_expected"] for st in rp_session["runner"]["stages"])
    assert len(set(rp_session["runner"]["distinct_pids"])) == 3


def test_RP_T02_plan_v1_definition(rp_session):
    v1 = _check(rp_session, "V1_plan_v1_definition")
    assert sorted(v1["facts"]["plan_v1_tasks"]) == ["A", "B", "C", "D", "E"]
    assert "E10RP_C_PLAN_V1_EXPECTED" in str(v1["facts"].get("c_criteria_v1"))


def test_RP_T03_phase1_outcomes(rp_session):
    p1 = rp_session["main"]["phase1"]
    assert p1["states"]["A"] == "COMPLETED" and p1["states"]["B"] == "COMPLETED"
    assert p1["states"]["C"] == "FAILED"
    assert p1["states"]["D"] == "BLOCKED" and p1["states"]["E"] == "BLOCKED"
    assert "Verification failed: not_evidenced" in str(p1["c_error"])


def test_RP_T04_s1_claim_without_record_not_classified(rp_session):
    s1 = rp_session["main"]["s1_insufficient_evidence"]
    exp = rp_session["expectations"]["s1_insufficient_evidence"]
    assert s1["claim_without_failure_record_is_classified"] is False
    assert s1["claim_without_failure_record_triggers_replan"] is False
    assert exp["claim_without_failure_record_is_classified"] is False


def test_RP_T05_s1_agent_claim_overturned_by_verifier(rp_session):
    o = rp_session["main"]["phase1"]["agent_claim_overturned"]
    assert o["agent_wrote_artifact"] is True
    assert o["verifier_verdict"] == "not_evidenced"
    assert "success=False" in o["task_result"]


def test_RP_T06_deviation_classification_with_evidence(rp_session):
    d = rp_session["main"]["deviation_record"]
    assert d["kind"] == "plan_deviation" and d["recovery_action"] == "replan"
    assert d["evidence"] and d["task"] == "C"
    # resolution linkage lives in the durable ledger (final snapshot):
    lf = rp_session["main"]["ledger_final"]["failures"]
    rec = next(f for f in lf if f.get("task_key") == "C" and f.get("kind") == "plan_deviation")
    assert rec["resolved_by"] == "replan->v2" and rec["resolved"] is True


def test_RP_T07_replan_v1_to_v2_shape(rp_session):
    r = rp_session["main"]["replan_v1_to_v2"]
    exp = rp_session["expectations"]["main"]["replan_v1_to_v2"]
    assert r["from_version"] == "v1" and r["to_version"] == "v2"
    assert r["invalidated"] == exp["invalidated"] == ["D"]
    assert r["preserved"] == exp["preserved"] == ["A", "B"]
    assert [a["task_key"] for a in r["added"]] == ["X"]
    assert [w["task_key"] for w in r["rewired"]] == ["E"]
    assert r["rewired"][0]["new_depends_on"] == ["X"]
    assert [m["task_key"] for m in r["modified"]] == ["C"]


def test_RP_T08_gate_refusal_unapproved_zero_execution(rp_session):
    g = rp_session["main"]["gate_refusals"]
    assert len(g) == 2
    assert "PLAN_REVIEW_GATE" in g[0]["error"] and "REFUSED" in g[0]["error"]
    z = rp_session["main"]["gate_zero_execution"]
    assert z["snapshot_after_first_refusal"] == z["snapshot_before_first_refusal"]


def test_RP_T09_review_v2_rejected_with_c6(rp_session):
    rv = rp_session["main"]["review_v2_first"]
    exp = rp_session["expectations"]["main"]["review_v2"]
    assert rv["verdict"].lower() == exp["first_verdict"].lower()
    failing = [c["check"] for c in rv["checks"] if not c["passed"]]
    assert failing == [exp["first_failing_check"]]


def test_RP_T10_gate_refusal_after_rejected_review(rp_session):
    g = rp_session["main"]["gate_refusals"]
    assert "REJECTED" in g[1]["error"].upper() or "rejected" in g[1]["error"]
    z = rp_session["main"]["gate_zero_execution"]
    assert z["snapshot_after_second_refusal_equals_before"] is True


def test_RP_T11_review_v2_approved_after_recovery(rp_session):
    rv = rp_session["main"]["review_v2_second"]
    exp = rp_session["expectations"]["main"]["review_v2"]
    assert rv["verdict"].lower() == exp["after_recovery_verdict"].lower()
    assert all(c["passed"] for c in rv["checks"])


def test_RP_T12_phase2_completion(rp_session):
    p2 = rp_session["main"]["phase2"]
    assert p2["states"]["C"] == "COMPLETED"
    assert p2["states"]["X"] == "COMPLETED"
    assert p2["states"]["E"] == "COMPLETED"
    assert "D" not in p2["states"]


def test_RP_T13_preserved_not_reexecuted(rp_session):
    pr = rp_session["main"]["preservation"]
    assert pr["attempts_after_phase2"]["A"] == 1
    assert pr["attempts_after_phase2"]["B"] == 1
    assert pr["attempts_after_phase2"]["C"] == 2
    v4 = _check(rp_session, "V4_causality_windows")
    assert v4["facts"]["post_replan_started"] == ["C", "E", "X"]


def test_RP_T14_c_adopted_without_rewrite(rp_session):
    j = rp_session["main"]["journal_task_c"]
    assert [r["record_type"] for r in j] == ["intent", "performed", "reconciled"]
    perf, recon = j[1], j[2]
    assert recon["mtime_ns"] == perf["mtime_ns"]
    assert recon["inode"] == perf["inode"]
    assert recon["artifact_id"] == perf["artifact_id"]


def test_RP_T15_verified_outcome(rp_session):
    main = rp_session["main"]
    assert main["verify_completion"]["passed"] is True
    assert "EVIDENCED" in str(main["finalize"])
    assert main["final_checkpoint"]["hash"]
    assert main["final_checkpoint"]["checkpoint_id"]


def test_RP_T16_duplicate_continuation_zero_effects(rp_session):
    d = rp_session["main"]["duplicate_continuation"]
    assert d["task_started_after"] == d["task_started_before"]
    assert d["journal_counts_after"] == d["journal_counts_before"]
    assert d["stats_identical"] is True


# ---------------------------------------------------------------- T17..T20 (S2)
def test_RP_T17_s2_nonplan_failure_retried_never_replanned(rp_session):
    cl = rp_session["s2"]["classification"]
    exp = rp_session["expectations"]["s2_minimal_scope"]["classification"]
    assert cl["B"]["kind"] == exp["B_first_attempt_kind"] == "tool_runtime_failure"
    assert cl["B"]["recovery"] == "retry"
    assert cl["B"]["resolved"] is True
    assert cl["B"]["resolved_by"] == "engine_retry_then_completed"


def test_RP_T18_s2_deviation_classification(rp_session):
    cl = rp_session["s2"]["classification"]
    assert cl["E"]["kind"] == "plan_deviation"
    assert cl["E"]["recovery"] == "replan"
    assert cl["E"]["resolved"] is False or cl["E"].get("resolved_by") == "replan->v2"


def test_RP_T19_s2_minimal_scope_replan(rp_session):
    r = rp_session["s2"]["replan_v1_to_v2"]
    exp = rp_session["expectations"]["s2_minimal_scope"]["replan_v1_to_v2"]
    assert r["invalidated"] == [] == exp["invalidated"]
    assert r["added"] == [] and r["rewired"] == []
    assert r["preserved"] == exp["preserved"] == ["A", "B", "C", "D"]
    assert [m["task_key"] for m in r["modified"]] == ["E"]


def test_RP_T20_s2_untouched_preservation(rp_session):
    pr = rp_session["s2"]["preservation"]
    assert pr["attempts_after"]["A"] == 1
    assert pr["attempts_after"]["B"] == 2
    assert pr["attempts_after"]["C"] == 1
    assert pr["attempts_after"]["D"] == 1
    assert pr["attempts_after"]["E"] == 3
    j = rp_session["s2"]["journal_task_e"]
    assert j[0]["record_type"] == "intent" and j[1]["record_type"] == "performed"
    assert all(r["record_type"] == "reconciled" for r in j[2:])


# ---------------------------------------------------------------- T21..T23 (verifier)
def _check(rp_session, name):
    c = next(x for x in rp_session["verifier"]["checks"] if x["check"] == name)
    assert c["verdict"] == "VERIFIED", c["problems"]
    return c


def test_RP_T21_verifier_causality_windows(rp_session):
    v4 = _check(rp_session, "V4_causality_windows")
    assert v4["facts"]["task_started_between_replan_and_approval"] == 0


def test_RP_T22_verifier_ledger_durable_with_reviews(rp_session):
    _check(rp_session, "V5_ledger_decision_chain")
    _check(rp_session, "V2_review_chain")
    # plan_reviews durable in the on-disk ledger snapshot
    assert "plan_reviews" in rp_session["main"]["ledger_final"]


def test_RP_T23_verifier_no_unevidenced_classification(rp_session):
    # V5 already asserts: every ledger failure is backed by a TASK_FAILED event
    _check(rp_session, "V5_ledger_decision_chain")
    v1 = _check(rp_session, "V1_plan_v1_definition")
    v3 = _check(rp_session, "V3_phase1_deviation_evidence")
    v6 = _check(rp_session, "V6_journal_side_effects")
    v7 = _check(rp_session, "V7_artifacts_on_disk")
    v8 = _check(rp_session, "V8_final_outcome")
    v9 = _check(rp_session, "V9_expectation_fidelity")
    s2a = _check(rp_session, "S2A_classification")
    s2b = _check(rp_session, "S2B_minimal_scope")
    s2c = _check(rp_session, "S2C_preservation")
