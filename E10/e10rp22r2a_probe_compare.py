#!/usr/bin/env python3
"""E10-RP2.2-R2A — probe re-run comparison vs the committed postfix
evidence (b983488).

Compares, per probe:
  * exit codes — must be IDENTICAL (same probes non-zero as at b983488);
  * normalized .out content — random temp-dir tokens and the worktree
    path prefix are masked (mkdtemp suffixes and the different worktree
    directory names make byte-identity impossible across worktrees);
    after masking, .out must be IDENTICAL.
  * .err files contain Python tracebacks (worktree paths + source line
    numbers legitimately differ between trees); they are NOT part of the
    identity claim — only the exception TYPE + message line are compared.

Verdict discipline: this is supplementary evidence (order §5 lists the
matrix + battery; the probes are re-run to prove no GAP reopened). The
six non-zero probes stay DECLARED NOT GREEN exactly as at b983488.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

NEW = Path(sys.argv[1])   # evidence_rp22r2a/probe_outputs_rerun
OLD = Path(sys.argv[2])   # evidence_rp22r2/probe_outputs_postfix

PROBES = ["G1", "G2", "G3", "G4", "G5", "G6", "S1", "S2", "S3", "S4",
          "X1", "X2", "A1", "A2", "O1"]


def norm_out(text: str) -> str:
    # worktree path prefixes (different worktrees between runs)
    text = re.sub(r"/home/z/my-project/e10rp22r2[a-z]*_work", "<WORKTREE>", text)
    # random mkdtemp suffixes (probe temp trees)
    text = re.sub(r"/tmp/r2[a-z0-9]*-[A-Za-z0-9_]+", "/tmp/R2TMP", text)
    text = re.sub(r"/tmp/[A-Za-z0-9_.-]*r2probe-[A-Za-z0-9_]+", "/tmp/R2TMP", text)
    # random engine identifiers (grant/mission/run/task/attempt/decision/
    # checkpoint/sandbox ids are uuid-hex derived per run)
    text = re.sub(r"\b(grant|mission|run|task|attempt|action|decision|checkpoint|"
                  r"sandbox|push|event|evidence|artifact)-[0-9a-f]{6,}\b",
                  r"\1-RAND", text)
    # fresh throwaway-repo commit shas (git commit sha depends on the
    # timestamp — differs between runs of the same probe)
    text = re.sub(r"\blog='[0-9a-f]{7,40}\b", "log='SHA", text)
    text = re.sub(r"\b[0-9a-f]{40}\b", "SHA40", text)
    return text


def err_signature(text: str) -> str:
    """Exception type + message of the FINAL traceback, plus every
    'PermissionError: ...' line — the semantic content of the failure."""
    lines = [l for l in text.splitlines() if l.strip()]
    sig = []
    for l in lines:
        if re.match(r"^[A-Za-z_.]+(Error|Exception|Rejected)\s*:", l):
            sig.append(l.strip())
    return "\n".join(sig)


identical_out, identical_exit, identical_err = 0, 0, 0
diffs = []
for p in PROBES:
    old_exit = (OLD / f"PROBE_{p}.exit").read_text().strip()
    new_exit = (NEW / f"PROBE_{p}.exit").read_text().strip()
    ex_ok = old_exit == new_exit
    identical_exit += ex_ok

    old_out = norm_out((OLD / f"PROBE_{p}.out").read_text(encoding="utf-8", errors="replace"))
    new_out = norm_out((NEW / f"PROBE_{p}.out").read_text(encoding="utf-8", errors="replace"))
    out_ok = old_out == new_out
    identical_out += out_ok

    old_err = err_signature((OLD / f"PROBE_{p}.err").read_text(encoding="utf-8", errors="replace"))
    new_err = err_signature((NEW / f"PROBE_{p}.err").read_text(encoding="utf-8", errors="replace"))
    err_ok = old_err == new_err
    identical_err += err_ok

    status = "OK" if (ex_ok and out_ok and err_ok) else "DIFF"
    print(f"[{status}] {p}: exit {old_exit}->{new_exit} out={'same' if out_ok else 'DIFF'} "
          f"err-sig={'same' if err_ok else 'DIFF'}")
    if status == "DIFF":
        diffs.append(p)
        if not out_ok:
            import difflib
            for line in list(difflib.unified_diff(
                    old_out.splitlines(), new_out.splitlines(),
                    "b983488", "r2a", lineterm=""))[:20]:
                print("    " + line)

print(f"\nexit identical: {identical_exit}/{len(PROBES)}; "
      f"normalized .out identical: {identical_out}/{len(PROBES)}; "
      f"err signature identical: {identical_err}/{len(PROBES)}")
sys.exit(0 if not diffs else 1)
