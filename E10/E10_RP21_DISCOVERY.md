# E10-RP2.1 — Discovery (proven at baseline `631f6fbb7bed2ea5411af240ea2147ad79318dfb`)

Scope: authorization PATH/DEPTH on the real write path (§2) + TASK-BOUND
verification (§3) + verifier ERROR CLASSIFICATION (§4). Every finding below
was established by direct code reading at the baseline commit BEFORE any
modification. No code was changed during discovery.

## D1 — §2.3: fixed `depth=0` bypasses the grant's depth limit

`src/eoe/engine_bridge.py:63` calls
`admission.admit_grant_id(grant_id, write=write, path=root, depth=0)`
unconditionally. In `src/eoe/access_gateway.py:380-381` the only depth rule is
`if depth > grant.max_depth: return DEPTH_EXCEEDED`. Since the bridge always
presents `depth=0` and `0 <= max_depth` for every grant, **the `max_depth`
field of a PATH_GRANT is never enforced**. An owner-issued `max_depth=0`
grant (intent: no writes below the target) silently authorizes writes at ANY
depth under the target.

## D2 — §2.2: the permission contract is implicit and root-only

The bridge's only authorization question is "does the grant target cover the
bound `artifacts_root`" (`path=root, depth=0`). The ACTUAL write target —
`artifacts_base_dir/sandbox-<task_id>/<relative path>`
(`src/unified/execution.py:1484, 2957-2963, 3072-3074`) — is **never presented
to the authorization layer**. Whether a grant authorizes the whole task root
or specific paths/depth within it is nowhere stated; the module docstring
claims "path isolation inside the root remains the sandbox's responsibility",
which D3 disproves.

## D3 — §2.3: the sandbox-isolation claim is FALSE (no containment anywhere)

- `src/unified/sandbox.py:343-348` (`SandboxManager.write_artifact`):
  "Allow writing to any sandbox_id - create directory if needed" — ANY
  sandbox id is accepted, including another task's.
- `src/unified/windows_adapter.py:605-606`
  (`WindowsSandboxAdapter.write_artifact`):
  `file_path = Path(artifacts_dir) / path; file_path.parent.mkdir(...)` —
  **no containment check**. A relative `path` containing `../..` escapes the
  sandbox directory; an ABSOLUTE `path` (`"/tmp/x"`) REPLACES the base
  entirely (pathlib join semantics); directory depth is unbounded.
  Containment failure modes verified by reasoning over `pathlib` semantics:
  `Path("/base/sbx") / "/etc/x"` → `Path("/etc/x")`.

So the claimed "second defensive layer" does not exist: no layer proves a
granted write stays inside the task's sandbox root.

## D4 — §2.4: the permission gate is name-level only

`src/unified/execution.py:565-584` (`ToolExecutor._check_permissions`) checks
only permission NAMES (`write`/`read`) via `context.grant_validator(grant_id,
perm)`. The concrete write's path and depth never enter the decision, and the
validator protocol `Callable[[str, str], bool]` cannot carry them. The
validated path (root) and the written path (root/sandbox-*/...) are different
objects — the gap between them is exactly D2/D3.

## D5 — §3: verifier reads the newest same-name file across ALL sandboxes

`src/orchestrator/canonical.py:608-617`
(`E3VerifierAgent._resolve_current_file`) resolves a criterion path by
globbing `sandbox-*/<rel_path>` under the base dir and picking the **highest
mtime** — `target_task_id` is available in the verify task context but is
NOT used for resolution. Consequence (the collision the order describes):
task A writes `output.txt`="alpha" to `sandbox-A/`, task B writes
`output.txt`="beta" to `sandbox-B/`; each task's verdict can be decided by
the OTHER task's file — false PASS (B's file satisfies A's criterion) and
false FAIL (A's newer file fails B's criterion) are both possible. The
engine writes task X's artifacts to `sandbox-<task_id>` (execution.py:1484),
so the task-bound path is always well-defined.

## D6 — §4: verifier failure type is INFERRED from strings, not carried

`src/orchestrator/canonical.py:1421-1426`
(`_record_verifier_failure`) classifies TOOL vs CRITERIA by:
`"Tool/runtime failure" in error_text`, `"sandbox" in error_text.lower()`,
and `"Verification failed" not in error_text and not missing` — inference
from `missing_evidence` presence/absence and substrings, exactly what the
order §4.2 forbids. No explicit failure-class field exists anywhere in the
verifier result chain (`AgentResult.output` → `VERIFICATION_COMPLETE`
payload → FailureRecord).

Related defects in the same chain:
- `canonical.py:649-651`: a READ error during criteria evaluation is
  recorded as `missing.append(f"file_contains error ...")` — a machinery
  error masquerading as a criteria failure (→ plan deviation path).
