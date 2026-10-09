# E10-RP2.2-R1 REPORT — FAIL-CLOSED PATH-AWARE VALIDATOR ENFORCEMENT

**Order:** E10-RP2.2-R1 (AUTHORIZED — targeted correction of the RP2.2
certification blocker)
**Execution baseline:** `6719fe371da3d7854cb612cfa64ef937c7d3d7b2`
(parent exactly `23ba93605a2ad6f8361453225eeef47002ef3eb6`)
**Branch (new):** `e10-rp22r1-path-aware-fail-closed` — derived from
`6719fe3` ONLY (merge-base proof in `E10/evidence_rp22r1/BASELINE.md`)
**Administrative decision honored:** no merge to `main`, no modification
or replacement of any accepted historical evidence.

---

## CLAIM / OBSERVED / VERIFIED / NOT PROVEN — summary ledger

| # | Statement | Status |
|---|---|---|
| 1 | No path-bearing tool can be authorized through a 2-arg validator or the coarse gateway alone | **VERIFIED** (probe F1 CLOSED + T01 6/6 + RP2.2 T18 updated) |
| 2 | An underivable concrete target never produces a fallback allow | **VERIFIED** (probe F2 CLOSED + T02; error path names the no-fallback rule; same grant then authorizes a derivable target) |
| 3 | No path disclosure or content read without a path-aware decision for each relevant path | **VERIFIED** (probe F4/F4b CLOSED + T03; `_path_disclosure_permitted` True-return deleted) |
| 4 | `admit_grant_kind(kind_only=True)` is never the FINAL decision for a concrete-path filesystem operation | **VERIFIED** (§2.3: `_check_permissions` structurally cannot reach the 2-arg branch for path tools; coarse form remains available only as preliminary/non-path tools) |
| 5 | The correct grant (scope+depth) still allows the authorized operation through the real EOE bridge + `AccessAdmission` | **VERIFIED** (T04: write/read/list/grep succeed; `grant.used` in ledger events; admission usage log carries the actual target) |
| 6 | Out-of-scope / out-of-depth grants are rejected for write, read AND exploration | **VERIFIED** (T05, incl. the honest exact-target-at-depth-0 boundary) |
| 7 | Rejections leave zero new side effects (files/folders/journal/events) | **VERIFIED** (T06 tree+journal+event snapshots identical; incl. after a prior allowed write under the same mission) |
| 8 | Full test battery is green | **NOT CLAIMED — FALSE BY RECORD**: 6 rows exit non-zero (pre-existing failures, failure-name sets IDENTICAL to baseline `6719fe3` — "no new regression proven in that comparison", which is NOT green) |
| 9 | Historical cleanliness of `e10rp21_work` at RP2.1 capture moment | **NOT PROVEN** (cause = high-confidence self-observation HYPOTHESIS; addendum `E10/evidence_rp21/BASELINE_CORRECTION_R1.md`) |
| 10 | `main` unchanged at `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` | **VERIFIED** (pre-work and post-delivery live `ls-remote`) |

---

## §1 — Hard baseline (before any modification)

All live-verified and recorded in `E10/evidence_rp22r1/BASELINE.md`:
origin/main == local main == `0a26fc70` (unchanged); baseline commit
`6719fe3` present with parent exactly `23ba936`; all six pre-existing
worktrees content-clean (raw porcelain: 0 entries each); new worktree
`/home/z/my-project/e10rp22r1_work` + branch
`e10-rp22r1-path-aware-fail-closed` created from `6719fe3` only
(merge-base == `6719fe3`). No `reset`/`clean`/`stash`/`restore` used
anywhere; the six original worktrees were never touched (re-verified
post-delivery, §6).

**Fail-open paths PROVEN BY EXECUTION at the baseline BEFORE any change**
(`E10/evidence_rp22r1/BASELINE_PROBE.txt`, probe preserved at
`/home/z/my-project/scripts/e10rp22r1_baseline_probe.py`):

- F1: legacy 2-arg permissive validator authorized an in-scope
  `write_file` through the real chain — FAIL_OPEN at baseline.
