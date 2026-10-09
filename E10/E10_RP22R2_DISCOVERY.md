# E10-RP2.2-R2-DISCOVERY — GIT & SANDBOX LIFECYCLE AUTHORIZATION AUDIT

Order: E10-RP2.2-R2-DISCOVERY (discovery & audit phase ONLY — no source
fixes; production files untouched; only discovery files, evidence, and
probe scripts added).

Baseline audited: `0945960427e833522789903e87a64b73c207bccd`
(`e10-rp22r1-path-aware-fail-closed`; parent exactly
`6719fe371da3d7854cb612cfa64ef937c7d3d7b2`). Discovery branch:
`e10-rp22r2-git-sandbox-auth-audit`, derived from that commit ONLY
(merge-base proof in `evidence_rp22r2_discovery/BASELINE.md` B3).

`main` remains `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` (B1). No merge,
no reset/clean/stash/restore, historical worktrees untouched (B4).

Everything marked VERIFIED below is proven BY EXECUTION at the baseline
tree, with the raw stdout/stderr/exit code of the probe saved and
re-runnable (`E10/evidence_rp22r2_discovery/probe_outputs/PROBE_*.out`,
`.err`, `.exit`; runner `E10/run_rp22r2_probes.sh`; probes
`E10/e10rp22r2_probes.py` + `E10/e10rp22r2_probes_lib.py`). Probe IDs are
cited as `[Gn]/[Sn]/[Xn]/[An]/[On]`. Source citations are line numbers at
the baseline commit (re-checkable by `git show 0945960:<path>`).

---

## 0. Evidence inventory

| Artifact | Content |
|---|---|
| `evidence_rp22r2_discovery/BASELINE.md` | §2 hard baseline, raw commands + outputs (B1–B6) |
| `evidence_rp22r2_discovery/probe_outputs/PROBE_{G1..G6,S1..S4,X1,X2,A1,A2,O1}.{out,err,exit}` | RAW probe stdout / stderr / exit codes (15 probes) |
| `evidence_rp22r2_discovery/probe_outputs/RUNNER_{HEADER,SUMMARY}.txt` | Runner environment + one-line verdicts |
| `E10/e10rp22r2_probes.py`, `E10/e10rp22r2_probes_lib.py` | Re-runnable probe suite (real ToolExecutor / SandboxManager / BaseAgent chains, real EOE bridge) |
| `E10/run_rp22r2_probes.sh` | Runner (per-probe exit codes captured) |

Probe call-classification vocabulary used throughout:
`PERMISSION_REJECTED` (stopped at an authorization layer),
`IMPL_CRASH` (passed every authorization layer, crashed inside the
implementation), `TOOL_RESULT` (completed).

---

## 1. Defects discovered (pre-existing at baseline; DF1/DF2 also on `main`)

### DF1 — git family implementation is DEAD: `subprocess` never imported

`src/unified/execution.py` imports no `subprocess` (module import block
lines 17–28), yet `_execute_git_tool`'s `run_git` helper calls
`subprocess.run(...)` (lines 1110–1119). Every git-family invocation that
PASSES authorization therefore crashes with
`NameError: name 'subprocess' is not defined`.

- VERIFIED by execution: `[G2]` git_branch/git_commit/git_status/git_diff
  all `[IMPL_CRASH] NameError`; `[G3]` same under the REAL EOE bridge;
  `[G4]` live-grant leg; `[G6]`/`[X1]` git_push crashes at the push call.
- History: `git log -S "import subprocess" -- src/unified/execution.py` →
  EMPTY (never present); defect present since the E3-era commit `0bf1f93`
  and on `main` (`git show 0a26fc70:src/unified/execution.py` has
  `run_git` but no `import subprocess`) — OBSERVED.
- Consequence for this audit: the git family can pass every authorization
  layer (the coarse kind gate is its final decision — GAP-1) but no git
  effect ever executes at baseline. Current "protection" of the git
  authorization gaps is an ACCIDENTAL CRASH, not a security control. A
  one-line `import subprocess` fix would ACTIVATE the weak authorization
  path — the crash fix and the authorization hardening are COUPLED and
  must ship together (see §7 proposed order).
- Why batteries never caught it: git tools were only ever tested in
  REJECTION scenarios (rejections stop before `_execute_implementation`);
  no prior battery executes a git tool positively through the governed
  chain — OBSERVED (battery records cited in `evidence_rp22r1/REGRESSIONS_BRANCH.txt`).

### DF2 — failure-path output validation MASKS the real error

