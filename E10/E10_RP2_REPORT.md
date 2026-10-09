# E10-RP2 — CANONICAL EXECUTION AUTHORIZATION & VERIFICATION TRUTH — DELIVERY REPORT

**Verdict: `E10_RP2_PASS` (CONDITIONAL — awaiting independent ratification; NO merge; `main` untouched)**

- Branch: `e10-rp2-canonical-auth-verification-truth` (derived from `6d83cec` ONLY)
- Baseline proven before any modification: `main` == `0a26fc70` local+remote
  (unchanged all session); RP1 branch == `6d83cec` local+remote; parent chain
  `6d83cec → ac70eb6e → 0a26fc70` verified; all four worktrees content-clean
  (filemode noise only, pre-existing). Evidence:
  `scripts/e10rp2_baseline_evidence.json` → `BASELINE_OK`, zero stop conditions.
- Matrix: **22/22** (`E10/test_e10rp2_matrix.py`, exit 0). Durable session:
  **9/9 runs PROVEN** (`E10/run_e10rp2.py` → `E10RP2_CHAIN_PROVEN`,
  evidence in `E10/evidence_rp2/canonical/`).

---

## 1. Executive summary

E10-RP2 closed the two blocking findings of the E10-RP1 arbitration and, in
doing so, uncovered and fixed a strictly worse pre-existing defect the
arbitration had suspected but not sized:

1. **Real authorization is now wired to the real operational path.** A new
   production bridge (`src/eoe/engine_bridge.py`) converts the REAL EOE
   grants contract (`GrantorService`/`AccessLedger`/`AccessAdmission` —
   owner-approved, HMAC-signed, revocable, expirable, path-scoped) into the
   engine's `grant_validator`. The canonical path now takes `grant_ids`
   alongside the validator and presents the owner-approved grant identity.
   Allow / deny (revoked, read-only, path-uncovered) / missing (validator,
   grants) are all proven from `create_canonical_orchestrator` — the actual
   creation point — with zero side effects on every denial.

2. **Verification truth is enforced per task.** `verify_completion` now
   requires, for every required task WITH criteria: a verification exists;
   its LATEST verdict is `evidenced`/`passed`; and that evidence is
   version-valid (performed at/after the plan version in which the task's
   criteria were last set). A current unresolved `not_evidenced` can no
   longer be covered by another task's success or by stale evidence. The
   §4.2 mixed case — which the pre-RP2 rule reported as SUCCESS — now
   fails, and resolution requires newer valid evidence (§4.3 proven with
   history preserved).

3. **The verifier layer was broken at baseline and is now real.** Every
   orchestrator-level verification at `6d83cec` failed internally
   (pydantic `ValidationError` on `content_type="verification"` — proven
   from the committed RP1 evidence, DISCOVERY D4) while the loose rule
   reported success. The verifier now checks each task's CURRENT criteria
   against the CURRENT on-disk state, binds the producing attempt + plan
   version + run, emits BOTH verdicts, and verifier-detected plan
   deviations flow into the EXISTING decision → `replan_mission` → review
   gate → continuation path (the RP1-disclosed gap, closed). Verifier
   tool/runtime errors never feed replanning (§3.5).

## 2. CLAIM / OBSERVED / VERIFIED / NOT PROVEN

### §2 — REAL AUTHORIZATION

| # | Claim | Observed | Status |
|---|---|---|---|
| 2.1 | All actual invocation points of `CanonicalOrchestrator`/`create_canonical_orchestrator` traced; EOE grant policy source identified | Callers = e3/e4 tests + E10 harnesses only (no production API caller — DISCOVERY D1); policy source = `src/eoe/access_gateway.py` (+ `src/grants/` E1 contract); NO bridge existed (D2) | **VERIFIED** |
| 2.2 | No test-param masquerading as production integration | The allow-all lambda appears ONLY in legacy fixtures/tests (declared) — no RP2 cycle uses it; every RP2 run uses `eoe.engine_bridge` over real owner-approved grants | **VERIFIED** |
| 2.3 | Real validator wired to the real path (clear production contract existed) | `eoe.engine_bridge.build_engine_grant_validator(admission, artifacts_root)` → `create_canonical_orchestrator(grant_validator=…, grant_ids=[grant_id])`; validates the SPECIFIC grant id via the new public `AccessAdmission.admit_grant_id` (never "any covering grant") | **VERIFIED** |
| 2.4 | Three cases from the actual creation point | allow: mission completes, files written, `grant.issued`/`grant.used` in the ledger, admission usage log non-empty; deny (revoked/read-only/path): PermissionError on every governed write, ZERO files, ZERO performed journal records, no replan; missing validator: "no validator available"; missing grants: "lacks required permission" | **VERIFIED** (T06–T08; auth cases 3/3–4/4) |
| 2.5 | No side effects on denial | `sandbox_files == []` and `performed_journal_records == 0` proven on ALL five deny/missing cases (facts.json `side_effects` per case) | **VERIFIED** |

