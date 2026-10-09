# E10-RP2.2 — DISCOVERY (findings at baseline 23ba936, BEFORE any change)

Order: E10-RP2.2 — COMPLETE WORKSPACE TOOL AUTHORIZATION & CLEAN-BASELINE
RECONCILIATION. Every finding below was verified by direct code reading at
the execution baseline `23ba93605a2ad6f8361453225eeef47002ef3eb6` (E10-RP2.1
delivery) BEFORE any modification. Arabic terms in quotes are the
arbitration's own wording.

## D1 — Workspace tools end at the coarse kind-only gate (Blockade 1, core)

`ToolExecutor._PATH_BEARING_TOOLS` (src/unified/execution.py @23ba936) =
`{artifact_write, write_artifact, artifact_read, read_artifact}` ONLY.
The seven workspace tools — `write_file`, `edit_file`, `read_file`,
`list_dir`, `grep`, `find_files`, `file_browser` — all declare
`required_permissions` (`["write"]` / `["read"]`, src/unified/tool_contract.py)
but are NOT in the set, so `_check_permissions` falls to the two-argument
coarse form `validator(grant_id, perm)` → `eoe.engine_bridge` →
`admit_grant_kind(kind_only=True)`: signature, state, expiry and SCOPE are
checked, but the actual path and depth NEVER reach the decision. Consequence:
any live `PATH_GRANT` with `read_write` scope — for ANY target on the machine
— authorized `write_file`/`edit_file` anywhere the workspace join allowed,
and any READ-scope grant authorized every read/exploration tool. The grants'
path scope and `max_depth` were simply not part of the decision.

## D2 — No structural containment on the workspace join (Blockade 1, enabler)

`_execute_filesystem_tool` resolved targets as `workspace / validated_input.path`
with NO containment proof: an ABSOLUTE `path` REPLACES the workspace base
entirely (pathlib join semantics), `..` traversal escapes, and symlinked
components resolve outside. The RP2.1 containment proof
(`_contained_write_target`) existed ONLY for the artifact families.

## D3 — Iterating tools disclose/read unbounded subtrees (Blockade 1, read side)

`list_dir(recursive)`, `grep`, `find_files`, `file_browser` walk
(`rglob`/recursive `build_tree`) everything below the requested root and
return/read every path. Even if the ROOT had been grant-checked, checking
the folder root then allowing unlimited reading inside is exactly what the
arbitration's §2.4 forbids.

## D4 — Governed grep could never execute (latent crash, new finding)

`GrepInput` does NOT declare `recursive`, but the executor reads
`validated_input.recursive`: pydantic (default extra=ignore) drops a
`recursive` kwarg, so the attribute access raises `AttributeError` on every
governed grep call. Additionally the grep branch referenced `fnmatch`
imported only inside the `list_dir` branch (`NameError` if list_dir's branch
had not run first). Proves zero test coverage of governed grep — and is
repaired as part of wiring the read side correctly (contract now declares
`recursive: bool = True`; `fnmatch` imported once at method top).

## D5 — Lower-layer sandbox creation BEFORE the containment proof (Blockade 2)

`SandboxManager.write_artifact` (src/unified/sandbox.py @23ba936) executed
`os.makedirs(<base>/<sandbox_id>)` FIRST (for any sandbox_id not active) and
only THEN ran the RP2.1 containment proof. `WindowsExecutorAdapter.write_artifact`
(src/unified/windows_adapter.py @23ba936) did the same
(`os.makedirs(artifacts_dir)` before the proof). A direct/legacy call with an
escaping target was rejected — but only AFTER a brand-new sandbox folder had
been created: the "no file-system trace at all before rejection" guarantee
did not hold for direct call points.

## D6 — sandbox_id never structurally validated (new finding, §3.1)