- F2: `artifact_write` with underivable target passed
  `_check_permissions` (decision degraded to the coarse 2-arg form) —
  FAIL_OPEN at baseline.
- F3: the bridge's 2-arg form terminates at `admit_grant_kind`
  (kind/scope only, no path/depth) — the coarse form existed as a
  reachable final decision for path tools.
- F4/F4b: `list_dir` disclosed every path under the workspace with a
  legacy validator; `_path_disclosure_permitted` returned True without a
  path-aware validator — FAIL_OPEN at baseline.

## §2 — The correction (source)

`src/unified/execution.py` — `ToolExecutor._check_permissions`:

1. **§2.1** For any tool in `_PATH_BEARING_TOOLS`, a validator without
   `__path_aware__` is REJECTED fail-closed (PermissionError, before any
   event/journal/side effect). The RP2.1/RP2.2 "legacy fixtures keep
   kind-level checks" acceptance is overruled by this order.
2. **§2.2** A path-bearing operation whose concrete contained target
   cannot be derived is REJECTED fail-closed. NO fallback to
   `grant_validator(grant_id, perm)` — even when the validator IS
   path-aware but cannot verify this operation's target.
3. **§2.3** The 2-arg branch of the decision loop is now reachable ONLY
   for tools WITHOUT a concrete path (git family, web, grants — the
   declared post-R1 boundary); §2.1/§2.2 structurally prevent any of the
   eleven path tools from reaching it. The coarse
   `admit_grant_kind(kind_only=True)` form of the bridge remains
   available as a preliminary condition only.
4. **§2.4** `_path_disclosure_permitted`: the `return True` on a missing
   / non-path-aware validator is DELETED (now `return False`) —
   exploration and disclosure fail closed; no contents read, no
   names/paths leaked outside policy.
5. **§2.5** The rule covers ALL ELEVEN tools (`artifact_write`,
   `write_artifact`, `artifact_read`, `read_artifact`, `read_file`,
   `write_file`, `edit_file`, `list_dir`, `grep`, `find_files`,
   `file_browser`) — the registry-level aliases
   (`write_artifact`/`read_artifact`) are additionally un-executable
   through the chain (no contract registered), and the rule is proven
   for their names via the direct gate call in T01.
6. **§2.6** No grant scope was expanded to pass tests; the real EOE
   verification was never replaced by a permissive test validator (every
   updated fixture wires the production bridge + an owner-approved grant
   over that test's OWN tree only).

## §2b — Fixture updates forced by §2.1 (disclosed, file-by-file)

The fail-closed rule intentionally breaks every fixture that drove
governed `artifact_write` through ToolExecutor with a permissive 2-arg
lambda (inventory + proof of ToolExecutor involvement in
`E10/E10_RP22R1_DISCOVERY.md`). All updated to the REAL EOE bridge
(`build_engine_grant_validator` on `AccessAdmission`) + an owner-approved
READ_WRITE PATH_GRANT over the test's own artifacts tree (default depth;
no scope expansion):

- `E10/e10_common.py` — new `build_grant_stack()`; `build_engine` now
  real-bridge + `grant_ids` (covers E10, CW1, CW1-R1 matrices + harnesses
  via the `e10cw1_common`/`e10cw1r1_common` re-exports)
- `E10/e10rp_common.py` — `build_engine` real-bridge (covers the E10-RP
  matrix via `run_e10rp.py`)
- `E10/e10rp1_cycle.py`, `E10/e10rp1_restore_probe.py`,
  `E10/test_e10rp1_matrix.py` (2 sites) — real-bridge (+ `grant_ids`)
- `E9-R/test_production_integration.py` — main flow + authorized-tool
  test real-bridge; the restrictive-validator NEGATIVE test keeps its
  2-arg validator BY DESIGN (its expected outcome is rejection, which
  §2.1 now guarantees even more strongly); the human-gate test is
  untouched (it drives `run_command`, a non-path coarse-boundary tool)
