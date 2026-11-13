# TRUSTED_SUITE_FAILURE_ANALYSIS — AES-P0-CONTAINMENT-PR-REMEDIATION-1113-R1 (fix 7 + §10)

## 1. The failing runs examined (OBSERVED — logs downloaded via API)

| Run | Event | SHA | Result | Duration |
|---|---|---|---|---|
| `43394921919` | push (branch) | `1adfaf1` | Trusted suite step: **failure** after successful checkout / setup-python / bubblewrap / install | 24:49 |
| `43394927622` | pull_request #4 | `1adfaf1` | Trusted suite step: **failure**, same place | 25:20 |
| `43404020521` | workflow_dispatch on `main` (baseline, created by R1; no changes to main) | `9d77a79` | Trusted suite step: **failure**, same place | 25:11 |

All three: `22 failed, 243 passed, 14 skipped`. The 16 failure IDs visible in each log (the `| tail -40` truncation hid the other 6 — see §5) are **byte-identical across all three runs** (VERIFIED by set-diff of the extracted `FAILED` lines).

After the R1 push (commit `cda8cf0`, runs `43407564302`/`43407569994`/`43407564140`/`43407569854`): `secret-guard` **succeeded** on both events, and the trusted suite reported `22 failed / 279 passed / 14 skipped` — the same 22 pre-existing failures (now with the **complete list printed**), plus the 36 new `tests/security` tests **all passing** in CI. No new failure was introduced.

## 2. Which tests fail (OBSERVED from logs; classes)

Visible 16 failure IDs (of 22):

| Area | Tests | Count |
|---|---|---|
| Live task cycle | `tests/api/test_task_live.py::test_task_live_cycle_passes_and_persists_conversation`, `::test_task_each_role_receives_its_own_provider_and_model` | 2 |
| UI structure (order006) | `test_plus_button_and_menu_present`, `test_send_button_visually_right_of_input_in_rtl`, `test_sidebar_with_real_conversations`, `test_settings_drawer_with_role_model_config`, `test_task_settings_bar_above_composer`, `test_no_internal_names_in_primary_ui`, `test_versioned_assets_and_new_modules`, `test_mode_chip_shows_current_selection` | 8 |
| UI structure (order010) | `test_settings_tabs_six_sections`, `test_error_boundary_present_and_wired` | 2 |
| UI asset versioning (011) | `test_index_serves_current_version_urls_not_stale_literal`, `test_index_etag_version_derived_and_conditional` | 2 |
| UI tokens (014) | `test_t1_canonical_token_values_locked`, `test_t4_g7_zero_letter_spacing_on_arabic` | 2 |

The 6 formerly-hidden failures (now enumerated by the fixed workflow on the R1 commit — OBSERVED):

- `tests/api/test_control_actions_0134.py::test_final_stop_is_durable_and_preserves_everything`
- `tests/api/test_control_actions_0134.py::test_pause_and_resume_same_durable_job`
- `tests/api/test_executor_no_starvation.py::test_preflight_blocked_run_terminates_and_releases_runner`
- `tests/api/test_projects_api.py::test_run_stream_completes_project`
- `tests/api/test_projects_api.py::test_sub_resources_exposed`
- `tests/core/test_stop_api.py::test_cycle_status_finished_shape`

These are earlier in pytest's summary order than the visible 16 — that is exactly why `tail -40` cut them.

## 3. Causes

### 3a. The 14 UI failures — tests/UI divergence (VERIFIED by git archaeology + repo scan)

- `src/ui/index.html` at `9d77a79`/`1adfaf1` (86 KB, AES-UI-v4 "قاعة تحكم المصنع") contains **none** of the asserted markers: `id="plus"`, `id="sidebar"`, `id="settings-drawer"`, `id="mode-chip"`, `id="error-boundary"`, `data-tab="general"`, `id="task-settings"`, `?v=807a9396` (OBSERVED: grep counts = 0).
- Marker history (OBSERVED via `git log -S`): the order006 DOM markers were introduced with `ccd9621` (2026-09-21). The last commit where they existed in `src/ui/index.html` is `d5dfac0^` (26,862-byte file, `id="plus"` count = 1). Commit `d5dfac0` (2026-11-11, "تثبيت قاعة التحكم المنشورة في المستودع" — pinning the **deployed** control-room UI into the repo, 84,778 bytes) **removed** them; the deployed UI simply does not contain that DOM. `9d77a79` (FACTORY MONO 1112) then rewrote colors only.
- Conclusion (INFERRED from the above): the tests encode the order006/010/011/014-era DOM; the repository UI was replaced by the deployed one in `d5dfac0` without updating those tests. This is the same family as the already-documented **server-vs-Git UI drift**; repairing tests or UI is explicitly out of R1 scope (owner decision, tied to the later UI-unification track).

