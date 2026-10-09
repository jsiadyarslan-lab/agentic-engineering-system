# E10-RP1 DELIVERY REPORT — CANONICAL REPLANNING PATH & REVIEW-GATE INTEGRATION

Executive order: E10-RP1 (STATUS: AUTHORIZED — TARGETED CORRECTION)
Base branch: `e10-rp-evidence-based-replanning` @ `ac70eb6e1681f55970b098b98d01d4a87c9240c9`
Baseline main: `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` (UNCHANGED — no merge, no push to main)
Delivered on branch: `e10-rp1-canonical-review-gate`

---

## 1. Hard baseline (order §1) — VERIFIED, zero stop conditions

Recorded BEFORE any modification (snapshot: `scripts/e10rp1_baseline_evidence.json`,
verdict `BASELINE_OK`, no stop conditions; live `ls-remote`, no assumptions):

- `origin/main == local main == 0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` — main untouched
  before, during, and after this order (re-verified at delivery).
- Baseline branch `e10-rp-evidence-based-replanning`: local == remote ==
  `ac70eb6e1681f55970b098b98d01d4a87c9240c9`; parent of `ac70eb6e` is exactly
  `0a26fc70` (ahead 1 / behind 0 vs main) — matches the arbitrator's GitHub check.
- Worktrees: original repo tree stayed as-found the whole session
  (`e10-cw1-r1-prejournal-crash` @ `0a26fc7`, 2278 mode-only ` M`, 0 untracked,
  no reset/clean/stash/restore anywhere); the E10-RP baseline tree
  (`e10rp_work`) stayed clean (0 porcelain) and untouched; the correction ran in
  a NEW isolated worktree `e10rp1_work` on a NEW branch from `ac70eb6e`.
- Commit `ac70eb6e` inspected before any change (48 files, +9403/-1, parent
  `0a26fc70`); `src/unified/mission_controller.py` and
  `src/orchestrator/canonical.py` hashes recorded in the snapshot.

## 2. Execution path BEFORE the correction (all pre-existing at baseline)

The arbitrator's finding was confirmed — and extended by two more defects,
each proven PRE-EXISTING at `ac70eb6e` by a two-state probe (identical findings
at the baseline commit and at the pre-fix worktree; probe:
`rp1_baseline_probe.py`, throwaway worktree removed after):

