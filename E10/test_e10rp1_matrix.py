#!/usr/bin/env python3
"""E10-RP1 REQUIRED TEST MATRIX — canonical replanning path & review-gate
integration (order E10-RP1 §3/§4), RP1-T00..RP1-T15.

A session-scoped fixture runs the complete proof chain as REAL OS processes
(run_e10rp1.py): a FULL canonical cycle and a BLOCKED canonical cycle, each
through CanonicalOrchestrator.execute_mission — the REAL operational path
(real MissionController + real ExecutionEngine + real ToolExecutor governed
execution; NO mocks of production decision logic). The two DISCLOSED control
inputs sit at decision boundaries only (planning / replanning decision) and
are documented in every facts.json under 'providers'.

Every test asserts its criterion against the DURABLE evidence the cycles
wrote to disk (facts/events/ledger/journal), never against re-executions.
"""
from __future__ import annotations

import asyncio
import inspect
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
def rp1_session(tmp_path_factory):
    out = tmp_path_factory.mktemp("rp1_session")
    proc = subprocess.run(
        [sys.executable, str(HERE / "run_e10rp1.py"), "--out", str(out / "session")],
        capture_output=True, text=True, timeout=900, cwd=str(REPO),
    )
    assert proc.returncode == 0, f"RP1 session failed:\n{proc.stdout[-8000:]}\n{proc.stderr[-2000:]}"
    line = [l for l in proc.stdout.splitlines() if l.startswith("[RUNNER] session=")][0]
    session = Path(line.split("=", 1)[1].strip())
    return {
        "session": session,
        "runner": _load(session / "evidence" / "runner.json"),
        "full": _load(session / "full" / "facts.json"),
        "full_checks": _load(session / "full" / "expectations_check.json"),
        "blocked": _load(session / "blocked" / "facts.json"),
        "blocked_checks": _load(session / "blocked" / "expectations_check.json"),
        "probe": _load(session / "full" / "restore_probe.json"),
    }


# ------------------------------------------------ §2 source-level guarantees

def test_RP1_T00_canonical_policy_is_explicit():
    """§2.1: the canonical path enables the review gate EXPLICITLY (default
    ON) and never relies on MissionController's library default (False)."""
    from unified.mission_controller import MissionController
    from orchestrator.canonical import CanonicalOrchestrator
    import orchestrator.canonical as canonical

    # library default stays False — every other direct caller unchanged
    assert inspect.signature(MissionController.__init__).parameters[
        "require_plan_review"].default is False
    # canonical default is True — the gated policy IS the operational path
    assert inspect.signature(CanonicalOrchestrator.__init__).parameters[
        "require_plan_review"].default is True

    src = (REPO / "src" / "orchestrator" / "canonical.py").read_text(encoding="utf-8")
    # explicit pass-through at construction — never the library default
    assert "require_plan_review=require_plan_review" in src
    # the old default-off construction is gone
    assert "MissionController(self.engine, state_dir=artifacts_base_dir)" not in src


def test_RP1_T01_stubs_removed_and_path_wired():
    """§2.5: the `pass` stubs that claimed failure/replanning handling are
    gone; the replanning branch is wired to the real path."""
    src = (REPO / "src" / "orchestrator" / "canonical.py").read_text(encoding="utf-8")
    for gone in ("# Delegate to MissionController replan",
                 "# This is a simplified path",
                 "# Could trigger replan here"):
        assert gone not in src, f"stub claim still present: {gone}"
    assert "self._run_replanning_cycle(" in src
    assert "self.mc.replan_mission(" in src
    assert "self.mc.recover_failed_task(" in src
    assert 'reviewer="canonical_orchestrator"' in src
    assert 'verdict="not_evidenced"' in src  # verifier failure recorded, not dropped