- `tests/orchestrator/test_e4_multi_task_mission.py` (8 sites),
  `tests/orchestrator/test_e6_durable_mission_orchestration.py` (11
  sites), `tests/unified/test_e33_mission_autonomy.py` (2),
  `tests/unified/e33_mission_runner.py` (1) — per-file `_granted()`
  helper, same real stack

**Intended behavior change inside a certified matrix (disclosed):**
RP2.2 matrix **T18** — its in-scope `write_file` assertion flipped from
"legacy validator succeeds" to "legacy validator rejected fail-closed
(path-aware error)". Its traversal/absolute-escape assertions still see
`WORKSPACE_CONTAINMENT_VIOLATION` (structural containment fires first
for escapes). This flip is exactly order §3.1.

## §3 — Binding tests (E10/test_e10rp22r1_matrix.py, 6 tests, all through the REAL chain)

- **T01 (§3.1)** non-path-aware 2-arg validator rejected for EVERY path
  tool — end-to-end for the 9 registry tools; the 2 unregistered aliases
  cannot execute at all (fail-closed "not registered") AND the rule is
  proven for their names via the actual `_check_permissions` method;
  the spy validator demonstrably answers True for the 2-arg form (the
  rejection is not explained by a denying validator).
- **T02 (§3.2)** underivable target (`sandbox_id=""` + context sandbox
  None; also `tool_input=None` direct gate call) rejected BEFORE any
  side effect, with the no-fallback error; the SAME grant authorizes a
  derivable target immediately after (the rejection is not a grant
  problem); zero files/journal/events.
- **T03 (§3.3)** all four exploration tools disclose and read NOTHING
  with a legacy validator AND with no validator; defense-in-depth
  `_path_disclosure_permitted` returns False for every path.
- **T04 (§3.4)** correct grant allows write/read/list/grep through the
  real bridge; `grant.used` recorded in ledger events; the admission
  usage log carries the ACTUAL target path.
- **T05 (§3.5)** out-of-scope grant rejected for write+read+exploration;
  `max_depth=0` grant rejects depth>0 write/read and discloses nothing
  inside; the exact-target-at-depth-0 boundary stays authorized (honest
  boundary, not over-rejection).
- **T06 (§3.6)** after a prior ALLOWED governed write (journal + events
  exist), a battery of rejections (out-of-scope, underivable target,
  traversal sandbox_id, legacy validator) leaves the file tree, journal
  and event history EXACTLY unchanged.

## §4 — Verification & regressions (exact commands + exits + tails in
`E10/evidence_rp22r1/REGRESSIONS_BRANCH.txt`; runner
`E10/run_rp22r1_regressions.sh`)

| Battery | Exit | Result |
|---|---|---|
| R1 matrix (new) | 0 | 6 passed |
| RP2.2 matrix | 0 | 22 passed (incl. updated T18) |
| RP2.1 matrix | 0 | 24 passed |
| RP2 matrix | 0 | 22 passed |
| RP2 session (fresh-dir, 9 scenarios) | 0 | 9/9 |
| RP1 matrix | 0 | 16 passed |
| E10-RP matrix | 0 | 23 passed |
| E10/CW1 matrix | 0 | 32 passed |
| E10-CW1-R1 matrix | 0 | 31 passed |
| E9-R | 0 | OVERALL PASS (real-bridge fixtures) |
| E8 negative gates | 0 | 4/4 REJECTED (expected) |
| vs001+vs002+vs003+vs004+e32e | **1** | pre-existing failures (vs003 env errors) |
| e3+e4 | **1** | 5F/4P/15S (pre-existing) |
| e6 | **1** | 4F/14P (pre-existing) |
| e33+e32f | **1** | 1F/1P/2S (pre-existing) |
| e35 | **1** | pre-existing |
| e37 | **1** | pre-existing |

**The battery is NOT green** (order §4.4): six rows exit non-zero.

