# E10-CW1-R1 EVIDENCE — Intent-First Journal & Pre-Journal Crash Proof

**Executive order:** E10-CW1-R1 (mandatory remaining processing after `E10_CW1_CONDITIONAL`)
**Baseline:** `d8b0620eb22527ff88d8a39abafba0ade426c7c8`
**Branch:** `e10-cw1-r1-prejournal-crash` (not merged to `main`)
**Harness:** `E10/e10cw1r1_*.py`, `E10/run_e10cw1r1.py`, matrix `E10/test_e10r1_matrix.py`

## Layout

```
canonical_r1/                     one full session: 6 scenarios x 2 chains
  <SCENARIO>/chain<N>/
    evidence/                     injection.json, crash_window_snapshot.json,
                                  resume_info.json (IDs only), corruption.json
                                  (D scenarios), process_b.json, verifier.json
    durable_artifacts/            side_effect_journal/<mission>/journal.jsonl,
                                  events/<mission>/event_log.jsonl,
                                  evidence_store/<mission>/{artifacts,evidence}.json,
                                  checkpoints/<mission>/*.json,
                                  sandbox-*/task_*_output.txt, mc_state ledger
  evidence/runner.json + chains.jsonl   session consolidation
baseline_gap_demo/                the order §2 gap, EMPIRICALLY demonstrated
  baseline/                       against a detached worktree of the BASELINE
                                  commit d8b0620 (A exit -9 = real SIGKILL at
                                  the exact R1-B boundary; B re-performs the
                                  write: mtime_ns changes, fresh artifact id —
                                  GAP_DEMONSTRATED__SIDE_EFFECT_EXECUTED_TWICE;
                                  never a pass of any acceptance criterion)
  fixed_control/                  same boundary on the FIXED tree: adoption
                                  without rewrite, identity preserved
  GAP_DEMO_SUMMARY.json
```

## Scenario map (which crash window each one actually kills in)

| Scenario | Injection point (real boundary) | Journal at kill | File at kill | Required resume behavior |
|---|---|---|---|---|
| A | after durable `intent`, before physical write | intent | absent | effect provably never happened → perform ONCE with the PLANNED identity; performed(direct); NO reconciliation event |
| B | after physical write (fsynced adapter), before `_journal_performance` — **the order §2 gap** | intent | present | DETECT + ADOPT without rewrite; performed(adopted_after_crash, performed_by_pid=A); ARTIFACT_RECONCILED(intent_adoption) |
| C | after durable `performed`, at ARTIFACT_CREATED emission, before completion (the CW1 window) | intent+performed | present | reconcile from performed; no rewrite (CW1 behavior retained) |
| D1 | B boundary + torn TRAILING journal line (corruptor) | intent + torn tail | present | ignore torn tail (never durable truth); adopt via intent; append truncates the tail (self-heal) |
| D2a | B boundary + trailing intent line byte-corrupted to invalid JSON | (intent destroyed) | present | unreconcilable ambiguity → explicit fail-closed SideEffectReconciliationError; file NEVER overwritten |
| D2b | C boundary + MIDDLE prior record (TASK_C performed) byte-corrupted | intent+performed (+ corrupt middle) | present | journal corruption that may hide a proven effect → SideEffectJournalCorruptionError; NOTHING appended, NOTHING re-performed |

Every chain: Process A and Process B are separate OS processes (runner-witnessed
PIDs, B != A, verifier a third PID); the kill is a real SIGKILL (exit -9); only
IDENTIFIERS cross the process boundary (resume_info.json); the independent
verifier reads persistent state only and never imports the engine.
