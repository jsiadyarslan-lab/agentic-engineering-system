# E10-RP — EVIDENCE-BASED REPLANNING — FINAL REPORT

Order: E10-RP (EVIDENCE-BASED REPLANNING), STATUS AUTHORIZED WITH AMENDMENTS.
Branch: `e10-rp-evidence-based-replanning` (worktree `/home/z/my-project/e10rp_work`).
Hard baseline: `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` (main; ls-remote verified
EXACT before any file was touched). No merge to main within this order.

Required cycle (order §0), all proven on the REAL production path:
MISSION → PLAN V1 → TASK EXECUTION → OBSERVED DEVIATION → EVIDENCE →
REPLANNING DECISION → PLAN V2 → REVIEW → CONTINUATION → VERIFIED OUTCOME.

---

## 1. HARD BASELINE (order §1)

- Live `git ls-remote origin refs/heads/main` == `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f`
  — EXACT match recorded (`scripts/e10rp_baseline_evidence.json`, captured
  BEFORE execution; `ls_remote_main_equals_expected: true`,
  `head_equals_expected: true`).
- Repo/branch/HEAD: original tree stayed on `e10-cw1-r1-prejournal-crash`
  @ `0a26fc7` with **2278 mode-only modifications and 0 untracked** — the
  as-found state, preserved untouched for the whole order (verified again
  at the end; no `reset`/`clean`/`stash`/`restore` was used anywhere).
- E10-CW1-R1 report + evidence verified present before execution:
  `E10/E10_CW1_REPORT.md` (sha256 8495833…), `E10/E10_CW1_R1_DISCOVERY.md`
  (sha256 4735773…), `E10/evidence_cw1_r1/` = 254 tracked files == on-disk,
  git tree sha `312a0eb…`. Recorded in the baseline snapshot JSON.
- Isolated execution tree: `git worktree add -b e10-rp-evidence-based-replanning
  /home/z/my-project/e10rp_work 0a26fc70…` — clean (0 porcelain), HEAD ==
  baseline exactly.

## 2. REPLANNING CONTRACT DISCOVERY (order §2)

Full matrix in `E10/E10_RP_DISCOVERY.md`. Summary (CLAIM / OBSERVED /
VERIFIED / NOT PROVEN):

| # | Capability | Classification |
|---|---|---|
| 1 | Plan representation + dependencies (`TaskSpec`, `define_mission`, `record_plan_v1`, `plan_version`, `task_graph`) | VERIFIED |
| 2 | Deviation logging linked to Mission/Run/Task (`TASK_FAILED` "Verification failed: not_evidenced" with mission/run/task ids; `scan_failures` → `FailureRecord`) | VERIFIED |
| 3 | Evidence source + sufficiency (deterministic `Verifier`; agent-claimed success overturned by real file content) | PARTIAL: source VERIFIED; dedicated sufficiency arbiter NOT PROVEN |
| 4 | Replan-necessity decision (`_classify` PLAN_DEVIATION; `_recovery_for` → REPLAN; application explicit, never silent) | VERIFIED |
| 5 | New plan + lineage (`replan_mission` → `ReplanRecord` v1→v2 with evidence/invalidated/preserved/added/rewired/modified; durable ledger) | VERIFIED |
| 6 | Review/approval before continuation | **NOT PROVEN — the gap** (PLAN_APPROVED event + PlanState existed but were never wired into the mission replan path) |
| 7 | Completed preserved / no unjustified re-execution | VERIFIED |
| 8 | Failure / retry / resume | VERIFIED (engine retry, checkpoints, journal); controller-state AUTO-restore into a fresh controller: NOT PROVEN (ledger durable on disk; recorded as gap) |

Searches were never treated as proof of absence: call paths were followed
(canonical orchestrator, e33/e35/e37/e4/e6 harnesses, engine emission sites).

## 3. Scope decision (order §3): **A + B**

- **A** — the replanning cycle already exists on the production path
  (e33-proven pattern): the controlled experiment runs it; nothing rebuilt.
