# E10-RP — REPLANNING CONTRACT DISCOVERY (§2) + SCOPE DECISION (§3)

Baseline: `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` (main, ls-remote verified).
Method: live code inspection of `src/unified` (production path), existing tests, and
durable evidence from E10/E10-CW1/E10-CW1-R1. "Absence of a search hit" was never
treated alone as proof of absence: call paths were followed (see per-capability notes).

## §2 — Capability matrix (CLAIM / OBSERVED / VERIFIED / NOT PROVEN)

| # | Capability (order §2) | Implementation (file:symbol) | Existing tests | Existing durable evidence | Classification |
|---|---|---|---|---|---|
| 1 | Original plan representation + task dependencies | `mission_controller.py` `TaskSpec` (107-115), `define_mission` (440-474), `record_plan_v1` (476-492), `plan_version` (400); `execution.py` `task_graph` | e33/e35/e37/e4/e6 harnesses | E10 evidence (5-task graph + checkpoints) | **VERIFIED** (re-proven by this experiment) |
| 2 | Deviation logging linked to Mission/Run/Task | `execution.py` 1683-1691: post-success acceptance verification → `TASK_FAILED` event `"Verification failed: not_evidenced"` (event carries mission_id/run_id/correlation_id=task_id); `verify_task` 3571-3663 (`VERIFICATION_COMPLETE` w/ verdict+checks+missing_evidence); `scan_failures` (`mission_controller.py` 601-685) → `FailureRecord(task_id, task_key, evidence, classification_reason, recovery_action)` | e33 runner (asserts PLAN_DEVIATION detected) | e33 ledger + this experiment | **VERIFIED** (re-proven) |
| 3 | Evidence source + sufficiency | Source: real artifact content vs acceptance criteria (`Verifier.verify` — `verification_standard.py` 233-289: pure deterministic, no LLM; failed check ⇒ verdict `not_evidenced`); agent-claimed success is OVERTURNED by verification (execution.py 1683-1691) — an unevidenced claim is never treated as fact. Sufficiency validator as a separate gate: none beyond the verifier | e33 (data-driven correction from artifact) | e33 | **PARTIAL**: source VERIFIED; dedicated sufficiency gate NOT PROVEN (classification trusts the verification report; no independent sufficiency arbiter) |
| 4 | Decision logic for replan necessity | `_classify` (662-676): `"Verification failed"` → PLAN_DEVIATION; `_recovery_for` (678-685): PLAN_DEVIATION → REPLAN, TOOL/TASK failure → RETRY. Application of a replan is an explicit caller decision (production caller: `src/orchestrator/canonical.py:966`) — no silent auto-replan | e33/e35/e37 + canonical orchestrator | e33 | **VERIFIED** (classification); application is driver-side BY DESIGN (protects against unnecessary replanning) |
| 5 | New plan creation + lineage to previous version | `replan_mission` (718-838) → `ReplanRecord(from_version → to_version, reason, evidence, added/invalidated/preserved/rewired/modified)`; engine `replan_task_graph` (`execution.py` 4844, E13); `plan_version` advanced; `_persist_ledger` (1426-1433) | e33 v1→v2 (invalidate E,F; add X; rewire G,H; correct D) | e33 ledger.json (durable) | **VERIFIED** (re-proven) |
| 6 | Review/approval mechanism before continuation | **MISSING on the mission replan path.** `PLAN_APPROVED` event type exists (`event_catalog.py:29`, routing :658) but `emitted_by` is Dashboard/CLI only; `PlanState.REVIEWING/APPROVED` exists (`state_machine.py`) for factory plans, unused for mission replans; `replan_mission` applies with NO review; `execute_run` (496) has no approval gate | none | none | **NOT PROVEN — THE GAP** |
| 7 | Completed tasks preserved; no unjustified re-execution | `replan_mission` docstring 729-743: invalidates only PENDING/BLOCKED/READY, never COMPLETED, never resets; engine skips COMPLETED on re-execution (`execution.py` 1931-1937, E10-proven T09/T11) | E10 matrix T09/T11; e33 | E10 evidence 20/20 | **VERIFIED** (re-proven) |
| 8 | Failure / retry / resume behavior | Engine retry loop (`max_retries`); `resume_from_checkpoint` + integrity gate (E10); `SideEffectJournal` intent/performed/reconciled (E10-CW1-R1); ledger durable incl. failures+replans (1417-1433) | E10 20/20; CW1 32/32; R1 31/31 | E10/CW1/R1 evidence trees | **VERIFIED** (relevant parts re-proven). Controller-state AUTO-restore into a fresh controller: NOT PROVEN (ledger is durable on disk; `restore_from_checkpoint` 1234-1290 restores graph+mission only — e33 runner rebuilt key maps manually). Recorded as a gap. |

