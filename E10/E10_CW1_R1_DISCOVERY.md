# E10-CW1-R1 DISCOVERY — ACTUAL CRASH BOUNDARIES IN THE GOVERNED artifact_write PATH

Code state: baseline `d8b0620eb22527ff88d8a39abafba0ade426c7c8` (branch `e10-cw1-r1-prejournal-crash`).
All line numbers refer to that tree. This document records the PROVEN operation
order (read from code, not assumed), and every independent crash window with
the expected disk/journal state at restore.

## 1. THE ACTUAL EXECUTION PATH

```
MissionTaskAgent.execute (mission_controller.py:281)
  -> ToolExecutor.execute_tool("artifact_write")          execution.py:375   [S1] contract+grants+gate, ACTION_REQUESTED, Action record
  -> ToolExecutor._execute_implementation                 execution.py:563   [S2] delegates sandbox tools to engine
  -> ExecutionEngine.execute_tool                          execution.py:2734  [S3] TOOL_STARTED; artifact_write branch at :2836
       resolve sandbox_id / content / path                 execution.py:2837-2843
       _reconcile_prior_side_effect                        execution.py:2986  [S4] journal lookup — EFFECTIVE records only ("performed"/"reconciled")
       (reconcile path)                                    execution.py:2852-2853 [S5] _artifact_from_journal + _journal_reconciliation — no rewrite
       (perform path) sandbox_manager.write_artifact       execution.py:2855  [S6]
         -> SandboxManager.write_artifact                  sandbox.py:327-346
         -> WindowsExecutorAdapter.write_artifact          windows_adapter.py:586-613
              makedirs                                     windows_adapter.py:593-597   [S6a]
              open(file,'wb'); write; close — NO fsync     windows_adapter.py:599-600   [S6b]  physical side effect (page cache)
              artifact_id = "artifact-"+uuid4  (AFTER write)  windows_adapter.py:603  [S6c]  identity NOT durable until [S7]
       _journal_performance                                execution.py:2861  [S7] stat + append "performed" + fsync file + fsync dir — FIRST durable outcome record
       artifact registry (in-memory)                       execution.py:2862-2873  [S8]
       _emit_artifact_created                              execution.py:2874→3108 [S9] ARTIFACT_CREATED (dedup vs in-memory history) + evidence + EVIDENCE_RECORDED
       TOOL_COMPLETED; return ToolResult                   execution.py:2875-2903 [S10]
agent completes                                            mission_controller.py:281-330
  TaskCompletedEvent + agent-layer ARTIFACT_CREATED RE-EMISSION  execution.py:2708-2731 [S11] (also :1640 variant) — NO dedup guard
checkpoint per task completion                             execution.py:3454-3543 [S12] task_states+attempts + _save_events_to_disk + evidence save + checkpoint json (hash)
```

## 2. INDEPENDENT CRASH WINDOWS (proven order; what a SIGKILL between consecutive steps leaves behind)

| Window | Between | File on disk | Journal | Durable events | Resume behavior at baseline | Verdict |
|---|---|---|---|---|---|---|
| W0 | before S6b (mid-write) | partial or absent | nothing | none | lookup → None → treated as NEW → fresh overwrite | no intent record: "never started" indistinguishable from "died mid-write"; partial file silently overwritten |
| **W1** | **S6b done → S7 (write COMPLETE, `performed` NOT yet appended)** | **EXISTS** (page cache; survives SIGKILL) | **nothing for this op** | none | **lookup → None → RE-PERFORMS: file rewritten (mtime_ns changes), NEW artifact_id, effect executed twice** | **THE GAP (order §2) — previous proof never killed here** |
| W2 | S7 → S9 | EXISTS | `performed` | none | lookup → performed → reconcile, no rewrite | OK (CW1 contract) |
| W3 | S9 → S12 | EXISTS | `performed` | ARTIFACT_CREATED only in A's memory | B reconciles; dedup guard misses (event never durable) → B emits once → durable log ends with exactly 1 | OK — **previous CW1 injection point was HERE (at the S9 emission), i.e. AFTER `performed`** |
| W4 | S12 → mission end | EXISTS | `performed` | task.completed + ARTIFACT_CREATED durable | skip-completed | OK (E10) |

**W1 is unproven and unsafe at baseline.** `SideEffectJournal.lookup`
(execution.py:319-320) only indexes `EFFECTIVE_RECORD_TYPES = ("performed",
"reconciled")` — absence of a record is treated as a NEW operation
(execution.py:2850→2854-2861). A crash in W1 leaves the file on disk with NO
journal record, so Process B re-performs the physical write.

**The previous CW1 proof (e10cw1_process_a.py) killed at the ARTIFACT_CREATED
emission** — which happens at [S9], AFTER `_journal_performance` [S7] already
fsynced. It therefore proved W2/W3, never W1. The `performed` record can never
be evidence for closing the window that precedes its own write.

## 3. THE ARTIFACT_CREATED CONTRADICTION (order §6)

Committed CW1 evidence (E10/evidence_cw1/fixed/chain2) shows TWO
ARTIFACT_CREATED events for the SAME artifact_id on EVERY task — including
tasks that never crashed (all ~0.5 ms apart, same run):

* [S9] tool layer: `_emit_artifact_created` (dedup vs in-memory history only)
* [S11] agent layer: unconditional re-emission at execution.py:2708-2731 and :1640

The CW1 verifier codified `len(d_artifact_created_events) == 2` as expected
("normal engine pattern"), while the CW1 report simultaneously claims "no
duplicate ARTIFACT_CREATED event" (section B) and misattributes the second
copy to "pre-crash durable + restored copy" (section D) — factually wrong:
both events in the final log were emitted by Process B (same run_id, both
post-resume; the pre-crash in-memory copy died with Process A).

## 4. OTHER RECONCILIATION-RELEVANT FACTS

* Exceptions inside `ExecutionEngine.execute_tool` are converted to failed
  `ToolResult(error_type=<ExceptionClass>)` (execution.py:2933-2956) — the
  fail-closed channel for reconciliation/corruption errors.
* `SideEffectJournal._load` (execution.py:298-317) ignores ANY unparseable
  line — including a corrupt line in the MIDDLE of the file (a prior record
  that may be the only proof of a proven effect). Order §4-CW1-R1-D forbids
  this: corruption of a prior record must fail closed.
* The adapter does not fsync the artifact file (windows_adapter.py:599-600);
  only the journal is fsynced. Durable-write guarantee limits must be stated.
* Direct `sandbox_manager.write_artifact` callers (operational.py,
  agent_role.py, mission_controller E33 fixture) bypass the governed branch —
  unaffected by intent-first journaling (legacy behavior preserved).