- **B** — one minimal contract-compatible addition closes gap #6, in ONE
  production file (`src/unified/mission_controller.py`):
  `PlanReviewRecord`; opt-in `require_plan_review=False` (default — every
  existing caller/test unchanged byte-for-byte); `review_plan()` with 8
  fail-closed checks C1..C8 derived only from live state; fail-closed
  continuation gate at the top of `execute_run` (unapproved / never-reviewed
  / rejected all REFUSE before any execution); durable
  STATE_TRANSITION(plan_review) events; `plan_reviews` in the durable ledger.
- NOT C: no scheduler/lifecycle/storage redesign; no new agents or
  interfaces; no external model integration. Diff: 1 production file
  (+ ~200 lines) + harness + evidence + this report.

## 4. The experiment and event sequence (order §4)

Single process per scenario (real OS processes per stage, PIDs witnessed by
the runner). MAIN scenario (plan v1: A → (B, C⚠) → D → E):

1. MISSION + PLAN V1 defined; C's acceptance expects the plan assumption
   (`E10RP_C_PLAN_V1_EXPECTED`) while its agent writes observed reality
   (`E10RP_C_REALITY_ACTUAL`) — the KNOWN, CONTROLLED deviation input.
2. REVIEW v1 → APPROVED (before any execution).
3. PHASE 1: A, B COMPLETED; C's verification verdict `not_evidenced`
   (literally: the claim is not evidenced) → terminal TASK_FAILED; D, E
   BLOCKED, never started; task_d.txt never written.
4. EVIDENCE: verification report + TASK_FAILED event (mission/run/task
   linked) → `scan_failures` → FailureRecord(kind=plan_deviation,
   recovery=replan, evidence carried).
5. S1 negative: with C's TASK_FAILED dropped from the stream (a claim
   without a record), `scan_failures` returns NOTHING for C → no
   classification → no replan decision possible.
6. REPLANNING DECISION → PLAN V2: data-driven correction derived from C's
   actual artifact; D invalidated (its product embeds the plan-v1
   expectation), X remediation added (dep C), E rewired onto X.
7. GATE: continuation REFUSED (unapproved v2) — zero execution.
8. REVIEW v2 #1 → REJECTED (C6: C still FAILED — plan not executable).
9. GATE: continuation REFUSED again — zero execution.
10. RECOVER C → REVIEW v2 #2 → APPROVED (8/8 checks).
11. CONTINUATION: C (passes under corrected criteria), X, E complete;
    A, B never re-executed (attempts A=1, B=1); C's artifact ADOPTED without
    rewrite (journal `reconciled` with same mtime_ns/inode/artifact_id).
12. VERIFIED OUTCOME: `verify_completion` PASS, finalize EVIDENCED, full
    checkpoint with integrity hash.
13. DUPLICATE CONTINUATION: zero new assignments, zero new journal records,
    artifacts byte-identical.

S2 scenario (minimal scope): A→B→C→D→E chain; E (terminal) deviates;
B has a REAL first-attempt tool failure recovered by the engine retry.
Replan touches ONLY E's criteria (no invalidation, no added, no rewiring);
A/B/C/D preserved and untouched.

Expected decisions were pre-registered BEFORE the run
(`pre_registered_expectations.json`, written by the runner before stage 1)
and never changed after observing outcomes.

## 5. Test results and exit codes (order §6)

All commands run in the isolated worktree on the branch; every result below
was run by this order (not inherited):

