# E10-RP2.2 — DELIVERY REPORT
## COMPLETE WORKSPACE TOOL AUTHORIZATION & CLEAN-BASELINE RECONCILIATION

**Status:** DELIVERED — awaiting independent ratification. **No merge to main.**

| Field | Value |
|---|---|
| Execution baseline | `23ba93605a2ad6f8361453225eeef47002ef3eb6` (E10-RP2.1) |
| Direct parent of delivery commit | `23ba93605a2ad6f8361453225eeef47002ef3eb6` (EXACT) |
| main baseline (untouched) | `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` |
| Branch | `e10-rp22-workspace-auth-clean-baseline` (new, derived from 23ba936 ONLY) |
| Worktree | `/home/z/my-project/e10rp22_work` (new; no original worktree touched) |
| Modified source files | `src/unified/execution.py`, `src/unified/tool_contract.py`, `src/unified/sandbox.py`, `src/unified/windows_adapter.py`, `src/eoe/engine_bridge.py`, `src/eoe/access_gateway.py` |
| New tests/evidence | `E10/test_e10rp22_matrix.py` (22 items), `E10/run_rp22_regressions.sh`, `E10/evidence_rp22/` (BASELINE, REGRESSIONS_BRANCH, TWO_STATE_BASELINE), `E10/evidence_rp21/BASELINE_CORRECTION.md`, `E10/E10_RP22_DISCOVERY.md`, this report |
| Diff size (source) | 6 files, +389/−88 |

Evidence index (all re-examinable in this branch):
- `E10/evidence_rp22/BASELINE.md` — live pre-modification baseline (raw porcelain lines, self-observation named explicitly)
- `E10/evidence_rp22/REGRESSIONS_BRANCH.txt` — full battery: exact commands, exit codes, raw output tails
- `E10/evidence_rp22/TWO_STATE_BASELINE.txt` — binary state comparison vs baseline 23ba936 for every non-zero row
- `E10/evidence_rp21/BASELINE_CORRECTION.md` — dated reconciliation of the RP2.1 baseline contradiction (old evidence NOT modified)

---

## §1 — HARD BASELINE / EVIDENCE INTEGRITY

- **CLAIM:** live verification of `origin/main`, current branch, direct parent, all worktree states; work started from `23ba936` only; original trees untouched; no `reset`/`clean`/`stash`/`restore` anywhere.
- **OBSERVED (pre-modification, recorded in `evidence_rp22/BASELINE.md`):** after a read-only `git fetch --prune`, `origin/main` = local `main` = `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f`; commit `23ba936` exists with parent exactly `631f6fbb`; the new worktree's HEAD = `23ba936` on the new branch with merge-base `23ba936`; all five pre-existing worktrees AND the new worktree: 0 porcelain entries (recorded RAW, per worktree, with HEADs).
- **VERIFIED:** every stop condition of the capture script was empty (`BASELINE_OK`). The evidence file itself records a second post-write porcelain pass that NAMES the single self-observation entry (`?? E10/evidence_rp22/`) explicitly — the RP2.1 ambiguity class cannot recur.
- **BASELINE CONTRADICTION RECONCILIATION (§1.4-§1.6):** the `e10rp21_work: 1 dirty entries` row is IDENTIFIED with high confidence as the RP2.1 capture process's own untracked evidence directory (`?? E10/evidence_rp21/`) — self-observation, not a source-tree modification; the four PRE-EXISTING worktrees were clean (VERIFIED in the same table). Supporting evidence: the count line is the last line of the file being written into that very worktree (capture stamp 19:02:14Z, file mtime 19:02:20); `.gitignore` excludes the plausible noise classes; porcelain collapses an untracked subdir to exactly one entry (mechanism reproduced in a throwaway worktree at 631f6fb, removed after); nothing else was ever left dirty (all evidence committed in 23ba936; current porcelain of `e10rp21_work` = 0). **NOT PROVEN (and declared as such in the correction):** the raw porcelain line at RP2.1 capture time (only the count was retained) and the RP2.1 capture command order (script not persisted). The old evidence file is byte-for-byte untouched; the correction is a NEW dated file. Baseline cleanliness of the four original trees: VERIFIED; of the new RP2.1 worktree: identified self-observation (not an unexplained contradiction).

## §2 — WORKSPACE-TOOL AUTHORIZATION BYPASS CLOSED

