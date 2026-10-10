#!/usr/bin/env bash
# E10-RP2.2-R2A §5 — REQUIRED REGRESSION BATTERY (exact commands, exit
# codes, raw output tails recorded). Runs from the R2A worktree root
# (derived from this script's location). Rows identical to the certified
# R2 battery, with the NEW R2A matrix first.
#
# Two-state comparison: run this SAME script with
# R2A_INCLUDE_NEW_MATRIX=0 in a throwaway worktree at the designated
# baseline b983488 (where test_e10rp22r2a_matrix.py does not exist); the
# comparison covers the SHARED rows. NOTE (disclosed): the R2 matrix row
# exists at BOTH trees but its T03 was AMENDED on this branch to the R2A
# push-destination contract (order §3.1) — the comparison is on exit
# codes + failure-name sets (0 == 0 expected); the content amendment is
# documented in E10_RP22R2A_REPORT.md.
set +e
OUT="$1"
if [ -z "$OUT" ]; then
  echo "usage: $0 <output-file>" >&2
  exit 2
fi
cd "$(dirname "$0")/.." || exit 1
mkdir -p "$(dirname "$OUT")"
: > "$OUT"

run() {
  local name="$1"; shift
  {
    echo "=== BATTERY: $name"
    echo "CMD: $*"
  } >> "$OUT"
  ( "$@" ) > /tmp/rp22r2a_batt.log 2>&1
  local ec=$?
  {
    echo "EXIT: $ec"
    echo "--- output tail ---"
    tail -c 2600 /tmp/rp22r2a_batt.log
    echo
    echo "=== END: $name"
    echo
  } >> "$OUT"
  echo "[$ec] $name"
}

session_fresh() {
  {
    echo "=== BATTERY: RP2 session (fresh-dir equivalent)"
    echo "CMD: python3 E10/e10rp2_cycle.py / e10rp2_auth.py into fresh temp dirs (session-equivalent)"
  } >> "$OUT"
  local fails=0
  local tmpd=$(mktemp -d)
  for spec in "cycle:resolution" "cycle:mixed-blocked" \
              "auth:allow" "auth:deny-revoked" "auth:deny-read-only" \
              "auth:deny-path" "auth:missing-validator" \
              "auth:missing-grants" "auth:tool-fail"; do
    local kind="${spec%%:*}"; local mode="${spec#*:}"
    local script="e10rp2_cycle.py"; [ "$kind" = "auth" ] && script="e10rp2_auth.py"
    local outdir="$tmpd/$kind-$mode"
    if [ "$kind" = "auth" ]; then
      python3 "E10/$script" --case "$mode" --out "$outdir" --expectations E10/evidence_rp2_expectations.json > /tmp/rp22r2a_batt.log 2>&1
    else
      python3 "E10/$script" --mode "$mode" --out "$outdir" --expectations E10/evidence_rp2_expectations.json > /tmp/rp22r2a_batt.log 2>&1
    fi
    local ec=$?
    [ $ec -ne 0 ] && fails=$((fails+1))
    echo "  [$ec] $kind/$mode: $(grep -E '^\[(CYCLE|AUTH)' /tmp/rp22r2a_batt.log | tail -1)" >> "$OUT"
  done
  rm -rf "$tmpd"
  {
    echo "EXIT: $fails"
    echo "=== END: RP2 session (fresh-dir equivalent)"
    echo
  } >> "$OUT"
  echo "[$fails] RP2 session (fresh-dir equivalent)"
}

# NEW R2A coverage first (skipped for the two-state baseline run at
# b983488, where this file does not exist: the comparison covers the
# SHARED rows), then the full inherited battery INCLUDING the R2 matrix
# (amended T03 — disclosed).
if [ "${R2A_INCLUDE_NEW_MATRIX:-1}" = "1" ]; then
  run "R2A matrix (new)"   python3 -m pytest E10/test_e10rp22r2a_matrix.py -p no:cacheprovider -q
fi
run "R2 matrix"          python3 -m pytest E10/test_e10rp22r2_matrix.py -p no:cacheprovider -q
run "R1 matrix"          python3 -m pytest E10/test_e10rp22r1_matrix.py -p no:cacheprovider -q
run "RP2.2 matrix"       python3 -m pytest E10/test_e10rp22_matrix.py -p no:cacheprovider -q
run "RP2.1 matrix"       python3 -m pytest E10/test_e10rp21_matrix.py -p no:cacheprovider -q
run "RP2 matrix"         python3 -m pytest E10/test_e10rp2_matrix.py -p no:cacheprovider -q
session_fresh
run "RP1 matrix"         python3 -m pytest E10/test_e10rp1_matrix.py -p no:cacheprovider -q
run "E10-RP matrix"      python3 -m pytest E10/test_e10rp_matrix.py -p no:cacheprovider -q
run "E10/CW1 matrix"     python3 -m pytest E10/test_e10_matrix.py -p no:cacheprovider -q
run "E10-CW1-R1 matrix"  python3 -m pytest E10/test_e10r1_matrix.py -p no:cacheprovider -q
run "E9-R"               python3 E9-R/test_production_integration.py
run "E8 negative gates"  env PYTHONPATH=src python3 run_e8_human_gates.py
run "vs001+vs002+vs003+vs004+e32e (sandbox/execution layers)" python3 -m pytest tests/unified/test_vs001_simple.py tests/unified/test_vs001_integration.py tests/unified/test_vs002.py tests/unified/test_vs002_e8.py tests/unified/test_vs002_r1.py tests/unified/test_vs003.py tests/unified/test_vs004_graph.py tests/unified/test_e32e_durable_execution.py -p no:cacheprovider -q
run "e3+e4"              python3 -m pytest tests/orchestrator/test_e3_canonical_orchestrator.py tests/orchestrator/test_e4_multi_task_mission.py -p no:cacheprovider -q
run "e6"                 python3 -m pytest tests/orchestrator/test_e6_durable_mission_orchestration.py -p no:cacheprovider -q
run "e33+e32f"           python3 -m pytest tests/unified/test_e33_mission_autonomy.py tests/unified/test_e32f_autonomous_replanning.py -p no:cacheprovider -q
run "e35"                env PYTHONPATH=src python3 tests/e35/test_long_mission.py
run "e37"                env PYTHONPATH=src python3 tests/e37/test_multi_task_mission.py

echo "ALL BATTERIES DONE -> $OUT"