### §3 — VERIFICATION TRUTH

| # | Claim | Observed | Status |
|---|---|---|---|
| 3.1 | Flow `run_verifier → VERIFICATION_COMPLETE → verify_completion/scan_failures` examined | DISCOVERY D4–D9: loose rule + broken verifier + no bindings + no wiring + state-machine block | **VERIFIED** (documented) |
| 3.2 | Verification bound to task + attempt + plan version | `VerificationCompleteEvent` gains `plan_version`/`run_id`/`verifier_attempt_id`/`criteria_source` (backward compatible); canonical verifier binds the PRODUCING attempt (`_producing_attempt_id`); engine-era events get their version derived from replan timestamps | **VERIFIED** (T11) |
| 3.3 | No EVIDENCED with a current unresolved failure on required work | Mixed case: A evidenced + C current `not_evidenced` → completion INCOMPLETE with `current_unresolved_verification_failure` for C (the pre-RP2 rule reported this exact state as SUCCESS — the false-success hole is closed) | **VERIFIED** (T09; mixed-blocked 8/8) |
| 3.4 | Historical failure resolved ONLY by newer valid evidence; history preserved | C: `evidenced@v1 → not_evidenced@v2 → evidenced@v3`; the v2 failure record resolved by `replan->v3`; criteria version v3; the not_evidenced event REMAINS in `events.jsonl` | **VERIFIED** (T10; resolution 18/18) |
| 3.5 | Deviation-type verification failures → existing replan/review path; tool/runtime failures stay in retry | Verifier PLAN_DEVIATION record → decision → `replan_mission` (v2→v3, through the legal `EVIDENCED→ADJUDICATED→EXECUTING` re-entry) → review approved → continuation; ordering `verifier_failure < replan_v3 < review_approval` proven from durable timestamps. Verifier machinery errors → `TOOL_RUNTIME_FAILURE` (retry), never replan. Real tool failure case: B recovered by engine retry (attempts=2), replans=0, verifier failures=0 | **VERIFIED** (T12, T14) |
| 3.6 | No unbounded redesign of the verification/task lifecycle | All changes are additive or in-place rule tightening; no schema rebuild, no new execution substrate | **VERIFIED** (diff: 6 source files, +673/−72) |

### §4 — REQUIRED TEST MATRIX — all proven through the REAL path

| Case | Evidence | Result |
|---|---|---|
| 1. allow / deny / missing (§4.1) | auth cases `allow`, `deny-revoked`, `deny-read-only`, `deny-path`, `missing-validator`, `missing-grants` + T06–T08 | 3/3 + 4/4×5 **PASS** |
| 2. mixed (§4.2) | `mixed_blocked` cycle + T09 | 8/8 **PASS** (no false success) |
| 3. historical (§4.3) | `resolution` cycle + T10 | 18/18 **PASS** |
| 4. replan path (§4.4) | `resolution` (both legs: engine-deviation v1→v2 AND verifier-deviation v2→v3) + T12/T13; RP1 matrix re-run 16/16 | **PASS** |
| 5. real tool failure (§4.5) | `tool-fail` case + T14 | 4/4 **PASS** |
| 6. duplicate side effects / preservation (§4.6) | `resolution` duplicate-continuation probe + T15 | **PASS** (zero new attempts, journal unchanged) |

Re-run matrices (commands + exit codes below): RP1 16/16 · E10-RP 23/23 ·
E10/CW1 32/32 · E10-CW1-R1 31/31 · E9-R OVERALL PASS · E8 4/4 REJECTED.

### NOT PROVEN / honest limits (unchanged or newly disclosed)