1. **Review gate off in the canonical path** (the arbitrator's finding):
   `MissionController(self.engine, state_dir=artifacts_base_dir)` — the
   orchestrator never enabled `require_plan_review` (library default False).
2. **Replanning branch was a `pass` stub** (the arbitrator's finding):
   the REPLAN branch ended in `pass`; the verifier-failure branch ended in
   `pass` ("Could trigger replan here") while doing nothing.
3. **No grant validator in the canonical engine** (NEW finding): every
   governed mission write failed with
   `PermissionError: Tool artifact_write requires grants but no validator
   available` — no canonical mission with file-based acceptance criteria
   could EVER complete at baseline.
4. **Agent misrouting** (NEW finding): the engine could reserve `e3-thinker`
   for a MISSION task; the `E3AgentWrapper` dispatched by reserved agent_id,
   so a mission task was routed to the thinker's plan-generation (ungoverned
   evidence-store artifact) instead of `MissionTaskAgent`'s governed sandbox
   write.
5. Completion verification used the stale pre-replan key set — after a
   replan it would always report INCOMPLETE (never reached at baseline only
   because no replan could ever complete).

Consequence at baseline: the canonical operational path could not execute a
single governed mission end-to-end, and the E10-RP replanning cycle was
provable only through direct `MissionController` calls — exactly the gap the
arbitrator identified.

## 3. Changes and the reason for each (order §2)

All in `src/orchestrator/canonical.py` (one production file), plus explicit
opt-outs in the two orchestrator test fixtures. No new agent, no new model
provider, no new interfaces, no architectural redesign.

| # | Change | Reason (order ref) |
|---|--------|--------------------|
| 1 | `CanonicalOrchestrator.__init__(..., require_plan_review: bool = True, ...)` — the gate is enabled EXPLICITLY as canonical policy (never the library default); passed to `MissionController` | §2.1 arbitrator finding #1 |
| 2 | `execute_mission` step 3.5: first plan review (v1) BEFORE any execution when the gate is on; rejected initial review blocks ALL execution (fail-closed) | §2.2 |
| 3 | `replan_decision_provider` — disclosed decision source at the replanning decision boundary; `_run_replanning_cycle` wires: REPLAN-class `FailureRecord` (+ its evidence) → valid decision → `replan_mission` → review gate → bounded revision rounds (recovery of corrected tasks, re-reviewed) → continuation ONLY after approval. No valid decision ⇒ no replan (fail-closed, mission fails honestly) | §2.3 |
| 4 | Continuation is refused while the modified plan is unapproved/rejected — orchestrator returns `PLAN_REVIEW_REJECTED` with zero execution after the rejection; the gate at the top of `execute_run` re-enforces independently (defense in depth) | §2.4 |
| 5 | Both `pass` stubs removed: the replanning branch now calls the real path; the verifier failure is durably RECORDED (`VERIFICATION_COMPLETE` verdict `not_evidenced`) instead of being silently dropped. Wiring verifier failures into the replanning decision remains a disclosed gap — NOT claimed | §2.5 |
| 6 | `grant_validator` parameter passed through to `create_execution_engine` (default None — behavior unchanged for callers that do not opt in). The proof cycles supply the E9-R-pattern test validator | pre-existing defect #3 (§2 preamble: "افحص المسار الفعلي ... بما في ذلك الإنشاء") |
| 7 | `E3AgentWrapper` dispatches by the TASK's declared role, not by the reserved agent_id — mission tasks always run `MissionTaskAgent`'s governed path; planning tasks (decomposer/thinker) still go to the thinker | pre-existing defect #4 |
| 8 | `required_keys` for completion verification now follows the LIVE graph (invalidated tasks gone, remediation tasks present) | correctness of the replanned path (§2.3 wiring must produce a working continuation) |
| 9 | `create_canonical_orchestrator` factory passes the new params through | consistency |
| 10 | `tests/orchestrator/test_e3_*` + `test_e4_*` fixtures: explicit `require_plan_review=False` — these tests drive `orchestrator.mc` directly for non-gate mechanics; the gated canonical policy is proven by the RP1 matrix | policy-change guard, visible in the diff |

## 4. Integration proof (order §3) — through the REAL canonical path

New matrix `E10/test_e10rp1_matrix.py` — 16/16 PASSED (exit 0). The session
fixture runs `run_e10rp1.py` as real OS subprocesses (runner + 2 cycles +
fresh-process probe = 3 distinct PIDs, witnessed from outside):
- FULL cycle: deviation at C (agent writes observed reality; plan v1 expects
  its own assumption) → terminal `TASK_FAILED` "Verification failed:
  not_evidenced" → classified PLAN_DEVIATION → replan v1→v2 (invalidate D;
  correct C from its observed artifact; add X after C; rewire E onto X) →
  review v2 #1 REJECTED (exactly `C6_plan_executable_no_failed_tasks`) →
  revision (recover C) → review v2 #2 APPROVED 8/8 → continuation → verified
  outcome `EVIDENCED`. Judged 27/27 against pre-registered expectations.
- BLOCKED cycle: same replan decision but NO revision after the rejection —
  the orchestrator returns `PLAN_REVIEW_REJECTED`; zero execution after the
  rejection. Judged 10/10.

The six required §3 proofs, each from durable evidence (never re-execution):

1. No execution/resumption without review of the plan in question —
   `no_attempt_before_v1_review` (v1 review APPROVED strictly precedes the
   first task.assigned) + `no_attempt_between_replan_and_v2_approval`
   (zero attempts in the replan→approval window) + T15 gate probe
   (refuses, then allows).
2. Rejected review prevents subsequent task execution — BLOCKED cycle: C6
   rejection, C never recovered (`FAILED` at end), X/E zero attempts ever,
   zero attempts after the rejection event.
3. Replanning decision linked to the specific deviation and evidence —
   `ReplanRecord.evidence == FailureRecord.evidence`; deviation
   `resolved_by == "replan->v2"`; review #2's C7 causal check passes.
4. Modified plan never executed before review/approval — durable timestamp
   chain `replan_requested < review_v2_rejected < recovered_C <
   review_v2_approved < first continuation attempt`.
5. Correctly completed tasks not re-executed — A/B exactly 1 attempt each
   across the whole history (preserved set == [A, B]); C's re-execution is
   the justified recovery (criteria corrected by the replan; recovered only
   after the review rejection).
6. Continuation after approval produces the required outcome without
   repeated side effects — `EVIDENCED`; journal shows exactly one
   `performed` per artifact path (C's repeated attempts `reconciled`
   without rewrite: 3 reconciled records, 1 physical write); duplicate
   continuation probe: zero new attempts, zero new side effects.

Components are REAL (asserted in facts.json): `MissionController` +
`ExecutionEngine` + ToolExecutor governed execution. The ONLY injected
inputs are the two DISCLOSED control inputs at decision boundaries
(scripted decomposition at the planning boundary; the decision provider at
the replanning boundary) — documented in every facts.json; neither is
claimed to be independent planning or untested self-intelligence.

