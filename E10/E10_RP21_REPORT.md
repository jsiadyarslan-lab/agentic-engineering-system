# E10-RP2.1 — Authorization Path/Depth + Task-Bound Verification — Delivery Report

- **Order:** E10-RP2.1 — AUTHORIZATION PATH/DEPTH + TASK-BOUND VERIFICATION (AUTHORIZED — TARGETED CORRECTION)
- **Execution baseline:** `631f6fbb7bed2ea5411af240ea2147ad79318dfb` (branch `e10-rp2-canonical-auth-verification-truth`, parent `6d83cec`)
- **main baseline (unchanged):** `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f`
- **Delivery branch (new):** `e10-rp21-auth-depth-task-verification` from `631f6fb` only
- **Merge to main:** NONE (forbidden by the order; held for independent arbitration)

## 1. Hard baseline proof (§1) — VERIFIED

`E10/evidence_rp21/BASELINE.md` (captured BEFORE any modification):

- Live `ls-remote origin`: `main = 0a26fc70…` (matches the order), RP2 branch = `631f6fb…`, RP1 = `6d83cec…`.
- `631f6fb` parent = `6d83cec` (history intact on `0a26fc70`).
- All 5 worktrees clean before work; the original trees were never touched; no `reset`/`clean`/`stash`/`restore` used anywhere in this execution.
- New worktree `/home/z/my-project/e10rp21_work` on `e10-rp21-auth-depth-task-verification` created from `631f6fb` exactly.

## 2. §2 — Authorization path & depth — VERIFIED

**The bridge chain, end to end (§2.1):**
`ToolExecutor._check_permissions` (execution.py) → path-aware
`eoe.engine_bridge.build_engine_grant_validator` validator →
`AccessAdmission.admit_grant_id` → `_check` (signature, expiry, revocation,
scope, path coverage, depth) — and the write itself lands at
`artifacts_base_dir/sandbox-<task_id>/<path>` through
`SandboxManager.write_artifact` → `WindowsSandboxAdapter.write_artifact`
(journal-intent first, then the fsynced physical write, then `performed`).

**The explicit permission contract (§2.2 — no implicit semantics):**
a grant does NOT authorize "the whole task root" — it authorizes **specific
paths and depth within the root**: a concrete write/read is admitted only if
its ACTUAL resolved absolute path lies inside the grant target AND its depth
below the target (number of path components below it; target itself = 0,
direct child = 1) is ≤ the grant's `max_depth`, AND the scope covers
write/read. `max_depth=0` therefore authorizes NO file write under the
target (any file is at depth ≥ 1) — enforced, tested (RP2.1-T04).

**No fixed `depth=0` (§2.3):** the bridge forwards the caller's depth and
`AccessAdmission.admit_grant_id(depth=None)` computes the HONEST depth from
the actual path (`_actual_depth`). The RP2 fixed-depth bypass (discovery D1)
is gone — proven by RP2.1-T05: with the same `max_depth=2` grant, a depth-2
write is admitted and a depth-3 write is rejected.

**Sandbox isolation is now REAL (§2.3, discovery D3):** the claimed
"second defensive layer" did not exist — `SandboxManager` accepted any
sandbox id and the adapter joined `Path(dir) / path` with no containment
(traversal and absolute paths escaped the sandbox entirely). Now enforced at
THREE layers: the permission gate (`ToolExecutor._contained_write_target`
resolves and proves the target inside `artifacts_base_dir/<sandbox_id>`
BEFORE any event/journal/side effect), the governed-write entry
(re-proved before the intent journal record), and structurally at BOTH
`SandboxManager.write_artifact` and `WindowsSandboxAdapter.write_artifact`
(last line, legacy callers included). All escapes rejected fail-closed
(RP2.1-T09: `../../escape.txt`, absolute `/tmp/...`, mixed `a/../../x`).

**No allow-all validator (§2.4):** every RP2.1 unit test and scenario wires
ONLY the real `eoe.engine_bridge` validator built on owner-approved signed
grants (propose → owner approval → sign → ledger). Legacy 2-arg test
validators in old fixtures keep their existing semantics via the documented
fallback — the operational path never uses them.

**Required tests (§2.5) — all VERIFIED with the §2.6 zero-side-effect
proof (zero new files + zero `performed` journal records on every
rejection):**

| Case | Result | Zero files | Zero journal |
|---|---|---|---|
| matching authorized-path grant → write admitted (T03) | PASS — file written, intent+performed journaled, admission usage log records the ACTUAL target | — (write intended) | — |
| `max_depth=0` grant → depth-1 write (T04) | REJECTED | 0 | 0 |
| grant out of required path scope (T06) | REJECTED | 0 | 0 |
| missing grant / missing validator (T07/T08) | REJECTED fail-closed | 0 | 0 |
| containment escapes ×3 (T09) | REJECTED `SANDBOX_CONTAINMENT_VIOLATION` | 0 | 0 |