`ToolExecutor.execute_tool` step 8 runs
`contract.output_schema(**tool_result.output)` even for FAILED results;
failure-path `ToolResult`s built with `output=None` then raise
`TypeError: argument after ** must be a mapping, not NoneType`, which is
caught and OVERWRITES the real error with "Output validation failed: …"
(execution.py lines 519–527).

- VERIFIED by execution: `[G6]` empty-nonce git_push — the intended error
  `git_push requires owner_approval_nonce` is REPLACED by
  `Output validation failed: … NoneType`; `[X2]` sandbox_execute — the
  real cause `ValueError: Unknown tool: sandbox_execute` is masked the
  same way.
- Impact: diagnostic integrity, not authorization. Fail-closed direction
  is preserved (success=False either way), but the true failure cause is
  hidden from callers and evidence records.

### DF3 — declared, still open (carried from R1)

`_emit_artifact_created` crashes on `context.sandbox_id=None` when the
artifact is not at the artifacts root (execution.py line 3820:
`os.path.join(self.artifacts_base_dir, context.sandbox_id, …)` with
`None`). Declared unfixed by R1 §4.5; re-confirmed present at baseline —
OBSERVED (source lines). NOT reachable on the run_command artifact path
today because run_command artifacts are never registered in the evidence
store (see OBS-1), so `_emit_artifact_created` is never invoked for them.

### OBS-1 — run_command stdout/stderr never reach the ToolResult (evidence-chain wiring gap)

The adapter writes stdout/stderr artifacts and returns bare artifact ids
(`windows_adapter.py` `_execute_subprocess_fallback` lines 549–557), but
nothing registers them in the evidence store; `engine.execute_tool` then
finds `get_artifact(id) → None` and skips them (execution.py lines
3152–3168), so `ToolResult.output["stdout"]` is always `""`.
- VERIFIED by execution: `[S4]` — command printed `S4-EXECUTED-ON-HOST`
  (marker file written; stdout artifact on disk contains it) but
  `ToolResult.output` shows `stdout: ''`.

### OBS-2 — image allowlist is name-only; digests are placeholders

`SandboxManager.validate_image` compares `entry.name == image` only
(sandbox.py lines 232–237); `DEFAULT_IMAGE_ALLOWLIST` digests are literal
placeholders (`"sha256:a1b2c3d4..."`, lines 106–131) and are never
checked. On the default backend (WindowsExecutorAdapter subprocess
fallback) the image is IGNORED entirely (it executes `request.command`
directly — windows_adapter.py lines 99–136). Also `engine.execute_tool`
builds the run_command request from
`tool_input.get("image", "python:3.11-slim")` — but `RunCommandInput`
has no `image` field, so the image is ALWAYS the default; and it reads
`tool_input.get("timeout", 300)` while the schema field is
`timeout_seconds`, so wall time is ALWAYS 300 — OBSERVED (source lines
3138–3147 + tool_contract.py lines 313–347).

---

## 2. Authorization path map (order §3 — the six questions per path)

Shared wiring facts (VERIFIED by direct inspection at baseline; probe
contexts replicate exactly this wiring — `e10rp22r2_probes_lib.py`):

- W1: `ExecutionContext.grant_validator` / `grant_ids` come from the
  ENGINE constructor (`ExecutionEngine(grant_validator=…, grant_ids=…)`)
  and are copied into every per-attempt context in
  `execute_task_graph_*` (execution.py lines 1744–1766). The default when
  `grant_ids=None` is the legacy `['test-grant']` (rejected by any real
  validator — fail-closed).
- W2: the SAME validator object is passed to `SandboxManager` at engine
  construction (execution.py lines 1384–1390).
- W3: NO production caller wires the engine today: `build_engine_grant_validator`
  and `ExecutionEngine(` appear only in E9-R/E10 harnesses inside the repo
  (repo-wide search) — the previously disclosed "no production API caller"
  boundary stands (NOT PROVEN beyond harnesses).
- W4: the engine's default sandbox backend is `WINDOWS_EXECUTOR`
  (execution.py line 1346), which on Linux resolves to
  `WindowsExecutorAdapter._execute_subprocess_fallback` — a PLAIN HOST
  subprocess (asyncio.create_subprocess_exec, cwd=working_dir,
  env={**os.environ}, no filesystem/network isolation — windows_adapter.py
  lines 503–523). The namespaced LocalSubstrate exists but is NOT the
  default wiring (and `core.substrate` is not importable in this
  environment — pre-existing vs003 battery finding).

### 2.0 What each operation PROTECTS (order §3: define the protected object before proposing any grant model)

The order forbids assuming git tools need a file-tool-shaped permission
model. The protected object and the correct grant meaning per operation:

| Operation | Protected object | Correct grant meaning (proposed, for arbitration) |
|---|---|---|
| `git_status` / `git_diff` | WORKING-TREE METADATA of the target repository (file names, change state, content diffs) — a disclosure surface | read-disclosure over a CONTAINED repo root (not the whole filesystem) |
| `git_branch` (create/delete) | The repository's REF NAMESPACE (branch pointers) — integrity of shared history | write over the repo root; destructive delete may warrant a narrower scope |
| `git_commit` | The repository's HISTORY + INDEX (stages `-A` when no files given — sweeps the whole worktree) | write over the repo root; the `-A` sweep makes file-level scoping meaningless without repo-level grounding |
| `git_push` | The REMOTE repository (a third-party asset) + the local repo's remote-tracking state — the only operation whose blast radius leaves the machine | a distinct PUSH authorization: verified owner nonce (approval record) + approved remote + contained repo — kind `admin` alone is not a sufficient statement |
| `run_command` / `sandbox_execute` | THE HOST (process execution surface: filesystem, environment, network, child processes) | the grant must speak about the COMMAND (or command class), working_dir, and backend isolation — a kind-only `execute` says nothing about any of them |
| `SandboxManager.execute` | Same as run_command + the artifacts custody tree (sandbox_id joins the base) | grant decision must be non-bypassable (no empty-list skip) + sandbox_id structurally validated before any join |
| `agent_role._validate_grant` / `_run_in_sandbox` | (surfaces) — no caller today | if ever revived: route through the governed chain or delete |

Common structural conclusion: for the git family the meaningful target is
the RESOLVED REPO ROOT (containment + scope), for run_command/sandbox it
is the COMMAND + working_dir + backend, and for git_push additionally a
VERIFIED owner approval. None of these objects is representable in a
kind-only decision — which is the root cause of GAP-1/2/3/4.

### 2.1 `git_branch` / `git_commit` / `git_diff` / `git_status` (ToolExecutor chain)

| Question | Answer at baseline |
|---|---|
| Contract & required permissions | `git_branch`/`git_commit`: `["write"]`, risk MEDIUM; `git_diff`/`git_status`: `["read"]`, risk LOW (tool_contract.py lines 367–435, 438+) |
| grant_validator source & route | W1: engine constructor → per-attempt context → `ToolExecutor._check_permissions` (execution.py lines 491–496) |
| Decision basis | **Kind-only.** None of the four is in `_PATH_BEARING_TOOLS` (line 578), so the final decision is the coarse 2-arg `validator(gid, perm)` (lines 789–796). `repo_path` is NEVER part of the decision: `_execute_git_tool` resolves `Path(validated_input.repo_path or workspace_root)` with NO containment proof (line 1108) — any absolute path on the host is accepted as the git working directory |
| Missing/revoked grant, absent validator, underivable target | Missing/revoked → PermissionError (fail-closed) — VERIFIED `[G4]`. Absent validator → PermissionError before any event/record — VERIFIED `[G1]`. "Underivable target" is NOT a defined state for git tools: the target is simply never grounded |
| Check order vs side effects | `_check_permissions` runs BEFORE `_emit_action_requested`/Action record (steps 3–6, lines 496–516) — rejection leaves zero events/actions — VERIFIED `[G4]/[G5]` (event/action/tree deltas 0) |
| Does rejection prevent side effects? | YES — VERIFIED `[G5]` (rejected branch absent from refs; no events/actions/files). BUT a call that PASSES authorization creates ActionRequested/Action records and then crashes (DF1) leaving a FAILED action record — audit-trail growth, no operational effect — VERIFIED `[G2]` |

Authorization-layer verdict: GAP-1 — the coarse kind gate is the FINAL
decision for all four tools; target/repo never grounded.
VERIFIED `[G2]` (legacy validator: calls PROCEED past all authorization
layers on an uncontained repo) and `[G3]` (REAL bridge with a live grant
scoped to treeA: git_branch/git_status still PROCEED on repoB outside the
grant scope). Execution never happens at baseline (DF1 crash).

### 2.2 `git_push` (ToolExecutor chain)

