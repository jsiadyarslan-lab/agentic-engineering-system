# E33 ROOT CAUSE — CROSS-RUNTIME REGRESSION

## Question this document answers

> Why does P1+P2 fail at cross-runtime execution (E33)?

E33 was authored and verified on Windows (commit `6b2b7b4`, evidence refreshed at
`be40a77`; `E33_PROCESS_TERMINATION.json` from that run records the mechanism as
`subprocess.Popen.kill() → TerminateProcess (Windows)`). On this runtime (Linux,
CPython 3.12) the suite fails. The failure is not one defect but **two stacked
defects**; each had to be excavated from the source, not from any report.

---

## Investigation method (from source, not from reports)

1. Baseline captured (`2a5965a`, LOCAL == REMOTE, clean worktree).
2. Canonical evidence tree snapshotted (1011 files, tree sha256
   `0e42f5216d65da39147f50deb39725eef1536f4d2a69494d5a93b67f9528111d`).
3. E33 executed as-is ONCE for diagnosis. Observed failure captured verbatim;
   canonical evidence restored byte-exact from git afterwards (43 mutations:
   34 deletions / 2 modifications / 7 additions — recorded in
   `containment-audit.json` as the pre-fix proof of the containment defect).
4. Each failure layer reproduced in isolation against the real P1+P2
   (`scripts/e2r2_repro_replan.py` — resumes CP1 exactly like the runner,
   reports mission state and replan preconditions).
5. Git archaeology (`git log -S`, `git show be40a77:...`) to date each behavior.

---

## LAYER 1 — tool-runtime failure injection is Windows-filesystem-specific

- **Failure location:** `tests/unified/test_e33_mission_autonomy.py` phase 1,
  line 268: `assert "OSError" in c_fail.description or "Tool/runtime" in c_fail.description`
- **Failing assertion:** the description of C's first-attempt failure is
  `'tool_runtime injection: sandbox accepted illegal path (unexpected)'`.
- **Runtime boundary:** `MissionTaskAgent.execute()` (P2, test-support agent
  registered by `register_mission_agent`) → `SandboxManager.write_artifact()`
  → `WindowsExecutorAdapter.write_artifact()` → host OS `open()`.
- **Expected contract:** the F2 injection performs a REAL sandbox write to a
  path "that the filesystem rejects" so a genuine tool error propagates
  (FailureKind.TOOL_RUNTIME_FAILURE, recovered by engine retry).
- **Actual contract on Linux:** the injected path was `e33_illegal|filename.txt`.
  `'|'` is an illegal filename character **only on Windows**. POSIX filesystems
  accept it, so the sandbox write SUCCEEDED (`artifact-3044b2670998,
  path=e33_illegal|filename.txt` was created and stored as evidence), the
  injection fell into its `unexpected` fallback, and the assertion failed.
- **State mismatch:** none in the engine — the misfit is between the injection's
  platform assumption and the host filesystem contract.
- **Root cause:** the injection relied on OS-specific filename illegality
  instead of a portable, deterministic filesystem rejection.

## LAYER 2 — E34 state restoration broke resume-then-replan across runtimes

Only observable after layer 1 was fixed (phase 1 then passes; phase 2 fails).

- **Failure location:** `e33_mission_runner.py` phase 2 (subprocess),
  `controller.replan_mission(...)` → `ExecutionEngine.replan_task_graph` →
  `RuntimeError: replan_task_graph failed for run ...` before the handshake —
  the runner dies early, before the process-kill proof can even start.
- **Failing guard:** `replan_task_graph` returns `False` when
  `mission.state != MissionState.EXECUTING` ("Can only replan during execution").
