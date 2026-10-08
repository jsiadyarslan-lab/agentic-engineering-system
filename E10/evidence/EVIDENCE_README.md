# E10 Canonical Evidence Package

Produced by `E10/run_e10.py` at the E10 commit on Linux (Python 3.12.14).

The complete durable tree of the proof run is committed here so every claim
can be re-examined from OUTSIDE Process A and Process B (E10-27):

- `runner.json`        — OS-level facts witnessed by the parent process
                         (PIDs, SIGKILL exit code -9, stage exit codes)
- `resume_info.json`   — the ONLY information that crossed the process
                         boundary (IDs, no state objects)
- `process_a.json`     — Process A evidence: boundary states, pre-termination
                         attempt/artifact/evidence snapshots, on-disk
                         checkpoint assertion (hash recomputed from the file)
- `process_b.json`     — Process B evidence: restoration log + fidelity,
                         continuation results, side-effect accounting,
                         verify_completion + finalize_mission
- `tamper.json`        — negative test: mutated checkpoint REJECTED,
                         no task execution
- `verifier.json`      — independent verifier (separate OS process) verdict
                         over persistent state only: VERIFIED (14 checks)
- `durable_artifacts/` — the actual durable storage of the proof run:
                         checkpoints/, events/, evidence_store/,
                         sandbox-<task>/ output files, mc_state/ ledger

Reproduce with: `python3 E10/run_e10.py` (fresh temp workdir per run) or
`python3 -m pytest E10/test_e10_matrix.py -v` (T01..T20, reruns the chain).
