# E10-RP Canonical Evidence

One coherent, re-examinable proof run of the E10-RP chain (order §6:
re-examinable evidence — separate run results are recorded in the reports,
not mixed into this tree).

- Session: `/tmp/e10rp_m4go78oo` (runner pid R, participants pids 3546/3547/3548)
- Runner verdict: `E10RP_CHAIN_PROVEN`
- Independent verifier verdict: `E10RP_VERIFIED` (12/12 checks VERIFIED)
- Pre-registered expectations: `evidence/pre_registered_expectations.json`
  (written durably BEFORE any stage ran; success criteria never changed
  after observing outcomes — order §4)
- Phase records: `evidence/main_scenario.json`, `evidence/s2_scenario.json`
- OS facts: `evidence/runner.json` (PIDs, exit codes, walls)
- Durable engine trees: `main_artifacts/`, `s2_artifacts/`
  (events/, checkpoints/, side_effect_journal/, evidence_store/,
  sandbox-task-*/)
- Durable controller ledgers: `main_mc_state/`, `s2_mc_state/`
  (`mission_controller/<mission>/ledger.json` incl. failures, replans,
  **plan_reviews**)

Re-run the whole chain: `python3 E10/run_e10rp.py`
Re-run the matrix: `python3 -m pytest E10/test_e10rp_matrix.py -v`
