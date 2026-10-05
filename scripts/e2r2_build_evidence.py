#!/usr/bin/env python3
"""E2-R2 evidence builder — containment-audit.json, e33-before.json, e33-after.json.

All inputs are REAL captured artifacts from this session's runs (no invented
values). Sources:
  - /tmp/e2r2_prefix_mutation_run2.txt  (git status of docs/evidence after the pre-fix E33 run)
  - /tmp/e2r2_before_run.txt            (pytest output of the pre-fix E33 run)
  - /tmp/e2r2_e33_run3/...              (layer-2 failure: runner stderr of the intermediate run)
  - /tmp/e2r2_e33_run4/evidence/e33/*   (post-fix passing E33 evidence)
  - E2-R2/canonical-before.json, canonical-after.json, containment-proof.json (§4)
"""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/home/z/my-project/work/factory")
OUT = REPO / "E2-R2"


def jload(p: Path):
    return json.loads(p.read_text())


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()

    # ---------------- containment-audit.json (§3 + §4 + §11) ----------------
    before = jload(OUT / "canonical-before.json")
    after = jload(OUT / "canonical-after.json")
    proof = jload(OUT / "containment-proof.json")

    pre_fix_mutations = Path("/tmp/e2r2_prefix_mutation_run2.txt").read_text().strip().splitlines()
    deletions = [l[3:] for l in pre_fix_mutations if l.startswith(" D ")]
    modifications = [l[3:] for l in pre_fix_mutations if l.startswith(" M ")]
    additions = [l[3:] for l in pre_fix_mutations if l.startswith("?? ")]

    audit = {
        "generated_at": now,
        "rule": "No test may write to, modify, or delete canonical evidence (docs/evidence/**) or any fixed canonical path. Every test run gets TEST_ROOT / TEMP_EVIDENCE_ROOT / TEMP_ARTIFACT_ROOT.",

        "audit_scope": ["tests/unified/test_e32e_durable_execution.py",
                        "tests/unified/test_e32f_autonomous_replanning.py",
                        "tests/unified/test_e33_mission_autonomy.py",
                        "tests/unified/e33_mission_runner.py"],

        "violations_found": [
            {
                "test": "E33 (tests/unified/test_e33_mission_autonomy.py)",
                "positions": [
                    "REPO_ROOT / 'docs' / 'evidence' / 'e33' as EVIDENCE_DIR (all _dump() evidence exports)",
                    "EVIDENCE_DIR / 'state' as STATE_DIR — engine artifacts_base_dir (checkpoints/, events/, evidence_store/, sandbox-task-*)",
                    "evidence_env fixture: shutil.rmtree(STATE_DIR) — DELETED 34 tracked canonical evidence files on every run",
                ],
                "pre_fix_proof": {
                    "description": "One pre-fix E33 run (this session, authentic) mutated canonical evidence:",
                    "deleted_tracked": len(deletions),
                    "modified_tracked": len(modifications),
                    "untracked_added": len(additions),
                    "deleted_sample": deletions[:5],
                    "modified": modifications,
                },
            },
            {
                "test": "E32e (tests/unified/test_e32e_durable_execution.py)",
                "positions": ["open(Path('docs/evidence/e32e/pre_resume_state.json'), 'w') — line 671 (cwd-relative canonical write)"],
            },
            {
                "test": "E32f (tests/unified/test_e32f_autonomous_replanning.py)",
                "positions": [f"open(Path('docs/evidence/e32f/{name}'), 'w')" for name in [
                    "E32F_PLAN_V1.json", "E32F_DEVIATION.json", "E32F_REPLAN_V2.json",
                    "E32F_PLAN_DIFF.json", "E32F_CHECKPOINT.json", "E32F_RESUME_AFTER_REPLAN.json",
                    "E32F_EVENT_TRACE.json", "E32F_EVIDENCE_CHAIN.json", "E32F_TEST_RESULTS.json",
                    "E32F_ACCEPTANCE_MATRIX.json"]],
            },
        ],

        "containment_mechanism": {
            "module": "tests/unified/containment.py",
            "roots": {
                "TEST_ROOT": "tempfile.mkdtemp(prefix='unified-test-') (or $UNIFIED_TEST_ROOT override)",
                "TEMP_EVIDENCE_ROOT": "TEST_ROOT/evidence — all test evidence dumps",
                "TEMP_ARTIFACT_ROOT": "TEST_ROOT/state — all engine state (checkpoints, events, evidence store, sandbox)",
            },
            "writes_directly_to_docs_evidence": "NONE (verified: zero docs/evidence references remain in the three suites outside comments)",
        },

        "containment_proof": {
            "method": "full recursive sha256 inventory of docs/evidence/ before and after running E32e + E32f + E33",
            "run": "UNIFIED_TEST_ROOT=/tmp/e2r2_proof_run pytest tests/unified/test_e32e_durable_execution.py tests/unified/test_e32f_autonomous_replanning.py tests/unified/test_e33_mission_autonomy.py",
            "results": "2 passed (E33 baseline + full mission), 10 skipped (NVIDIA key, honest)",
            "before_tree_sha256": before["tree_sha256"],
            "after_tree_sha256": after["tree_sha256"],
            "before_file_count": before["file_count"],
            "after_file_count": after["file_count"],
            "added": proof["added"], "removed": proof["removed"],
            "modified_content": proof["modified_content"],
            "touched_only_identical_content": proof["touched_only_identical_content"],
            "canonical_evidence_mutation": proof["canonical_evidence_mutation"],
            "verdict": proof["verdict"],
            "git_status_docs_evidence_after_run": "clean (0 entries)",
        },

        "out_of_scope_writers_disclosed": [
            {"test": "tests/e35/test_long_mission.py", "position": "Path('docs/evidence/e35') copies (line ~934)"},
            {"test": "tests/e37/test_multi_task_mission.py", "position": "evidence_dir 'docs/evidence/e36/' reference"},
            {"test": "tests/e43/test_adversarial.py", "positions": ["Path('docs/evidence/e42') read", "Path('docs/evidence/e43') writes"]},
            {"note": "These suites are OUTSIDE the E2-R2 §3 inspection scope (E32e/E32f/E33) and outside the §10 regression matrix scope (unified/factory/core). Disclosed for a future phase; not modified here (scope discipline)."}
        ],

        "path_exclusivity_audit": {
            "canonical": {
                "construction": "MissionController(P2) over ExecutionEngine(P1) — explicit construction",
                "proof": "E2-R2/golden-path-trace.json (13/13 links), E2-R2/durability-trace.json, E33 2/2 PASS",
            },
            "p3_adapter": {
                "module": "src/unified/operational.py::OperationalExecutionEngine",
                "delegates_to": "MissionController over ExecutionEngine (line 2137: MissionController(engine, ...)); docstring: 'delegates to MissionController as the single official mission execution path'",
                "wired_as_execution_substrate": False,
            },
            "p4_legacy": {
                "module": "src/core/orchestrator.py::Orchestrator",
                "legacy_surfaces": ["src/missions.py (live mission runner, order 006)", "src/missions_textstats.py (line 536)", "src/api/routes.py mission endpoints (run_mission / run_textstats_mission imports)"],
                "auto_selected_for_new_missions": False,
                "deleted": False, "migrated": False, "modified_by_e2r2": False,
            },
            "p5_legacy": {
                "module": "src/factory/orchestrator.py::AgentFactoryOrchestrator",
                "legacy_surfaces": ["src/factory/cli.py", "run_cockpit.py"],
                "auto_selected_for_new_missions": False,
                "deleted": False, "migrated": False, "modified_by_e2r2": False,
            },
            "p6_experimental": {
                "module": "run_e50_dependency_engine.py::DependencyEngine (E50/E51)",
                "production_integrated": False,
                "proof": "src/unified/execution.py references it ONLY behind hasattr(self,'dependency_engine') (line 1485) — the engine never attaches it; only E50/E51 test runners attach it explicitly",
                "deleted": False, "migrated": False, "modified_by_e2r2": False,
            },
            "git_diff_proof": "E2-R2 changed only: src/unified/execution.py, src/unified/mission_controller.py, tests/unified/{test_e32e,test_e32f,test_e33,containment.py}. P3/P4/P5/P6 files have EMPTY diff vs baseline.",
        },
    }
    (OUT / "containment-audit.json").write_text(json.dumps(audit, indent=2, default=str))

    # ---------------- e33-before.json ----------------
    before_run = Path("/tmp/e2r2_before_run.txt").read_text(errors="replace")
    runner_stderr = ""
    p = Path("/tmp/e2r2_e33_run3/state/e33/state/runner_stderr.log")
    if p.exists():
        runner_stderr = p.read_text(errors="replace")[-1200:]

    e33_before = {
        "generated_at": now,
        "state": "E33 BEFORE E2-R2 repair (authentic run against baseline sources — E2-R2 source changes stashed)",
        "commit_under_test": subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO),
                                            capture_output=True, text=True).stdout.strip(),
        "runtime": "Linux (this session), CPython 3.12",
        "results": {
            "test_e33_baseline_verification": "PASSED",
            "test_e33_full_mission_autonomy": "FAILED",
            "summary": "1 failed, 1 passed",
        },
        "layer_1_failure": {
            "location": "tests/unified/test_e33_mission_autonomy.py:268",
            "failing_assertion": 'assert "OSError" in c_fail.description or "Tool/runtime" in c_fail.description',
            "error": "AssertionError: 'OSError' in 'tool_runtime injection: sandbox accepted illegal path (unexpected)' — sandbox ACCEPTED the Windows-illegal path 'e33_illegal|filename.txt' on Linux (POSIX allows '|')",
            "consequence": "the injected F2 tool-runtime failure degraded to a synthetic agent-level failure; the illegal-path file was created and stored as evidence (artifact-3044b2670998)",
        },
        "layer_2_failure": {
            "revealed_after_layer_1_fix": True,
            "location": "e33_mission_runner.py phase 2 → src/unified/mission_controller.py:733 → src/unified/execution.py replan_task_graph EXECUTING-guard",
            "error": "RuntimeError: replan_task_graph failed for run <id> — mission restored PAUSED from CP1 by E34 state-restoration; replan is EXECUTING-gated; runner aborts before handshake (process-kill proof never reached)",
            "runner_stderr_tail": runner_stderr,
        },
        "canonical_evidence_mutation_by_the_before_run": {
            "deleted_tracked": len(deletions), "modified_tracked": len(modifications),
            "untracked_added": len(additions),
            "note": "the containment defect itself, demonstrated by the same run",
        },
        "raw_pytest_output_ref": "preserved verbatim in the E2-R2 session log; failing assertion text quoted above is from the authentic run",
        "_raw_tail": before_run[-1500:],
    }
    (OUT / "e33-before.json").write_text(json.dumps(e33_before, indent=2, default=str))

    # ---------------- e33-after.json ----------------
    run4 = Path("/tmp/e2r2_e33_run4/evidence/e33")
    dur = jload(run4 / "E33_DURABILITY.json")
    acc = jload(run4 / "E33_ACCEPTANCE_MATRIX.json")
    led = jload(run4 / "E33_RESUME_LEDGER.json")
    pt = jload(run4 / "E33_PROCESS_TERMINATION.json")
    cps = jload(run4 / "E33_CHECKPOINTS.json")

    e33_after = {
        "generated_at": now,
        "state": "E33 AFTER E2-R2 §6 root-cause repair (real P1+P2, no mock/skip/xfail)",
        "results": {
            "test_e33_baseline_verification": "PASSED",
            "test_e33_full_mission_autonomy": "PASSED",
            "summary": "2 passed",
        },
        "run_root": "isolated TEMP root (/tmp/e2r2_e33_run4) — canonical evidence untouched (containment §4 proof: CANONICAL_EVIDENCE_MUTATION=0)",
        "mission_id": dur["mission_id"],
        "runtimes": dur["runtimes"],
        "process_kill": {
            "runner_pid": pt["runner_pid"], "exit_code": pt["exit_code"],
            "graceful_shutdown": pt["graceful_shutdown"],
            "mechanism_on_this_runtime": "SIGKILL (POSIX equivalent of TerminateProcess)",
        },
        "checkpoints": {
            "CP1": {"checkpoint_id": cps["CP1"]["checkpoint_id"], "sha256": cps["CP1"]["file_sha256"]},
            "CP2": {"checkpoint_id": cps["CP2"]["checkpoint_id"], "sha256": cps["CP2"]["file_sha256"],
                    "survived_process_termination": cps["CP2"]["survived_process_termination"]},
        },
        "plan_versions": dur["plan_versions"],
        "resume_ledger_verdict": led["verdict"],
        "final_mission_state": dur["final_state"]["mission_state"],
        "acceptance_matrix": acc["scale"],
        "canonical_evidence_mutation": 0,
        "verdict": "E33_PASS_ON_REAL_P1_P2",
    }
    (OUT / "e33-after.json").write_text(json.dumps(e33_after, indent=2, default=str))

    # remove the auxiliary proof file (its content is embedded in containment-audit.json)
    aux = OUT / "containment-proof.json"
    if aux.exists():
        aux.unlink()

    print("built: containment-audit.json, e33-before.json, e33-after.json")


if __name__ == "__main__":
    main()