## 5. Durable review state (order §4)

- **VERIFIED**: plan identity/versions/replan decisions/reviews are durably
  persisted — `mission_controller/<mission>/ledger.json` carries
  `plan_version v2`, 1 replan, 3 plan_reviews (approved / rejected / approved)
  including the rejection reasons, plus the key map with X.
- **NOT PROVEN** (recorded, not claimed): restoring controller state
  (plan_version, replans, plan_reviews) into a NEW controller from the
  ledger. A fresh controller starts at v1 with empty records while the
  durable ledger on disk holds v2. Impact on recoverable operation: a
  review-gated mission cannot be continued from a new process/controller
  until state restoration is implemented — and the gate makes that SAFE:
- **VERIFIED (fail-closed)**: continuation is REFUSED when state cannot be
  restored — in-process fresh controller AND fresh-PROCESS probe
  (`e10rp1_restore_probe.py`): `PLAN_REVIEW_GATE: continuation REFUSED ...
  never been reviewed (fail-closed)`, zero new events, before any execution.
  No cross-process resume support is claimed anywhere in this order.

## 6. Regression (order §5) — commands, exit codes, results

Run in the isolated worktree on the corrected tree; every affected battery
also run at the BASELINE commit in a throwaway worktree (removed after) —
failure sets IDENTICAL at both states, i.e. zero regressions and zero
unexplained deltas:

| Battery | Command | Exit | Result | vs baseline |
|---|---|---|---|---|
| RP1 matrix (new) | `python3 -m pytest E10/test_e10rp1_matrix.py -v -p no:cacheprovider` | 0 | 16/16 | new (§3/§4 proof) |
| E10-RP matrix | `python3 -m pytest E10/test_e10rp_matrix.py -p no:cacheprovider` | 0 | 23 passed | identical to ratified |
| E10/CW1 matrix | `python3 -m pytest E10/test_e10_matrix.py -p no:cacheprovider` | 0 | 32 passed | identical |
| E10-CW1-R1 matrix | `python3 -m pytest E10/test_e10r1_matrix.py -p no:cacheprovider` | 0 | 31 passed | identical |
| E9-R | `python3 E9-R/test_production_integration.py` | 0 | OVERALL: PASS | identical |
| E8 negative gates | `PYTHONPATH=src python3 run_e8_human_gates.py` | 0 | 4/4 REJECTED | identical (known import-path dependency, unchanged) |
| e3 + e4 | `python3 -m pytest tests/orchestrator/test_e3_... test_e4_... -p no:cacheprovider` | 1 | 5 failed / 4 passed / 15 skipped (NVIDIA) | IDENTICAL set — pre-existing (2 are HEAD≠main artifacts of running in a worktree; 3 are the documented pre-existing e4 failures) |
| e6 | `python3 -m pytest tests/orchestrator/test_e6_... -p no:cacheprovider` | 1 | 4 failed / 14 passed | IDENTICAL set — pre-existing |
| e33 + e32f | `python3 -m pytest tests/unified/test_e33_... test_e32f_... -p no:cacheprovider` | 0/5 | 1 failed (baseline-verify artifact) + 1 passed, 2 skipped (NVIDIA) | identical |
| e35 | `PYTHONPATH=src python3 tests/e35/test_long_mission.py` | 1 | `RuntimeError: T2 failure not detected` | IDENTICAL — pre-existing, unchanged (not expanded per §5) |
| e37 | `PYTHONPATH=src python3 tests/e37/test_multi_task_mission.py` | 1 | `E37 PARTIALLY VERIFIED (4/15)` | IDENTICAL — pre-existing, unchanged (not expanded per §5) |

Raw outputs preserved under `/home/z/my-project/scripts/` (smoke runs,
e3/e4/e6 two-state lists, e35/e37 outputs) and in the committed evidence
session.

## 7. Review / deviation / continuation evidence (committed)

`E10/evidence_rp1/canonical/` (34 files, 608K):
`evidence/pre_registered.json` (written BEFORE any cycle ran; expectations
never changed after outcomes — the diagnostic rounds only identified
pre-existing defects, and the final runs passed against the ORIGINAL
expectations), `evidence/runner.json` (verdict `E10RP1_CHAIN_PROVEN`,
distinct PIDs), per-cycle `facts.json` + `expectations_check.json` (27/27
and 10/10) + `events.jsonl` + durable originals: `mission_controller/<m>/
ledger.json`, `side_effect_journal/<m>/journal.jsonl`, `checkpoints/`,
`sandbox-task-*/task_*.txt`, `evidence_store/`, and
`full/restore_probe.json` (fresh-process refusal).