| Question | Answer at baseline |
|---|---|
| Contract | `["write","admin"]`, risk CRITICAL, `owner_approval_nonce: str` REQUIRED in input (tool_contract.py lines 707–735) |
| Decision basis | Kind-only coarse gate (`write`+`admin`), PLUS human gate (CRITICAL), PLUS nonce PRESENCE check in `_execute_git_tool` (lines 1191–1203): any non-empty string passes; the nonce is NEVER validated against any owner-approval record. `remote`, `branch`, `repo_path` uncontained; `force` input flag is IGNORED (never appended to the push command) |
| Human gate behavior | Registered mission: gate created → PermissionError "paused" — VERIFIED `[G2]`-class behavior via run_command in `[X1]` leg 1 and git_push pending-gate semantics. Pre-approved gate (mission.metadata `action_gate_git_push_*` + decision approve): the approval is MISSION-WIDE — any action of that tool in the mission passes (execution.py lines 828–835). Unregistered mission_id: gate SILENTLY SKIPPED (lines 824–826: `mission = engine.missions.get(...); if not mission: return`) — VERIFIED `[X1]` |
| Under the REAL bridge | `admin` is not establishable in EOE grant policy (bridge rejects every permission except write/read — engine_bridge.py lines 105–111) → ALWAYS PermissionError — VERIFIED `[G3]` (fail-closed; tool functionally dead under the real policy) |
| Rejection side effects | Permission-layer rejection: zero events/actions — VERIFIED `[G1]`. Gate-pending rejection: gate record written to mission.metadata (the gate itself). Nonce-missing rejection: ToolResult failure (masked by DF2) — VERIFIED `[G6]` |
| Positive path | With legacy validator + approved/absent gate + FAKE nonce the call passes EVERY pre-execution layer — VERIFIED `[G6]`/`[X1]` — then dies at DF1 (NameError) before `git push` runs. The push has never executed at baseline |

Authorization-layer verdict: GAP-2 — nonce presence-only, arbitrary
remote, uncontained repo_path, mission-wide gate approval, and the
mission-lookup gate bypass (GAP-5) all compound on the CRITICAL tool.

### 2.3 `run_command` (ToolExecutor chain → engine.execute_tool → SandboxManager.execute → adapter)

| Question | Answer at baseline |
|---|---|
| Contract | `["execute"]`, risk HIGH, isolation SANDBOX (tool_contract.py lines 332–347) |
| Decision basis | Kind-only coarse gate on `execute`. The command, working_dir, env are NEVER part of the authorization decision |
| Human gate | Registered mission → gate (paused) — VERIFIED `[X1]` leg 1. Unregistered mission_id → SILENTLY SKIPPED, command EXECUTES — VERIFIED `[X1]` leg 2 (GAP-5) |
| Under the REAL bridge | `execute` not establishable → ALWAYS PermissionError — VERIFIED `[G3]` (fail-closed; functionally dead) |
| SandboxManager layer | `execute` checks: single-use per sandbox_id → image allowlist (name-only, OBS-2) → limits → `validate_grants(required_grant_ids, "agent")` — a 2-arg call whose second argument is the SUBJECT STRING "agent", not a permission (sandbox.py lines 243–276). Under the real bridge ANY non-empty list fails (fail-closed) — VERIFIED `[S1]`; an EMPTY list SKIPS the grant decision entirely and the command EXECUTES — VERIFIED `[S1]/[A2]` (GAP-3). Note: through the engine path the request always carries `context.grant_ids` (execution.py line 3145), which under the real bridge is non-empty → SandboxError (fail-closed); the empty-list bypass is reachable via direct/agent/operational callers |
| What actually executes | On the default backend: a HOST subprocess — cwd = arbitrary `working_dir`, env = full `os.environ`, NO filesystem/network isolation — VERIFIED `[S4]` (marker file written inside working_dir; stdout artifact on disk) |
| Check order vs side effects | Permission gate before events (VERIFIED `[G1]`). SandboxManager grant rejection BEFORE `_active` tracking and BEFORE the adapter (no dir, no events) — VERIFIED `[S3]`. A command that RUNS but FAILS still leaves the sandbox artifacts dir + stdout/stderr files (evidence capture by design) |
| Rejection side effects | Clean at every authorization layer (VERIFIED `[G1]/[S3]`); audit events for engine-layer failures only (TOOL_STARTED/TOOL_FAILED from the engine wrapper) |

Authorization-layer verdict: GAP-4 (host subprocess, arbitrary
working_dir, kind-only decision that never sees the command) +
GAP-3 (empty grant list) + GAP-5 (mission-lookup gate bypass).

### 2.4 `sandbox_execute` (ToolExecutor chain)

Registered in the registry (contract `["execute"]`, risk HIGH,
`SandboxExecuteInput` with `sandbox_id/image/command/working_dir/
required_grant_ids` — tool_contract.py lines 550–585) and routed by
`_execute_implementation` to `engine.execute_tool` (execution.py line
890) — but the engine has NO handler for it: `else: raise
ValueError(f"Unknown tool: …")` (line 3304). With an approved gate the
call completes as a FAILURE whose real cause is masked by DF2 — VERIFIED
`[X2]`. The input's `required_grant_ids` field is never consumed.
Under the real bridge it is rejected at the permission layer — VERIFIED
`[G3]`. Verdict: REGISTERED-BUT-UNIMPLEMENTED (GAP-6); the contract
promises sandbox semantics no code provides.