| Command | Result | Exit |
|---|---|---|
| `python3 -m pytest E10/test_e10rp_matrix.py -v` | **23 passed** (fresh full chain per run) | 0 |
| `python3 E10/run_e10rp.py` (repeatability ×3) | `E10RP_CHAIN_PROVEN` 3/3 | 0 |
| `python3 -m pytest E10/test_e10r1_matrix.py` (R1 regression) | 31 passed | 0 |
| `python3 -m pytest E10/test_e10_matrix.py` (E10/CW1 regression) | 32 passed | 0 |
| `PYTHONPATH=<wt>/src python3 run_e8_human_gates.py` | 4/4 negative REJECTED (incl. duplicate_decision FIRST_ACCEPTED_SECOND_REJECTED) | 0 |
| `python3 E9-R/test_production_integration.py` | OVERALL: PASS | 0 |
| `python3 -m pytest tests/unified/test_e33_mission_autonomy.py` | 2 passed | 0 |
| `python3 -m pytest tests/unified/test_e32f_autonomous_replanning.py` | 2 skipped (NVIDIA API key — environmental, pre-existing class) | 0 |
| `PYTHONPATH=<wt>/src python3 tests/e35/test_long_mission.py` | FAILS — **proven pre-existing at 0a26fc7** (identical at baseline via throwaway detached worktree: same "T2 failure not detected"; only random IDs differ) | 1 both states |
| `PYTHONPATH=<wt>/src python3 tests/e37/test_multi_task_mission.py` | FAILS — **proven pre-existing at 0a26fc7** (identical "E37 PARTIALLY VERIFIED (4/15)", identical AC results) | 1 both states |
| `python3 -m pytest tests/orchestrator/test_e6…py tests/orchestrator/test_e4…py` | 3 failed / 23 passed / 8 skipped — the SAME 3 pre-existing failures proven at 0a26fc7 in the E10-CW1-R1 ratification (e5_regression, e4_regression, e4_no_p1_p2_modification) | 1 |

The E8 invocation dependency (script inserts repo ROOT not `src/`) was
proven pre-existing at d8b0620 and 0a26fc7 during the integration gate; same
class applies to e35/e37 script tests (documented again here with two-state
proof).

## 6. Evidence for plans, deviation, decision, review (order §6)

Canonical tree: `E10/evidence_rp/canonical/` (38 files; re-examinable):

- Plan v1: TASK_CREATED events (pre-replan window) — 5 tasks A..E with
  deps + acceptance criteria; C's criteria carry the plan assumption.
