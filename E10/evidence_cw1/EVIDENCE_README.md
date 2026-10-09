# E10-CW1 Evidence — Crash-Window Idempotency Proof

## Layout

* `fixed/` — canonical proof run of the E10-CW1 code (branch
  `e10-cw1-crash-window-idempotency`). Session = 2 consecutive chains;
  each chain: Process A (SIGKILL inside the crash window) -> Process B
  (durable-only restore + reconciliation) -> independent verifier
  (VERIFIED, 9/9 mandatory checks).
* `baseline_gap/` — the SAME scenario, SAME harness, run against the
  **pre-fix** code at commit `50f5371e` (E10's final-report commit) via a
  detached git worktree. Both chains show the pre-existing failure the
  E10-CW1 order targets: the crash-window side effect IS re-performed
  after resume (`no_physical_rewrite=false` — the file is physically
  rewritten with a NEW artifact identity). This documents the pre-existing
  failure as-is; it is never a pass of E10-18.

## Reproducing the baseline run

```bash
git worktree add /tmp/cw1_baseline 50f5371e
cp E10/e10cw1_*.py E10/run_e10cw1.py /tmp/cw1_baseline/E10/
cd /tmp/cw1_baseline && python3 E10/run_e10cw1.py --mode baseline
```

## Key evidence files (per chain)

* `evidence/injection.json` — harness marker written immediately before the
  self-SIGKILL; proves the kill point (after the governed artifact write,
  before any durable completion record).
* `evidence/crash_window_snapshot.json` — runner's external OS-level stat of
  the side-effect file right after the crash: sha256 / mtime_ns / inode.
* `evidence/resume_info.json` — the ONLY object crossing the process
  boundary: resume identifiers (IDs), never state objects.
* `evidence/process_b.json` — restoration fidelity + side-effect accounting
  of the resumed process.
* `evidence/verifier.json` — independent verification (persistent state only).
* `evidence/chains.jsonl` — per-chain runner records (repeatability).
* `durable_artifacts/` — the actual durable storage of the run (copied from
  the session's `artifacts/`): `checkpoints/`, `events/`, `evidence_store/`,
  `sandbox-<task>/` side-effect files, `mc_state/`, and
  `side_effect_journal/<mission>/journal.jsonl` — the engine's durable
  side-effect journal (fsynced at write time). For chain 2 of the fixed run
  the journal shows TASK_D's `performed` record (PID 8182) followed by the
  `reconciled` record (PID 8183) with the SAME mtime_ns/inode and the SAME
  original artifact id — the exactly-once proof in durable form.