### 2.5 `SandboxManager.execute` (direct / lifecycle)

| Question | Answer at baseline |
|---|---|
| Entry conditions | sandbox_id single-use; image in (name-only) allowlist; limits within defaults; grants per §2.3 |
| Decision basis | Kind/subject-level only; the COMMAND is never authorized; `working_dir` never contained; `network_mode` is `Literal["NONE"]` in the request model (domain_model.py line 447) but the subprocess fallback does not enforce network isolation on the host |
| sandbox_id structural validation | **ABSENT at execute()**: `WindowsExecutorAdapter.execute` does `os.path.join(artifacts_base_dir, sandbox_id)` + `os.makedirs` with NO `validate_sandbox_id` (windows_adapter.py lines 93–97). A traversal sandbox_id (`../r2s2_escape_dir`) creates directories OUTSIDE the artifacts base — VERIFIED `[S2]` (GAP-7). Contrast: `write_artifact`/`read_artifact`/`list_artifacts` DO validate (sandbox.py lines 359, 408, 434 — the RP2.2 §3.1 fix); `SandboxManager.execute` itself does not validate either |
| Order vs side effects | grants rejected BEFORE `_active` tracking/events/adapter — VERIFIED `[S3]` (no dir, no entry). The adapter's makedirs + stdout/stderr artifacts happen once the adapter is reached (even for a failing command) — OBSERVED `[S2]` (artifacts base empty but escape dir created; command ran) |
| Lifecycle enforcement | Single-execute per sandbox_id enforced at BOTH manager (sandbox.py line 260) and adapter — VERIFIED `[S3]` ("Sandbox s3-x already used"); active-count returns to 0 |

### 2.6 `agent_role._validate_grant`

2-arg kind-only wrapper over `context.grant_validator`
(agent_role.py lines 525–529): fail-closed when validator/context absent
(VERIFIED `[A1]`), `True` for any kind under a permissive validator
(VERIFIED `[A1]`), and under the real bridge it degrades to the coarse
kind gate — `'write'` allowed regardless of target, `'execute'` rejected
(VERIFIED `[A1]`). Repo-wide search: NO callers — dead code today, a
latent kind-only surface (OBSERVED).

### 2.7 `agent_role._run_in_sandbox` (bypass primitive, dormant)

Builds a `SandboxRequest` with `required_grant_ids=context.grant_ids` and
calls `context.sandbox_manager.execute` DIRECTLY — no
`_check_permissions`, no contract, no human gate, no path grounding
(agent_role.py lines 530–562). With an EMPTY grant_ids list the command
executes with ZERO authorization even under the real bridge — VERIFIED
`[A2]` (GAP-3 reachable here too). Repo-wide search: NO callers — a
dormant bypass primitive, not an active path (OBSERVED).

### 2.8 Parallel legacy path: `unified.operational` agents + `OperationalExecutionEngine`

Seven operational agent classes (Implementer/Verifier/Explorer/Analyst/
Planner/Designer/Reviewer/Security) implement `operation == "run_command"`
by calling `context.sandbox_manager.execute(SandboxRequest(...))` with NO
`required_grant_ids`, no ToolExecutor, no contract, no human gate
(operational.py lines 197–239 and the six sibling call sites 697/874/
1051/1228/1405/1618). VERIFIED `[O1]`: `OperationalImplementerAgent`
executes a command with ZERO grants. `OperationalSecurityAgent`'s
`_check_permissions` (lines 1776–1783) is a heuristic `..`-string audit
helper, not a permission gate. Active in legacy e2x/e4x harnesses
(e26/e29/run_e44/run_e48/test_security_audit), NOT imported by unified
production code (OBSERVED). GAP-8.

---

## 3. Classification table (order §6: CLAIM / OBSERVED / VERIFIED / NOT PROVEN)

