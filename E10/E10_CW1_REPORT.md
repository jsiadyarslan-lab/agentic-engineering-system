# E10-CW1 FINAL REPORT — CRASH-WINDOW IDEMPOTENCY PROOF

**EXECUTIVE ORDER:** E10-CW1 (crash-window addendum to E10 — durable execution & cross-process resume)
**VERDICT:** `E10_CW1_PASS` (superseded for the crash-window claim by the E10-CW1-R1 addendum below — see section I)
**PARENT BASELINE:** `50f5371e306a7c44410dee928992892ba1b2d9f7` (E10 final-report commit, == origin/main at the time)
**WORK BRANCH:** `e10-cw1-crash-window-idempotency` (from 50f5371)
**EVIDENCE SESSIONS:** `E10/evidence_cw1/fixed/` (canonical proof) + `E10/evidence_cw1/baseline_gap/` (pre-fix gap demonstration, run against a detached worktree of `50f5371`)

> **E10-CW1-R1 CORRECTIONS (order E10-CW1-R1 §8):** three claims in the original
> CW1 sections below are superseded by the R1 addendum (section I):
> 1. Section D's row “`ARTIFACT_CREATED` events for D | same original id twice
>    in log (pre-crash durable + restored copy)” was **factually wrong**: both
>    events in the final durable log were emitted by Process B in the SAME
>    post-resume run — the duplication was the engine's normal TOOL-LAYER +
>    AGENT-LAYER double emission (execution.py S9 + S11 sites), not a
>    crash/restore artifact. The R1 event contract (section I.6) removes the
>    duplicate at the source: exactly ONE ARTIFACT_CREATED per artifact
>    identity, with ARTIFACT_RECONCILED as the DISTINCT reconciliation
>    semantics.
> 2. The phrase “The crash window … is now closed with a fail-closed,
>    exactly-once reconciliation contract” (section H) overstated the scope:
>    CW1 proved only the (performed → completion) window. The
>    (effect → performed) window — a crash between the physical write and the
>    journal record — remained OPEN at d8b0620 and is closed by R1 (section I).
> 3. The CW1 harness injection point (the ARTIFACT_CREATED emission) sits
>    AFTER `_journal_performance` — it could never prove the pre-performed
>    window. R1 injects at the real boundaries (section I.2).

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

---

# I. E10-CW1-R1 ADDENDUM — INTENT-FIRST JOURNAL & PRE-JOURNAL CRASH PROOF

**EXECUTIVE ORDER:** E10-CW1-R1 (mandatory remaining processing after `E10_CW1_CONDITIONAL`)
**R1 BASELINE:** `d8b0620eb22527ff88d8a39abafba0ade426c7c8` (== origin/main at R1 start)
**WORK BRANCH:** `e10-cw1-r1-prejournal-crash` (from d8b0620; NOT merged to main)
**EVIDENCE:** `E10/evidence_cw1_r1/` (canonical session + empirical baseline gap demo)
**DISCOVERY DOC:** `E10/E10_CW1_R1_DISCOVERY.md` (proven operation order + window table)

## I.1 The windows that are ACTUALLY tested (no conflation)

The R1 discovery (committed as `E10/E10_CW1_R1_DISCOVERY.md`) maps the real
operation order of the governed `artifact_write` path and its independent
crash windows. Each mandatory scenario kills at exactly ONE real boundary,
in a REAL OS process, by a REAL SIGKILL witnessed by the external runner:

| Window | Scenario | Between | Proven resume behavior |
|---|---|---|---|
| W(intent→effect) | **A** | durable `intent` record ↔ physical write | file absent PROVES the effect never happened → perform ONCE with the PLANNED identity (first execution, `performed(direct)`, no reconciliation semantics) |
| W(effect→performed) — **the order §2 gap, previously OPEN** | **B** | physical write (fsynced by the adapter) ↔ `_journal_performance` | DETECT the existing effect, ADOPT it: original planned identity, mtime_ns/inode/sha256 UNCHANGED, `performed(adopted_after_crash, performed_by_pid=A)`, `ARTIFACT_RECONCILED(intent_adoption)` |
| W(performed→completion) | **C** | durable `performed` ↔ completion records | CW1 behavior retained: reconcile from the performed record, no rewrite |
| torn FINAL record | **D1** | W(effect→performed) + torn trailing journal line | torn tail ignored (never durable truth); intent still governs; B's own append truncates the tail (self-healing file) |
| destroyed trailing intent | **D2a** | W(effect→performed) + intent line corrupted to invalid JSON | existing file + no journal record = unreconcilable ambiguity → explicit fail-closed `SideEffectReconciliationError`; the file is NEVER overwritten |
| corrupt PRIOR record | **D2b** | W(performed→completion) + a MIDDLE prior performed record corrupted | a prior record that may be the only proof of a proven effect → `SideEffectJournalCorruptionError`; NOTHING appended, NOTHING re-performed, the corrupt line is PRESERVED as evidence |

The **empirical baseline gap demonstration**
(`E10/evidence_cw1_r1/baseline_gap_demo/`): the SAME R1-B boundary, the same
harness, against a detached worktree of the baseline commit `d8b0620` —
Process A dies by SIGKILL (exit −9) with the file written and ZERO journal
records for the operation; Process B re-performs the physical write
(`GAP_DEMONSTRATED__SIDE_EFFECT_EXECUTED_TWICE`: mtime_ns changed, a fresh
artifact id, the effect executed twice). The fixed-tree control at the same
boundary adopts without rewrite (`WINDOW_CLOSED__ADOPTED_WITHOUT_REWRITE`).
This documents the pre-existing failure — it is never a pass of any
acceptance criterion.

## I.2 The fix (intent-first; minimal, production path only)

| Component | Change | Where |
|---|---|---|
| Stable operation identity | `(mission_id, task_id, path)` — NEVER `attempt_id` (attempt ids are informational fields in records, never keys) | journal records |
| `intent` record | durably appended (fsync file + dir) BEFORE the physical side effect; fixes the PLANNED artifact id, content sha256 and size pre-effect | `SideEffectJournal`, `_journal_intent` |
| Planned identity carried through the write | `write_artifact(..., artifact_id=planned)` on SandboxManager → adapter (optional param; legacy adapters fall back and the manager rebinds); the artifact id is therefore identical whether or not a crash occurs | `sandbox.py`, `windows_adapter.py` |
| `performed` record | after the effect, with `performed_via` = `direct` \| `adopted_after_crash`, `performed_by_pid` (the process that physically wrote) and `intent_journal_record_id` (the link back to the intent) | `_journal_performance` |
| Intent-only reconciliation | intent + file ABSENT → effect provably never happened → perform with the planned identity; intent + file PRESENT + fingerprint match → ADOPT (no rewrite), performed(adopted_after_crash) | `_governed_artifact_write` |
| First-sight guard | a governed write whose target file exists with NO journal record for the operation is unreconcilable ambiguity (a lost/corrupt record may be the only proof of a prior effect) → explicit fail-closed, never a blind overwrite | `_governed_artifact_write` |
| Fail-closed journal loader | torn/corrupt TRAILING line → ignored (never durable truth) + truncated before the next append; corrupt/semantically-invalid NON-TRAILING line → `SideEffectJournalCorruptionError` (a prior record may hide a proven effect) | `SideEffectJournal._load`, `_truncate_torn_tail` |
| Divergence refusals (CW1, retained) | journaled content ≠ requested; file missing; on-disk content diverged; file rewritten/touched (mtime/inode); existing file vs destroyed intent | `_reconcile_prior_side_effect`, `_lookup_prior_intent` |
| Adapter durability | the artifact file and its parent dir are now fsynced by the adapter before returning (aligned with journal durability) | `windows_adapter.write_artifact` |

## I.3 Reconciliation contract across repeated resumes

`intent` + `performed` + `reconciled` form one consistent contract
(unit-proven, R1-T17): a fresh write produces `[intent, performed]`; a later
life reconciling from `performed` appends `reconciled`; a crash after that
reconciles AGAIN the same way — one identity across all lives, the file
written exactly once, and a reconciliation result never becomes a new
execution attempt.

## I.4 Event contract (order §6) — resolved, not redefined