- **Root cause chain (proven by `scripts/e2r2_repro_replan.py` against CP1 of a
  real failed run):**
  1. Phase 1 pauses at the C-handoff: `pause_requested` → engine transitions
     `EXECUTING → PAUSED` (legal; `execute_task_graph` returns `paused=True`).
  2. `create_full_checkpoint` records `state: PAUSED` into CP1 (verified in the
     checkpoint JSON: `"state": "PAUSED"`).
  3. The runner resumes CP1 in a new process. Pre-E34 code forced the mission
     back to EXECUTING — its comment read: *"Resume execution implies mission
     should be in EXECUTING state. This enables replan/human_gate to work after
     cross-runtime resume."* Commit `2805567` (E34) generalized resume to
     restore the checkpoint's recorded state; for CP1 that is **PAUSED**.
  4. The resumed mission is PAUSED. `execute_task_graph` has no entry-state
     guard, so D executes and fails verification (the deviation) — but
     `replan_task_graph` IS EXECUTING-gated, so the mission-level replan that
     E33's autonomy proof requires is refused → runner aborts.
- **Expected contract:** resuming a checkpoint taken during a pause continues
  execution (the state machine defines `PAUSED → EXECUTING` for exactly this);
  replan-after-resume works cross-runtime (the pre-E34 documented contract).
- **Actual contract:** resume restores the mission INTO the pause, and a paused
  mission can execute tasks but can never replan — an internal inconsistency
  (execute allowed, replan refused) that leaves long-running autonomy flows
  dead across the runtime boundary.
- **Event mismatch (secondary):** because the runner aborts pre-handshake, the
  events `replan.applied`, the CP2 checkpoint, the real process termination and
  the phase-3 resume/completion can never occur.

## Why this is a CROSS-RUNTIME regression in the precise sense

- Layer 1 binds failure semantics to the host OS filesystem (Windows vs POSIX).
- Layer 2 binds mission-continuation semantics to the process boundary: state
  serialized by one runtime (PAUSED at handoff) is restored by another runtime
  into a mode that forbids the very operation (replan) the continuation needs.
- Both defects live exactly on the runtime boundary that E33 exists to police.

## Repair (§6) — root cause only, no scope expansion

1. **Layer 1** — `src/unified/mission_controller.py`, `MissionTaskAgent` F2
   injection: write a guard FILE through the real sandbox, then attempt to
   write an artifact UNDER that file. A parent path that exists as a regular
   file is rejected by every supported filesystem with a real OSError
   (`FileExistsError` from the adapter's `Path.mkdir(parents=True, exist_ok=True)`
   — pathlib behavior identical on POSIX and Windows; verified on this runtime).
   The real error propagates through the real tool layer; no mock, no skip,
   no xfail, no relaxed assertion.
2. **Layer 2** — `src/unified/execution.py`, `resume_from_checkpoint`: when the
   checkpoint has no active human gate and its recorded state is PAUSED, the
   resume operation itself transitions the mission to EXECUTING (restoring the
   documented pre-E34 contract). E34's HUMAN_REQUIRED durability branch is
   untouched; E11's `pause_mission`/`resume_mission` public APIs are untouched;
   no test in the repo depends on resuming INTO a paused state (verified by
   sweep of all `resume_from_checkpoint` consumers).

## What was explicitly NOT done

No skip, no xfail, no assertion relaxation, no hardcoded expectation, no mock,
no fixture substitution, no adapter simulating P1+P2, no new architecture, no
orchestration layer, no new agent model, no UI, no DependencyEngine production
integration, no legacy migration.

## Result

- E33 executed against real P1 `Unified ExecutionEngine` + P2
  `MissionController` (the runner subprocess is driven through the same public
  engine/controller APIs; no adapter in the path):
  **2 passed** (`test_e33_baseline_verification`, `test_e33_full_mission_autonomy`).
- Achieved proof inventory (isolated run root, preserved verbatim):
  3 runtimes (phase 2 killed: exit −9, not graceful) · CP1+CP2 durable ·
  4 injected failures recovered/replanned · plan v1→v2 (E,F invalidated; X
  added; G,H rewired) · resume ledger `NO_FALSE_REEXECUTION` · final state
  `EVIDENCED` (owner-gated VERIFIED not claimed) · acceptance matrix 14/14
  VERIFIED.