| # | Statement | Classification | Evidence |
|---|---|---|---|
| 1 | Absent validator: all 7 in-scope tools rejected before any event/action/file/git effect | VERIFIED | `[G1]` raw out/err/exit |
| 2 | Git family final decision is the coarse kind gate; `repo_path` never grounded (legacy validator AND real bridge, uncontained repo) | VERIFIED | `[G2]`, `[G3]` |
| 3 | DF1: git implementation dead — `subprocess` NameError after passing authorization (also on `main`, since E3-era `0bf1f93`) | VERIFIED (execution) + OBSERVED (history) | `[G2]`/`[G3]`/`[G4]`/`[G6]`/`[X1]`; `git log -S` empty; `git show 0a26fc70` |
| 4 | Missing/revoked grant fail-closed for git family; rejection emits no event/action; repo unchanged | VERIFIED | `[G4]` |
| 5 | Rejected git op after a prior allowed op in the same mission: refs/events/actions/files untouched | VERIFIED | `[G5]` |
| 6 | git_push nonce is presence-checked only; arbitrary remote; uncontained repo; mission-wide gate approval; `force` ignored | VERIFIED (authorization layers; push itself stopped by DF1) | `[G6]` |
| 7 | Unregistered mission_id silently skips HIGH/CRITICAL human gates (run_command EXECUTES; git_push proceeds to DF1 crash) | VERIFIED | `[X1]` |
| 8 | Under the REAL bridge: `execute`/`admin` unattainable → run_command/sandbox_execute/git_push ALWAYS rejected (fail-closed, functionally dead) | VERIFIED | `[G3]` |
| 9 | sandbox_execute registered-but-unimplemented (ValueError "Unknown tool" masked by DF2) | VERIFIED | `[X2]` |
| 10 | SandboxManager empty `required_grant_ids` skips the grant decision entirely; command executes (even under the real bridge) | VERIFIED | `[S1]`, `[A2]` |
| 11 | SandboxManager grant validation is a 2-arg SUBJECT call (`'agent'`), not a permission; non-empty lists fail-closed under the real bridge | VERIFIED | `[S1]` |
| 12 | sandbox_id NOT structurally validated at execute(): traversal sandbox_id creates directories OUTSIDE the artifacts base; write/read/list DO validate | VERIFIED | `[S2]` |
| 13 | Sandbox lifecycle: single-use per sandbox_id enforced; grant-rejected execute leaves no dir/entry/event | VERIFIED | `[S3]` |
| 14 | run_command executes a HOST subprocess on the default backend (no fs/network isolation, full os.environ, arbitrary working_dir) | VERIFIED | `[S4]` |
| 15 | run_command stdout/stderr never reach the ToolResult (artifact ids never registered in the evidence store) | VERIFIED | `[S4]` (OBS-1) |
| 16 | Image allowlist name-only; placeholder digests never checked; image/timeout input fields effectively dead (OBS-2) | OBSERVED (source, line-cited) | §1 OBS-2 |
| 17 | `agent_role._validate_grant`: 2-arg kind-only; fail-closed without validator; dead code (no callers) | VERIFIED (behavior) + OBSERVED (no callers) | `[A1]` |
| 18 | `agent_role._run_in_sandbox`: zero-authorization direct sandbox execution primitive; dead code (no callers) | VERIFIED (behavior) + OBSERVED (no callers) | `[A2]` |
| 19 | `unified.operational` parallel path executes run_command with zero grants/gates (active in legacy harnesses only) | VERIFIED (behavior) + OBSERVED (usage) | `[O1]` |
| 20 | Engine wiring facts W1–W4 (validator/grant_ids propagation; default backend; no production caller) | OBSERVED (line-cited) + NOT PROVEN (production usage beyond harnesses) | §2 W1–W4 |
| 21 | DF2: failure-path output validation masks real errors (`output=None` → TypeError overwrite) | VERIFIED | `[G6]`, `[X2]` |
| 22 | DF3: `_emit_artifact_created` sandbox_id=None crash (declared R1, still open; unreachable on run_command path due to OBS-1) | OBSERVED (source) | §1 DF3 |
| 23 | Windows-native behavior (pywin32 Job Objects path), LocalSubstrate namespaced backend behavior in this environment | NOT PROVEN (not executable here; Linux container) | — |
| 24 | TOCTOU symlink races; concurrent multi-process access to SandboxManager._active | NOT PROVEN (single-process probes only) | — |
| 25 | GitHub CI for this commit | NOT PROVEN (no CI results recorded for the branch) | — |

CLAIM (executor assertion without saved output): NONE in this report —
every load-bearing statement carries a probe citation or a line-cited
source observation.

---

## 4. Proven gaps (for the R2 execution order) and secure behaviors

Proven gaps (all at the authorization/lifecycle layer; DF1 currently
blocks git effects but is NOT a control):

- GAP-1 git family kind-only final decision + uncontained `repo_path`
  (`[G2]`, `[G3]`).