def test_RP1_T02_e3_e4_fixtures_opt_out_explicitly():
    """Policy-change guard: the two orchestrator test files opt out of the
    gate EXPLICITLY (visible in the diff), so their historical behavior is
    unchanged; the gated canonical policy is proven by this matrix."""
    for rel in ("tests/orchestrator/test_e3_canonical_orchestrator.py",
                "tests/orchestrator/test_e4_multi_task_mission.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert "require_plan_review=False" in src, rel


# ---------------------------------------------------- §3 through the real path

def test_RP1_T03_runner_chain_and_real_components(rp1_session):
    """§3: the proof chain ran as real OS processes; every cycle went
    through the REAL MissionController + ExecutionEngine with the gate ON."""
    s = rp1_session
    assert s["runner"]["verdict"] == "E10RP1_CHAIN_PROVEN"
    assert all(st["rc_as_expected"] for st in s["runner"]["stages"])
    assert len(set(s["runner"]["distinct_pids"])) == 3  # runner witnesses distinct PIDs
    for facts in (s["full"], s["blocked"]):
        rc = facts["real_components"]
        assert rc["mission_controller"] == "MissionController"
        assert rc["execution_engine"] == "ExecutionEngine"
        assert rc["require_plan_review"] is True
        assert "NOT claimed as independent planning" in facts["providers"]["disclosure"]


def test_RP1_T04_no_execution_before_review_full(rp1_session):
    """§3.1: in the gated canonical path, execution NEVER starts before the
    plan in question is reviewed — durable ordering, not co-incidence."""
    f = rp1_session["full"]
    ordering = f["ordering"]
    assert ordering["invariants"]["no_attempt_before_v1_review"] is True
    # reviews sequence: v1 approved (before first execution), v2 rejected, v2 approved
    assert [r["verdict"] for r in f["reviews"]] == ["approved", "rejected", "approved"]
    assert [r["plan_version"] for r in f["reviews"]] == ["v1", "v2", "v2"]
    chain = ordering["chain"]
    assert chain["review_v1_approved"] < min(
        e["timestamp"] for e in _load(rp1_session["session"] / "full" / "events.jsonl")
        if e["event_type"] == "task.assigned")


def test_RP1_T05_deviation_linked_to_replan_with_evidence(rp1_session):
    """§3.3: the replanning decision is linked to the specific deviation and
    its evidence — ReplanRecord.evidence == FailureRecord.evidence, the
    deviation is resolved by exactly that replan, and review #2's causal
    check C7 passes on the live state."""
    f = rp1_session["full"]
    dev, rp = f["deviation"], f["replan"]
    assert dev["kind"] == "plan_deviation"
    assert "Verification failed" in dev["description"]
    assert dev["task_key"] == "C"
    assert dev["resolved_by"] == "replan->v2"
    assert list(dev["evidence"]) == list(rp["evidence"])
    review2 = f["reviews"][2]
    c7 = next(c for c in review2["checks"] if c["check"] == "C7_causality_deviation_to_replan")
    assert c7["passed"] is True


def test_RP1_T06_modified_plan_never_executed_before_approval(rp1_session):
    """§3.4 (+§2.4): between the replan and the v2 approval there is ZERO
    execution; the causal chain replan < rejection < recovery < approval
    < first continuation attempt is strictly ordered in durable time."""
    f = rp1_session["full"]
    o = f["ordering"]
    assert o["invariants"]["no_attempt_between_replan_and_v2_approval"] is True
    assert o["invariants"]["replan_lt_reject_lt_recover_lt_approve"] is True
    assert o["invariants"]["first_continuation_attempt_after_v2_approval"] is True
    c = o["chain"]
    assert c["replan_requested"] < c["review_v2_rejected"] < c["recovered_C"] < c["review_v2_approved"]


def test_RP1_T07_rejected_review_blocks_through_orchestrator(rp1_session):
    """§3.2 (BLOCKED cycle through the orchestrator): a rejected review
    prevents any subsequent task execution — the orchestrator returns
    PLAN_REVIEW_REJECTED; C is never recovered; X/E never run at all."""
    b = rp1_session["blocked"]
    assert b["result"]["final_state"] == "PLAN_REVIEW_REJECTED"
    assert b["result"]["success"] is False
    assert [r["verdict"] for r in b["reviews"]] == ["approved", "rejected"]
    rejected = next(r for r in b["reviews"] if r["verdict"] == "rejected")
    failing = [c["check"] for c in rejected["checks"] if not c["passed"]]
    assert failing == ["C6_plan_executable_no_failed_tasks"]  # real reason: C still FAILED
    assert b["ordering"]["invariants"]["zero_attempts_after_rejection"] is True
    assert b["states"]["C"] == "FAILED"
    assert b["attempts_per_key"] == {"A": 1, "B": 1, "C": 3, "X": 0, "E": 0, "D": 0}
    assert b["files"]["task_d.txt"]["present"] is False
    assert b["files"]["task_x.txt"]["present"] is False
    assert b["files"]["task_e.txt"]["present"] is False


def test_RP1_T08_completed_work_preserved_not_reexecuted(rp1_session):
    """§3.5: correctly completed tasks (A, B) are never re-executed — exactly
    one attempt each across the WHOLE history; the replan preserved exactly
    them; C's re-execution is the justified recovery (criteria corrected by
    the replan, recovered only after review rejection)."""
    f = rp1_session["full"]
    assert f["attempts_per_key"] == {"A": 1, "B": 1, "C": 4, "X": 1, "E": 1, "D": 0}
    assert f["replan"]["preserved_tasks"] == ["A", "B"]
    assert f["states"] == {k: "COMPLETED" for k in ("A", "B", "C", "X", "E")} | {"D": "REMOVED"}
    # justification for C's 4th attempt: criteria corrected + recovery event
    assert [m["task_key"] for m in f["replan"]["modified_tasks"]] == ["C"]
    c8 = next(c for c in f["reviews"][2]["checks"] if c["check"] == "C8_corrected_criteria_applied")
    assert c8["passed"] is True


def test_RP1_T09_continuation_verified_outcome_no_repeated_effects(rp1_session):
    """§3.6: after approval, continuation produces the required outcome —
    EVIDENCED through the real path; every artifact physically written
    exactly ONCE (journal 'performed'); C's repeated attempts reconcile
    without rewrite; D's file never exists."""
    f = rp1_session["full"]
    assert f["result"]["success"] is True
    assert f["result"]["final_state"] == "EVIDENCED"
    assert f["files"]["task_c.txt"]["present"] and f["files"]["task_c.txt"]["contains_reality"]
    assert f["files"]["task_d.txt"]["present"] is False
    assert f["files"]["task_x.txt"]["present"] is True
    assert f["files"]["task_e.txt"]["present"] is True
    j = f["journal"]
    assert j["performed_per_path"] == {
        "task_a.txt": 1, "task_b.txt": 1, "task_c.txt": 1,
        "task_x.txt": 1, "task_e.txt": 1}
    assert j["reconciled_per_path"].get("task_c.txt") == 3  # retries + recovery: no rewrite
    assert j["reconciled_per_path"].get("task_a.txt") is None


def test_RP1_T10_duplicate_continuation_zero_new_effects(rp1_session):
    """§3.6 (duplicate continuation probe): re-driving execute_run after
    completion produces ZERO new attempts and ZERO new side effects."""
    dup = rp1_session["full"]["duplicate_continuation"]
    assert dup["result_success"] is True
    assert dup["zero_new_attempts"] is True
    assert dup["journal_unchanged"] is True


def test_RP1_T11_all_pre_registered_expectations_hold(rp1_session):
    """The cycles were judged ONLY against expectations fixed BEFORE any
    outcome was observed; every one of them holds (nothing was changed
    after the fact)."""
    for checks in (rp1_session["full_checks"], rp1_session["blocked_checks"]):
        failed = [c for c in checks if not c["pass"]]
        assert not failed, failed


# ------------------------------------------------------------------ §4 durable

def test_RP1_T12_durable_review_state_written(rp1_session):
    """§4a (VERIFIED): plan identity/versions/replan decisions/reviews are
    durably persisted in the ledger on disk."""
    s = rp1_session
    led = _load(s["session"] / "full" / "mission_controller"
                / s["full"]["mission_id"] / "ledger.json")
    assert led["plan_version"] == "v2"
    assert len(led["replans"]) == 1
    assert len(led["plan_reviews"]) == 3
    assert [r["verdict"] for r in led["plan_reviews"]] == ["approved", "rejected", "approved"]
    assert "X" in led["key_map"]


def test_RP1_T13_fresh_controller_not_restored_fail_closed(rp1_session):
    """§4b/§4c: a NEW controller does NOT restore review state from the
    ledger (recorded NOT PROVEN — no restoration code exists in this scope),
    and continuation is REFUSED fail-closed (RuntimeError before ANY
    execution). This is the in-process variant; the fresh-PROCESS variant
    is T14."""
    s = rp1_session
    from unified.execution import ExecutionEngine
    from unified.mission_controller import MissionController

    state_dir = s["session"] / "full"
    engine = ExecutionEngine(artifacts_base_dir=str(state_dir),
                             grant_validator=lambda g, p: True)
    mc = MissionController(engine, state_dir=str(state_dir), require_plan_review=True)

    # NOT PROVEN: durable ledger has v2 on disk, fresh controller has nothing
    assert mc.plan_version == "v1" and not mc.replans and not mc.plan_reviews
    probe = s["probe"]
    assert probe["durable_ledger_on_disk"]["plan_version"] == "v2"
    assert probe["durable_ledger_on_disk"]["n_plan_reviews"] == 3

    # fail-closed: continuation REFUSED before any execution
    n_before = len(engine.event_bus.history)
    with pytest.raises(RuntimeError, match="PLAN_REVIEW_GATE"):
        asyncio.run(mc.execute_run(s["full"]["run_id"]))
    assert len(engine.event_bus.history) == n_before


def test_RP1_T14_fresh_process_refused_fail_closed(rp1_session):
    """§4c (fresh PROCESS): a new interpreter taking over the durable state
    cannot continue — the gate refuses before any execution; the durable
    ledger is readable on disk but not restorable into the controller."""
    probe = rp1_session["probe"]
    assert probe["fresh_controller_state"]["plan_version"] == "v1"
    assert probe["fresh_controller_state"]["n_plan_reviews"] == 0
    assert probe["fresh_controller_state"]["restored_from_ledger"] is False
    assert probe["continuation"]["refused"] is True
    assert probe["continuation"]["new_events"] == 0
    assert "PLAN_REVIEW_GATE" in probe["continuation"]["error"]
    assert "never been reviewed" in probe["continuation"]["error"]


def test_RP1_T15_gate_probe_refuses_then_allows(rp1_session, tmp_path):
    """§3.1 supplementary probe (disclosed as such — the primary proof is
    the orchestrator path in T04): on a fresh gated controller, execute_run
    is REFUSED before any review; after review+approval the same call
    proceeds. Fail-closed both ways, by the production gate itself."""
    from orchestrator.canonical import create_canonical_orchestrator
    from unified.mission_controller import TaskSpec

    orch = create_canonical_orchestrator(
        llm_provider=None, artifacts_base_dir=str(tmp_path),
        auto_approve_plans=True, require_plan_review=True,
        # E9-R construction pattern: governed writes need a grant validator
        # (disclosed test validator; the canonical baseline had none at all).
        grant_validator=lambda g, p: True)
    specs = [
        TaskSpec(key="P1", name="Probe 1", description="", depends_on=[],
                 acceptance_criteria=["file_contains:task_p1.txt:RP1_P1"],
                 context={"content": "RP1_P1", "output_path": "task_p1.txt", "sleep_s": 0.05}),
        TaskSpec(key="P2", name="Probe 2", description="", depends_on=["P1"],
                 acceptance_criteria=["file_contains:task_p2.txt:RP1_P2"],
                 context={"content": "RP1_P2", "output_path": "task_p2.txt", "sleep_s": 0.05}),
    ]
    mission, run, _ = orch.mc.define_mission("RP1 gate probe", specs)
    events_before = len(orch.mc.engine.event_bus.history)
    with pytest.raises(RuntimeError, match="PLAN_REVIEW_GATE"):
        asyncio.run(orch.mc.execute_run(run.run_id))
    assert len(orch.mc.engine.event_bus.history) == events_before  # zero execution
    rv = orch.mc.review_plan(run.run_id, reviewer="probe", note="gate probe")
    assert rv.verdict == "approved"
    res = asyncio.run(orch.mc.execute_run(run.run_id))
    assert res["success"] is True
    assert orch.mc.engine.missions[mission.mission_id].state.value == "EVIDENCED"
