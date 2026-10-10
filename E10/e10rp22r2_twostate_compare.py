#!/usr/bin/env python3
"""E10-RP2.2-R2 §6.2 — TWO-STATE battery comparison.

Compares the regression battery run on the R2 execution tree against the
SAME battery run in a throwaway worktree at the designated baseline
0945960 (shared rows only — the R2 matrix does not exist at the baseline).
Comparison discipline (inherited from R1): per-row EXIT codes AND
failure-name sets must be IDENTICAL. Matching failure sets do NOT make a
non-zero row green (order §6.4).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BRANCH = Path(sys.argv[1])          # REGRESSIONS_BRANCH.txt (R2 tree, includes R2 row)
BASE = Path(sys.argv[2])            # REGRESSIONS_BASELINE_0945960.txt (throwaway worktree)
OUT = Path(sys.argv[3])             # TWO_STATE_BASELINE.json


def parse(path: Path) -> dict:
    rows: dict[str, dict] = {}
    cur = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^=== BATTERY: (.+)$", line)
        if m:
            cur = m.group(1)
            rows[cur] = {"exit": None, "failed": [], "tail": ""}
            continue
        if cur is None:
            continue
        m = re.match(r"^EXIT: (-?\d+)$", line)
        if m:
            rows[cur]["exit"] = int(m.group(1))
            continue
        m = re.match(r"^(FAILED|ERROR) (\S+)", line)
        if m:
            name = m.group(2).strip()
            # normalize random temp-path prefixes only (pytest node ids keep test names)
            rows[cur]["failed"].append(name)
    return rows


branch = parse(BRANCH)
base = parse(BASE)

shared = [r for r in base if r in branch]
result = {
    "branch_file": str(BRANCH),
    "baseline_file": str(BASE),
    "baseline_commit": "0945960427e833522789903e87a64b73c207bccd",
    "rows_compared": len(shared),
    "rows": {},
    "exit_codes_identical": True,
    "failure_sets_identical": True,
    "overall_two_state": 0,
}
for row in shared:
    b, s = branch[row], base[row]
    exit_same = b["exit"] == s["exit"]
    fail_b = sorted(set(b["failed"]))
    fail_s = sorted(set(s["failed"]))
    fail_same = fail_b == fail_s
    if not exit_same:
        result["exit_codes_identical"] = False
    if not fail_same:
        result["failure_sets_identical"] = False
    result["rows"][row] = {
        "exit_branch": b["exit"], "exit_baseline": s["exit"],
        "exit_identical": exit_same,
        "failed_branch": fail_b, "failed_baseline": fail_s,
        "failure_set_identical": fail_same,
    }
    print(f"[{'OK' if exit_same and fail_same else 'DIFF'}] exit {s['exit']}->{b['exit']} "
          f"fails {len(fail_s)}->{len(fail_b)}  {row}")

new_rows = [r for r in branch if r not in base]
result["rows_only_on_branch"] = new_rows
result["overall_two_state"] = 0 if (
    result["exit_codes_identical"] and result["failure_sets_identical"]) else 1
result["note"] = (
    "Non-zero rows stay DECLARED NOT GREEN (order §6.4): identical exit codes "
    "and identical failure-name sets prove NO NEW REGRESSION, not battery "
    "greenness. Rows only on the branch (the new R2 matrix) cannot exist at "
    "the baseline and are excluded from the comparison; they are green on "
    "the branch (see REGRESSIONS_BRANCH.txt)."
)

OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nOVERALL_TWO_STATE={result['overall_two_state']} "
      f"(exit codes identical: {result['exit_codes_identical']}, "
      f"failure sets identical: {result['failure_sets_identical']})")
sys.exit(result["overall_two_state"])
