# E10-RP2.2-R2 — GIT & SANDBOX LIFECYCLE AUTHORIZATION HARDENING — EXECUTION REPORT

Order: E10-RP2.2-R2 (AUTHORIZED WITH AMENDMENTS; MERGE HOLD ACTIVE).
Execution branch: `e10-rp22r2-git-sandbox-hardening` (worktree
`/home/z/my-project/e10rp22r2x_work`), derived from the designated
baseline `0945960427e833522789903e87a64b73c207bccd` ONLY (parent exactly
`6719fe37...`; merge-base proof in `evidence_rp22r2/BASELINE.md` B5).
The discovery branch `dbe28da` was NOT used for execution (order §1.1).

`main` remains `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` (verified live
after delivery). No merge, no reset/clean/stash/restore, no force-push;
historical worktrees and evidence untouched.

Everything marked VERIFIED below is proven BY EXECUTION with saved raw
outputs: the binding matrix `E10/test_e10rp22r2_matrix.py` (19/19 exit 0),
the re-run of the original 15 discovery probes
(`evidence_rp22r2/probe_outputs_postfix/`, verdict mapping in
`evidence_rp22r2/POSTFIX_PROBE_VERDICTS.md`), the full regression battery
(`evidence_rp22r2/REGRESSIONS_BRANCH.txt`), and the two-state comparison
at the baseline (`evidence_rp22r2/TWO_STATE_BASELINE.json`,
OVERALL_TWO_STATE=0).

---

## 0. Delivery inventory

| Artifact | Content |
|---|---|
| `src/unified/execution.py` | §2/§3 fixes: subprocess import (DF1), `_REPO_GROUNDED_TOOLS` + `_ground_repo_root`, git grounding in `_check_permissions`, human-gate fail-closed + action-scoped approvals (`_gate_input_digest`), DF2 output-validation fix, git_push nonce/registry/force path, engine `push_approval_registry` wiring, git handler output `success` fields (DF5) |
| `src/eoe/push_engine.py` | §3.4/§3.5: `PushApproval` extended with `remote`/`force` (inside the signed payload), `OwnerApprovalService.sign` scope params, NEW `PushApprovalRegistry` (nonce→record lookup, signature+TTL, repo/remote/branch/commit/force scope, single-use consume) |
| `src/substrate/windows_executor.py` | DF4 fix: duplicated UNGUARDED `import win32pipe...` debris block removed (made `substrate` and `eoe.push_engine` UNIMPORTABLE on Linux) |
| `src/unified/sandbox.py` | §4.1/§4.2: `validate_sandbox_id` + EMPTY_GRANT_IDS rejection at `SandboxManager.execute` |
| `src/unified/windows_adapter.py` | §4.2/§4.3: sandbox_id validated before join/makedirs; host-subprocess fallback = explicit declared degraded mode, refused by default |
| `src/unified/agent_role.py` | §4.5: `_run_in_sandbox` disabled fail-closed |
| `src/unified/tool_contract.py` | §4.4: `sandbox_execute` removed from the registry (dormant definition kept, documented) |
| `E10/test_e10rp22r2_matrix.py` | Binding matrix R2-T01..T11 (T07 parametrized ×9 = 19 tests) |
| `E10/e10rp22r2_probes{,_lib}.py`, `E10/run_rp22r2_probes.sh` | The ORIGINAL discovery probes (copied byte-identical from `dbe28da`) + parameterized runner |
| `E10/run_rp22r2_regressions.sh`, `E10/e10rp22r2_twostate_compare.py` | Battery + two-state comparison tooling |
| `E10/evidence_rp22r2/` | BASELINE.md, probe_outputs_postfix/ (15×3 raw), POSTFIX_PROBE_VERDICTS.md, REGRESSIONS_BRANCH.txt, TWO_STATE_BASELINE.json |

Diff vs baseline: 7 production files (+545/−142) + new discovery/test
evidence files. No historical file modified.

---

## 1. Order §2 — shared execution gates (all VERIFIED)