- GAP-2 git_push: nonce presence-only; arbitrary remote; mission-wide
  gate approval; `force` ignored (`[G6]`).
- GAP-3 SandboxManager empty `required_grant_ids` = no grant decision
  (`[S1]`, `[A2]`).
- GAP-4 run_command host subprocess on the default backend; command and
  working_dir never in the decision (`[S4]`).
- GAP-5 `_check_human_gate` mission-lookup bypass for unregistered
  mission_ids (HIGH and CRITICAL tools) (`[X1]`).
- GAP-6 sandbox_execute registered-but-unimplemented; `required_grant_ids`
  input never consumed (`[X2]`).
- GAP-7 sandbox_id NOT validated at `SandboxManager.execute` /
  `WindowsExecutorAdapter.execute` (traversal escapes the artifacts base
  at makedirs) (`[S2]`).
- GAP-8 `unified.operational` parallel zero-authorization execution path
  (`[O1]`); dormant sibling `_run_in_sandbox` (`[A2]`).
- DF1/DF2/OBS-1/OBS-2 as defects/diagnostics (§1).

Secure behaviors to PRESERVE (regression guards for R2):

- SEC-1 absent validator → all tools rejected, zero trace (`[G1]`).
- SEC-2 missing/revoked grants fail-closed, zero-trace rejection
  (`[G4]`, `[S3]`).
- SEC-3 `execute`/`admin` unattainable under the real bridge (`[G3]`).
- SEC-4 single-execute-per-sandbox_id lifecycle (`[S3]`).
- SEC-5 permission gate ordering before events/journal (`[G1]`, `[G4]`,
  `[G5]`).
- SEC-6 sandbox_id validated at write/read/list (RP2.2 §3.1 intact)
  (`[S2]` contrast leg).
- SEC-7 human gate active for registered missions (`[X1]` leg 1).

---

## 5. Proposed BINDING test matrix for the R2 execution phase

Every test through the REAL chains (ToolExecutor.execute_tool /
SandboxManager.execute / real EOE bridge `build_engine_grant_validator`
+ `AccessAdmission`), mirroring the probe wiring. DF1's import fix is a
PREREQUISITE so positive git paths are executable at all.

- R2-T01 git family target grounding: with the real bridge and a grant
  scoped to treeA, `git_status`/`git_diff` on repoB (outside treeA) MUST
  be rejected (target resolved + contained like workspace tools; inside
  an authorized universe).
- R2-T02 git kind scoping: a READ-scope grant must not authorize
  `git_branch`/`git_commit` (write ops) on any repo; a write-scope grant
  over treeA must not authorize git ops outside treeA.
- R2-T03 git_push: a FAKE/arbitrary nonce MUST be rejected (nonce
  verified against a real owner-approval record — e.g. EOE grant kind or
  owner_gate issuance); unapproved remote MUST be rejected; the CRITICAL
  gate must apply EVEN when the mission is unregistered (fail-closed
  instead of skip); approval must be action-scoped or explicitly
  tool+input-scoped, not silently mission-wide.
- R2-T04 human-gate fail-closed: HIGH/CRITICAL tools with an
  unregistered mission_id MUST be rejected (gate-lookup miss =
  PermissionError, not silent return).
- R2-T05 run_command: under the real bridge stays unattainable
  (SEC-3 preserved); if the R2 order defines an authorized execute path
  (e.g. a COMMAND_GRANT or explicit owner policy), the COMMAND and
  working_dir must be part of the decision and the backend must provide
  the isolation the contract claims (the host-subprocess fallback must
  become an explicitly-declared degraded mode or be refused).
- R2-T06 SandboxManager.execute: EMPTY `required_grant_ids` MUST NOT
  bypass the grant decision (fail-closed default or an explicit
  no-grant-required class declared by the order).
- R2-T07 sandbox_id structural validation at execute(): traversal /
  separator / absolute sandbox_ids rejected BEFORE makedirs, leaving
  zero directories (parity with write_artifact).
- R2-T08 sandbox_execute: either implemented with the contract's
  semantics (grants consumed, containment, single-use) or REMOVED from
  the registry (no registered-but-unimplemented contract); its failure
  must never be masked (DF2 fix).
- R2-T09 DF2: failure-path ToolResults must surface their true error
  (no output-validation crash on `output=None`) for at least the
  git_push-nonce-missing and unknown-tool cases.
- R2-T10 parallel paths: `_run_in_sandbox` and the operational agents'
  run_command must route through the governed chain or be removed /
  fail-closed (no zero-authorization sandbox execution anywhere).
- R2-T11 zero-trace preservation: every new rejection leaves
  events/actions/journal/artifacts-tree identical (SEC-1/2/5 guards).
