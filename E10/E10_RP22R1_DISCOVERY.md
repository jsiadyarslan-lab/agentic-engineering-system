# E10-RP2.2-R1 — DISCOVERY (fail-open authorization paths at baseline 6719fe3)

Order: E10-RP2.2-R1 (AUTHORIZED — targeted correction of the RP2.2
certification blocker: fail-closed path-aware validator enforcement).

Baseline: `6719fe371da3d7854cb612cfa64ef937c7d3d7b2` (parent exactly
`23ba93605a2ad6f8361453225eeef47002ef3eb6`), branch
`e10-rp22r1-path-aware-fail-closed` derived from it ONLY.

Every finding below is PROVEN BY EXECUTION at the baseline tree before any
modification (raw probe output: `E10/evidence_rp22r1/BASELINE_PROBE.txt`,
probe script preserved at `scripts/e10rp22r1_baseline_probe.py` in the
session workspace). No finding rests on source reading alone.

## F1 (order §2.1) — non-path-aware validator is a FINAL decision for path tools

`ToolExecutor._check_permissions` (src/unified/execution.py) resolves the
concrete target for `_PATH_BEARING_TOOLS`, but the decision loop then
branches: `if path_aware and actual_target is not None: validator(gid,
perm, actual_target)` **`elif validator(gid, perm)`** — with a legacy 2-arg
validator (`__path_aware__` absent) the SECOND branch is the final
decision. PROVEN: `write_file` (in-scope path, permissive
`lambda g, p: True`) SUCCEEDS through the real `execute_tool` chain and the
file lands on disk (`PROBE/F1_legacy_validator_write_file_succeeds/FAIL_OPEN`).
This is exactly the behavior RP2.2 matrix T18 codified ("legacy validator
still structurally contained" asserted `ok["success"] is True`) — the
RP2.1/RP2.2 "fixtures only, never operational" acceptance is now OVERRULED
by order §2.1/§3.1: a non-path-aware validator must be REJECTED for every
path-bearing tool even when its 2-arg form returns True.

## F2 (order §2.2) — underivable target degrades to the coarse gateway

For the artifact family, `actual_target` is derived only when
`sandbox_id and rel_path` are truthy; otherwise `actual_target` stays
`None` and the decision loop falls to the same 2-arg branch — **even with
a path-aware validator**. PROVEN: with the REAL EOE bridge and a valid
grant, `artifact_write` with `sandbox_id=""` and `context.sandbox_id=None`
passes `_check_permissions` without rejection
(`PROBE/F2_underivable_target_not_rejected/FAIL_OPEN`) — the authorization
degraded to `admit_grant_kind` (kind/scope only, no path, no depth).
(Through the full `execute_tool` chain the input schema normally forces a
non-empty `sandbox_id`, but the gate itself must be structurally
fail-closed — order §2.2 requires rejection with NO fallback, not
"usually saved by a schema".)

## F3 (order §2.3) — the bridge's 2-arg form ends at the coarse kind gate

`eoe.engine_bridge.build_engine_grant_validator`'s 2-arg form calls
`admission.admit_grant_kind(grant_id, write=...)` (internally
`_admit(kind_only=True)`) and returns True with NO path and NO depth in
the decision. PROVEN: `PROBE/F3_bridge_two_arg_form_coarse_only/FAIL_OPEN`.
The coarse form is legitimate as a PRELIMINARY condition (signature /
validity / scope) but must never be the FINAL decision for a concrete-path
filesystem operation. After §2.1/§2.2 enforcement the engine's
`_check_permissions` never takes the 2-arg branch for path-bearing tools,
so the coarse gate can no longer terminate a path-tool decision; it
remains available for the non-path tools (git family, web, grant) — the
declared post-R1 boundary.

## F4 (order §2.4) — exploration/disclosure is fail-OPEN without a path-aware policy

`_path_disclosure_permitted` returns **`True`** when
`validator is None or not __path_aware__` — i.e. with a legacy validator,
`list_dir` / `grep` / `find_files` / `file_browser` disclose EVERY path
under the (structurally contained) workspace and grep reads every file's
content, with zero per-path grant decisions. PROVEN:
`PROBE/F4_list_dir_discloses_all_with_legacy_validator/FAIL_OPEN` and
`PROBE/F4b_disclosure_permitted_true_without_path_aware/FAIL_OPEN`.
Order §2.4: delete the `True` return; exploration must be rejected
fail-closed, disclosing neither contents nor names/paths outside policy.

## Blast radius (fixtures that relied on F1)

Governed `artifact_write` through the REAL ToolExecutor chain with a
permissive 2-arg fixture validator — every site below BREAKS once §2.1 is
enforced (by design; each is updated to the REAL EOE bridge + an
owner-approved grant covering only that test's own artifacts tree — no
scope expansion, no permissive substitute validator, order §2.6):

| File | Sites | Consumers |
|---|---|---|
| `E10/e10_common.py` `build_engine` | 1 | E10, CW1, CW1-R1 matrices + harnesses (re-exported by `e10cw1_common`, `e10cw1r1_common`) |
| `E10/e10rp_common.py` `build_engine` | 1 | E10-RP matrix (via `run_e10rp.py` subprocess) |
| `E10/e10rp1_cycle.py` (canonical orchestrator) | 1 | `run_e10rp1.py` durable cycle |
| `E10/e10rp1_restore_probe.py` | 1 | fresh-process restore probe |
| `E10/test_e10rp1_matrix.py` | 2 | RP1 matrix in-process probes |
| `E9-R/test_production_integration.py` | 2 of 3 | main flow (line 57) + authorized-tool test (line 283); the restrictive-validator negative test (line 239) KEEPS its 2-arg validator — its expected outcome is rejection, which §2.1 now guarantees even more strongly |
| `tests/orchestrator/test_e4_multi_task_mission.py` | 9 | e4 battery |
| `tests/orchestrator/test_e6_durable_mission_orchestration.py` | 13 | e6 battery |
| `tests/unified/test_e33_mission_autonomy.py` | 2 | e33 battery |
| `tests/unified/e33_mission_runner.py` | 1 | e33 cross-runtime runner |

NOT affected (verified — no ToolExecutor path-tool involvement):
`vs001` (MockGrantValidator feeds a directly-constructed SandboxManager,
never ToolExecutor), `vs002` (engine-level `execute_tool` with
`run_command` — the sandbox-lifecycle coarse boundary, declared post-R1),
`vs003`, `vs004`, `e32e`, `e32f`, `e3`, `e35`, `e37`, and the RP2 / RP2.1 /
RP2.2 harnesses (already real-bridge wired).

Also updated BY THE ORDER ITSELF (intended behavior change, §3.1):
RP2.2 matrix **T18** — its in-scope `write_file` assertion flips from
"legacy validator succeeds" to "legacy validator rejected fail-closed";
its traversal/absolute-escape assertions keep seeing
`WORKSPACE_CONTAINMENT_VIOLATION` (structural containment still fires
first for escapes).

## Out of scope (declared, untouched)

- Git-family tools (`git_branch`/`git_commit`/`git_diff`/`git_status`/
  `git_push`) and the sandbox lifecycle (`run_command`/`sandbox_execute`,
  `SandboxManager.execute` grants, `agent_role._validate_grant`) remain on
  the coarse gateway — the order's own "post RP2.2-R1" boundary; a
  separate phase is mandated for them.
- `run_e10rp2.py` idempotency and the pre-existing e3/e4/e6/e35/e37
  defects: untouched unless the direct change requires otherwise.
- D7 engine-layer verify_task first-match (RP2.1 disclosure, stands).