**Two-state comparison** (`E10/evidence_rp22r1/TWO_STATE_BASELINE.json`,
script `/home/z/my-project/scripts/e10rp22r1_two_state.py`; throwaway
worktree at baseline `6719fe3`, removed after): every non-zero row re-run
at BOTH states — **exit codes AND failure-name sets IDENTICAL on all six
rows (OVERALL_TWO_STATE=0)** — "no new regression proven in that
comparison", which does NOT mean those rows are green. (Comparison
normalizes only the worktree path prefix in non-pytest traceback tails —
a location artifact, disclosed.)

`run_e10rp2.py` idempotency and the pre-existing e3/e4/e6/e35/e37
defects were NOT touched (order §4.5) — except the fixture rewiring in
§2b, which the direct change required.

## §5 — Historical baseline description correction

`E10/evidence_rp21/BASELINE_CORRECTION_R1.md` (new, dated; the historical
`BASELINE.md` and the RP2.2-era `BASELINE_CORRECTION.md` untouched
byte-for-byte): the cause of the `1 dirty entry` in the RP2.1 worktree is
recorded as a **high-confidence self-observation HYPOTHESIS — not a fully
proven fact** (the raw porcelain line and the original capture command
order were never retained); the cleanliness of `e10rp21_work` at the
historical capture moment is therefore **NOT PROVEN**. What remains proven
from the retained table: the four pre-existing worktrees were clean, and
no tracked file was modified anywhere.

## §6 — Delivery

- New commit on `e10-rp22r1-path-aware-fail-closed` (parent exactly
  `6719fe3`), pushed WITHOUT force to origin; **no merge, no push to
  `main`** (re-verified live post-push: `origin/main` still
  `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f`, all earlier phase branches
  unchanged).
- Files: 1 source file corrected (`src/unified/execution.py`,
  +63/-11 in the decision path), 11 fixture files updated to the real
  bridge, RP2.2 T18 updated (intended flip), new R1 matrix (6 tests),
  new regression runner, DISCOVERY, BASELINE + REGRESSIONS +
  TWO_STATE evidence, RP2.1 baseline-correction addendum.
- Windows-path debris (`C:/...`, created by the pre-existing e6/e37
  tests DURING the battery run — same class as every prior phase)
  removed before commit; not part of the delivery.

## Disclosed / NOT PROVEN (outside this correction's scope)

- **Pre-existing defect found and NOT fixed (order §4.5):**
  `_emit_artifact_created` (engine layer) crashes with
  `TypeError: join() ... NoneType` when `context.sandbox_id is None` and
  the artifact file is not at the artifacts root — the ToolExecutor then
  masks it as an output-validation failure. PROVEN identical at baseline
  `6719fe3` (same probe, same error) — fail-closed crash, NOT a security
  bypass; left for a future order.
- The bridge's coarse 2-arg form still exists (preliminary-only by
  construction now); git-family tools, `run_command`/`sandbox_execute`
  and the sandbox `execute()` lifecycle, and `agent_role._validate_grant`
  remain on the coarse gateway — the order's own post-R1 boundary
  (separate phase mandated).
- TOCTOU symlink race (theoretical, single-process tests) — as in RP2.2.
- Engine-layer `verify_task` first-match (RP2.1 D7) — stands as declared.
- `run_e10rp2.py` idempotency — pre-existing, untouched.
- No production API caller for CanonicalOrchestrator; replan decision
  content is a disclosed control input; cross-process controller-state
  restore NOT PROVEN; GitHub CI unverifiable from this environment.

## Acceptance criteria mapping

1. *No path tool accesses via a 2-arg validator or coarse gateway alone*
   — VERIFIED (§2.1/§2.3 + T01 + probes).
2. *Missing actual target never produces a fallback allow* — VERIFIED
   (§2.2 + T02).
3. *No disclosure/content read without a path-aware decision per relevant
   path* — VERIFIED (§2.4 + T03/T05).
4. *Test results documented honestly, successes separated from baseline
   failures* — VERIFIED (§4 table; two-state comparison; battery NOT
   called green).
5. *Unresolved historical cleanliness marked NOT PROVEN* — VERIFIED (§5
   addendum).