## 8. Remaining gaps — CLAIM / OBSERVED / VERIFIED

| Item | Classification |
|---|---|
| Canonical path enables the review gate explicitly (default ON, opt-out visible) | VERIFIED (source + 16/16 matrix) |
| Canonical path manages the full replanning cycle (deviation→evidence→decision→replan→review→continuation) | VERIFIED (27/27 + durable ordering chain) |
| Rejected review blocks continuation; unapproved modified plan never executes | VERIFIED (BLOCKED 10/10 + gate probes) |
| Completed work preserved; no repeated side effects (journal performed==1 per path) | VERIFIED |
| Durable ledger (plan version/replans/reviews) | VERIFIED (written) |
| Restore controller state into a NEW controller/process from the ledger | NOT PROVEN — fail-closed refusal proven instead; impact documented in §5 |
| Replanning decision content beyond the disclosed provider (independent replanning planner) | NOT PROVEN — the decision content is a disclosed control input at the decision boundary; the PATH is the canonical operational path |
| Wiring verifier failures into the replanning decision path | NOT PROVEN — recorded durably now; not claimed |
| Real EOE grant integration for production (proof uses the E9-R-pattern test validator, disclosed) | NOT PROVEN — the baseline had NO validator at all; the pass-through now exists |
| Sufficiency arbiter for evidence (independent reviewer beyond the structural C1..C8 review) | NOT PROVEN (unchanged from E10-RP) |
| e35/e37 + import-path dependencies (E8 needs `PYTHONPATH=src`; `llm` needs repo root on path) | OBSERVED pre-existing — unchanged, not expanded |

## 9. Branch / diff / main state

- Delivered on branch `e10-rp1-canonical-review-gate` (from `ac70eb6e`),
  one commit on top of the ratified E10-RP commit; NO merge, NO push to
  `main` — `main` remains `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f`
  (local == remote, re-verified by live ls-remote at delivery).
- Diff vs `ac70eb6e`: `src/orchestrator/canonical.py` (review-gate policy,
  wired replanning path, stub removal, grant validator pass-through,
  role-based agent dispatch, live-graph completion keys) + explicit
  opt-outs in the two orchestrator test fixtures + the new
  `E10/e10rp1_*` modules and `E10/test_e10rp1_matrix.py` +
  `E10/evidence_rp1/canonical/` evidence.

## 10. Acceptance (order §7) and oversight update

**VERDICT: `E10_RP1_PASS` (CONDITIONAL — awaiting independent ratification;
branch NOT merged; main untouched).**

The canonical path now ENFORCES the plan review gate by default, MANAGES
the replanning cycle through the path operations actually uses (real
MissionController + ExecutionEngine + ToolExecutor), and BLOCKS unapproved
continuation — the exact §7 acceptance conditions. The proof is no longer
confined to direct `MissionController` calls: the FULL and BLOCKED cycles
run through `CanonicalOrchestrator.execute_mission`, judged against
pre-registered expectations, from durable evidence.

Notion is NOT accessible from this environment (disclosed — same as the
E10-RP session). Paste-ready oversight entry:

```
E10-RP1 — Canonical Replanning Path & Review-Gate Integration
Branch: e10-rp1-canonical-review-gate (one commit on ac70eb6e; main untouched at 0a26fc70)
Corrections (canonical.py): review gate ON by default (explicit policy) ·
replan branch wired to replan_mission (stub removed) · verifier failure
recorded (stub removed) · grant validator pass-through (pre-existing
defect: no canonical mission could complete) · role-based agent dispatch
(pre-existing defect: thinker misrouted to mission tasks) · live-graph
completion keys.
Proof: E10/test_e10rp1_matrix.py 16/16; FULL cycle 27/27 (deviation →
replan v1→v2 → review REJECTED (C6) → recovery → review APPROVED 8/8 →
continuation → EVIDENCED); BLOCKED cycle 10/10 (rejected review blocks,
zero execution); fresh-process restore probe REFUSED fail-closed.
Regression: E10-RP 23/23 · E10/CW1 32/32 · E10-CW1-R1 31/31 · E9-R PASS ·
E8 4/4 REJECTED · e3/e4/e6/e35/e37 identical pre-existing sets (two-state
proven). Zero new regressions.
NOT PROVEN (kept honest): controller-state restore into a new
controller/process (fail-closed refusal proven instead) · independent
replanning decision content (disclosed control input) · verifier-failure
→ replan wiring · real EOE grant integration (test validator, disclosed).
Verdict: E10_RP1_PASS (CONDITIONAL — awaiting ratification; no merge).
```