No layer validated `sandbox_id` as a single path component. The RP2.1
containment proof anchors on `Path(artifacts_base_dir) / sandbox_id`: with
`sandbox_id = "../evil"` the anchor ITSELF escapes the artifacts base while
the target remains "contained" relative to the ESCAPED root — the artifacts
base could be escaped through the identity join, and `os.makedirs` would
create the escaped directory. The arbitration's §3.1 wording ("فحص الاحتواء
والتحقق من sandbox_id إلى ما قبل إنشاء مجلد sandbox") names exactly this.

## D7 — No containment at all on artifact READS (new finding, acceptance 2)

`SandboxManager.read_artifact` and `WindowsExecutorAdapter.read_artifact`
opened `Path(<base>/<sandbox_id>) / path` with NO containment proof:
`path = "../../x"` read outside the sandbox custody tree on direct/legacy
calls. `list_artifacts` walked an unvalidated join.

## D8 — Bridge universe excluded workspace paths; string-prefix containment

`build_engine_grant_validator(admission, artifacts_root)` at 23ba936
contained the path decision to `artifacts_root` via
`resolved.startswith(root + "/")`: (a) workspace targets could never reach
`admit_grant_id` even under a correct grant (workspace tools were never
wired — consistent with D1); (b) string-prefix containment is not
OS-normalization-safe (Windows separators) — the arbitration's §2.5
explicitly forbids relying on `startswith(root + "/")` when Windows is
supported (this repo ships a Windows sandbox adapter).

## B1 — Baseline evidence contradiction (§1, evidence integrity)

`E10/evidence_rp21/BASELINE.md` line 34 records
`e10rp21_work: 1 dirty entries` while `E10/E10_RP21_REPORT.md` line 15
claims "All 5 worktrees clean before work". Investigated and reconciled in
`E10/evidence_rp21/BASELINE_CORRECTION.md` (dated, old evidence untouched):
the single entry is IDENTIFIED with high confidence as the untracked
`E10/evidence_rp21/` evidence directory written by the RP2.1 capture process
into its own brand-new worktree (self-observation artifact; mechanism
reproduced in a throwaway worktree at 631f6fb: one untracked file in a new
subdir = exactly one `?? E10/evidence_rp21/` porcelain entry). The four
PRE-EXISTING worktrees were clean (VERIFIED in the same table). What remains
NOT PROVEN: the raw porcelain line at capture time (only the count was
retained) and the capture command order (the RP2.1 capture script was not
persisted — identification rests on structural + timeline evidence).

## Out-of-scope observations (declared, NOT fixed here — unchanged from the arbitration's "حدود أخرى بقيت معلنة")

- D7-RP2.1 (engine layer `verify_task` first-path-match across tasks): still
  present, still disclosed (RP2.1 D7; caught by the task-bound orchestrator
  verifier).
- `run_e10rp2.py` idempotency flake: pre-existing, proven identical at
  631f6fb in RP2.1; NOT fixed in RP2.2 (scope decision per order §5 last
  paragraph — left NOT PROVEN; the fresh-dir session equivalent is the
  recorded coverage).
- No production API caller for `CanonicalOrchestrator` yet; replan decision
  content remains a declared control input; cross-process controller restore
  unproven (all unchanged from RP2.1 disclosure).
- Sandbox LIFECYCLE (`WindowsExecutorAdapter.execute`): creates
  `<base>/<sandbox_id>` without the new `validate_sandbox_id` guard. Out of
  §3's write_artifact scope; unreachable in the governed path (the
  `sandbox_execute` tool requires the "execute" permission which the EOE
  bridge rejects fail-closed); direct legacy lifecycle calls remain a
  disclosed boundary recommended for a future order.
- Git-family tools (`git_commit`/`git_push`/...) still pass the coarse gate
  (permission-kind level) — they were NOT in the arbitration's enumerated
  §2.1 tool list (file-access tools); disclosed as the next-boundary
  candidate alongside the lifecycle note.
- Pre-existing test quirk observed during the battery: e6/e37 tests embed
  absolute Windows paths (`C:\Users\jaber\...`) which create literal
  `C:`/`C:\...` debris directories when run on Linux; identical behavior at
  baseline (two-state proven); debris was removed from the worktree before
  commit and is not part of this delivery.
