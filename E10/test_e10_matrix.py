#!/usr/bin/env python3
"""E10 REQUIRED TEST MATRIX (E10 section 26) — T01..T20.

A session-scoped fixture runs the COMPLETE cross-process chain as real OS
subprocesses (Process A -> SIGKILL -> Process B -> tamper -> independent
verifier). Every test then asserts its criterion against the recorded
evidence, so the whole proof is repeatable (E10-26) and re-examinable from
outside Process B (E10-27).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def _load(p: Path):
    return json.loads(p.read_text())


@pytest.fixture(scope="session")
def chain(tmp_path_factory):
    """Run the full E10 cross-process chain once; return evidence bundle."""
    workdir = tmp_path_factory.mktemp("e10_matrix_")
    proc = subprocess.run(
        [sys.executable, str(HERE / "run_e10.py")],
        capture_output=True, text=True, timeout=600,
        cwd=str(REPO),
    )
    # run_e10.py creates its own temp workdir; locate it from its output
    assert proc.returncode == 0, f"E10 chain failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-2000:]}"
    wd_line = [l for l in proc.stdout.splitlines() if l.startswith("[RUNNER] workdir=")][0]
    work = Path(wd_line.split("=", 1)[1].strip())
    ev = work / "evidence"
    return {
        "workdir": work,
        "evidence_dir": ev,
        "runner": _load(ev / "runner.json"),
        "process_a": _load(ev / "process_a.json"),
        "process_b": _load(ev / "process_b.json"),
        "resume_info": _load(ev / "resume_info.json"),
        "tamper": _load(ev / "tamper.json"),
        "verifier": _load(ev / "verifier.json"),
        "stdout": proc.stdout,
    }


# ---------------------------------------------------------------- T01
def test_E10_T01_fresh_mission_execution(chain):
    """Fresh mission executed on the production path with a 5-task graph."""
    pa = chain["process_a"]
    assert pa["status"] == "PROCESS_A_COMPLETE"
    assert len(pa["task_ids"]) == 5
    states = pa["boundary_task_states"]
    assert states["TASK_A"] == "COMPLETED"
    assert states["TASK_B"] == "COMPLETED"
    assert states["TASK_C"] == "COMPLETED"
    # mission + run executed through MissionController.execute_run
    assert pa["execute_run_result"]["paused"] is True


# ---------------------------------------------------------------- T02
def test_E10_T02_checkpoint_durable_payload(chain):
    """Checkpoint file on disk carries the full durable payload."""
    cp = chain["process_a"]["checkpoint"]
    assert cp["ALL_DURABLE_CHECKPOINT_ASSERTIONS_PASSED"] is True
    assert cp["checkpoint_file_exists"] and cp["checkpoint_json_valid"]
    assert cp["task_states_present"]
    deps = cp["dependencies_present"]
    assert {k: sorted(v) for k, v in deps.items()} == {
        "TASK_A": [], "TASK_B": ["TASK_A"], "TASK_C": ["TASK_A"],
        "TASK_D": ["TASK_B", "TASK_C"], "TASK_E": ["TASK_D"],
    }
    assert all(len(v) == 1 for k, v in cp["attempt_history_present"].items()
               if k in ("TASK_A", "TASK_B", "TASK_C"))
    assert len(cp["artifact_ids_present"]) == 3
    # each artifact yields two evidence records (ToolExecutor + agent-side
    # compatibility record) with the SAME content hash -> 6 records, 3 unique
    hashes = cp["evidence_hashes_present"]
    assert len(hashes) == 6 and len(set(hashes)) == 3
    assert cp["evidence_hashes_are_content_hashes"] is True
    assert cp["mission_run_identity_present"] is True


# ---------------------------------------------------------------- T03
def test_E10_T03_process_a_termination(chain):
    """Process A REALLY terminated — SIGKILL witnessed by the runner."""
    runner = chain["runner"]
    assert runner["process_a"]["termination"].startswith("SIGKILL")
    assert runner["stage_exit_codes"]["PROCESS_A"] == -9
    assert runner["process_a"]["pid_match"] is True


# ---------------------------------------------------------------- T04
def test_E10_T04_process_b_different_pid(chain):
    """Process B is a different OS process: PID_B != PID_A, both witnessed."""
    runner = chain["runner"]
    assert runner["pid_difference"] is True
    assert runner["process_a"]["runner_observed_pid"] != runner["process_b"]["runner_observed_pid"]
    assert chain["process_b"]["pid_difference"] is True
    assert chain["process_b"]["process_a_pid"] == runner["process_a"]["runner_observed_pid"]


# ---------------------------------------------------------------- T05
def test_E10_T05_checkpoint_loaded_from_disk(chain):
    """Process B read the checkpoint from DISK, not from memory."""
    log = {s["step"]: s for s in chain["process_b"]["restoration_log"]}
    read = log["read_checkpoint_from_disk"]
    assert read["path"].endswith(".json")
    assert Path(read["path"]).exists()
    # the memory-first path would not need the file: prove the file is the source
    assert read["integrity_verified"] is True


# ---------------------------------------------------------------- T06
def test_E10_T06_checkpoint_integrity_verified(chain):
    """Integrity hash recomputed and matched BEFORE any execution."""
    log = {s["step"]: s for s in chain["process_b"]["restoration_log"]}
    read = log["read_checkpoint_from_disk"]
    assert read["stored_hash"] == read["recomputed_hash"]
    assert len(read["stored_hash"]) == 64
    # and the tamper test proves the check actually rejects (see T17)
    assert chain["tamper"]["detected_mismatch"] is True


# ---------------------------------------------------------------- T07
def test_E10_T07_mission_identity_restored(chain):
    fid = chain["process_b"]["restoration_fidelity"]
    assert fid["mission_identity_unchanged"] is True
    assert chain["verifier"]["checks"]["mission_identity_preserved"]["passed"] is True


# ---------------------------------------------------------------- T08
def test_E10_T08_run_task_graph_reconstructed(chain):
    fid = chain["process_b"]["restoration_fidelity"]
    assert fid["task_count_identical"] is True
    assert fid["task_ids_preserved"] is True
    assert fid["task_dependencies_preserved"] is True
    assert fid["run_lineage_preserved"] is True
    assert chain["verifier"]["checks"]["run_lineage_verified"]["passed"] is True


# ---------------------------------------------------------------- T09
def test_E10_T09_completed_tasks_preserved(chain):
    fid = chain["process_b"]["restoration_fidelity"]
    assert fid["completed_tasks_preserved"] is True
    assert fid["restored_states"]["TASK_A"] == "COMPLETED"
    assert fid["restored_states"]["TASK_B"] == "COMPLETED"
    assert fid["restored_states"]["TASK_C"] == "COMPLETED"


# ---------------------------------------------------------------- T10
def test_E10_T10_incomplete_task_resumed(chain):
    pb = chain["process_b"]
    assert pb["final_task_states"] == {
        "TASK_A": "COMPLETED", "TASK_B": "COMPLETED", "TASK_C": "COMPLETED",
        "TASK_D": "COMPLETED", "TASK_E": "COMPLETED",
    }
    acc = pb["side_effect_accounting"]
    assert len(acc["new_attempts_post_resume"]["TASK_D"]) == 1
    assert len(acc["new_attempts_post_resume"]["TASK_E"]) == 1


# ---------------------------------------------------------------- T11
def test_E10_T11_completed_task_not_reexecuted(chain):
    pb = chain["process_b"]
    assert pb["completed_tasks_not_reexecuted"] is True
    acc = pb["side_effect_accounting"]
    for k in ("TASK_A", "TASK_B", "TASK_C"):
        assert acc["new_attempts_post_resume"][k] == []
        # engine's own skip marker for resumed tasks
        assert pb["resumed_task_markers"][k].get("resumed") is True
    assert pb["completed_artifacts_unchanged"] is True


# ---------------------------------------------------------------- T12
def test_E10_T12_artifact_continuity(chain):
    cont = chain["process_b"]["artifact_continuity"]
    assert cont, "no artifact continuity records"
    for key, v in cont.items():
        assert v["read_from_disk"] is True, key
        assert v["sha256_matches_record"] is True, key
    assert chain["verifier"]["checks"]["artifact_hashes_valid"]["passed"] is True
    assert chain["verifier"]["checks"]["completed_work_preserved_across_processes"]["passed"] is True


# ---------------------------------------------------------------- T13
def test_E10_T13_evidence_continuity(chain):
    v = chain["verifier"]["checks"]["evidence_valid"]
    assert v["passed"] is True
    for eid, rec in v["observed"].items():
        assert rec["is_content_hash"] is True
        assert rec["hash_matches_source_artifact"] is True


# ---------------------------------------------------------------- T14
def test_E10_T14_attempt_ledger_continuity(chain):
    fid = chain["process_b"]["restoration_fidelity"]
    assert fid["attempt_history_preserved"] is True
    v = chain["verifier"]["checks"]["attempt_history_consistent"]
    assert v["passed"] is True
    for key, rec in v["observed"].items():
        if key in ("TASK_A", "TASK_B", "TASK_C"):
            assert rec["attempts_pre_resume"] == 1 and rec["attempts_post_resume"] == 0
        else:
            assert rec["attempts_pre_resume"] == 0 and rec["attempts_post_resume"] == 1


# ---------------------------------------------------------------- T15
def test_E10_T15_event_continuity(chain):
    log = {s["step"]: s for s in chain["process_b"]["restoration_log"]}
    ev = log["event_history_restored_from_disk"]
    assert ev["restored_events_exact"] is True
    assert ev["lost"] == 0
    assert ev["duplicated_old_events"] == 0
    assert ev["new_events_all_resume_emitted"] is True
    assert chain["verifier"]["checks"]["event_history_durable_no_restoration_duplicates"]["passed"] is True


# ---------------------------------------------------------------- T16
def test_E10_T16_side_effect_idempotency(chain):
    v = chain["verifier"]["checks"]["no_unsafe_duplicate_side_effects"]
    assert v["passed"] is True
    per_task = v["observed"]["artifact_records_per_task"]
    assert all(n == 1 for n in per_task.values())
    files = v["observed"]["sandbox_files_per_task"]
    assert all(len(lst) == 1 for lst in files.values())


# ---------------------------------------------------------------- T17
def test_E10_T17_tampered_checkpoint_rejected(chain):
    t = chain["tamper"]
    assert t["resume_result"] == "REJECTED"
    assert "CheckpointIntegrityError" in t["rejection_reason"]
    assert t["detected_mismatch"] is True
    assert t["no_task_execution"] is True
    assert t["attempts_created"] == 0 and t["task_graphs_created"] == 0


# ---------------------------------------------------------------- T18
def test_E10_T18_independent_verifier_confirms(chain):
    v = chain["verifier"]
    assert v["verdict"] == "VERIFIED"
    assert v["verifier_pid"] != chain["process_b"]["process_b_pid"]
    assert all(c["passed"] for c in v["checks"].values())
    # verifier truth sources are persistent files only
    for src in v["truth_sources"].values():
        assert Path(src).exists()


# ---------------------------------------------------------------- T19
def test_E10_T19_e8_regression(chain):
    """E8 regression suite passes at the E10-changed code."""
    proc = subprocess.run(
        [sys.executable, "run_e8_human_gates.py"],
        capture_output=True, text=True, timeout=600, cwd=str(REPO),
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO / "src")},
    )
    assert proc.returncode == 0, proc.stdout[-3000:]
    assert proc.stdout.count("REJECTED") >= 4  # 4/4 negative tests REJECTED


# ---------------------------------------------------------------- T20
def test_E10_T20_e9_regression(chain):
    """E9/E9-R1 regression suite passes at the E10-changed code."""
    proc = subprocess.run(
        [sys.executable, "E9-R/test_production_integration.py"],
        capture_output=True, text=True, timeout=600, cwd=str(REPO),
    )
    assert proc.returncode == 0, proc.stdout[-3000:]
    assert "OVERALL: PASS" in proc.stdout
    assert "E9-R VERIFIED" in proc.stdout


# ============================================================
# E10-CW1 — CRASH-WINDOW IDEMPOTENCY PROOF (order E10-CW1)
#
# The E10 chain above proves resume from a SAFE boundary (checkpoint
# after completed work). E10-CW1 proves the harder window: Process A is
# SIGKILLed AFTER the governed side effect of TASK_D and BEFORE any
# durable record of TASK_D's completion. Process B must reconcile —
# never re-perform the physical write.
# ============================================================

CW1_HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="session")
def cw1_chain(tmp_path_factory):
    """Run the complete E10-CW1 cross-process proof (2 chains)."""
    workdir = tmp_path_factory.mktemp("e10cw1_matrix_")
    proc = subprocess.run(
        [sys.executable, str(CW1_HERE / "run_e10cw1.py")],
        capture_output=True, text=True, timeout=600, cwd=str(REPO),
    )
    assert proc.returncode == 0, f"E10-CW1 chain failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-2000:]}"
    sess_line = [l for l in proc.stdout.splitlines() if l.startswith("[RUNNER] session=")][0]
    session = Path(re.match(r"\[RUNNER\] session=(\S+)", sess_line).group(1))
    ev = session / "evidence"
    chains = [_load_line(l) for l in (ev / "chains.jsonl").read_text().splitlines() if l.strip()]
    return {
        "session": session,
        "runner": _load(ev / "runner.json"),
        "chains": chains,
        "chain": {
            "runner": chains[-1],
            "resume_info": _load(session / "chain2" / "evidence" / "resume_info.json"),
            "injection": _load(session / "chain2" / "evidence" / "injection.json"),
            "snapshot": _load(session / "chain2" / "evidence" / "crash_window_snapshot.json"),
            "process_b": _load(session / "chain2" / "evidence" / "process_b.json"),
            "verifier": _load(session / "chain2" / "evidence" / "verifier.json"),
        },
    }


def _load_line(l):
    return json.loads(l)


# ---------------------------------------------------------------- CW1-T01
def test_E10CW1_T01_crash_point_inside_window(cw1_chain):
    """The kill landed AFTER the side effect and BEFORE any durable
    completion record — at a real lifecycle boundary, not a safe stop."""
    ch = cw1_chain["chain"]
    inj = ch["injection"]
    snap = ch["snapshot"]
    assert inj["task_key"] == "TASK_D"
    assert inj["reached_at_utc"]
    iw = snap["crash_point_in_window"]
    assert iw["injection_reached"] is True
    assert iw["crash_window_task_not_completed_in_checkpoint"] is True
    assert iw["completed_tasks_in_checkpoint"] is True
    assert iw["no_durable_task_completed_for_crash_window_task"] is True
    assert iw["side_effect_file_exists"] is True
    # the side effect (journaled) happened strictly BEFORE the kill
    jrec = snap["journal_performed_record"]
    assert jrec and jrec["recorded_at_utc"] <= inj["reached_at_utc"]
    assert iw["journal_recorded_before_kill"] is True
    # the resume checkpoint still shows D not completed — the gap is not covered
    assert iw["last_checkpoint_states"]["TASK_D"] in ("READY", "PENDING", "RUNNING")


# ---------------------------------------------------------------- CW1-T02
def test_E10CW1_T02_real_sigkill_and_new_pid(cw1_chain):
    for c in cw1_chain["chains"]:
        assert c["process_a"]["exit_code"] == -9
        assert c["process_a"]["termination_reason"].startswith("SIGKILL")
        assert c["pid_difference"] is True
        assert c["process_b"]["runner_observed_pid"] != c["process_a"]["runner_observed_pid"]


# ---------------------------------------------------------------- CW1-T03
def test_E10CW1_T03_no_durable_completion_at_crash(cw1_chain):
    ch = cw1_chain["chain"]
    pb = ch["process_b"]
    fid = pb["restoration_fidelity"]
    assert fid["restored_states"]["TASK_D"] in ("READY", "PENDING", "RUNNING")
    assert fid["restored_states"]["TASK_E"] == "BLOCKED"
    # the pre-crash in-memory attempt/artifact records were NEVER durable:
    assert fid["durable_attempt_for_crash_window_task"] == 0
    assert fid["durable_artifact_record_for_crash_window_task"] == 0
    # but the side effect itself WAS durably journaled at write time:
    assert fid["journal_performed_for_crash_window_task"] == 1
    assert fid["journal_reconciled_before_resume"] == 0
    # nothing touched the file between the crash and the resume:
    log = {s["step"]: s for s in pb["restoration_log"]}
    assert log["side_effect_file_untouched_since_crash"]["untouched"] is True


# ---------------------------------------------------------------- CW1-T04
def test_E10CW1_T04_restore_from_durable_only(cw1_chain):
    ch = cw1_chain["chain"]
    v = ch["verifier"]["checks"]["process_b_new_process_restored_from_durable_only"]
    assert v["passed"] is True
    assert v["observed"]["resume_info_ids_only"] is True
    assert v["observed"]["pid_difference"] is True


# ---------------------------------------------------------------- CW1-T05
def test_E10CW1_T05_side_effect_not_reperformed(cw1_chain):
    """THE core claim: the physical write is NOT repeated across the crash
    window — proven by OS-level mtime_ns/inode/sha256 comparison."""
    for c in cw1_chain["chains"]:
        se = c["side_effect_file"]
        assert se["no_physical_rewrite"] is True
        assert se["pre_resume"]["mtime_ns"] == se["post_resume"]["mtime_ns"]
        assert se["pre_resume"]["inode"] == se["post_resume"]["inode"]
        assert se["pre_resume"]["sha256"] == se["post_resume"]["sha256"]
    v = cw1_chain["chain"]["verifier"]["checks"]["records_reflect_stored_truth_not_declared_values"]
    assert v["passed"] is True
    three_way = v["observed"]["d_three_way_mtime"]
    assert three_way["journal_performed"] == three_way["reconciled_observed"] == three_way["file_now"]


# ---------------------------------------------------------------- CW1-T06
def test_E10CW1_T06_original_artifact_identity_preserved(cw1_chain):
    ch = cw1_chain["chain"]
    acc = ch["process_b"]["side_effect_accounting"]
    ai = acc["artifact_identity"]
    assert ai["count"] == 1
    assert ai["is_original"] is True
    assert ai["after_resume"] == [ai["original_from_journal"]]
    # E10-CW1-R1 §6: exactly ONE ARTIFACT_CREATED per artifact identity +
    # ONE ARTIFACT_RECONCILED (distinct reconciliation semantics)
    assert acc["events"]["artifact_created_ids"] == [ai["original_from_journal"]]
    assert acc["events"]["artifact_reconciled_for_crash_window_task"] == 1
    assert acc["events"]["artifact_reconciled_modes"] == ["performed_record"]
    v = cw1_chain["chain"]["verifier"]["checks"]["side_effect_identity_linked_to_correct_task_and_operation"]
    assert v["passed"] is True


# ---------------------------------------------------------------- CW1-T07
def test_E10CW1_T07_exactly_once_records(cw1_chain):
    ch = cw1_chain["chain"]
    v = ch["verifier"]["checks"]["side_effect_count_matches_expected_no_unsafe_copy"]
    assert v["passed"] is True
    obs = v["observed"]
    assert obs["journal_for_d"] == {"performed": 1, "reconciled": 1, "no_physical_rewrite_flag": True}
    assert all(n == 1 for n in obs["artifact_records_per_task"].values())
    assert obs["total_task_completed_events"] == 5
    assert obs["duplicate_event_tuples"] == 0
    ev = ch["verifier"]["checks"]["attempts_and_events_consistent_with_crash_and_resume"]["observed"]
    assert all(n == 2 for n in ev["evidence_per_task"].values())


# ---------------------------------------------------------------- CW1-T08
def test_E10CW1_T08_task_e_fresh_and_dependency_order(cw1_chain):
    ch = cw1_chain["chain"]
    acc = ch["process_b"]["side_effect_accounting"]
    # TASK_E was never started before the crash -> it executes fresh post-resume
    # (journal_index filters to effective records: 1 performed; the intent
    # record preceding it is asserted by the R1 harness)
    assert len(acc["journal_records_for_task_e"]) == 1
    assert acc["journal_records_for_task_e"][0]["record_type"] == "performed"
    v = ch["verifier"]["checks"]["attempts_and_events_consistent_with_crash_and_resume"]
    assert v["passed"] is True
    att = v["observed"]["attempts"]
    assert att["TASK_E"]["pre_resume"] == 0 and att["TASK_E"]["post_resume"] == 1


# ---------------------------------------------------------------- CW1-T09
def test_E10CW1_T09_independent_verifier_verified(cw1_chain):
    ch = cw1_chain["chain"]
    v = ch["verifier"]
    assert v["verdict"] == "VERIFIED"
    assert v["verifier_pid"] != ch["process_b"]["process_b_pid"]
    assert len(v["checks"]) == 9
    assert all(c["passed"] for c in v["checks"].values())
    for src in v["truth_sources"].values():
        assert Path(src).exists()
    for c in cw1_chain["chains"]:
        assert c["verifier_exit_code"] == 0


# ---------------------------------------------------------------- CW1-T10
def test_E10CW1_T10_repeat_runs_same_result(cw1_chain):
    r = cw1_chain["runner"]
    assert r["status"] == "E10_CW1_CHAIN_COMPLETE"
    assert r["started_at_utc"] < r["consolidated_at_utc"]  # honest timing fields
    assert len(cw1_chain["chains"]) >= 2
    assert all(c["side_effect_file"]["no_physical_rewrite"] for c in cw1_chain["chains"])
    v = cw1_chain["chain"]["verifier"]["checks"]["repeat_runs_produce_same_result"]
    assert v["passed"] is True
    assert v["observed"]["this_chain_no_physical_rewrite"] is True


# ---------------------------------------------------------------- CW1-T11 (unit)
def test_E10CW1_T11_layered_idempotency_records_persisted():
    """Deterministic coverage of the OTHER sub-variant of the single crash
    window: the side-effect records WERE durably persisted (e.g. by a
    parallel task's checkpoint) while the task's completion was not.
    The reconcile path must then not duplicate any record at any layer."""
    import asyncio
    import hashlib
    import tempfile

    sys.path.insert(0, str(CW1_HERE))
    from e10cw1_common import build_engine, journal_path, read_journal, stat_snapshot

    tmp = tempfile.mkdtemp(prefix="cw1_unit_persisted_")
    art = Path(tmp) / "artifacts"

    async def scenario():
        engine = build_engine(art)
        from unified.contracts import new_attempt_id
        ctx = type("Ctx", (), {})()  # minimal ExecutionContext-like carrier
        # use the REAL ExecutionContext of the engine
        from unified.execution import ExecutionContext
        from unified.agent_role import AgentType
        context = ExecutionContext(
            mission_id="m-cw1-unit", run_id="r-cw1-unit", task_id="task-cw1-unit",
            attempt_id=new_attempt_id(), agent_id="", agent_type=AgentType.IMPLEMENTER,
            sandbox_id="sandbox-task-cw1-unit",
        )
        context.tool_executor = engine.tool_executor
        context.grant_validator = engine.grant_validator
        result1 = await engine.execute_tool(
            context, "artifact_write",
            {"sandbox_id": context.sandbox_id, "path": "out.txt", "content": "cw1-unit-payload"},
        )
        f = Path(art) / "sandbox-task-cw1-unit" / "out.txt"
        st1 = stat_snapshot(f)
        # a parallel checkpoint persists the records (events + evidence store)
        engine._save_events_to_disk("m-cw1-unit")
        engine.evidence_store.save_to_disk("m-cw1-unit")

        # NEW process: fresh engine, records restored from disk (as resume does)
        engine2 = build_engine(art)
        engine2.evidence_store.load_from_disk("m-cw1-unit")
        engine2._restore_events_from_disk("m-cw1-unit")
        ev_before = len([e for e in engine2.event_bus.history
                          if e.event_type.value == "artifact.created"
                          and (e.payload or {}).get("artifact_id") == result1.output["artifact_id"]])
        evid_before = sum(1 for ev in engine2.evidence_store._evidence.values()
                           if ev.source_id == result1.output["artifact_id"])

        result2 = await engine2.execute_tool(
            context, "artifact_write",
            {"sandbox_id": context.sandbox_id, "path": "out.txt", "content": "cw1-unit-payload"},
        )
        return engine, engine2, result1, result2, st1, ev_before, evid_before, f

    engine, engine2, r1, r2, st1, ev_before, evid_before, f = asyncio.run(scenario())
    # original identity, no re-write
    assert r2.output["artifact_id"] == r1.output["artifact_id"]
    assert r2.output["sha256"] == r1.output["sha256"]
    st2 = stat_snapshot(f)
    assert st2["mtime_ns"] == st1["mtime_ns"] and st2["inode"] == st1["inode"]
    # no duplicate ARTIFACT_CREATED event (already restored from disk)
    ev_after = len([e for e in engine2.event_bus.history
                     if e.event_type.value == "artifact.created"
                     and (e.payload or {}).get("artifact_id") == r1.output["artifact_id"]])
    assert ev_after == ev_before == 1
    # no duplicate evidence record for the same source artifact
    evid_after = sum(1 for ev in engine2.evidence_store._evidence.values()
                      if ev.source_id == r1.output["artifact_id"])
    assert evid_after == evid_before == 1
    # exactly one artifact record for the path
    arts = [a for a in engine2.evidence_store._artifacts.values() if a.path == "out.txt"]
    assert len(arts) == 1 and arts[0].artifact_id == r1.output["artifact_id"]
    # journal: E10-CW1-R1 contract — 1 intent (pre-effect identity) +
    # 1 performed (the original physical write) + 1 reconciled (the resume
    # reconciliation). The R1 contract is TIGHTER than the CW1 one: the
    # intent record must precede the effect; the physical write stays at
    # exactly one.
    recs = read_journal(art, "m-cw1-unit")
    assert [r["record_type"] for r in recs if r["task_id"] == "task-cw1-unit"] == [
        "intent", "performed", "reconciled"
    ]
    d_recs = [r for r in recs if r["task_id"] == "task-cw1-unit"]
    assert d_recs[1]["intent_journal_record_id"] == d_recs[0]["journal_record_id"]
    assert d_recs[0]["artifact_id"] == d_recs[1]["artifact_id"] == r1.output["artifact_id"]


# ---------------------------------------------------------------- CW1-T12 (unit, negative)
def test_E10CW1_T12_fail_closed_reconciliation():
    """Any prior journal record that cannot be reconciled safely makes the
    operation FAIL CLOSED at the tool boundary (the engine's existing tool
    contract converts tool-layer exceptions into failed ToolResults):
    success=False, error_type=SideEffectReconciliationError, an explicit
    reason — and the physical write is NEVER re-performed and never
    silently skipped."""
    import asyncio
    import os as _os
    import tempfile

    sys.path.insert(0, str(CW1_HERE))
    from e10cw1_common import build_engine, stat_snapshot

    tmp = tempfile.mkdtemp(prefix="cw1_unit_neg_")
    art = Path(tmp) / "artifacts"

    async def prepare():
        engine = build_engine(art)
        from unified.contracts import new_attempt_id
        from unified.agent_role import AgentType
        from unified.execution import ExecutionContext
        context = ExecutionContext(
            mission_id="m-cw1-neg", run_id="r-cw1-neg", task_id="task-cw1-neg",
            attempt_id=new_attempt_id(), agent_id="", agent_type=AgentType.IMPLEMENTER,
            sandbox_id="sandbox-task-cw1-neg",
        )
        await engine.execute_tool(
            context, "artifact_write",
            {"sandbox_id": context.sandbox_id, "path": "out.txt", "content": "neg-payload"},
        )
        return context

    context = asyncio.run(prepare())
    f = Path(art) / "sandbox-task-cw1-neg" / "out.txt"
    base = stat_snapshot(f)

    async def call(eng, content):
        return await eng.execute_tool(
            context, "artifact_write",
            {"sandbox_id": "sandbox-task-cw1-neg", "path": "out.txt", "content": content},
        )

    def fresh_engine():
        return build_engine(art)

    def assert_fail_closed(res, fragment, state_desc, state_check):
        assert res is not None, "tool call must return, not raise"
        assert res.success is False
        assert res.error_type == "SideEffectReconciliationError"
        assert res.error.startswith("SIDE_EFFECT_RECONCILIATION_FAILED")
        assert fragment in res.error
        assert state_check(), f"side effect state diverged: {state_desc}"

    # (1) file deleted after the journal record -> missing-from-disk refusal
    f.unlink()
    res = asyncio.run(call(fresh_engine(), "neg-payload"))
    assert_fail_closed(res, "missing from disk", "file must stay deleted", lambda: not f.exists())

    # (2) content tampered on disk -> divergence refusal (no re-write)
    f.write_bytes(b"tampered")
    res = asyncio.run(call(fresh_engine(), "neg-payload"))
    assert_fail_closed(res, "diverged", "tampered content must stay", lambda: f.read_bytes() == b"tampered")

    # (3) different content requested for the same logical operation -> refusal
    f.write_bytes(b"neg-payload")
    st = f.stat()
    _os.utime(f, ns=(st.st_atime_ns, base["mtime_ns"]))
    res = asyncio.run(call(fresh_engine(), "DIFFERENT"))
    assert_fail_closed(res, "differs from the requested content hash",
                       "file must stay untouched", lambda: f.read_bytes() == b"neg-payload")

    # (4) same content but the file was rewritten externally (mtime changed)
    f.write_bytes(b"neg-payload")  # same content, new mtime
    res = asyncio.run(call(fresh_engine(), "neg-payload"))
    assert_fail_closed(res, "rewritten or touched",
                       "file must stay untouched", lambda: f.read_bytes() == b"neg-payload")

    # journal must contain exactly ONE intent + ONE performed record for the
    # logical operation (never re-performed; E10-CW1-R1: the intent record
    # precedes the effect and pins the identity)
    from e10cw1_common import read_journal
    recs = [r for r in read_journal(art, "m-cw1-neg") if r["task_id"] == "task-cw1-neg"]
    assert [r["record_type"] for r in recs] == ["intent", "performed"]
    assert all(r["artifact_id"] == recs[0]["artifact_id"] for r in recs)