- **CLAIM:** no path-bearing tool ends at the coarse kind-only gate; `write_file`/`edit_file` present the actual normalized, contained target to the EOE grant decision with path + honest depth; read/exploration tools are governed per-path; structural containment (traversal/absolute/symlink) on every workspace target; OS-aware normalization (pathlib, not `startswith`); no allow-all validator in the operational path.
- **OBSERVED (implementation):**
  - `ToolExecutor._PATH_BEARING_TOOLS` now carries all ELEVEN file-access tools; `_WORKSPACE_PATH_TOOLS` marks the seven workspace tools; `_check_permissions` resolves each workspace target via the new `_contained_workspace_target` (resolve + `is_relative_to` on the workspace root) and hands the ACTUAL absolute path to the path-aware bridge validator (`admit_grant_id` with honest depth). `workspace_root` is never an implicit grant.
  - `_execute_filesystem_tool` re-proves containment at the execution layer (defense in depth) and gates every DISCLOSED path and every CONTENT read of `list_dir`/`grep`/`find_files`/`file_browser` through `_path_disclosure_permitted` (per-path grant decision; unauthorized paths are neither disclosed nor opened).
  - `build_engine_grant_validator(admission, artifacts_root, workspace_root=None)`: the engine containment universe is explicit (artifacts root ∪ wired workspace root), decided with `Path.is_relative_to` (the `startswith(root + "/")` string form is gone); backward compatible — 2-arg callers keep RP2.1 behavior.
  - `eoe.access_gateway`: PATH_GRANT coverage and honest depth now decided on normalized components (`PurePath`) — `_path_covers` — correct for the platform separator, case-insensitive on Windows, sibling-prefix paths sharing a string prefix are NOT covered.
  - `GrepInput` now declares `recursive: bool = True` and the grep branch no longer depends on another branch's import (discovery D4 — governed grep previously crashed on every call).