- `canonical.py:912`: an exception from `factory.execute_agent_by_id` in
  `run_verifier` propagates and crashes `execute_run` — no classified
  verifier-error result at all.
- `canonical.py:919-924 + 935`: when the producing attempt cannot be
  established, the note is appended to `missing_evidence` but the verdict can
  still be `"evidenced"` — evidenced DESPITE unprovable provenance.

## D7 — engine-layer first-path-match collision (found during RP2.1 scenario design; PRE-EXISTING, disclosed, NOT fixed here)

`src/unified/verification_standard.py:331-343, 360-375` — the ENGINE's
execution-time verification (`ExecutionEngine.verify_task` →
`Verifier._check_file_exists/_check_file_contains/_check_file_hash`)
matches the FIRST recorded artifact whose `path`/`name` equals the
criterion's relative path across ALL tasks' evidence (the artifacts map is
the whole evidence store, insertion-ordered). Two tasks writing the same
relative name: the second task's engine-level check can be decided by the
FIRST task's recorded artifact (false pass — observed live in the RP2.1
collision scenario: task B completed engine-level on A's artifact). This is
the same name-collision class the order §3 targets, at a DIFFERENT layer
(recorded evidence-store matching, not the orchestrator verifier's on-disk
resolution). It is OUT of RP2.1 §3's stated scope (the order names
`E3VerifierAgent._resolve_current_file`); it is CAUGHT by the now
task-bound orchestrator verifier (proven in the collision-resolve
scenario), and is disclosed here as an RP2.2 candidate. No engine-layer
change was made.

## Fix design (implemented after this discovery)

**§2 — explicit contract, actual path+depth, structural containment:**
1. `access_gateway.admit_grant_id(..., depth=None)`: when `depth is None`,
   compute the ACTUAL depth of `path` below the grant target. Explicit depth
   convention: `depth(path, T)` = number of path components of `path` below
   `T` (T itself = 0, direct child file = 1). `max_depth=0` therefore
   authorizes NO file write under the target (a file is at depth >= 1).
2. `engine_bridge.build_engine_grant_validator` v2: the returned validator
   supports BOTH arities and carries `__path_aware__ = True`:
   - `validator(gid, perm)` — coarse validity + scope-kind gate (valid
     signature/state/scope for the permission KIND). Necessary, never
     sufficient for a concrete write.
   - `validator(gid, perm, path, depth=None)` — the FULL per-operation
     decision: the grant must cover the ACTUAL resolved path with the ACTUAL
     depth below the grant target (`depth=None` → honest computation inside
     admission).
   Contract answer to order §2.2: **a grant authorizes specific paths and
   depth within the root (target-prefix + depth <= max_depth), never the
   whole task root unconditionally.**
3. `execution.py`: `_contained_write_target(sandbox_id, path)` resolves the
   absolute write target and REJECTS anything that escapes
   `artifacts_base_dir/<sandbox_id>` (traversal, absolute paths, symlink
   escapes). `_check_permissions` is enriched with the tool input: governed
   writes/reads present the ACTUAL contained target to path-aware validators
   (2-arg fallback preserved for legacy test validators — never in the
   operational path). Uncontained target → `PermissionError` BEFORE any
   event, journal record, or side effect. `_governed_artifact_write`
   re-checks containment at entry (defense in depth, before the intent
   journal).
4. `sandbox.py` + `windows_adapter.py`: structural containment at BOTH the
   manager and the filesystem adapter — the last line for ALL writes
   (governed and legacy).

**§3 — task-bound evidence resolution:**
`_resolve_current_file` resolves `base_dir / sandbox-<target_task_id> /
<rel_path>` ONLY (no glob, no mtime race, no cross-sandbox reads). Every
criterion check records the resolved path; the verification output carries
`evidence_paths` so tests can prove each task's verdict came from its own
file. Read errors during evaluation become machinery errors (D6 fix), NOT
criteria failures.

**§4 — explicit failure classification:**
The verifier chain carries an explicit `failure_class` field:
- `"criteria_mismatch"` — evidence read OK, criteria mechanically unmet →
  PLAN_DEVIATION (replan-eligible: decision → replan_mission → review →
  continuation only after approval).
- `"provenance_unprovable"` — the producing attempt cannot be established →
  verdict `not_evidenced` (fail-closed; was: evidenced-with-note) →
  PLAN_DEVIATION (a replan can recover via re-execution).
- `"verifier_error"` — read/execution/verifier-machinery failure (including
  an exception from the agent execution itself, now caught and classified in
  `run_verifier`) → TOOL_RUNTIME_FAILURE (retry territory), NEVER replan, and
  completion stays blocked while the latest verdict is not_evidenced.
A result with NO explicit class is conservatively classified
TOOL_RUNTIME_FAILURE (never replan on unknown) — no string heuristics remain.
