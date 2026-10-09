#!/usr/bin/env bash
# E10-RP2.2-R2-DISCOVERY — probe runner.
# Runs every discovery probe at the baseline commit and captures RAW
# stdout / stderr / exit code per probe under E10/evidence_rp22r2_discovery/probe_outputs/.
# Re-runnable: probes are self-contained (per-probe throwaway temp trees).
set -u
cd "$(dirname "$0")/.."

EV="E10/evidence_rp22r2_discovery/probe_outputs"
mkdir -p "$EV"

PROBES="G1 G2 G3 G4 G5 G6 S1 S2 S3 S4 X1 X2 A1 A2 O1"

echo "== E10-RP2.2-R2 probe runner: $(date -u +%Y-%m-%dT%H:%M:%SZ) ==" | tee "$EV/RUNNER_HEADER.txt"
echo "python: $(python3 --version 2>&1)" | tee -a "$EV/RUNNER_HEADER.txt"
echo "cwd: $(pwd)" | tee -a "$EV/RUNNER_HEADER.txt"

OVERALL=0
for p in $PROBES; do
  echo "--- running probe $p ---"
  python3 "E10/e10rp22r2_probes.py" --probe "$p" \
    > "$EV/PROBE_${p}.out" 2> "$EV/PROBE_${p}.err"
  rc=$?
  echo "$rc" > "$EV/PROBE_${p}.exit"
  echo "probe $p exit=$rc"
  if [ "$rc" -ne 0 ]; then OVERALL=1; fi
done

echo "OVERALL_EXIT=$OVERALL" | tee "$EV/RUNNER_SUMMARY.txt"
grep -h "RESULT\]" "$EV"/PROBE_*.out | tee -a "$EV/RUNNER_SUMMARY.txt"
exit $OVERALL