**§2.1 human-gate fail-closed on mission-lookup miss (GAP-5).**
`_check_human_gate` now RAISES `PermissionError` ("...mission ... is not
registered in the engine — refused fail-closed") instead of silently
returning. VERIFIED end-to-end: run_command (HIGH) and git_push
(CRITICAL) with a ghost mission are rejected with ZERO events/actions
(matrix T04 leg 2, T11; probes X1/O1 raw outputs). The registered-mission
gate behavior is preserved (T04 leg 1; E9-R human-gate test still PASS).

**§2.2 action-scoped approval binding.** Gate creation now records a
canonical input digest (`_gate_input_digest`, sorted-key JSON sha256); an
approved gate authorizes ONLY the same tool AND the same input payload.
The mission-wide "any approved gate for this tool name" carry-over is
CLOSED: a different input (T04 leg 4) and a legacy approval record with
no digest (T04 leg 5) both require a NEW gate decision. The same-input
retry after a REAL approval passes the gate (T04 leg 3, T05 full-chain
leg) — the E9-R approve-and-resume flow is preserved (E9-R row green).
For git_push this binds the approval to the push operation itself
(repo/remote/branch/force/nonce are all inside the digested input) —
order §3.5.

**§2.3 DF2 — no error masking.** Output validation is skipped for
`output=None` results; a failed result's ORIGINAL error is never
overwritten. VERIFIED through the full real chain: `web_search` on a real
READ grant fails in its handler and surfaces "Network access denied..."
with `error_type=NetworkDeniedError` — NOT "Output validation failed
... NoneType" (T09 leg 1); the git_push nonce requirement surfaces
verbatim (T09 leg 2); the unregistered `sandbox_execute` ValueError
surfaces directly (T08; probe X2 post-fix).

## 2. Order §3 — git family: DF1 fix + authorization in ONE change (VERIFIED)

**§3.1 DF1.** `import subprocess` added to `src/unified/execution.py` IN
THE SAME COMMIT as the authorization grounding — never shipped alone. The
git family is now EXECUTABLE: positive legs through the real bridge
actually run git (T01: `git_status`/`git_diff` succeed and return real
output; T02: `git_branch create` creates a real branch).

**§3.2 target grounding.** NEW `_REPO_GROUNDED_TOOLS` (all five git
tools) + `_ground_repo_root`: `repo_path` is resolved (relative against
`workspace_root`), the REPO ROOT is derived STRUCTURALLY (bounded walk-up
to a `.git` marker — NO git subprocess before the authorization decision),
and both the candidate and the repo root are proven contained inside the
workspace universe (pathlib, not string prefixes). The repo root is
presented to the path-aware validator as the operation's concrete target.
Underivable ("not inside a git repository"), out-of-universe ("resolves
outside the workspace universe"), and out-of-scope ("not covered by any
presented grant") targets are all rejected fail-closed with NO fallback
to the coarse kind gate — the R1 post-phase boundary for the git family
is CLOSED. A non-path-aware (legacy 2-arg) validator is rejected for
every git tool (T01/T02; probes G2/G6 post-fix). Authorization and
implementation share the SAME grounding helper, so they can never
disagree about the target.

**§3.3 permission mapping.** The contracts already map
git_status/git_diff→read and git_branch/git_commit→write; the grounding
makes the mapping a REAL path-scoped decision: a READ-scope grant
authorizes status/diff on the in-scope repo but NEVER branch/commit (T02
leg 1-2); a read_write grant over treeA authorizes branch/commit inside
treeA but nothing on repoB (T02 leg 3-4).

**§3.4-§3.6 git_push — fail-closed until a verifiable owner approval.**
git_push requires write+admin; under the REAL EOE bridge `admin` is
unattainable, so push is rejected at the permission layer (SEC-3
preserved; T03 leg a — fake nonce + ghost mission, zero remote effects,
zero trace). The owner-approval mechanism is the REAL EOE one
(`eoe.push_engine`): the `owner_approval_nonce` is verified through the
NEW `PushApprovalRegistry` against a signed record
(`OwnerApprovalService` HMAC + TTL) bound to repository, remote, branch,
commit_sha (the repo's CURRENT HEAD — the owner approved pushing THIS
commit), and the force flag, consumed single-use via the `NonceLedger`
(plus registry burn). VERIFIED at the registry level (T03 leg b: fake /
reused / wrong-remote / wrong-branch / wrong-commit / force-mismatch /
expired nonces ALL rejected; exactly one correctly-scoped approval
accepted once) and at the handler level (T03 leg c: no registry wired →
"git_push disabled fail-closed: no owner-approval registry is wired"
— order §3.6; a valid scoped approval → the push really lands on a local
bare remote; a NON-force push of a diverged history is rejected by git
and only a force-scoped approval with force=True pushes — §3.5 force
semantics FIXED: `--force` is actually passed and is part of the approval
scope). `force` is implemented (not removed) and no longer silently
ignored.

**Two additional pre-existing defects in the same cluster, fixed because
the DF1 fix ACTIVATES the git family (they were unreachable at baseline):**

* **DF4** — `src/substrate/windows_executor.py` carried a duplicated
  UNGUARDED `import win32pipe ...` block at module end: the ENTIRE
  `substrate` package — and with it `eoe.push_engine`, the REAL
  owner-approval mechanism — was UNIMPORTABLE on any non-Windows host.
  The debris block is removed (everything it provided exists at the top
  of the module or in the guarded pywin32 block). This fix is REQUIRED by
  §3.4 (the approval records must be wireable at all).
* **DF5** — the git handlers' output dicts never carried the mandatory
  base-schema `success` field: with DF1 fixed, every successful git call
  would have been marked FAILED by output validation (the defect was
  invisible while the tools were dead). All five handlers now emit
  contract-conforming outputs (proven by every positive leg).

## 3. Order §4 — sandbox & command-execution paths (all VERIFIED)

**§4.1 empty `required_grant_ids`.** `SandboxManager.execute` rejects an
empty list (`EMPTY_GRANT_IDS` SandboxError) — the bypass is closed for
EVERY caller class: direct (T06), agent (T10), and the operational
parallel path (T06 leg 3 / T10 leg 2: the operational agents' run_command
now fails closed with EMPTY_GRANT_IDS — probe O1 post-fix shows
`success=False`). Rejections leave zero directories and zero lifecycle
entries. No tool-contract exception to the grant requirement was declared
(none exists), so the refusal is uniform.

**§4.2 sandbox_id before any join/makedirs.** `validate_sandbox_id` now
runs FIRST in BOTH `SandboxManager.execute` and
`WindowsExecutorAdapter.execute` (the adapter already imported it; it was
simply never called on this path). Traversal/separator/absolute/whitespace
ids are rejected with ZERO directories created inside OR outside the
artifacts base (T07 ×9 forms, snapshot-proven; probe S2 post-fix:
"directory OUTSIDE artifacts base created: False"). Parity with
write/read/list (RP2.2 §3.1) preserved (T07 last leg).

**§4.3 no unisolated host subprocess as a safe sandbox.** The
`WindowsExecutorAdapter` subprocess fallback is now an EXPLICITLY-DECLARED
DEGRADED MODE: `allow_host_subprocess_fallback` (constructor flag,
default **False**). With no isolation-proving backend available (pywin32
absent here) `execute()` raises `SandboxUnavailableError`
(HOST_SUBPROCESS_FALLBACK_DISABLED) BEFORE makedirs (T05: marker file
never written, zero tree delta). The degraded mode executes only when
explicitly opted in at construction (T05 leg 2 — the declared mode works
and is the ONLY leg that wrote the marker). Full-chain proof: past the
permission layer AND an approved action-scoped gate, run_command is still
refused at the execution layer (T05 full-chain leg) — no host subprocess
anywhere by default.

**§4.4 sandbox_execute removed.** The contract is out of
`ALL_TOOL_CONTRACTS`; a call now fails at contract lookup
("Tool not registered: sandbox_execute") BEFORE any event/action/side
effect (T08; probe X2 post-fix surfaces the true error — no DF2 masking).
The engine's `_populate_tool_registry` VERIFIES its absence (an
accidental re-registration raises), and the dormant contract definition
is kept documented for a future implementing order.

**§4.5 parallel paths closed.** `_run_in_sandbox` raises fail-closed
(RuntimeError, §4.5 citation) regardless of wiring (T10; probe A2
post-fix); the operational agents' direct `sandbox_manager.execute` calls
are refused at the manager via §4.1 (T06/T10; probe O1 post-fix).

**§4.6 declaration discipline.** With §4.1-§4.5 in place there is NO
remaining in-repo path that reaches command execution without a grant
decision, a (registered-mission) gate where required, and an
isolation-proving or explicitly-declared backend. This claim is scoped to
the paths that exist in this repository (see §6 limits: Windows-native
Job Objects and LocalSubstrate backends remain NOT PROVEN here).

## 4. Order §5 — binding test matrix

`E10/test_e10rp22r2_matrix.py`: **19/19 exit 0** (T01..T11, T07
parametrized ×9), every test through the REAL chains (real ToolExecutor /
SandboxManager / WindowsExecutorAdapter / real EOE bridge + AccessAdmission
+ owner-approved PATH_GRANTs / real OwnerApprovalService + NonceLedger +
PushApprovalRegistry). Anti-cheat: the in-scope grant covers exactly
`<workspace>/treeA`; every expected-rejection target is outside it or
outside the universe; the four legs that use a permissive scaffold are
labeled inline and exist ONLY to reach the layer ABOVE the permission
decision (git_push handler, execution layer) — they never weaken the
layer under test. T12 = the battery + two-state evidence (below).

## 5. Order §6 — regression, two-state, delivery

* **Probes re-run (§6.1):** the ORIGINAL 15 probes, byte-identical,
  saved in unified format under `evidence_rp22r2/probe_outputs_postfix/`.
  Verdict mapping (baseline → post-fix) per probe:
  `POSTFIX_PROBE_VERDICTS.md`. OVERALL_EXIT=1 is expected: the six
  non-zero probes stop exactly at the NEW enforcement raises (each
  `.err` traceback cites the R2 rule) — the fixes firing, not failures.
* **Battery (§6.2):** `REGRESSIONS_BRANCH.txt` — R2 19/19 · R1 6/6 ·
  RP2.2 22/22 · RP2.1 24/24 · RP2 22/22 · RP2 fresh-dir session 9/9 ·
  RP1 16/16 · RP 23/23 · CW1 32/32 · CW1-R1 31/31 · E9-R OVERALL PASS ·
  E8 4/4 negative gates REJECTED · vs-row exit 1 · e3+e4 exit 1 · e6
  exit 1 · e33+e32f exit 1 · e35 exit 1 · e37 exit 1.
* **Two-state at 0945960 (§6.2):** same battery in a throwaway worktree
  at the baseline commit (removed after).
  `TWO_STATE_BASELINE.json`: all 17 shared rows IDENTICAL exit codes AND
  identical failure-name sets → **OVERALL_TWO_STATE=0** (no new
  regression PROVEN). The 6 non-zero rows are IDENTICAL to baseline and
  remain DECLARED NOT GREEN (order §6.4 — identical sets do not make
  them green). The R2-matrix row exists only on the branch (green
  there); e35/e37 are non-pytest rows compared by exit code (their
  normalized output content was additionally diffed manually during
  development: identical modulo random ids/paths).
* **Live main check (§6.6):** performed after commit — see §7.

## 6. CLAIM / OBSERVED / VERIFIED / NOT PROVEN

| # | Statement | Class | Evidence |
|---|---|---|---|
| 1 | Unregistered mission → explicit rejection for HIGH/CRITICAL tools; zero trace | VERIFIED | T04, T11; probes X1/O1 post-fix |
| 2 | Gate approvals bind to tool+inputs (digest); mission-wide carry-over closed; same-input retry passes | VERIFIED | T04, T05; E9-R row green |
| 3 | Failed ToolResults keep their original error at output=None (DF2) | VERIFIED | T08, T09; probe X2 post-fix |
| 4 | DF1 fixed in the same change as git grounding; git family executes positively under a correct grant | VERIFIED | T01, T02 (real branch/status/diff) |
| 5 | repo_path resolved + structurally contained + repo-root target to the path-aware validator; no coarse fallback for any git tool | VERIFIED | T01, T02; probes G2/G3/G4/G6 post-fix |
| 6 | read↔status/diff, write↔branch/commit scoping | VERIFIED | T02 |
| 7 | git_push rejected under the real bridge (admin unattainable) with zero remote effects | VERIFIED | T03(a), T11 |
| 8 | Owner-approval registry: fake/reused/out-of-scope/expired nonces rejected; single valid scoped approval consumed once | VERIFIED | T03(b) |
| 9 | No registry wired → push refused outright (§3.6); valid scoped approval → push executes; force scoped + implemented | VERIFIED | T03(c) |
| 10 | Empty required_grant_ids refused at SandboxManager.execute for every caller; zero trace | VERIFIED | T06, T10; probes S1/S3/O1/A2 post-fix |
| 11 | sandbox_id validated before join/makedirs at BOTH layers; zero directories on rejection | VERIFIED | T07 ×9; probe S2 post-fix |
| 12 | Host-subprocess fallback = declared degraded mode, refused by default, before makedirs | VERIFIED | T05 |
| 13 | sandbox_execute unregistered; absence engine-verified; true error surfaced | VERIFIED | T08; probe X2 post-fix |
| 14 | _run_in_sandbox disabled fail-closed; operational parallel path fails closed at the manager | VERIFIED | T06, T10; probes A2/O1 post-fix |
| 15 | DF4: substrate/push_engine were unimportable on Linux (unguarded win32 debris) — fixed | VERIFIED (fix proven by import + all T03 legs) | git status; matrix |
| 16 | DF5: git handler outputs lacked the mandatory `success` field — fixed | VERIFIED | every positive leg |
| 17 | Full battery + two-state: no new regression; 6 legacy rows not green | VERIFIED | REGRESSIONS_BRANCH.txt, TWO_STATE_BASELINE.json |
| 18 | Windows-native Job Objects path behavior (pywin32) — not executable here | NOT PROVEN | — |
| 19 | LocalSubstrate namespaced backend behavior — `core.substrate` absent here | NOT PROVEN | — |
| 20 | TOCTOU/symlink races; multi-process concurrency | NOT PROVEN | single-threaded probes |
| 21 | files_digest binding of PushApproval is not re-verified by the unified git_push tool (PushEngine's own flow verifies it) | OBSERVED (declared design limit) | §2 design note |
| 22 | SandboxManager.validate_grants' 2-arg SUBJECT call ('agent') — unchanged (fail-closed under the real bridge; no order mandate to change) | OBSERVED | T05 manager leg |
| 23 | `agent_role._validate_grant` remains kind-only dead code (no callers; outside §4.5's list) | OBSERVED | probe A1 post-fix |
| 24 | OBS-1 (run_command stdout wiring), OBS-2 (image allowlist digests), DF3 (_emit_artifact_created sandbox_id=None) — untouched, out of scope (order §7) | OBSERVED | — |
| 25 | GitHub CI for this branch | NOT PROVEN (no CI recorded) | — |

CLAIM (executor assertion without saved output): NONE — every
load-bearing statement above carries a matrix/probe/battery citation.

## 7. Delivery discipline (order §6.6-§6.7)

Commit on `e10-rp22r2-git-sandbox-hardening` (parent exactly `0945960`),
pushed WITHOUT force. `main` verified live at `0a26fc70` after push; all
historical branches/worktrees untouched; no merge. Windows-path debris
from the battery runs (same class as every prior phase) removed before
commit. STOPPED after delivery — awaiting independent arbitration; no
merge, no push of any fix to `main`.