- **VERIFIED (tests `test_e10rp22_matrix.py`, all through the REAL `ToolExecutor.execute_tool` chain with REAL owner-approved EOE grants):** in-scope grant allows write/edit/read with the file on disk and the admission consulted on the actual target (T03); different-path grant rejects `write_file` AND `edit_file` with zero files/folders/journal/events (T04); artifacts-root grant does not authorize workspace writes and vice-versa (T05); traversal/absolute escapes rejected before ANY trace, parametrized ×4 (T06); symlink escapes rejected for read and write (T07); exploration roots out of scope rejected whole (T08); per-path disclosure under a depth-limited grant — deeper files never listed/found/browsed and grep never READS their content (T09); max_depth=0 discloses nothing inside (T10); exact depth boundary with the same grant (T11); missing grants/validator fail-closed for all seven tools (T12); legacy fixture validators still get STRUCTURAL containment (T18); gateway OS-aware coverage semantics (T19).
- **NOT PROVEN / disclosed boundaries:** legacy 2-arg validators carry no per-path policy — they remain kind-level-only for FIXTURES (the operational path wires only the bridge; RP2.1-accepted design, restated here for the record). Git-family tools and the sandbox lifecycle `execute()` remain coarse-gated/kind-gated (outside the order's enumerated §2.1 tool list) — disclosed in `E10_RP22_DISCOVERY.md` with the fail-closed mitigations that apply today.

## §3 — LOWER-LAYER ZERO-SIDE-EFFECT REJECTION

- **CLAIM:** in `SandboxManager.write_artifact` and `WindowsExecutorAdapter.write_artifact`, the sandbox_id validation AND the containment proof run BEFORE the sandbox directory creation and before any disk trace; direct calls with escaping targets are refused with zero new files AND zero new folders; reads are contained too.
- **OBSERVED (implementation):** both layers now (1) `validate_sandbox_id` — single structural component: separators, `.`/`..`, absolute/drive forms, whitespace, control bytes rejected (closes the D6 identity-join escape of the artifacts base); (2) containment proof on the resolved target; and only THEN (3) `os.makedirs`. `read_artifact` and `list_artifacts` at BOTH layers validate the id and prove read containment before any `open()`/walk (closes D7).
- **VERIFIED (direct legacy-caller simulation, T13-T15):** for `../../escape.txt`, an absolute path, and a symlink planted inside the sandbox root — at BOTH layers — every rejection leaves the artifacts tree byte-identical (full file+folder inventory compared before/after), a FRESH sandbox dir is never created on rejection (`sandbox-fresh` stays non-existent), no journal records appear; malformed sandbox_ids (`../evil`, `a/b`, `..`, `/abs`, `C:\x`, whitespace, empty) are refused before any disk effect with no escaped directory anywhere; direct reads with escaping paths are refused as containment violations (not `FileNotFoundError`), while legitimate direct reads still work.
- **NOT PROVEN:** TOCTOU between proof and write (single-process test scope — a symlink planted concurrently between check and effect is a theoretical race inherent to the check-then-act pattern and is not covered by this order).

## §4 — REQUIRED TESTS

All seven required categories are covered by `E10/test_e10rp22_matrix.py` (22 pytest items, exit 0):

| Order §4 requirement | Test |
|---|---|
| 1. correct-path grant allows in-scope write | T03 (write/edit/read + admission consulted on actual target) |
| 2. different-path grant rejects write_file+edit_file, zero traces | T04, T05 |
| 3. outside-workspace/traversal rejected before any trace | T06 (×4 parametrized), T07 (symlink), T11 (depth-3) |
| 4. read/exploration cannot exceed scope via the coarse gateway | T08 (root out of scope), T09 (per-path disclosure + content reads), T10 (max_depth=0) |
| 5. missing grant or validator blocks access fail-closed | T12 (all seven tools) |
| 6. direct lower-layer calls create not even a folder on rejection | T13, T14, T15 |
| 7. no general/historical permission state covers a different target | T16 (prior success + journal never covers new targets), T17 (revoked + expired grants) |

No tool had to be disabled: a correct permission contract was provided for all eleven tools (the §4 fallback was not needed).

## §5 — REGRESSION BATTERY

Full record: `E10/evidence_rp22/REGRESSIONS_BRANCH.txt` (exact commands, exit codes, raw tails). Summary (cwd = worktree root):

| Battery | Exit | Result |
|---|---|---|
| RP2.2 matrix (new) | 0 | 22 passed |
| RP2.1 matrix | 0 | 24 passed |
| RP2 matrix | 0 | 22 passed |
| RP2 session (fresh-dir equivalent, 9 scenarios) | 0 | 9/9 |
| RP1 matrix | 0 | 16 passed |
| E10-RP matrix | 0 | 23 passed |
| E10/CW1 matrix | 0 | 32 passed |
| E10-CW1-R1 matrix | 0 | 31 passed |
| E9-R | 0 | OVERALL PASS |
| E8 negative gates | 0 | 4/4 REJECTED |
| vs001+vs002+vs003+vs004+e32e (sandbox/execution layers — NEW row) | 1 | 40 passed, 11 skipped, 3 pre-existing errors |
| e3+e4 | 1 | 5F/4P/15S (pre-existing) |
| e6 | 1 | 4F/14P (pre-existing) |
| e33+e32f | 1 | 1F/1P/2S (pre-existing) |
| e35 | 1 | pre-existing |
| e37 | 1 | pre-existing |

**Two-state comparison (`evidence_rp22/TWO_STATE_BASELINE.txt`):** every non-zero row was re-run at BASELINE `23ba936` in a throwaway worktree (removed after): exit codes AND failure-name sets IDENTICAL on all six rows (`OVERALL_TWO_STATE=0`) — the vs-row's 3 errors are `ModuleNotFoundError: core.substrate` (missing Linux substrate module, environmental) and the e3/e4/e6/e33/e35/e37 failures are the same pre-existing sets RP2.1 already documented. **ZERO new regressions, ZERO masked failures.** No test is called green without a recorded exit code.

**`run_e10rp2.py` idempotency:** NOT fixed (pre-existing, proven identical at 631f6fb in RP2.1) — left NOT PROVEN by scope decision per order §5 last paragraph; the fresh-dir session equivalent remains the recorded coverage. No certified directory was overwritten silently.

## §6 — ACCEPTANCE CRITERIA

1. **No workspace path-bearing tool can exceed grant scope/depth via the coarse gateway — VERIFIED** (all eleven tools ground the actual path; T01-T12; the coarse form remains only as the bridge's explicit separate API, never the final decision for a path-bearing tool).
2. **No write or read outside the authorized path — VERIFIED** for the eleven file-access tools and both sandbox layers (T03-T15); disclosed boundaries: git-family tools, sandbox lifecycle `execute()`, legacy fixture validators (kind-level only, fixtures).
3. **Rejection leaves no file, folder, or journal record — VERIFIED** (T04, T06, T13, T14: full tree inventories + journal + events compared).
4. **Baseline-evidence contradiction resolved or explicitly NOT PROVEN — RESOLVED with declared limits**: entry identified as the RP2.1 capture process's own evidence directory (self-observation), correction added as a NEW dated file (`evidence_rp21/BASELINE_CORRECTION.md`), old evidence untouched; the two evidentiary gaps (raw porcelain line, capture command order) are explicitly declared NOT PROVEN inside the correction.
5. **New tests and affected matrices documented with actual results — VERIFIED** (§5 table + raw record files).
6. **main remains at baseline — VERIFIED** (`0a26fc70ce13e69932db7fe54c810fcbf0f99d3f`, local + remote, re-checked at delivery; branch pushed WITHOUT force; no merge).

## Honest limits of this delivery (NOT PROVEN / out of scope)

- Cross-process controller restore; production API caller for `CanonicalOrchestrator`; replan decision content as a control input (unchanged, still disclosed from RP2.1).
- Engine-layer `verify_task` first-path-match across tasks (RP2.1 D7) — disclosed, unchanged, caught by the task-bound verifier.
- TOCTOU symlink race between proof and effect (theoretical, single-process tests).
- Git-family tools and sandbox lifecycle `execute()` remain kind-gated/coarse — disclosed as the next boundary candidates with today's fail-closed mitigations.
- GitHub CI: no workflow runs exist for this commit tree; all evidence is local commands + exit codes + raw outputs (recorded).