## 3. §3 — Task-bound verification — VERIFIED

**The fix (discovery D5):** `E3VerifierAgent._resolve_current_file` no
longer globs `sandbox-*/<rel>` and takes the newest mtime — it resolves
`<base_dir>/sandbox-<target_task_id>/<rel_path>` ONLY. No glob, no mtime
race, no cross-sandbox reads; a missing target-task identity yields no
evidence (fail-closed, never a cross-sandbox scan).

**Direct collision tests (§3.3) — both directions:**
- T10: two tasks, same relative name, different contents, adversarial
  mtimes (the other task's file NEWER — the exact old-glob trap) → BOTH
  evidenced, each from its OWN file (evidence_paths prove the exact file
  read).
- T11: the false-pass trap — task B's own file lacks the token while task
  A's newer same-name file HAS it → B is `not_evidenced`
  (`criteria_mismatch`) read from B's OWN file. Event-level task/attempt
  binding alone would NOT have caught this (order §3.2) — the file itself
  was task-bound.
- T12: missing evidence — B's own sandbox empty, A's sandbox holds a
  correct same-name file → B stays `not_evidenced`.
- End-to-end (T17 / scenario `collision-resolve`): the ENGINE layer passes
  B falsely through a first-path-match collision on the recorded evidence
  store (disclosed pre-existing engine-layer gap, discovery D7) — the
  task-bound orchestrator verifier CATCHES it; replan v2 corrects B's
  criteria to observed reality (RP2 D-pattern); review approves;
  continuation runs; B evidenced under v2 by NEWER evidence; history
  preserved; mission completes. 10/10 scenario checks.

**Missing evidence / unprovable attempt / criteria-after-replan (§3.4):**
missing evidence → `criteria_mismatch` (T12); unprovable producing attempt →
`not_evidenced` with explicit `provenance_unprovable` class — replacing the
RP2 evidenced-with-disclosure hole (T14 unit, T20 scenario: replan-eligible
but provider declines → honest failure); criteria correction after replan →
resolution only by newer evidence bound to the corrected criteria (T17, plus
the RP2 matrix T10 stale-evidence rule re-run). No historical success covers
a current verification failure (the RP2 per-task latest-verdict rule
re-proven in the RP2.1 scenarios' completion reports:
`current_unresolved_verification_failure`).

## 4. §4 — Verifier error classification — VERIFIED

**Explicit class, end to end (§4.1/§4.2):** the verifier chain carries
`failure_class ∈ {criteria_mismatch, provenance_unprovable, verifier_error}`
in the AgentResult output, the `VERIFICATION_COMPLETE` payload (new optional
fields, backward compatible), and the FailureRecord. The RP2
string-sniffing classifier (`"sandbox" in error_text.lower()`,
missing_evidence presence/absence) is DELETED (T16 asserts the patterns are
gone). A read failure during criteria evaluation is a machinery error, not a
criteria mismatch (the old `file_contains error …` path is fixed). A result
with NO explicit class is conservatively classified TOOL_RUNTIME (never
replan on unknown).

**Mapping (tested):** `criteria_mismatch` → PLAN_DEVIATION (replan-eligible);
`provenance_unprovable` → PLAN_DEVIATION (a replan can recover by
re-execution); `verifier_error` → TOOL_RUNTIME_FAILURE (retry territory).

**§4.3 direct proofs:**
- Read error (T15 unit / T18 scenario): file exists but reading it raises →
  `verifier_error` → the replan decision provider is NEVER consulted
  (`provider_calls == 0`), `replan_mission` never invoked, and the mission
  produces NO final success (completion names
  `current_unresolved_verification_failure`).
- Execution crash (T19 scenario): `AgentFactory.execute_agent_by_id` raises
  for the verifier → caught and classified inside `run_verifier` (the run
  itself never crashes — the RP2 propagation hole, discovery D6, closed) →
  same guarantees: no replan, no success.
- Actual criteria failure (T17 scenario): flows through decision →
  `replan_mission` (v1→v2) → review gate → continuation ONLY after approval
  (same wire as the RP2 resolution cycle, re-proven on the RP2.1 collision
  scenario).

## 5. §5 — Required regression battery — VERIFIED (raw log committed)

`E10/evidence_rp21/REGRESSIONS_BRANCH.txt` — every command, exit code, and
output tail recorded. `E10/evidence_rp21/SESSION_RUNNER_BASELINE_FLAKE.txt`
documents the two-state comparison.

| Battery | Command (cwd = worktree) | Exit | Result |
|---|---|---|---|
| **RP2.1 matrix (new)** | `python3 -m pytest E10/test_e10rp21_matrix.py -p no:cacheprovider -q` | 0 | **24 passed** |
| RP2 matrix | `python3 -m pytest E10/test_e10rp2_matrix.py -p no:cacheprovider -q` | 0 | 22 passed |
| RP2 session (fresh-dir equivalent) | `e10rp2_cycle.py` ×2 + `e10rp2_auth.py` ×7 into fresh dirs | 0 | 9/9 PROVEN |
| RP1 matrix | `python3 -m pytest E10/test_e10rp1_matrix.py -p no:cacheprovider -q` | 0 | 16 passed |
| E10-RP matrix | `python3 -m pytest E10/test_e10rp_matrix.py -p no:cacheprovider -q` | 0 | 23 passed |
| E10/CW1 matrix | `python3 -m pytest E10/test_e10_matrix.py -p no:cacheprovider -q` | 0 | 32 passed |
| E10-CW1-R1 matrix | `python3 -m pytest E10/test_e10r1_matrix.py -p no:cacheprovider -q` | 0 | 31 passed |
| E9-R | `python3 E9-R/test_production_integration.py` | 0 | OVERALL: PASS |
| E8 negative gates | `PYTHONPATH=src python3 run_e8_human_gates.py` | 0 | 4/4 REJECTED |
| e3+e4 | `python3 -m pytest tests/orchestrator/test_e3_canonical_orchestrator.py tests/orchestrator/test_e4_multi_task_mission.py -p no:cacheprovider -q` | 1 | 5F/4P/15S — **IDENTICAL set at 631f6fb** |
| e6 | `python3 -m pytest tests/orchestrator/test_e6_durable_mission_orchestration.py -p no:cacheprovider -q` | 1 | 4F/14P — **IDENTICAL set** |
| e33+e32f | `python3 -m pytest tests/unified/test_e33_mission_autonomy.py tests/unified/test_e32f_autonomous_replanning.py -p no:cacheprovider -q` | 1 | 1F/1P/2S — **IDENTICAL set** |
| e35 | `PYTHONPATH=src python3 tests/e35/test_long_mission.py` | 1 | `RuntimeError: T2 failure not detected` — IDENTICAL |
| e37 | `PYTHONPATH=src python3 tests/e37/test_multi_task_mission.py` | 1 | `E37 PARTIALLY VERIFIED (4/15)` — IDENTICAL |

Two-state comparison (order §5): the five pre-existing-failure batteries were
re-run at BASELINE `631f6fb` in a throwaway worktree (removed after) —
failure-name sets are IDENTICAL (set-diff verified, recorded in
SESSION_RUNNER_BASELINE_FLAKE.txt). Zero new regressions.

**Disclosed finding (not a regression — proven at baseline):** re-running
`python3 E10/run_e10rp2.py` inside a worktree whose
`E10/evidence_rp2/canonical/` committed evidence exists fails
NONDETERMINISTICALLY: the runner writes into the committed evidence dirs
without cleaning them and `find_mission_id = next(iterdir())` then picks a
STALE mission id (accumulated mission_controller dirs) → the event filter
matches nothing → `permission_errors=0` → check fails. Reproduced
IDENTICALLY at `631f6fb` WITHOUT any RP2.1 change (two consecutive baseline
runs failed different case subsets). The committed RP2 evidence itself was
restored bit-for-bit to its committed state after my battery probe (tracked
files via `git checkout HEAD -- E10/evidence_rp2/`, untracked run artifacts
removed); the battery records the session as the fresh-dir equivalent
exactly covering the same 9 scenarios.

## 6. Modified files & diff

7 source files (+546/−111), 3 new E10 harness/test files, evidence session:

| File | Change |
|---|---|
| `src/eoe/access_gateway.py` | `admit_grant_id(depth=None)` → honest `_actual_depth` from the actual path; new `admit_grant_kind` coarse gate; `_check(kind_only=…)`; explicit depth convention documented |
| `src/eoe/engine_bridge.py` | v2 dual-arity path-aware validator (`__path_aware__`), actual-path+depth full decision, bound-root first layer, no fixed depth |
| `src/unified/execution.py` | `_contained_write_target` + `_PATH_BEARING_TOOLS`; `_check_permissions(tool_input)` grounds the ACTUAL contained target for path-aware validators; governed-write entry containment re-check (before any journal record) |
| `src/unified/sandbox.py` | structural containment in `SandboxManager.write_artifact` (every writer) |
| `src/unified/windows_adapter.py` | structural containment in the filesystem adapter (last line; CW1-R1 docstring preserved) |
| `src/orchestrator/canonical.py` | task-bound `_resolve_current_file`/`_check_criteria_now` (structured results + `evidence_paths`); explicit `failure_class` in the verifier result; `run_verifier` catches execution crashes + fail-closes unprovable provenance; `_record_verifier_failure` class-driven (string heuristics deleted) |
| `src/unified/event_catalog.py` | `VerificationCompleteEvent.failure_class` + `evidence_paths` (optional, backward compatible) |
| `E10/e10rp21_scenarios.py` | NEW — 4 scenario modes with disclosed fault injections |
| `E10/test_e10rp21_matrix.py` | NEW — 24-test matrix (unit auth/collision + scenarios) |
| `E10/run_rp21_regressions.sh` | NEW — battery runner (exact commands + exits + tails) |
| `E10/E10_RP21_DISCOVERY.md` | NEW — D1–D7 proven at baseline before any change |
| `E10/evidence_rp21/` | NEW — BASELINE.md, REGRESSIONS_BRANCH.txt, SESSION_RUNNER_BASELINE_FLAKE.txt |

## 7. Acceptance conditions (order §6) — status

1. **Grant path/depth limits per explicit, tested contract on actual
   writes** — VERIFIED (§2 above; T03–T09).
2. **Each task's verifier uses its own task's evidence source; name
   collision cannot produce false verification** — VERIFIED (§3; T10–T12,
   T17; incl. the engine-layer first-match collision caught by the
   orchestrator layer).
3. **Verifier operational errors not classified as plan deviation** —
   VERIFIED (§4; T15, T16, T18, T19 — explicit class, never replan, never
   success).
4. **No `EVIDENCED` with a current unresolved verification failure** —
   VERIFIED (RP2 per-task latest-verdict rule re-proven in every RP2.1
   failing scenario: `current_unresolved_verification_failure`).
5. **main unchanged until new independent arbitration** — VERIFIED
   (live ls-remote at delivery: `main = 0a26fc70…`; nothing pushed to main;
   branch pushed from `631f6fb` only).

## 8. CLAIM / OBSERVED / VERIFIED / NOT PROVEN

- **VERIFIED** (re-examinable from committed evidence + live commands):
  everything in §1–§7 above.
- **CLAIM → OBSERVED:** "the operational write path now enforces
  path+depth on the actual target" — OBSERVED in the admission usage logs
  (actual sandbox paths, not the bare root) and the zero-side-effect
  inventories; "each verdict from the task's own file" — OBSERVED in the
  `evidence_paths` recorded in every verification artifact/event.
- **NOT PROVEN (honest boundaries, unchanged from RP2 unless noted):**
  1. No production API caller for the canonical path (D1 of RP2 stands).
  2. Replanning decision CONTENT remains a disclosed control input
     (the PATH is production; the content is scripted per scenario).
  3. Cross-process controller-state restore remains out of scope.
  4. GitHub CI remains unverifiable from this environment (every local
     battery above has its exact command + exit code recorded instead).
  5. NEW disclosed gap (D7): the ENGINE-layer verification
     (`Verifier._check_file_*`) matches the FIRST recorded artifact by
     relative path across ALL tasks' evidence — the same-name collision at
     the engine layer. It is CAUGHT by the (now task-bound) orchestrator
     verifier, but the engine layer itself remains un-fixed (out of the
     order's §2/§3 scope: it concerns recorded-artifact matching, not the
     verifier's on-disk resolution). Proposed as an RP2.2 candidate.
  6. NEW disclosed pre-existing flake: `run_e10rp2.py` is not idempotent
     w.r.t. its committed evidence dirs (proven at baseline; §5 above).
     Not fixed here (touching the RP2 harness was out of scope); the
     battery uses the fresh-dir equivalent.
  7. The engine's `write_file`/`edit_file` workspace tools remain outside
     the EOE grant model (pre-existing boundary; the order's §2 chain is
     the artifact_write governed path — no grant grounds the workspace
     root, so the bridge cannot map it; disclosed, unchanged).

## 9. Delivery

Branch `e10-rp21-auth-depth-task-verification` (from `631f6fb` only),
pushed WITHOUT force; `main` untouched. History: `631f6fb` ← this commit.
No factory-level refactor; no test-expectation weakened (RP2 matrix 22/22
on the same pre-registered expectations; RP2.1 expectations pre-registered
in `e10rp21_scenarios.py::EXPECTATIONS` before any passing run).

**Verdict: E10_RP21_PASS (CONDITIONAL — awaiting independent ratification;
branch NOT merged; main still `0a26fc70`).**
