#!/usr/bin/env python3
"""R2A2 §5 — TWO-STATE battery comparison: this branch (74c8ec1 + R2A2)
vs the designated baseline 74c8ec1, on the SHARED rows.

Comparison = exit codes + failure-name sets (the pytest failure names of
non-zero rows must be IDENTICAL sets — a new failure name on this branch
would be a NEW regression). This branch amends NO test content (order
§3.7: no pre-existing test modified; the R2A2 change is production code
+ NEW files only) — so the AMENDED set is EMPTY and every shared row must
match without any content-amendment flag.
"""
import json
import re
import sys

BRANCH = "E10/evidence_rp22r2a2/REGRESSIONS_BRANCH.txt"
BASELINE = "/tmp/r2a2_baseline_battery.txt"

AMENDED: set = set()  # no content-amended rows this round (disclosed)


def parse(path):
    rows = {}
    text = open(path, encoding="utf-8").read()
    for block in text.split("=== BATTERY: ")[1:]:
        name = block.split("\n", 1)[0].strip()
        m = re.search(r"^EXIT: (\d+)$", block, re.M)
        ec = int(m.group(1)) if m else None
        fails = sorted(set(re.findall(r"^FAILED (\S+)", block, re.M)))
        rows[name] = {"exit": ec, "failures": fails}
    return rows


def main():
    branch = parse(BRANCH)
    base = parse(BASELINE)
    shared = [k for k in base if k in branch]
    out = {
        "baseline": "74c8ec12122df759bec5688f2980e181ea8976bb",
        "branch_rows": len(branch),
        "baseline_rows": len(base),
        "shared_rows": len(shared),
        "rows": [],
        "overall_two_state": 0,
    }
    diffs = 0
    for name in shared:
        b, s = branch[name], base[name]
        same_ec = b["exit"] == s["exit"]
        same_fails = b["failures"] == s["failures"]
        ok = same_ec and same_fails
        if not ok:
            diffs += 1
        out["rows"].append({
            "row": name,
            "baseline_exit": s["exit"], "branch_exit": b["exit"],
            "baseline_failures": s["failures"], "branch_failures": b["failures"],
            "exit_match": same_ec, "failure_sets_match": same_fails,
            "content_amended_on_branch": name in AMENDED,
            "row_status": "IDENTICAL" if ok else "DIVERGENT",
        })
    out["overall_two_state"] = diffs
    out["verdict"] = (
        "NO NEW REGRESSION (all shared rows identical exit codes and "
        "failure-name sets; zero content-amended rows this round)"
        if diffs == 0 else f"{diffs} DIVERGENT ROW(S)"
    )
    dst = "E10/evidence_rp22r2a2/TWO_STATE_BASELINE.json"
    if len(sys.argv) > 1:
        dst = sys.argv[1]
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    for r in out["rows"]:
        flag = " [CONTENT-AMENDED]" if r["content_amended_on_branch"] else ""
        print(f"{r['row_status']:10s} {r['baseline_exit']}=={r['branch_exit']}{flag}  {r['row']}")
        if r["row_status"] == "DIVERGENT":
            print(f"           base fails: {r['baseline_failures']}")
            print(f"           branch fails: {r['branch_failures']}")
    print(f"\nOVERALL_TWO_STATE = {out['overall_two_state']} — {out['verdict']}")


if __name__ == "__main__":
    main()