- Deviation evidence: `task.failed` (error "Verification failed:
  not_evidenced", mission/run/task ids) + `verification.complete` for C
  (verdict not_evidenced, missing_evidence detail) — the durable record.
- Decision: ledger `failures[]` (kind plan_deviation, recovery replan,
  `resolved_by "replan->v2"`) + `replans[0]` (v1→v2; invalidated [D];
  preserved [A,B]; added [X dep C]; rewired [E→X]; modified [C]);
  `replan.evidence == deviation.evidence` (causal carry, not co-occurrence).
- Plan v2 identity: `plan_version v2` in ledger + final checkpoint
  task_states {A,B,C,X,E: COMPLETED} (D absent).
- Reviews: ledger `plan_reviews` = [v1 approved, v2 rejected (C6), v2
  approved] + STATE_TRANSITION(plan_review) events in the event log.
- Task states before/after: scenario phase records (phase1/phase2 states)
  + final checkpoint attempt_history (A=1, B=1, C=2, X=1, E=1).
- Causality windows (independent verifier, from durable timestamps only):
  deviation marker < replan marker; ZERO task assignments between the
  replan decision and the v2 approval; every post-replan assignment ≥ the
  v2 approval; phase-2 assignments are exactly {C, X, E}.
- Side effects: journal per path — A/B/X/E: intent+performed exactly once;
  C: intent+performed+reconciled (reconciled.mtime_ns == performed.mtime_ns,
  same inode/artifact_id → adoption without rewrite); task_d.txt: NO
  journal records and file absent on disk.

## 7. Safety cases and unproven gaps (order §5)

| Case | Result | Evidence |
|---|---|---|
| S1 Insufficient Evidence | **VERIFIED** | Claim without TASK_FAILED record → no classification → no replan (S1a, main flow); agent-claimed success overturned by verifier verdict `not_evidenced` (S1b); every ledger failure is backed by a real TASK_FAILED event (verifier V5 loop) |
| S2 Irrelevant Deviation | **VERIFIED** | Non-plan failure (real tool failure) → TOOL_RUNTIME_FAILURE/retry, resolved by engine retry — never a replan; terminal-task deviation → only that task's criteria change, nothing else touched |
| S3 Affected Dependencies | **VERIFIED** | Only D invalidated (product embeds the deviated expectation); E rewired onto remediation X; completed A/B preserved (attempts 1 each; artifacts untouched); C corrected + re-executed exactly once |
| S4 Replanning/Review Failure | **VERIFIED** | Unapproved v2 → REFUSED (zero execution); rejected review → REFUSED again (zero execution); approval only after recovery; continuation strictly after approval (durable timestamps) |
| S5 Retry/Resume | **VERIFIED (per scope)** | Engine retry recovers non-plan failure (S2 B); duplicate continuation → zero new side effects; plan versions + decision evidence durable in ledger.json + journal.jsonl (not lost). Controller-state AUTO-restore into a fresh controller: NOT PROVEN (gap below) |

NOT PROVEN / NOT SUPPORTED (honestly recorded, no PASS assigned):
- Dedicated evidence-SUFFICIENCY arbiter beyond the deterministic verifier
  (capability #3 partial).
- Controller-state auto-restore (plan_version/replans/reviews) into a FRESH
  controller process (ledger is durable on disk; `restore_from_checkpoint`
  restores graph+mission only — the e33 pattern rebuilds key maps manually).
- e35/e37 script tests remain red at BOTH states (pre-existing, two-state
  proven) — they are legacy harness issues, not engine defects; fixing them
  is out of this order's scope.
- `run_e8_human_gates.py` / e35 / e37 import-path dependency (repo root vs
  `src/`) — pre-existing invocation defect (two-state proven for E8 at
  d8b0620 and 0a26fc7).

## 8. Git, worktrees, and original-tree integrity (order §7)

- Execution: isolated worktree `/home/z/my-project/e10rp_work` on branch
  `e10-rp-evidence-based-replanning` from the baseline commit (exact).
- The ORIGINAL tree (`/home/z/my-project/repo`, branch
  `e10-cw1-r1-prejournal-crash`) recorded before AND after: HEAD
  `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f`, 2278 mode-only ` M`, 0
  untracked — untouched (no destructive commands anywhere in this order).
- Diff reviewed before commit; no merge to main; branch delivered (SHA in
  §10). `git worktree list` at the end: the two worktrees above only.
- Notion: NOT ACCESSIBLE from this environment — recorded honestly; the
  oversight entry content is provided in §10 ready to paste. E9-R Notion
  HOLD: no Notion write performed; per the standing rule, no HOLD was
  replaced by a success verdict anywhere (E9-R's own ratification chain is
  independent of this order).

## 9. CLAIM / OBSERVED / VERIFIED

- CLAIM → every capability mapped to file:symbol in the discovery matrix.
- OBSERVED → live code paths + call sites followed (§2 of discovery).
- VERIFIED → this run: RP matrix 23/23, repeatability 3/3, independent
  verifier 12/12 (V1..V9 + S2A..S2C) on durable state only, regressions
  green or two-state-proven pre-existing.
- NOT PROVEN → the four gaps in §7 (recorded as gaps, not passes).

## 10. Proposed verdict and next phase

**E10-RP PASS (CONDITIONAL on branch review — not merged to main).**

The full cycle from deviation to decision to plan v2 to review to verified
continuation is proven on the production path with pre-registered criteria,
a real review rejection, real gate refusals, and an independent verifier
reading durable state only. Proposed next steps (for the admin):

1. Independent ratification of this branch (same pattern as E10-CW1-R1).
2. Integration gate → main (after ratification).
3. Backlog (mutation orders, none executed here): controller-state
   auto-restore from ledger for fresh processes; dedicated sufficiency
   arbiter; fix `run_e8_human_gates.py`/e35/e37 import paths to `src/`;
   revisit the two e35/e37 legacy harness failures.
4. Notion oversight entry (paste-ready):
   > E10-RP @ branch e10-rp-evidence-based-replanning (baseline 0a26fc70):
   > PASS — full replanning cycle VERIFIED (23/23 matrix, 3/3 repeatability,
   > independent verifier 12/12; regressions green or proven pre-existing).
   > CLAIM/OBSERVED/VERIFIED per E10/E10_RP_REPORT.md §9; gaps §7.
   > Decision: await independent ratification; do not merge to main yet.
   > Next phase: E10-RP ratification.
