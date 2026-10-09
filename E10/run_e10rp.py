#!/usr/bin/env python3
"""E10-RP RUNNER — orchestrates the proof as REAL OS processes:

    [RUNNER pid R]
       |-- subprocess M (python e10rp_main.py  ...)  -> exit 0 (full cycle)
       |-- subprocess S (python e10rp_safety.py ...) -> exit 0 (S2 minimal scope)
       `-- subprocess V (python e10rp_verifier.py ..) -> exit 0 (VERIFIED)

The PRE-REGISTERED expectations are written durably BEFORE any stage runs
(order §4: expected decisions fixed before observing outcomes). The runner
witnesses OS-level facts (PIDs, exit codes, wall times) from OUTSIDE every
participant process. Exit code 0 == full E10-RP chain proven.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from e10rp_common import PRE_REGISTERED_EXPECTATIONS, durable_write_json  # noqa: E402


def run_stage(name: str, script: str, session: Path, expect_rc: int = 0) -> dict:
    cmd = [
        sys.executable, str(HERE / script),
        "--artifacts-dir", str(session / f"{name.lower()}_artifacts"),
        "--mc-state-dir", str(session / f"{name.lower()}_mc_state"),
        "--evidence-dir", str(session / "evidence"),
    ] if script != "e10rp_verifier.py" else [sys.executable, str(HERE / script), str(session)]
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    pid = proc.pid
    out, _ = proc.communicate()
    rc = proc.returncode
    wall = round(time.time() - t0, 3)
    print(f"\n{'=' * 78}\n[{name}] pid={pid} exit={rc} wall={wall}s\n{'=' * 78}")
    print(out[-4000:])
    return {
        "stage": name, "script": script, "command": cmd,
        "runner_observed_pid": pid, "exit_code": rc, "wall_seconds": wall,
        "stdout_tail": out[-2500:],
        "expected_rc": expect_rc,
        "rc_as_expected": rc == expect_rc,
    }


def main() -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    session = Path(tempfile.mkdtemp(prefix="e10rp_"))
    evidence_dir = session / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    print(f"[RUNNER] session={session}")

    # ---- PRE-REGISTRATION (before any execution; fixed success criteria) ----
    durable_write_json(evidence_dir / "pre_registered_expectations.json", {
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "note": "fixed BEFORE any stage ran; never changed after observing outcomes",
        **PRE_REGISTERED_EXPECTATIONS,
    })
    print("[RUNNER] pre-registered expectations written BEFORE any stage runs")

    stages = []

    m = run_stage("MAIN", "e10rp_main.py", session)
    stages.append(m)
    if not m["rc_as_expected"]:
        print("[RUNNER] FATAL: MAIN scenario failed")
        return 2

    s = run_stage("S2", "e10rp_safety.py", session)
    stages.append(s)
    if not s["rc_as_expected"]:
        print("[RUNNER] FATAL: S2 scenario failed")
        return 3

    v = run_stage("VERIFIER", "e10rp_verifier.py", session)
    stages.append(v)
    if not v["rc_as_expected"]:
        print("[RUNNER] FATAL: independent verifier REJECTED the chain")
        return 4

    pids = [st["runner_observed_pid"] for st in (m, s, v)]
    if len(set(pids)) != 3:
        print("[RUNNER] FATAL: PID reuse across sequential processes is not plausible")
        return 5

    durable_write_json(evidence_dir / "runner.json", {
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "session": str(session),
        "stages": stages,
        "distinct_pids": pids,
        "verdict": "E10RP_CHAIN_PROVEN",
    })
    print(f"\n[RUNNER] session={session}")
    print("[RUNNER] E10RP_CHAIN_PROVEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