* The historical double `ARTIFACT_CREATED` (tool layer + agent layer, same
  artifact id, EVERY write — including non-crashed tasks) was a logical
  duplicate of creation. It is now PREVENTED at the source by a shared
  per-identity guard (`_artifact_created_emitted`) at all three emission
  sites. Counted BY ARTIFACT IDENTITY (not run_id): exactly ONE
  `ARTIFACT_CREATED` per artifact id in every durable log (R1-T11 across all
  12 canonical chains; R1-T18 unit).
* Cross-process reconciliation now has DISTINCT semantics:
  `ARTIFACT_RECONCILED` (`artifact.reconciled`, payload
  `ArtifactReconciledEvent`) with `mode` = `performed_record` (CW1 window)
  or `intent_adoption` (pre-performed window) and the observed
  mtime/inode/no-rewrite facts. It NEVER claims a new artifact came into
  existence.
* CW1-T06/T07/T11 expectations were updated to the TIGHTER contract
  (1 creation + 1 reconciliation instead of 2 creations). This is not a
  weakened test — the previous `== 2` expectation codified the duplicate the
  order told us to remove.

## I.5 Durable-write guarantee limits (stated precisely)

* The journal (intent/performed/reconciled), the artifact file and their
  parent directories are fsynced at write time. After `write_artifact`
  returns, the effect is on disk, not merely in the page cache.
* Durability is proven under PROCESS DEATH (SIGKILL) by real tests. POWER
  LOSS / storage-level torn writes are covered by policy, not by test
  hardware: a torn trailing journal line is ignored as never-durable truth
  and truncated at the next append; a torn/partial ARTIFACT FILE cannot
  match the intent fingerprint and therefore fails closed
  (`SideEffectReconciliationError`), never adopts garbage.
* The exactly-once claim is scoped to the GOVERNED sandbox artifact path
  (the engine-controlled `artifacts_base_dir` tree). It is NOT generalized
  to external side effects that lack a stable identity or a verifiable
  reconciliation handle (order §3 final paragraph).
* Legacy callers without `(mission_id, task_id)` identity keep their
  previous direct-write behavior (no journaling) — unchanged by R1.

## I.6 Results at this tree

* Canonical R1 session: **6 scenarios × 2 chains = 12/12 VERIFIED**
  (`E10_CW1_R1_CHAINS_COMPLETE`); independent verifier (separate PID,
  persistent-state-only) passes every scenario check set, including the
  order §5 hard rule — the pre-performed window is proven by the intent
  record's provenance (PID=A, recorded before the kill), the three-way file
  stat continuity, and the performed record's OWN provenance
  (written-by=B, performed-by=A) — never by the performed record's mere
  existence.
* R1 matrix: **31/31 PASS** (R1-T01..T20 incl. unit tests).
* E10 + CW1 matrix at this tree: **32/32 PASS** (T01–T20 + CW1-T01..T12
  under the tightened event contract).
* E8 human gates: COMPLETE, 4/4 negative REJECTED. E9-R production
  integration: PASS.
* E6/E4/E33: the SAME 3 pre-existing failures classified at the clean
  baseline 63ba3fc (never-committed E5 file; stale E4 guard cascade).
  e41 kill-resume script: exit 1 — PROVEN identical at d8b0620 via git-stash
  (E9-R1 grant contract vs pre-E9-R1 fixture). e42/e43: 2 failures — PROVEN
  identical at d8b0620. VS003: 3 errors — pre-existing (uncommitted
  substrate). execution/tools/roles/factory: 8 collection errors —
  environmental (sqlalchemy not installed), identical at baseline.
  **Zero new regressions.**

## I.7 Deliverables and their status

* Committed in this repo (branch `e10-cw1-r1-prejournal-crash`): the fix,
  the R1 harness, the R1 matrix, the discovery document, this report, and
  the canonical evidence under `E10/evidence_cw1_r1/`.
* The user-facing PDF is a LOCAL deliverable (`/home/z/my-project/download/`),
  produced from this report — it is NOT committed to the repository. No
  path in this repo claims a committed PDF (verified: `find -name "*.pdf"`
  over the tree returns nothing).