Non-capability findings recorded during discovery:
- `run_e8_human_gates.py` inserts repo ROOT (not `src/`) into `sys.path` — known invocation dependency (proven pre-existing at d8b0620 and 0a26fc7 during the E10-CW1-R1 integration gate).
- `operational.py` `OperationalVerifierAgent` (285+) is a separate operational verifier; the mission path uses `verification_standard.Verifier` via `engine.verify_task`.

## §3 — Scope decision: **A + B**

**A — the replanning cycle already exists on the production path** (`MissionController.replan_mission` + `scan_failures` + engine `replan_task_graph`, e33-proven pattern):
the controlled experiment (§4) runs it on the real path; nothing existing is rebuilt.

**B — one minimal, contract-compatible addition closes the single gap (capability #6):**
a fail-closed plan-review gate, in ONE production file (`src/unified/mission_controller.py`):

1. `PlanReviewRecord` dataclass (review_id, run/mission ids, plan_version, verdict approved/rejected, reviewer, checks, reasons, reviewed_at).
2. `MissionController(require_plan_review=False)` opt-in flag — default preserves every existing caller/test byte-for-byte (no weakening, no behavior change for existing flows).
3. `review_plan(run_id, reviewer)` — 8 checks (C1..C8) derived ONLY from live graph + durable decision records:
   C1 version-chain continuity; C2 no completed work destroyed; C3 preserved-set == graph reality;
   C4 added tasks present with valid deps; C5 rewired tasks blocked while deps incomplete;
   C6 plan executable (no FAILED task remains — the honest rejection trigger while the deviated task is unrecovered);
   C7 causal link deviation→replan (evidence equality + `resolved_by == "replan->vN"`); C8 corrected criteria actually applied to the real task objects.
   Emits a durable `STATE_TRANSITION` (entity_type=plan_review) event; appends to the durable ledger.
4. Fail-closed continuation gate at the top of `execute_run`: with the flag on, continuation is REFUSED (RuntimeError) unless the CURRENT plan version's LATEST review is APPROVED. Rejected review or missing review both refuse. Nothing executes during refusal.
5. `ledger_snapshot` now includes `plan_reviews` (durable decision-evidence chain).

**NOT C:** no scheduler/task-lifecycle/storage redesign; no new agents or interfaces; no
external model integration. ~170 lines in one file, plus the E10-RP harness.

## Experiment design summary (§4, pre-registered)

Main scenario (single mission, real path, grant-validated engine, governed writes):
plan v1 = A → (B, C⚠) → D → E, where C is a CONTROLLED, KNOWN deviation input:
C's agent durably writes observed reality while plan v1's acceptance expects the
plan's assumption — verification verdict `not_evidenced` (literally: the conclusion
is not evidenced) → TASK_FAILED → scan_failures classifies PLAN_DEVIATION/replan.
Data-driven correction derives C's corrected criteria from C's actual artifact;
replan v1→v2 invalidates D (its product embeds the invalidated expectation), adds
remediation X (depends on C), rewires E onto X, corrects C's criteria.
Gate/refusal sequence: continuation refused (unapproved v2) → review v2 REJECTED
(C6: C still FAILED — plan not executable) → refusal again → recover C → review v2
APPROVED → continuation completes C, X, E; A, B never re-executed; C's artifact
adopted without rewrite (journal reconciled, same mtime/inode); verify_completion
+ finalize EVIDENCED; duplicate continuation ⇒ zero new side effects.

Safety cases: S1 insufficient evidence (claim without record ⇒ no classification ⇒
no replan; agent-claimed success overturned by verifier); S2 minimal scope
(terminal-task deviation ⇒ only that task's criteria change; nothing else touched;
non-plan failure ⇒ RETRY classification, never replan); S3 affected dependencies
(main scenario: only D/E futures changed, completed A/B preserved); S4
replanning/review failure (gate refusals + rejected review, zero execution between);
S5 retry/resume (duplicate continuation zero side effects; ledger/journal durable).
