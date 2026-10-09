# E10-CW1 FINAL REPORT — CRASH-WINDOW IDEMPOTENCY PROOF

**EXECUTIVE ORDER:** E10-CW1 (crash-window addendum to E10 — durable execution & cross-process resume)
**VERDICT:** `E10_CW1_PASS`
**PARENT BASELINE:** `50f5371e306a7c44410dee928992892ba1b2d9f7` (E10 final-report commit, == origin/main)
**WORK BRANCH:** `e10-cw1-crash-window-idempotency` (from 50f5371)
**EVIDENCE SESSIONS:** `E10/evidence_cw1/fixed/` (canonical proof) + `E10/evidence_cw1/baseline_gap/` (pre-fix gap demonstration, run against a detached worktree of `50f5371`)

---

## A. WHAT E10 DID NOT PROVE (the crash window)

E10 proved cross-process resume from a **safe boundary**: Process A paused at a
lifecycle boundary, durably checkpointed COMPLETED work, and only then died.
The harder window — the one E10's own order text calls out — was NOT covered:

```text
   governed side effect performed (file written, fsynced)
            |
            |   <=== CRASH WINDOW ===>
            v
   task/attempt completion durably recorded (checkpoint / events / evidence)
```

If the process dies inside this window, the durable state says the task is NOT
complete, so resume must re-execute it — and a naive re-execution re-performs
the physical write. For an artifact write this is observable duplication
(mtime changes, new artifact identity, duplicate records at the event/evidence
layers); for an external side effect (payment, e-mail, deploy) it is
unacceptable.

**Baseline gap demonstration (E10/evidence_cw1/baseline_gap/):** the SAME
scenario, SAME harness, run against the PRE-FIX code at `50f5371` via a
detached git worktree — 2 consecutive chains, both SIGKILLed inside the
window (exit −9, runner-observed PIDs 8192/8194). Result per chain: the
physical write WAS re-performed after resume (`no_physical_rewrite=false`,
mtime_ns changed, a NEW artifact identity `artifact-60ea97e46aa1` replaced the
original, `is_original=false`). This documents the pre-existing failure the
order targets — it is never a pass of any acceptance criterion.

---

## B. THE FIX (minimal, production-path only — `src/unified/execution.py`)

| Component | What it does | Where |
|---|---|---|
| `SideEffectJournal` | Append-only, fsynced JSONL journal of governed artifact writes, written at side-effect time — BEFORE the completion is durably recorded. Torn trailing lines (crash mid-append) are ignored: they never became durable truth. | `execution.py` (new class) |
| Reconciliation identity | Keyed by the STABLE logical operation `(mission_id, task_id, path)` — **never `attempt_id`**, which changes on every resume. | `_reconcile_prior_side_effect` |
| Fail-closed contract | A prior record that cannot be reconciled safely raises `SideEffectReconciliationError` (`SIDE_EFFECT_RECONCILIATION_FAILED: …`) — the effect is neither re-performed nor silently skipped. Four guarded cases: (1) journaled content hash ≠ requested content, (2) journaled file missing from disk, (3) on-disk content diverged from journal, (4) file rewritten/touched after the journal (mtime_ns/inode differ). The existing tool contract converts the exception into a failed `ToolResult` (`success=False`, explicit reason). | `_reconcile_prior_side_effect` |
| Reconcile-not-rewrite | On safe reconciliation the ORIGINAL artifact identity is reconstructed from the journal (no new artifact id, no physical write, file mtime_ns/inode untouched) and a `reconciled` journal record is appended with the same schema the guard checks (a repeat crash can reconcile again). | `_artifact_from_journal`, `_journal_reconciliation` |
| Layered idempotency | `_emit_artifact_created` materializes each record exactly once per logical artifact: no duplicate `ARTIFACT_CREATED` event (even if the pre-crash event was already durably persisted and restored), no duplicate evidence record for the same source artifact, idempotent artifact registration. | `_emit_artifact_created` |
| Durable journal write | `performed` record (content sha256, size, artifact_id, mtime_ns, inode, PID, UTC timestamp) appended + fsynced (file and parent dir) at side-effect time. | `_journal_performance` |

Also corrected (E10-CW1 order §8, honest timing): `E10/run_e10.py` now captures
`started_at_utc` at the runner's ACTUAL start (previously filled at
consolidation time) and records `consolidated_at_utc` separately.

---

## C. THE PROOF HARNESS (`E10/e10cw1_*.py`, `E10/run_e10cw1.py`)

Same production 5-task graph as E10 (A → (B, C) → D → E), same real path:
`MissionController.define_mission → execute_run → ExecutionEngine
.execute_task_graph_parallel → agent reservation → MissionTaskAgent.execute →
ToolExecutor.execute_tool("artifact_write") → SandboxManager → journal`.