- R2-T12 regression battery: full prior battery (R1 6/6, RP2.2 22/22,
  RP2.1 24/24, RP2 22/22, RP2 fresh-dir 9/9, RP1 16/16, RP 23/23, CW1
  32/32, CW1-R1 31/31, E9-R, E8, vs-row, e-rows) + two-state comparison
  at baseline 0945960 (exit codes AND failure-name sets; battery not
  called green while any row is non-zero).

---

## 6. Proposed executive order for the R2 EXECUTION phase (draft for arbitration)

E10-RP2.2-R2 — GIT & SANDBOX LIFECYCLE AUTHORIZATION HARDENING

1. §1 Hard baseline: same discipline as this phase (live verification,
   new worktree+branch from the arbitration-designated commit, main
   untouched, no reset/clean/stash/restore, historical evidence
   immutable).
2. §2 Coupled defect+authorization fix (they MUST ship together):
   a. DF1: import `subprocess` in `src/unified/execution.py` (the git
      family becomes executable — therefore §2b hardening is MANDATORY
      in the same change, never shipped before it).
   b. Git family target grounding: `repo_path` resolved, structurally
      contained inside an authorized universe (workspace_root and/or a
      repo-scope grant), grounded into a path-aware decision (extend the
      R1 `_PATH_BEARING_TOOLS` grounding to the git family with a
      repo-operation permission mapping: read-ops ↔ read, write-ops ↔
      write). No grant → fail-closed; underivable/uncontainable target →
      fail-closed with NO coarse fallback (R1 §2.2 semantics extended).
   c. git_push: nonce verified against a real owner-approval record
      (owner_gate / EOE-issued nonce — implementation choice documented
      in the report); CRITICAL gate fail-closed on mission-lookup miss
      (GAP-5); approval scope narrowed to action or tool+input; `force`
      either implemented or removed from the contract.
   d. `_check_human_gate`: unregistered mission → PermissionError
      (fail-closed) instead of silent return, for ALL HIGH/CRITICAL
      tools.
   e. SandboxManager.execute: `validate_sandbox_id` BEFORE any join/
      makedirs (parity with write_artifact); EMPTY required_grant_ids no
      longer bypasses the grant decision (fail-closed default unless the
      order explicitly declares a no-grant operation class).
   f. sandbox_execute: implement (consume required_grant_ids, sandbox
      semantics, single-use) or unregister the contract — arbitration to
      pick; either way no registered-but-unimplemented tool.
   g. DF2: failure-path output validation must not mask true errors.
   h. Dormant/parallel paths: `_run_in_sandbox` and the operational
      run_command operations route through the governed chain or are
      removed/fail-closed.
3. §3 Binding tests: the R2-T01..T12 matrix (§5), all through the real
   chains; anti-cheat: no grant scope expansion to make tests pass, no
   permissive substitute validators (R1 §2.6 discipline).
4. §4 Regression battery + two-state comparison at baseline 0945960
   (R2-T12); binary baseline discipline unchanged.
5. §5 Out of scope unless arbitration extends: OBS-1 (run_command stdout
   wiring), OBS-2 (image allowlist digests), DF3
   (_emit_artifact_created), Windows-native pywin32 path verification,
   TOCTOU races, LocalSubstrate enablement.
6. §6 Delivery: commit on a new branch derived from the designated
   baseline ONLY; push without force; main untouched; full evidence
   bundle (probes re-run at the fixed tree proving each gap CLOSED);
   stop and await arbitration.

Acceptance criteria (verifiable): every GAP-1..GAP-8 probe re-run at the
fixed tree flips to rejection/correct behavior with saved raw outputs;
SEC-1..SEC-7 behaviors unchanged; DF1 fixed WITH the git grounding in
the same commit; battery two-state comparison shows no new regression
(identical failure sets) while no non-zero row is called green.

---

## 7. NOT PROVEN / declared limits of this discovery

- Windows-native (pywin32) and LocalSubstrate backends are not
  executable in this environment — backend-specific behavior beyond the
  subprocess fallback is NOT PROVEN.
- TOCTOU/symlink races and multi-process concurrency NOT PROVEN
  (single-process probes).
- No production deployment wiring exists in-repo (W3): all conclusions
  are about the code paths as wired by the canonical harness pattern.
- GitHub CI: no recorded results for this branch (NOT PROVEN).
- The git tools' POSITIVE execution semantics (output shape, exit codes)
  cannot be probed at baseline because of DF1 — the authorization-layer
  conclusions stand on their own; execution-layer behavior becomes
  testable only after the DF1 fix.

