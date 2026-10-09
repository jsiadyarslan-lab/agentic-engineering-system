#!/usr/bin/env python3
"""E10-RP2 session runner — executes the complete proof chain as REAL OS
processes and lands the durable evidence session under
E10/evidence_rp2/canonical/ (re-examinable, committed with the branch):

  resolution     — the full verification-truth cycle (§4.3/§4.4/§3.5)
  mixed_blocked  — the §4.2 mixed state (no false success)
  allow / deny-* / missing-* / tool-fail — the §4.1/§4.5 authorization cases

Every run goes through CanonicalOrchestrator.execute_mission with the REAL
EOE grant authorization (eoe.engine_bridge) — no allow-all test validator
anywhere in this session. Exit 0 iff every run's expectations pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
EVIDENCE = HERE / "evidence_rp2" / "canonical"
EXPECTATIONS = HERE / "evidence_rp2_expectations.json"

CYCLES = [("resolution", ["--mode", "resolution"]),
          ("mixed_blocked", ["--mode", "mixed-blocked"])]
AUTH = ["allow", "deny-revoked", "deny-read-only", "deny-path",
        "missing-validator", "missing-grants", "tool-fail"]


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    started = time.time()
    runs = []

    def run(script: str, extra: list, name: str) -> dict:
        out = EVIDENCE / name
        proc = subprocess.run(
            [sys.executable, str(HERE / script), *extra,
             "--out", str(out), "--expectations", str(EXPECTATIONS)],
            capture_output=True, text=True, timeout=600, cwd=str(REPO),
        )
        verdict = "UNKNOWN"
        for line in proc.stdout.splitlines():
            if line.startswith("[CYCLE") or line.startswith("[AUTH"):
                verdict = line.strip()
        entry = {
            "name": name, "script": script, "args": extra,
            "exit": proc.returncode, "verdict": verdict,
            "out_dir": str(out.relative_to(REPO)),
            "stdout_tail": proc.stdout[-1500:],
        }
        runs.append(entry)
        print(f"[RUNNER] {name}: exit={proc.returncode} | {verdict}")
        return entry

    for name, extra in CYCLES:
        run("e10rp2_cycle.py", extra, name)
    for case in AUTH:
        run("e10rp2_auth.py", ["--case", case], case)

    failed = [r for r in runs if r["exit"] != 0]
    runner = {
        "phase": "E10-RP2 — CANONICAL EXECUTION AUTHORIZATION & VERIFICATION TRUTH",
        "verdict": "E10RP2_CHAIN_PROVEN" if not failed else "E10RP2_CHAIN_FAILED",
        "runs": runs,
        "failed": [r["name"] for r in failed],
        "duration_s": round(time.time() - started, 1),
        "expectations": "E10/evidence_rp2_expectations.json (pre-registered)",
        "control_inputs": (
            "ScriptedDecomposerProvider (planning boundary) + decision "
            "providers (replanning decision boundary) — disclosed, decision "
            "boundaries only; everything else is production code under test. "
            "Authorization is the REAL EOE grants contract in every run."
        ),
    }
    (EVIDENCE / "runner.json").write_text(
        json.dumps(runner, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[RUNNER] verdict={runner['verdict']} runs={len(runs)} "
          f"failed={runner['failed']} duration={runner['duration_s']}s")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