### 3b. The 2 live-cycle failures (OBSERVED locally at both SHAs)

`test_task_live` drives a full live cycle; on a CI runner without live model backing the cycle ends `HARD STOP` (messages: "الحالة النهائية FAILED — الدورة لم تكتمل أدلةً", "مهام فاشلة: T1"). Reproduced locally at **both** SHAs with identical failure output — i.e. not PR-dependent, and not a bwrap-availability differentiator (bubblewrap was installed in CI and the tests still failed).

## 4. Baseline reconciliation — is it a PR regression? (VERIFIED: NO)

Ordered comparison, same workflow, same runner image, only the SHA differs:

| SHA | Relationship | Result |
|---|---|---|
| `9d77a79` — base of PR #4 (run `43404020521`, dispatched on main; main itself was not modified) | baseline | `22 failed, 243 passed, 14 skipped` |
| `1adfaf1` — PR #4 head (runs `43394921919`, `43394927622`) | PR | `22 failed, 243 passed, 14 skipped`, failure IDs identical to baseline |

Local cross-check (same venv, no editable install, src via pytest `pythonpath`): the failing subset (14 UI + 2 task_live + 1 stop_api = 17 tests) produced **identical failure sets at both SHAs** (`r1_compare_shas.sh`, 2026-11-13).

Code-path check (VERIFIED): the PR commit `1adfaf1` touches only `.github/workflows/secret-guard.yml`, `.secretguard-allow`, `scripts/ops/secret_guard.py`, `scripts/ops/w2t25_audit_check.py`, `w2t25-monitor-v2/*` — none of which are imported by any failing test.

**Classification: the trusted-suite failure is PRE-EXISTING AT BASELINE (`9d77a79`) — not a regression caused by PR #4, and not a runner/environment artifact.**

## 5. CI-history context (OBSERVED via Actions API)

The trusted suite has failed on **every** run since 2026-10-24T05:52 UTC across all branches (20 consecutive red runs before PR #4); the last green run was `40063480742` (`c9f3cdfdde`, aes-exp-04-execution-recovery, 2026-10-24T04:43). No trusted-suite run existed on `main` before R1 because the workflow's push trigger ignores `main` — that gap is why the baseline had to be dispatched explicitly.

## 6. Workflow repair shipped on this branch (OBSERVED in diff)

- `tests/security` (36 new tests) is now part of the trusted suite.
- `| tail -40` removed — the complete failure list is printed; `set -o pipefail` retained so the exit code remains the tests' own.

## 7. Mandatory-check policy — what a workflow can and cannot do (§10; OBSERVED state, nothing changed)

Three different guarantees, often confused:

1. **A workflow that scans on push/PR** (what secret-guard is): detects a violation *after* it has been pushed; it can fail a run and draw attention, but it cannot stop the push, and it cannot stop a merge by itself.
2. **A required status check** (merge-blocking): configured in branch protection ("require status checks to pass before merging"); a PR cannot merge while the check fails. This is what would make `secret-guard` actually gate PR #4-style merges.
3. **Branch protection against direct pushes**: disallows unreviewed direct pushes to `main` altogether; without it, anyone with push access can commit a credential straight to `main` — the workflow would then only report it after the fact.

Current state (OBSERVED 2026-11-13, via API with the repo's push-capable token):
- `GET /repos/…/branches/main/protection` → **404 "Branch not protected"**.
- `GET /repos/…/rulesets` → `[]` (no rulesets).

Therefore: **secret-guard does NOT currently prevent a credential from entering `main` by direct push.** Making it merge-blocking (required check + branch protection) is an owner administrative decision; per the R1 command, no protection setting was changed in this task.

## 8. Evidence classes

- Failure lists of the three runs: OBSERVED (downloaded logs, sanitized copies in the R1 evidence bundle).
- Pre-existing-at-baseline verdict: VERIFIED (baseline dispatched run + local both-SHA comparison + code-path analysis).
- UI divergence root cause: VERIFIED (git archaeology: `id="plus"` 1→0 across `d5dfac0`; tests still assert it) — the *decision* on which side to fix is INFERRED/deferred to the owner.
- Live-cycle cause (no model backing on runners): INFERRED from the deterministic HARD STOP at both SHAs and environments.
