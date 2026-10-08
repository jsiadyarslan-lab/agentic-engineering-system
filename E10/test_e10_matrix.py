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
