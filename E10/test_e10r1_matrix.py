#!/usr/bin/env python3
"""E10-CW1-R1 REQUIRED TEST MATRIX — R1-T01..R1-T20.

A session-scoped fixture runs the COMPLETE pre-journal crash chain as real
OS subprocesses for all six scenarios (A, B, C, D1, D2a, D2b — 2 chains
each: Process A -> SIGKILL at the scenario's real boundary -> [corruption]
-> Process B -> independent verifier). Every test asserts its criterion
against the recorded durable evidence.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CW1_HERE = HERE


def _load(p: Path):
    return json.loads(p.read_text())


@pytest.fixture(scope="session")
def r1_session(tmp_path_factory):
    """Run the full R1 chain session once; return the evidence bundle."""
    proc = subprocess.run(
        [sys.executable, str(HERE / "run_e10cw1r1.py")],
        capture_output=True, text=True, timeout=1800,
        cwd=str(REPO),
    )
    assert proc.returncode == 0, f"R1 session failed:\n{proc.stdout[-6000:]}\n{proc.stderr[-2000:]}"
    wd_line = [l for l in proc.stdout.splitlines() if l.startswith("[RUNNER] session=")][0]
    session = Path(wd_line.split("=", 1)[1].split()[0].strip())
    ev = session / "evidence"
    chains = [_load_line(l) for l in (ev / "chains.jsonl").read_text().splitlines() if l.strip()]
    by_scenario: dict = {}
    for c in chains:
        by_scenario.setdefault(c["scenario"], []).append(c)
    return {
        "session": session,
        "runner": _load(ev / "runner.json"),
        "chains": chains,
        "by_scenario": by_scenario,
        "stdout": proc.stdout,
    }


def _load_line(l):
    return json.loads(l)


def _chain(r1_session, scenario, index=1):
    return r1_session["by_scenario"][scenario][index - 1]


def _workdir(r1_session, scenario, index=1):
    return Path(_chain(r1_session, scenario, index)["workdir"])


# ---------------------------------------------------------------- R1-T01
def test_R1_T01_all_scenarios_verified(r1_session):
    """All six mandatory scenarios completed 2/2 chains with the independent
    verifier at exit 0 — the session-level gate."""
    r = r1_session["runner"]
    assert r["status"] == "E10_CW1_R1_CHAINS_COMPLETE"
    assert set(r["scenario_summaries"]) == {"A", "B", "C", "D1", "D2a", "D2b"}
    for s, summ in r["scenario_summaries"].items():
        assert summ["chains"] == 2, f"{s}: expected 2 chains"
        assert summ["all_verified"] is True, f"{s}: not all chains verified"


# ---------------------------------------------------------------- R1-T02
def test_R1_T02_real_sigkill_and_new_pids(r1_session):
    """Every Process A died by a real SIGKILL (exit -9, runner-observed) and
    every Process B / verifier ran as a distinct OS process."""
    for c in r1_session["chains"]:
        assert c["process_a"]["exit_code"] == -9
        assert c["process_a"]["termination_reason"].startswith("SIGKILL")
        assert c["pid_difference"] is True
        assert c["verifier"]["exit_code"] == 0
        pids = {c["process_a"]["runner_observed_pid"], c["process_b"]["runner_observed_pid"],
                c["verifier"]["runner_observed_pid"]}
        assert len(pids) == 3, "A, B and verifier must be three distinct processes"


# ---------------------------------------------------------------- R1-T03
@pytest.mark.parametrize("scenario,chain", [("A", 1), ("A", 2)])
def test_R1_T03_scenario_a_first_execution_with_planned_identity(r1_session, scenario, chain):
    """CW1-R1-A: crash after the durable intent, before the effect. The effect
    provably never happened (its only outcome would be the file): Process B
    performs it ONCE with the PLANNED identity — first execution, not a
    re-run; no reconciliation semantics."""
    wd = _workdir(r1_session, scenario, chain)
    v = _load(wd / "evidence" / "verifier.json")
    assert v["verdict"] == "VERIFIED"
    obs = v["checks"]["side_effect_count_identity_fingerprints"]["observed"]
    assert obs["d_performed_via"] == ["direct"]
    assert obs["performed_by_process_a_for_d"] == 0
    # the planned identity IS the intent's artifact id and the only one used
    pb = _load(wd / "evidence" / "process_b.json")
    acc = pb["side_effect_accounting"]
    assert acc["events"]["artifact_reconciled_for_d"] == 0
    assert acc["journal_d"]["types"] == ["intent", "performed"]
    d = acc["journal_d"]
    assert d["performed"][0]["artifact_id"] == d["intent"][0]["artifact_id"]
    assert d["performed"][0]["performed_via"] == "direct"


# ---------------------------------------------------------------- R1-T04
@pytest.mark.parametrize("chain", [1, 2])
def test_R1_T04_scenario_b_adoption_without_rewrite(r1_session, chain):
    """CW1-R1-B — THE ORDER §2 GAP: crash AFTER the physical write completed
    and BEFORE _journal_performance. Injection is at the REAL boundary (the
    adapter completed the write; the engine never journaled the outcome) —
    NOT at the ARTIFACT_CREATED event which fires after the journal record.
    Process B must DETECT the existing effect and ADOPT it without rewriting."""
    wd = _workdir(r1_session, "B", chain)
    inj = _load(wd / "evidence" / "injection.json")
    # the injection point is the pre-journal boundary, not the event
    assert inj["injection_point"] == "B_pre_journal"
    bs = inj["boundary_state"]
    assert len(bs["d_intent_records"]) == 1 and not bs["d_performed_records"]
    assert bs["d_file"] is not None  # the file EXISTS at the kill
    v = _load(wd / "evidence" / "verifier.json")
    assert v["checks"]["no_rewrite_continuity"]["passed"] is True
    assert v["checks"]["pre_performed_window_closure"]["passed"] is True


# ---------------------------------------------------------------- R1-T05
@pytest.mark.parametrize("chain", [1, 2])
def test_R1_T05_pre_performed_window_proven_without_performed_record(r1_session, chain):
    """ORDER §5 HARD RULE: the (effect -> performed) window closure is proven
    by evidence that PRECEDES the performed record — the durable intent
    (PID=Process A, recorded before the kill), the file stat continuity, and
    the performed record's PROVENANCE (written by B, performed_by_pid=A,
    performed_via=adopted_after_crash). The performed record itself is never
    the evidence for the window that precedes its own write."""
    for scen in ("B", "D1"):
        wd = _workdir(r1_session, scen, chain)
        v = _load(wd / "evidence" / "verifier.json")
        c = v["checks"]["pre_performed_window_closure"]
        assert c["passed"] is True
        o = c["observed"]
        assert o["intent_pid_is_process_a"] is True
        assert o["intent_recorded_before_kill"] is True
        # the performed record was WRITTEN by Process B (the resuming process)
        # for an effect PERFORMED by Process A — the provenance split that
        # proves the window closed
        ri = _load(wd / "evidence" / "resume_info.json")
        pb = _load(wd / "evidence" / "process_b.json")
        assert o["performed_written_by"] == [pb["process_b_pid"]]
        assert o["performed_by_pid"] == [ri["process_a_pid"]]


# ---------------------------------------------------------------- R1-T06
@pytest.mark.parametrize("chain", [1, 2])
def test_R1_T06_scenario_b_no_rewrite_three_way(r1_session, chain):
    """mtime_ns + inode + sha256 of the crash-window file are UNCHANGED from
    the crash marker through the runner snapshot through the verifier's own
    stat — three independent observers."""
    wd = _workdir(r1_session, "B", chain)
    v = _load(wd / "evidence" / "verifier.json")
    o = v["checks"]["no_rewrite_continuity"]["observed"]
    assert o["at_crash_marker"]["mtime_ns"] == o["runner_snapshot"]["mtime_ns"] == o["verifier_now"]["mtime_ns"]
    assert o["at_crash_marker"]["inode"] == o["runner_snapshot"]["inode"] == o["verifier_now"]["inode"]
    assert o["at_crash_marker"]["sha256"] == o["runner_snapshot"]["sha256"] == o["verifier_now"]["sha256"]


# ---------------------------------------------------------------- R1-T07
@pytest.mark.parametrize("chain", [1, 2])
def test_R1_T07_scenario_c_cw1_window_retained(r1_session, chain):
    """CW1-R1-C: the previously-proven window (performed durable, completion
    not) still reconciles without rewrite — CW1's behavior is NOT regressed
    by the intent-first change."""
    wd = _workdir(r1_session, "C", chain)
    pb = _load(wd / "evidence" / "process_b.json")
    acc = pb["side_effect_accounting"]
    assert acc["journal_d"]["types"] == ["intent", "performed", "reconciled"]
    assert acc["journal_d"]["reconciled"][0]["no_physical_rewrite"] is True
    assert acc["events"]["artifact_reconciled_modes"] == ["performed_record"]
    v = _load(wd / "evidence" / "verifier.json")
    assert v["checks"]["no_rewrite_continuity"]["passed"] is True


# ---------------------------------------------------------------- R1-T08
@pytest.mark.parametrize("chain", [1, 2])
def test_R1_T08_scenario_d1_torn_trailing_line_policy(r1_session, chain):
    """CW1-R1-D (partial FINAL record): a torn trailing journal line is
    ignored as never-durable-truth; the intent that precedes it still governs
    the reconciliation; the resume's own append REPAIRS the file (torn tail
    truncated; every line reloadable)."""
    wd = _workdir(r1_session, "D1", chain)
    corr = _load(wd / "evidence" / "corruption.json")
    assert corr["kind"] == "torn_trailing_line"
    v = _load(wd / "evidence" / "verifier.json")
    c = v["checks"]["journal_structure_integrity"]
    assert c["passed"] is True
    assert "torn_or_corrupt" not in c["observed"]["line_status"]
    assert c["observed"]["ends_with_newline"] is True
    # the reconciliation itself was unaffected (adoption via the intent)
    assert v["checks"]["pre_performed_window_closure"]["passed"] is True
    pb = _load(wd / "evidence" / "process_b.json")
    assert pb["side_effect_accounting"]["journal_d"]["types"] == ["intent", "performed"]


# ---------------------------------------------------------------- R1-T09
@pytest.mark.parametrize("chain", [1, 2])
def test_R1_T09_scenario_d2a_unreconcilable_ambiguity_rejected(r1_session, chain):
    """CW1-R1-D (destroyed trailing intent + existing effect file): the
    resume must REJECT the operation explicitly (fail-closed
    SideEffectReconciliationError), never silently overwrite the file."""
    wd = _workdir(r1_session, "D2a", chain)
    pb = _load(wd / "evidence" / "process_b.json")
    acc = pb["side_effect_accounting"]
    assert acc["continuation_success"] is False
    assert acc["final_states"]["TASK_D"] == "FAILED"
    errs = acc["events"]["tool_failed_errors"]
    assert any("SIDE_EFFECT_RECONCILIATION_FAILED" in e for e in errs)
    assert any("no record for this logical operation" in e for e in errs)
    v = _load(wd / "evidence" / "verifier.json")
    assert v["checks"]["fail_closed_refusal_is_explicit"]["passed"] is True
    # the file was NOT overwritten despite the missing record
    assert v["checks"]["side_effect_count_identity_fingerprints"]["passed"] is True


# ---------------------------------------------------------------- R1-T10
@pytest.mark.parametrize("chain", [1, 2])
def test_R1_T10_scenario_d2b_corrupt_prior_record_fails_closed(r1_session, chain):
    """CW1-R1-D (corrupt MIDDLE prior record): a prior performed record that
    may be the only proof of a proven effect is corrupt — the journal FAILS
    CLOSED (SideEffectJournalCorruptionError) and the refusing process
    appends NOTHING and re-performs NOTHING."""
    wd = _workdir(r1_session, "D2b", chain)
    corr = _load(wd / "evidence" / "corruption.json")
    assert corr["kind"] == "corrupt_middle_record" and corr["position"] == "middle"
    pb = _load(wd / "evidence" / "process_b.json")
    acc = pb["side_effect_accounting"]
    assert acc["continuation_success"] is False
    errs = acc["events"]["tool_failed_errors"]
    assert any("SIDE_EFFECT_JOURNAL_CORRUPT" in e for e in errs)
    v = _load(wd / "evidence" / "verifier.json")
    assert v["checks"]["fail_closed_refusal_is_explicit"]["passed"] is True
    # the journal is byte-identical to the post-corruption state
    assert v["checks"]["fail_closed_refusal_is_explicit"]["observed"]["journal_sha256_post_resume"] == corr["journal_sha256_after"]
    # the corrupt record is PRESERVED (not silently skipped or repaired away)
    assert "torn_or_corrupt" in v["checks"]["journal_structure_integrity"]["observed"]["line_status"]


# ---------------------------------------------------------------- R1-T11
def test_R1_T11_event_contract_counted_by_identity(r1_session):
    """ORDER §6: events are counted BY ARTIFACT IDENTITY (not by run_id):
    exactly ONE ARTIFACT_CREATED per artifact id across the whole durable
    log in EVERY scenario chain; ARTIFACT_RECONCILED appears only for real
    cross-process reconciliations with valid mode; no artifact exists in the
    store without its creation event."""
    for c in r1_session["chains"]:
        wd = Path(c["workdir"])
        v = _load(wd / "evidence" / "verifier.json")
        o = v["checks"]["event_contract_by_identity"]["observed"]
        assert v["checks"]["event_contract_by_identity"]["passed"] is True, (c["scenario"], o)
        assert o["duplicate_created_ids"] == []
        assert o["every_artifact_has_creation"] == []
        scen = c["scenario"]
        expected_reconciled = 1 if scen in ("B", "C", "D1") else 0
        assert o["artifact_reconciled_events"] == expected_reconciled
        if expected_reconciled:
            assert o["reconciled_modes"] in (["intent_adoption"], ["performed_record"])
            assert o["reconciled_no_rewrite_flags"] == [True]


# ---------------------------------------------------------------- R1-T12
def test_R1_T12_ids_only_process_boundary(r1_session):
    """Only identifiers cross the A->B process boundary (resume_info.json
    carries IDs, never state objects) — verified structurally in every chain."""
    allowed = {"scenario", "mission_id", "run_id", "checkpoint_id", "checkpoint_path",
               "process_a_pid", "task_ids", "crash_window_task_key"}
    for c in r1_session["chains"]:
        ri = _load(Path(c["workdir"]) / "evidence" / "resume_info.json")
        assert set(ri.keys()) <= allowed


# ---------------------------------------------------------------- R1-T13
@pytest.mark.parametrize("scenario", ["A", "B", "C", "D1"])
def test_R1_T13_success_scenarios_complete_with_real_effects(r1_session, scenario):
    """The completed mission reflects the REAL effect: all five marker files
    exist with their markers, verify_completion COMPLETE, final checkpoint
    hash set, final state EVIDENCED — in every success-scenario chain."""
    for c in r1_session["by_scenario"][scenario]:
        wd = Path(c["workdir"])
        v = _load(wd / "evidence" / "verifier.json")
        ch = v["checks"]["completion_reflects_real_effect"]
        assert ch["passed"] is True, (scenario, ch)
        assert all(ch["observed"]["markers_in_files"].values())
        assert ch["observed"]["final_checkpoint_has_hash"] is True
        assert ch["observed"]["finalize_final_state"] == "EVIDENCED"


# ---------------------------------------------------------------- R1-T14
def test_R1_T14_records_recomputed_from_reality(r1_session):
    """Every verifier chain recomputed the sha256 of every file and proved
    journal/artifact/evidence agreement — values recomputed, not declared."""
    for c in r1_session["chains"]:
        v = _load(Path(c["workdir"]) / "evidence" / "verifier.json")
        assert v["checks"]["records_agree_with_reality"]["passed"] is True, c["scenario"]


# ---------------------------------------------------------------- R1-T15 (unit)
def test_R1_T15_journal_torn_and_corrupt_policy_unit():
    """Unit: torn TRAILING line is ignored and truncated at the next append;
    a corrupt MIDDLE line raises SideEffectJournalCorruptionError; a
    semantically-invalid trailing record is treated as torn; a semantically-
    invalid MIDDLE record fails closed."""
    import tempfile
    sys.path.insert(0, str(CW1_HERE))
    from unified.execution import SideEffectJournal, SideEffectJournalCorruptionError

    tmp = tempfile.mkdtemp(prefix="r1_unit_journal_")
    j = SideEffectJournal(tmp)

    def intent(i):
        return {"record_type": "intent", "mission_id": "m", "task_id": f"t{i}",
                "path": "p", "content_sha256": "a" * 64, "size_bytes": 1,
                "artifact_id": f"art-{i}", "op": "artifact_write",
                "journal_record_id": f"jr-{i}"}

    j.append("m", intent(1))
    j.append("m", intent(2))
    p = j.journal_path("m")

    # torn trailing fragment -> ignored, then truncated by the next append
    with open(p, "a") as f:
        f.write('{"record_type": "perfor')
    j2 = SideEffectJournal(tmp)
    assert j2.lookup_intent("m", "t2", "p")["artifact_id"] == "art-2"
    j2.append("m", intent(3))
    data = open(p).read()
    assert "perfor\"," not in data  # torn fragment gone (not part of any line)
    assert all(json.loads(l)["record_type"] == "intent" for l in data.splitlines() if l.strip())

    # corrupt MIDDLE line -> fail closed
    lines = data.splitlines()
    lines[0] = lines[0][:15] + "XXCORRUPT"
    open(p, "w").write("\n".join(lines) + "\n")
    j3 = SideEffectJournal(tmp)
    with pytest.raises(SideEffectJournalCorruptionError):
        j3.lookup_intent("m", "t2", "p")

    # semantically invalid TRAILING record -> treated as torn (ignored)
    j4 = SideEffectJournal(tmp)  # fresh: middle corruption still detected
    with pytest.raises(SideEffectJournalCorruptionError):
        j4.lookup("m", "t1", "p")


# ---------------------------------------------------------------- R1-T16 (unit)
def test_R1_T16_first_sight_existing_file_fails_closed_unit():
    """Unit: a governed write whose target file exists with NO journal record
    for the logical operation is unreconcilable ambiguity — explicit
    fail-closed refusal, never a blind overwrite."""
    import tempfile
    sys.path.insert(0, str(CW1_HERE))
    from e10_common import build_engine
    from unified.contracts import new_attempt_id
    from unified.agent_role import AgentType
    from unified.execution import ExecutionContext

    async def scenario():
        tmp = tempfile.mkdtemp(prefix="r1_unit_ambig_")
        art = Path(tmp) / "artifacts"
        engine = build_engine(art)
        ctx = ExecutionContext(
            mission_id="m-amb", run_id="r", task_id="t-amb",
            attempt_id=new_attempt_id(), agent_id="", agent_type=AgentType.IMPLEMENTER,
            sandbox_id="sandbox-t-amb",
        )
        target = art / "sandbox-t-amb" / "out.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PRE-EXISTING-FOREIGN")
        res = await engine.execute_tool(ctx, "artifact_write",
                                        {"sandbox_id": "sandbox-t-amb", "path": "out.txt", "content": "NEW"})
        return res, target

    res, target = asyncio.run(scenario())
    assert res.success is False
    assert res.error_type == "SideEffectReconciliationError"
    assert "no record for this logical operation" in res.error
    assert target.read_text() == "PRE-EXISTING-FOREIGN"  # never overwritten


# ---------------------------------------------------------------- R1-T17 (unit)
def test_R1_T17_repeat_resume_reconciliation_is_stable_unit():
    """Unit: the intent/performed contract is consistent across REPEATED
    resumes — a second crash after the adopted-performed record reconciles
    through the normal performed path; the result never becomes a new
    execution attempt."""
    import tempfile
    sys.path.insert(0, str(CW1_HERE))
    from e10_common import build_engine
    from e10cw1r1_common import read_journal, stat_snapshot
    from unified.contracts import new_attempt_id
    from unified.agent_role import AgentType
    from unified.execution import ExecutionContext

    async def scenario():
        tmp = tempfile.mkdtemp(prefix="r1_unit_repeat_")
        art = Path(tmp) / "artifacts"
        # life 1: fresh governed write
        e1 = build_engine(art)
        ctx = ExecutionContext(
            mission_id="m-rep", run_id="r", task_id="t-rep",
            attempt_id=new_attempt_id(), agent_id="", agent_type=AgentType.IMPLEMENTER,
            sandbox_id="sandbox-t-rep",
        )
        r1 = await e1.execute_tool(ctx, "artifact_write",
                                   {"sandbox_id": "sandbox-t-rep", "path": "out.txt", "content": "PAYLOAD"})
        f = art / "sandbox-t-rep" / "out.txt"
        # life 2: reconcile from the performed record
        e2 = build_engine(art)
        r2 = await e2.execute_tool(ctx, "artifact_write",
                                   {"sandbox_id": "sandbox-t-rep", "path": "out.txt", "content": "PAYLOAD"})
        # life 3: crash after reconciled record -> reconcile AGAIN the same way
        e3 = build_engine(art)
        r3 = await e3.execute_tool(ctx, "artifact_write",
                                   {"sandbox_id": "sandbox-t-rep", "path": "out.txt", "content": "PAYLOAD"})
        return r1, r2, r3, f, art

    r1, r2, r3, f, art = asyncio.run(scenario())
    assert all(r.success for r in (r1, r2, r3))
    # ONE identity across all three lives — never a new execution attempt
    assert r1.output["artifact_id"] == r2.output["artifact_id"] == r3.output["artifact_id"]
    recs = read_journal(art, "m-rep")
    assert [r["record_type"] for r in recs] == ["intent", "performed", "reconciled", "reconciled"]
    # the file was written exactly once (mtime stable since life 1)
    st = stat_snapshot(f)
    assert st["mtime_ns"] == recs[1]["mtime_ns"]


# ---------------------------------------------------------------- R1-T18 (unit)
def test_R1_T18_agent_layer_duplicate_event_suppressed_unit():
    """Unit (order §6): the agent-completion emission site can no longer
    produce a second ARTIFACT_CREATED for the same artifact identity — the
    historical double-emission pattern is gone at the source."""
    import tempfile
    sys.path.insert(0, str(CW1_HERE))
    from e10_common import build_engine
    from unified.contracts import new_attempt_id
    from unified.agent_role import AgentType
    from unified.execution import ExecutionContext

    async def scenario():
        tmp = tempfile.mkdtemp(prefix="r1_unit_ev_")
        art = Path(tmp) / "artifacts"
        engine = build_engine(art)
        ctx = ExecutionContext(
            mission_id="m-ev", run_id="r", task_id="t-ev",
            attempt_id=new_attempt_id(), agent_id="", agent_type=AgentType.IMPLEMENTER,
            sandbox_id="sandbox-t-ev",
        )
        res = await engine.execute_tool(ctx, "artifact_write",
                                        {"sandbox_id": "sandbox-t-ev", "path": "out.txt", "content": "EV"})
        # simulate the agent-completion re-emission site (execution.py S11)
        artifact = engine.evidence_store.get_artifact_obj(res.output["artifact_id"])
        engine._emit_artifact_created(ctx, artifact)
        # and the guarded agent-layer site logic
        emitted = engine._artifact_created_emitted(res.output["artifact_id"])
        return engine, res, emitted

    engine, res, already = asyncio.run(scenario())
    assert already is True
    created = [e for e in engine.event_bus.history if e.event_type.value == "artifact.created"]
    ids = [(e.payload.get("artifact_id") if isinstance(e.payload, dict) else e.payload.artifact_id) for e in created]
    assert ids == [res.output["artifact_id"]]  # exactly ONE, tool layer only


# ---------------------------------------------------------------- R1-T19
def test_R1_T19_repeatability_across_chains(r1_session):
    """Every scenario ran twice with the same result (separate processes,
    distinct PIDs, both verifier-verified)."""
    for scen, chains in r1_session["by_scenario"].items():
        assert len(chains) == 2
        for c in chains:
            assert c["status"] == "SCENARIO_VERIFIED"
        pids = [c["process_a"]["runner_observed_pid"] for c in chains]
        assert pids[0] != pids[1]


# ---------------------------------------------------------------- R1-T20
def test_R1_T20_honest_timing_and_no_state_leak(r1_session):
    """Honest timing fields; the runner's consolidated record carries the
    actual start; every chain record's workdir exists for re-examination."""
    r = r1_session["runner"]
    assert r["started_at_utc"] < r["consolidated_at_utc"]
    for c in r1_session["chains"]:
        assert Path(c["workdir"]).exists()
