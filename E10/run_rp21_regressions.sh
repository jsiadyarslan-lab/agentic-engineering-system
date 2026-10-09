#!/usr/bin/env bash
# E10-RP2.1 §5 — REQUIRED REGRESSION BATTERY (exact commands, exit codes,
# raw output tails recorded). Run from the RP2.1 worktree root.
set +e
OUT="$1"
mkdir -p "$(dirname "$OUT")"
: > "$OUT"

run() {
  local name="$1"; shift
  {
    echo "=== BATTERY: $name"
    echo "CMD: $*"
  } >> "$OUT"
  ( "$@" ) > /tmp/rp21_batt.log 2>&1
  local ec=$?
  {
    echo "EXIT: $ec"
    echo "--- output tail ---"
    tail -c 2600 /tmp/rp21_batt.log
    echo
    echo "=== END: $name"
    echo
  } >> "$OUT"
  echo "[$ec] $name"
}

# E10-RP2.1 note: `python3 E10/run_e10rp2.py` itself re-runs into the
# COMMITTED evidence dirs without cleaning them — a PRE-EXISTING harness
# idempotency flake (proven identical at baseline 631f6fb; see
# SESSION_RUNNER_BASELINE_FLAKE.txt). The session-equivalent coverage is
# therefore recorded as the 9 scenarios run into FRESH dirs (exactly what
# the RP2 matrix session fixture does — plus the matrix itself as its own
# battery row above).
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
      python3 "E10/$script" --case "$mode" --out "$outdir" --expectations E10/evidence_rp2_expectations.json > /tmp/rp21_batt.log 2>&1
    else
      python3 "E10/$script" --mode "$mode" --out "$outdir" --expectations E10/evidence_rp2_expectations.json > /tmp/rp21_batt.log 2>&1
    fi
    local ec=$?
    [ $ec -ne 0 ] && fails=$((fails+1))
    echo "  [$ec] $kind/$mode: $(grep -E '^\[(CYCLE|AUTH)' /tmp/rp21_batt.log | tail -1)" >> "$OUT"
  done
  rm -rf "$tmpd"
  {
    echo "EXIT: $fails"
    echo "=== END: RP2 session (fresh-dir equivalent)"
    echo
  } >> "$OUT"
  echo "[$fails] RP2 session (fresh-dir equivalent)"
}

cd /home/z/my-project/e10rp21_work || exit 1

run "RP2.1 matrix (new)" python3 -m pytest E10/test_e10rp21_matrix.py -p no:cacheprovider -q
run "RP2 matrix"         python3 -m pytest E10/test_e10rp2_matrix.py -p no:cacheprovider -q
session_fresh
run "RP1 matrix"         python3 -m pytest E10/test_e10rp1_matrix.py -p no:cacheprovider -q
run "E10-RP matrix"      python3 -m pytest E10/test_e10rp_matrix.py -p no:cacheprovider -q
run "E10/CW1 matrix"     python3 -m pytest E10/test_e10_matrix.py -p no:cacheprovider -q
run "E10-CW1-R1 matrix"  python3 -m pytest E10/test_e10r1_matrix.py -p no:cacheprovider -q
run "E9-R"               python3 E9-R/test_production_integration.py
run "E8 negative gates"  env PYTHONPATH=src python3 run_e8_human_gates.py
run "e3+e4"              python3 -m pytest tests/orchestrator/test_e3_canonical_orchestrator.py tests/orchestrator/test_e4_multi_task_mission.py -p no:cacheprovider -q
run "e6"                 python3 -m pytest tests/orchestrator/test_e6_durable_mission_orchestration.py -p no:cacheprovider -q
run "e33+e32f"           python3 -m pytest tests/unified/test_e33_mission_autonomy.py tests/unified/test_e32f_autonomous_replanning.py -p no:cacheprovider -q
run "e35"                env PYTHONPATH=src python3 tests/e35/test_long_mission.py
run "e37"                env PYTHONPATH=src python3 tests/e37/test_multi_task_mission.py

echo "ALL BATTERIES DONE -> $OUT"