1. **The canonical orchestrator still has no production API caller** (D1).
   RP2 proves the authorization and verification truth on the real
   MC+EE+ToolExecutor path from the real creation point; wiring the
   canonical orchestrator into `src/api/routes.py` is a separate,
   larger integration decision (belongs to the arbitrator, not to this
   targeted correction).
2. **Replan decision CONTENT remains a disclosed control input** (the
   provider). RP2 deliberately made one decision WRONG (the v2 criteria
   correction for C) to prove the truth rule — not the decision —
   protects completion. Independence of decision content is NOT claimed.
3. **Controller-state restore into a new controller/process** — still
   NOT claimed (RP1's fail-closed refusal stands; untouched by RP2).
4. **The engine's legacy default `grant_ids=["test-grant"]` remains**
   for pre-existing batteries (documented in code; REJECTED by any real
   validator — unknown grant — so fail-closed holds). Removing the
   default entirely touches ~30 test files; inventoried, proposed as a
   follow-up, NOT done here (§5 limits).
5. **Engine execution-time criteria checking still SKIPS unknown
   criterion types** (pre-existing); the new final verifier FAILS them
   (fail-closed). The asymmetry is disclosed (D9), not silently unified.
6. **`D=4` attempts expectation was calibrated in diagnostic round #1**
   (a crashed run — `RoleCoordinator.artifacts_base_dir` AttributeError;
   fixed) to the engine's observed retry semantics. The properties under
   test were never relaxed after a passing run; disclosed here and in
   `e10rp2_common.attempts_note`.
7. **Pre-existing battery failures are unchanged, not fixed** (per §5):
   e3+e4 5F/4P/15S, e6 4F/14P, e33+e32f 1F/1P/2S, e35 exit 1, e37 exit 1 —
   failure sets IDENTICAL at baseline and at this branch (two-state).
8. **CI on GitHub** could not be verified from this environment (the
   commit-status API returned an empty list for `6d83cec`); all test
   evidence here is local, with commands and exit codes recorded.
9. **Notion** is not accessible from this environment; a paste-ready
   oversight entry is provided (§10).

## 3. Corrections applied (all in the isolated worktree; original trees untouched)

| File | Change |
|---|---|
| `src/eoe/access_gateway.py` | + public `AccessAdmission.admit_grant_id()` — validates ONE specific grant (id lookup + APPROVED state + signature/expiry/revocation/scope/path/depth via the existing `_check`); additive, no existing-caller change |
| `src/eoe/engine_bridge.py` | NEW production bridge: `build_engine_grant_validator(admission, artifacts_root)` — engine permission strings → EOE admission semantics; `write`→READ_WRITE, `read`→any, anything else (e.g. `execute`) → **deny** (fail-closed); all failures → False |
| `src/unified/execution.py` | `grant_ids: Optional[List[str]]` parameter on `ExecutionEngine.__init__` + `create_execution_engine`; context uses the injected ids; `None` keeps the documented E9-R legacy default (the single remaining `"test-grant"` hardcode — rejected by any real validator) |
| `src/unified/event_catalog.py` | `VerificationCompleteEvent` += `plan_version`/`run_id`/`verifier_attempt_id`/`criteria_source` (optional, backward compatible) |
| `src/unified/mission_controller.py` | (a) `verify_completion`: per-task latest-verdict + plan-version-validity rule (replaces `evidenced>0`); per-task report + machine-readable `verification_failures` (reasons: `no_verification`, `current_unresolved_verification_failure`, `stale_evidence_for_corrected_criteria`); (b) `replan_mission`: legal re-entry `EVIDENCED→ADJUDICATED→EXECUTING` (validated + emitted per hop) when a verifier-triggered replan arrives after the run finished |
| `src/orchestrator/canonical.py` | (a) `grant_ids` param + pass-through; (b) `E3VerifierAgent` upgraded: CURRENT criteria vs CURRENT on-disk state (file_exists/file_contains/file_hash_matches; unknown criterion FAILS; latest-mtime sandbox resolution) + `content_type="report"` (repairs the D4 ValidationError); (c) `run_verifier`: binds producing attempt/plan version/run, emits BOTH verdicts; (d) step 6 → verification-truth loop over ALL completed required tasks with criteria; verifier PLAN_DEVIATIONs feed `_run_replanning_cycle` (bounded by `max_review_rounds`); tool/runtime verifier errors recorded but never replanned; (e) `_record_verifier_failure`/`_resolve_verifier_failure` (dedup + newer-evidence resolution) |
| `E10/test_e10rp1_matrix.py` | ONE assertion updated (disclosed): the RP1-era literal `verdict="not_evidenced"` source pattern was replaced by the RP2 bound emission `verdict="evidenced" if result.success else "not_evidenced"` — same intent (failure recorded, not dropped), stronger form. No expectation was weakened. |
| `E10/e10rp2_*` + `E10/test_e10rp2_matrix.py` + `E10/run_e10rp2.py` | NEW harness: scenario, providers, real-EOE auth builder, cycle/auth runners, pre-registered expectations, 22-test matrix, durable-session runner |

## 4. Acceptance gate (order §6) — condition by condition

1. **Real write authorization wired to the operational path, or the path
   fails closed clearly in its absence** — VERIFIED: wired
   (`engine_bridge` + `grant_ids` from `create_canonical_orchestrator`);
   missing validator → "no validator available"; missing grants →
   "lacks required permission" — both with zero writes (T07/T08).
2. **A current unresolved verification failure cannot produce a
   successful completion** — VERIFIED: T09 (mixed case fails with
   `current_unresolved_verification_failure`; the identical state was a
   false SUCCESS under the pre-RP2 rule).
3. **Historical failure resolution only with newer valid evidence** —
   VERIFIED: T10 (`evidenced@v1 → not_evidenced@v2 → evidenced@v3`;
   stale evidence for corrected criteria is rejected by the
   version-validity rule — observed live in diagnostic round #1).
4. **The real path, not a separate harness, passes the required cases
   with re-examinable traces** — VERIFIED: every case runs
   `CanonicalOrchestrator.execute_mission` → real MC+EE+ToolExecutor;
   durable evidence committed under `E10/evidence_rp2/canonical/`
   (facts, expectations_check, events, ledgers, journals, sandbox
   artifacts, runner.json).

## 5. Regression (order §4) — commands, exit codes, two-state comparison

All batteries re-run in the isolated worktree; affected/pre-existing-failure
batteries ALSO run at the BASELINE commit `6d83cec` in a throwaway worktree
(removed after) — failure sets IDENTICAL, i.e. zero new regressions:

| Battery | Command | Exit | Mine @ RP2 | Baseline @ 6d83cec |
|---|---|---|---|---|
| RP2 matrix (new) | `python3 -m pytest E10/test_e10rp2_matrix.py -p no:cacheprovider` | 0 | 22 passed | — (new) |
| RP2 session (new) | `python3 E10/run_e10rp2.py` | 0 | E10RP2_CHAIN_PROVEN 9/9 | — (new) |
| RP1 matrix | `python3 -m pytest E10/test_e10rp1_matrix.py -p no:cacheprovider` | 0 | 16 passed (1 source-pattern assertion updated — §3) | 16 passed |
| E10-RP matrix | `python3 -m pytest E10/test_e10rp_matrix.py -p no:cacheprovider` | 0 | 23 passed | 23 passed |
| E10/CW1 matrix | `python3 -m pytest E10/test_e10_matrix.py -p no:cacheprovider` | 0 | 32 passed | 32 passed |
| E10-CW1-R1 matrix | `python3 -m pytest E10/test_e10r1_matrix.py -p no:cacheprovider` | 0 | 31 passed | 31 passed |
| E9-R | `python3 E9-R/test_production_integration.py` | 0 | OVERALL: PASS | OVERALL: PASS |
| E8 negative gates | `PYTHONPATH=src python3 run_e8_human_gates.py` | 0 | 4/4 REJECTED | 4/4 REJECTED |
| e3 + e4 | `python3 -m pytest tests/orchestrator/test_e3_… test_e4_… -p no:cacheprovider` | 1 | 5F/4P/15S | **IDENTICAL set** |
| e6 | `python3 -m pytest tests/orchestrator/test_e6_… -p no:cacheprovider` | 1 | 4F/14P | **IDENTICAL set** |
| e33 + e32f | `python3 -m pytest tests/unified/test_e33_… test_e32f_… -p no:cacheprovider` | 1 | 1F/1P/2S | **IDENTICAL set** |
| e35 | `PYTHONPATH=src python3 tests/e35/test_long_mission.py` | 1 | `RuntimeError: T2 failure not detected` | IDENTICAL |
| e37 | `PYTHONPATH=src python3 tests/e37/test_multi_task_mission.py` | 1 | `E37 PARTIALLY VERIFIED (4/15)` | IDENTICAL |

Note (disclosed): an earlier e3+e4 probe run with a NON-standard PYTHONPATH
(both repo root and `src`) showed 6F instead of 5F at BOTH states — an
invocation artifact, not a code difference; the table uses the EXACT RP1 §6
invocation (cwd=worktree), reproducing the ratified 5F/4P/15S at both states.

## 6. Evidence session (committed, re-examinable)

`E10/evidence_rp2/canonical/` — 9 runs: `resolution/`, `mixed_blocked/`,
`allow/`, `deny-revoked/`, `deny-read-only/`, `deny-path/`,
`missing-validator/`, `missing-grants/`, `tool-fail/`; each with
`facts.json`, `expectations_check.json`, `events.jsonl` + the engine's
durable trees (events, evidence_store, mission_controller ledgers,
side_effect_journal, checkpoints, sandbox artifacts). Top-level
`runner.json` (E10RP2_CHAIN_PROVEN, 9 runs, per-run exit + verdict).
Pre-registered expectations: `E10/evidence_rp2_expectations.json`
(written before any passing cycle; `written_before_any_cycle: true`;
the single post-diagnostic calibration is disclosed in §2 item 6).

## 7. §5 limits compliance

- No claim of independent replanning decision content (control input disclosed).
- No claim of controller-state restore across processes.
- No claim of locally re-run tests that were not actually run (every row in
  §5 has its command + exit code; CI on GitHub remains unverified from here).
- No push to `main`, no merge, no general factory rebuild (6 source files,
  +673/−72; everything else is the E10 harness + evidence).
- The three §2.3 stop-conditions did not trigger: a clear production
  contract (the EOE grants system) EXISTS, so the validator was wired, not
  invented — the bridge contains no policy of its own.

## 8. Proposed follow-ups (decisions for the arbitrator, not executed)

1. Remove the engine's legacy `grant_ids=["test-grant"]` default (≈30 test
   files to update explicitly; inventory in DISCOVERY D3).
2. Wire the canonical orchestrator into a production API route (or
   formally designate it test/harness-only).
3. Unify unknown-criterion handling between execution-time (skip) and
   final verification (fail) — decide the engine-side semantics.
4. Cross-process controller-state restore (unchanged from RP1).

## 9. Paste-ready oversight entry (Notion)

> **E10-RP2 — Canonical Execution Authorization & Verification Truth — DELIVERED**
> Branch `e10-rp2-canonical-auth-verification-truth` @ `<commit>` (parent `6d83cec`; main still `0a26fc70`; NO merge).
> Real EOE grant authorization wired to the canonical operational path via the new `eoe.engine_bridge` (owner-approved signed grants; allow/deny/missing proven from `create_canonical_orchestrator`, zero side effects on denial). Verification truth enforced per task (latest-verdict + plan-version validity): the §4.2 mixed state that the pre-RP2 rule reported as SUCCESS now fails; resolution requires newer valid evidence (§4.3, history preserved). DISCOVERY: the baseline verifier layer was entirely broken (all published RP1 orchestrator verifications were `not_evidenced` on a pydantic ValidationError) and invisible under the loose `evidenced>0` rule — repaired and proven. Verifier→replan wiring closed (plan deviations only; tool errors stay in retry). Matrix 22/22; session 9/9 E10RP2_CHAIN_PROVEN; regressions: RP1 16/16, RP 23/23, CW1 32/32, CW1-R1 31/31, E9-R PASS, E8 4/4 — pre-existing failure sets IDENTICAL at baseline and branch (two-state). NOT PROVEN: production API caller for the canonical path; independent decision content; cross-process restore; GitHub CI (unverifiable from this environment).

## 10. Arbitration pointers

- Commit under arbitration: this branch's head (see `git log -1`).
- Baseline evidence: `scripts/e10rp2_baseline_evidence.json`.
- Discovery: `E10/E10_RP2_DISCOVERY.md` (D1–D10, each with file/line/provenance).
- Proof: `E10/test_e10rp2_matrix.py` (22) + `E10/run_e10rp2.py` (9 runs) +
  `E10/evidence_rp2/canonical/`.
