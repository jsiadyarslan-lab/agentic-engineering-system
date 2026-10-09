# E10-RP2 — DISCOVERY (pre-correction findings, proven at baseline `6d83cec`)

All findings below were established on the UNMODIFIED baseline tree
(`e10-rp1-canonical-review-gate` @ `6d83cec11c959d3a38ad802b33faef04d77a185f`)
before any correction was applied. Findings that required runtime proof were
reproduced in a throwaway baseline worktree (removed after; two-state
comparison in `E10_RP2_REPORT.md` §6).

## §2 — AUTHORIZATION findings

### D1 — The canonical orchestrator has NO production invocation point
`CanonicalOrchestrator` / `create_canonical_orchestrator` are invoked ONLY by:
- `tests/orchestrator/test_e3_canonical_orchestrator.py`
- `tests/orchestrator/test_e4_multi_task_mission.py`
- `E10/e10rp1_cycle.py` + `E10/test_e10rp1_matrix.py` (the RP1 proof harness)

The production API paths are SEPARATE systems:
- `/api/mission/stream` → `src/missions.py::run_mission` → `core.orchestrator`
  (the live five-role mission system, its own `ToolContext(grant_root=…)`)
- `/api/v2/eoe/stream` → `src/eoe/eoe_engine.py::EoeEngine` (the executive
  orders engine)

Consequence: "the real operational path" for the canonical orchestrator IS
its factory + the E10 harness that drives it through the real
MissionController/ExecutionEngine/ToolExecutor chain. Wiring real
authorization therefore means wiring it at `create_canonical_orchestrator`
(the actual creation point) — which §2.4's three cases exercise.

### D2 — The EOE grant policy source exists and is complete — but was never connected
`src/eoe/access_gateway.py` is a full fail-closed production contract:
`GrantorService` (propose → owner approval → HMAC sign; keys enter at
runtime from the caller — engineering never signs), `AccessLedger`
(register / revoke / lookup / sweep_expired), `AccessAdmission`
(`admit_access`: signature, expiry, revocation, scope, path coverage,
depth — all fail-closed). `src/grants/` holds the parallel E1
`ResourceGrant` contract (typed, expirable, revocable, HMAC-signed).

**No bridge existed** between this contract and the unified engine's
`grant_validator` hook (`ToolExecutor._check_permissions`). Every proof
cycle up to E10-RP1 supplied the disclosed allow-all test lambda.

### D3 — A fake test grant identity was hardcoded in PRODUCTION code
`src/unified/execution.py` (baseline line ~1489) constructed every
`ExecutionContext` with `grant_ids=["test-grant"]  # E9-R: default grant
for testing`. Whatever validator is wired, the engine presents it a
hardcoded test grant id. With a REAL validator this id is rejected
(unknown grant → deny) so the path stays fail-closed, but the identity
injection was not a parameter — the canonical path could not present its
real owner-approved grant ids even if it had them.

### D4 (severity: highest) — The completion verdict could not see verifier failures — and the verifier layer was ENTIRELY broken at baseline
Two independent defects compounded:

1. `MissionController.verify_completion`'s `verification_history` check
   passed on **`evidenced > 0`** — ANY evidenced verification anywhere
   (another task's, or one predating a criteria correction) covered ANY
   number of concurrent unresolved `not_evidenced` results.

2. `E3VerifierAgent` (the orchestrator's verifier) constructed
   `EvidenceRecord(content_type="verification", …)` — a value the
   EvidenceRecord contract **REJECTS** (`Literal["artifact","stdout",
   "stderr","log","report","checkpoint"]`, pydantic ValidationError). The
   exception was swallowed by the agent-execution wrapper, so the agent
   returned `success=False` for **every** verification.

**Proven from the COMMITTED RP1 evidence** (not a re-run — the published
artifacts of the ratified E10-RP1 session):
`E10/evidence_rp1/canonical/full/events.jsonl` contains exactly THREE
`verification.complete` events with `source="canonical_orchestrator"` —
**all three are `not_evidenced`** (they are the verifier layer failing on
the ValidationError), while the mission's final verdict was
`EVIDENCED`/success — the loose rule counted the ENGINE's evidenced
events and the broken verifier layer was invisible. The arbitrator's
suspicion ("تسجيل الفشل وحده لا يضمن أن النتيجة النهائية ستُمنع") was
correct, and the baseline reality was strictly worse than suspected.

### D5 — No verification bindings
`run_verifier` emitted `VERIFICATION_COMPLETE` **only on success**, with
`attempt_id=new_attempt_id()` — a fresh RANDOM id unrelated to the
attempt that produced the verified artifact. The orchestrator's separate
failure-recording emission (added in RP1) also used a random id. No
`plan_version`, no run binding, no producing-attempt provenance existed
anywhere in the verification event stream.

### D6 — Verifier → replan wiring absent (the RP1-disclosed gap)
Verifier failures were durably recorded (RP1 §2.5) but never classified
as deviations and never fed the replanning decision path. Only
engine-level `TASK_FAILED("Verification failed…")` events reached
`scan_failures` → PLAN_DEVIATION → replan.

### D7 — A verifier-triggered replan was structurally impossible
`ExecutionEngine.replan_task_graph` operates ONLY on missions in state
`EXECUTING`. After a successful continuation the mission sits at
`EVIDENCED` (EXECUTED → VERIFYING → EVIDENCED inside `execute_run`), so
even with D6 fixed, `replan_mission` would fail on any replan triggered
by post-execution verification. The state machine already contained the
legal return path `EVIDENCED → ADJUDICATED → EXECUTING` — unused.

## §3 — VERIFICATION TRUTH findings

### D8 — Two verification layers, two different truth bases, neither checks current reality
- Engine `verify_task` (execution time): checks criteria against the
  artifact **as recorded in the evidence store** (write-time snapshot).
- Orchestrator `E3VerifierAgent` (final pass): checked only that the
  artifacts list was non-empty (and per D4 actually always failed).

No layer ever read the CURRENT on-disk state, and no layer re-checked a
PRESERVED task whose criteria were later corrected by a replan — the
exact hole the §4.2 mixed case exposes (a wrong criteria correction on a
completed task sails through `evidenced > 0`).

### D9 — Classification asymmetries
`scan_failures._classify` orders "Verification failed" BEFORE the
tool/runtime patterns, so an error string containing both classifies as
PLAN_DEVIATION; unknown criterion types are silently SKIPPED by
`verify_task` at execution time (a task can complete without its
criteria ever being enforced). The final verification layer now FAILS
unknown criteria (fail-closed) — the asymmetry is disclosed rather than
silently unified (changing the engine's execution-time semantics is
outside this order's surgical scope).

### D10 — Engine retry semantics (documented for the record)
A verification-failed task is retried by the engine up to
`max_retries` (observed: 3 failed attempts) before terminal failure;
`recover_failed_task` then re-executes it once. RP2's pre-registered
`D=4` attempts expectation was calibrated to this observed behavior in
diagnostic round #1 (a crashed run — see REPORT §7) and never changed
after a passing run.