```text
[RUNNER pid R]  one session = 2 consecutive chains (repeatability)
   per chain:
   |-- PROCESS A  (e10cw1_process_a.py)  executes A/B/C, starts D,
   |      dies INSIDE the crash window: after TASK_D's governed artifact
   |      write + its fsynced journal record, before any durable record of
   |      TASK_D's completion. Self-SIGKILL at an injection point in the
   |      real agent loop.            -> exit -9 (runner-observed)
   |-- RUNNER post-crash witness (outside any participant):
   |      crash-point validation from DURABLE records only; OS-level stat
   |      snapshot of the side-effect file (sha256 / mtime_ns / inode);
   |      resume_info.json = IDs ONLY across the process boundary.
   |-- PROCESS B  (e10cw1_process_b.py)  new OS process, different PID;
   |      durable-only restore; asserts the file was untouched between
   |      crash and resume; resumes THROUGH the window; TASK_D reconciles,
   |      TASK_E completes fresh; verify_completion; finalize (EVIDENCED);
   |      final durable checkpoint (hash set).
   |-- RUNNER post-resume witness: re-stats the file — the core claim is
   |      proven by mtime_ns + inode + sha256 UNCHANGED across resume.
   `-- VERIFIER   (e10cw1_verifier.py)  independent OS process; persistent
          state only; 9 mandatory checks; verdict VERIFIED.
```

---

## D. CANONICAL FIXED-MODE RESULTS (`E10/evidence_cw1/fixed/`)

Session `e10cw1_fixed_o4wlgxpg` (2026-10-09T00:24:57Z → 00:25:01Z), 2 chains:

```text
chain 1: CRASH_WINDOW_IDEMPOTENT   PIDs A=8179 (exit -9) B=8180   verifier exit 0
chain 2: CRASH_WINDOW_IDEMPOTENT   PIDs A=8182 (exit -9) B=8183   verifier exit 0
all_chains_no_physical_rewrite = TRUE      pid_differences = [true, true]
```

Chain-2 facts (all from durable records / OS observation):

| Fact | Value |
|---|---|
| Crash point | injection reached on TASK_D (`task-931ea40048a9`) at 00:25:00.137Z; last checkpoint: A/B/C COMPLETED, D **READY**, E BLOCKED; zero durable `task.completed` for D; side-effect file exists; journal `performed` recorded ≤ injection time |
| Restored states (Process B) | A/B/C COMPLETED, D READY, E BLOCKED |
| Durable attempt/artifact records for D at crash | 0 / 0 (never durable) — but journal `performed` = 1 |
| Side-effect file across resume | mtime_ns `1791505500135640591` UNCHANGED, inode `270529` UNCHANGED, sha256 `d8b3c531a59ab82d…` UNCHANGED |
| Journal for D | `["performed", "reconciled"]` — exactly one physical write, one reconciliation |
| Artifact identity | original `artifact-eca2b0daffa1` preserved (`is_original=true`, count=1) |
| `ARTIFACT_CREATED` events for D | same original id twice in log (pre-crash durable + restored copy) — no duplicate tuple, physical write never repeated |
| Evidence per task | 2 records per task A–E, no duplicates |
| TASK_E | fresh post-resume (`performed` only, pre-resume attempts 0, post-resume 1) |
| Attempts per task | 1 each — D did NOT run twice physically |
| Completion | `verify_completion` verdict COMPLETE; all 5 tasks COMPLETED; final state EVIDENCED; final checkpoint `checkpoint-fe7db9bb6102` with hash set |
| Run lineage | run 2 parent_run_id = interrupted run 1 (`run-6aee873839c9`) |

Independent verifier (PID 8184 ≠ any participant): **VERIFIED, 9/9 mandatory
checks passed** —
`process_a_died_at_injection_point`,
`process_b_new_process_restored_from_durable_only`,
`first_side_effect_readable_and_verifiable`,
`side_effect_identity_linked_to_correct_task_and_operation`,
`side_effect_count_matches_expected_no_unsafe_copy`,
`records_reflect_stored_truth_not_declared_values` (three-way mtime:
journal_performed == reconciled_observed == file_now),
`attempts_and_events_consistent_with_crash_and_resume`,
`final_state_agrees_with_actual_evidence`,
`repeat_runs_produce_same_result`.

---

## E. TEST MATRIX — CW1-T01..T12 (all PASS; `E10/test_e10_matrix.py`)

| # | Test | Verdict |
|---|---|---|
| CW1-T01 | crash point strictly inside the window (real lifecycle boundary, not a safe stop) | PASS |
| CW1-T02 | real SIGKILL (exit −9) + new OS PID per chain | PASS |
| CW1-T03 | no durable completion at crash; journal performed = 1; file untouched between crash and resume | PASS |
| CW1-T04 | Process B restored from durable storage only (IDs-only boundary) | PASS |
| CW1-T05 | **side effect NOT re-performed** (mtime_ns/inode/sha256 across resume; three-way mtime) | PASS |
| CW1-T06 | original artifact identity preserved; events linked to correct task/operation | PASS |
| CW1-T07 | exactly-once records (journal 1+1, artifact records 1/task, 5 completions, 0 duplicate tuples, 2 evidence/task) | PASS |
| CW1-T08 | TASK_E fresh + dependency order (D before E; attempts pre/post-resume split) | PASS |
| CW1-T09 | independent verifier VERIFIED (9/9, separate PID, truth sources exist) | PASS |
| CW1-T10 | repeat runs same result; honest timing fields | PASS |
| CW1-T11 | layered idempotency when the pre-crash records WERE persisted (other sub-variant): no duplicate event/evidence/artifact record after restore; journal 1 performed + 1 reconciled | PASS |
| CW1-T12 | fail-closed negative: deleted file / tampered content / different content / externally rewritten file → `SideEffectReconciliationError` ToolResult, write NEVER re-performed; journal keeps exactly one `performed` | PASS |

Full matrix re-run at this tree: **32/32 PASS** (E10 T01–T20 + CW1 T01–T12).

---

## F. REGRESSIONS AT THIS TREE

| Suite | Result | Classification |
|---|---|---|
| `E9-R/test_production_integration.py` | PASS (exit 0, "E9-R VERIFIED") | — |
| `run_e8_human_gates.py` | PASS (exit 0; 4/4 negative tests REJECTED) | — |
| E10 original chain + matrix (T01–T20) | PASS (fresh session fixture) | — |
| `test_e6_durable_mission_orchestration.py` | 2 FAILED (`test_e6_e5_regression`, `test_e6_e4_regression`) | **Pre-existing** at clean baseline 63ba3fc (proven via git-stash in E10): never-committed E5 test file; cascade from stale E4 guard |
| `test_e4_multi_task_mission.py` | 1 FAILED (`test_e4_no_p1_p2_modification`) | **Pre-existing** at clean baseline (stale E4-era guard vs later ratified commits) |
| `test_e33_mission_autonomy.py` | PASS | — |

The failure set is IDENTICAL to the pre-existing set classified in E10 —
the CW1 changes introduce **zero** new regressions.

---

## G. ACCEPTANCE CRITERIA

| # | Criterion | Verdict |
|---|---|---|
| CW1-01 | Process A dies inside the crash window on the production path (after governed side effect + journal record, before durable completion) | VERIFIED |
| CW1-02 | Kill is a real OS SIGKILL witnessed by an external runner (exit −9, PIDs recorded) | VERIFIED |
| CW1-03 | Crash point validated from durable records only (checkpoint states, event log, journal, file existence) | VERIFIED |
| CW1-04 | Process B is a new OS process restoring from durable storage only | VERIFIED |
| CW1-05 | Only identifiers cross the process boundary (resume_info.json = IDs, never state objects) | VERIFIED |
| CW1-06 | Side-effect journal is durable at write time (fsync file + dir, before completion records) | VERIFIED |
| CW1-07 | Resume reconciles the journaled side effect — physical write NOT re-performed (mtime_ns + inode + sha256 unchanged, OS-observed) | VERIFIED |
| CW1-08 | Original artifact identity preserved (no new artifact id) | VERIFIED |
| CW1-09 | Layered records exactly once (journal, events, evidence, artifact registry) — both sub-variants of the window | VERIFIED |
| CW1-10 | Reconciliation identity is stable logical operation (mission, task, path) — not attempt-scoped | VERIFIED |
| CW1-11 | Fail-closed reconciliation on missing/diverged/rewritten/different-content targets (SideEffectReconciliationError, explicit reason, never silent skip, never re-perform) | VERIFIED |
| CW1-12 | TASK_E (blocked at crash) executes fresh post-resume with correct dependency order | VERIFIED |
| CW1-13 | verify_completion COMPLETE; mission finalized EVIDENCED; final durable checkpoint with integrity hash | VERIFIED |
| CW1-14 | Run lineage preserved (resumed run's parent = interrupted run) | VERIFIED |
| CW1-15 | Independent verifier (separate process, persistent state only) — VERIFIED 9/9 | VERIFIED |
| CW1-16 | Repeatability — 2 consecutive chains same result (and full matrix re-run) | VERIFIED |
| CW1-17 | Baseline gap demonstrated against pre-fix code (same harness, detached worktree at 50f5371) — documents the pre-existing failure, never counted as a pass | VERIFIED |
| CW1-18 | Honest timing fields (started_at_utc at actual start; consolidated_at_utc separate) | VERIFIED |
| CW1-19 | E10 original matrix (T01–T20) still PASS at this tree | VERIFIED |
| CW1-20 | E8 + E9-R regressions PASS; E6/E4 failure set identical to pre-existing baseline set | VERIFIED |

---

## H. VERDICT

```text
E10_CW1_PASS
  - fixed mode:   2/2 chains CRASH_WINDOW_IDEMPOTENT; verifier VERIFIED 9/9
  - matrix:       CW1-T01..T12 PASS; full file 32/32 PASS
  - regressions:  E8 PASS, E9-R PASS, E6/E4 pre-existing set unchanged
  - gap demo:     baseline (pre-fix 50f5371) re-performs the write in 2/2 chains
```

The crash window between "a governed side effect happened" and "its completion
is durably recorded" is now closed with a fail-closed, exactly-once
reconciliation contract on the real production path.
