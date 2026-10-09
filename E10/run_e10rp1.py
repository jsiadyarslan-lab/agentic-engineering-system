#!/usr/bin/env python3
"""E10-RP1 RUNNER — orchestrates the proof as REAL OS processes:

    [RUNNER pid R]
       |-- subprocess FULL    (python e10rp1_cycle.py --mode full)     -> exit 0
       |-- subprocess BLOCKED (python e10rp1_cycle.py --mode blocked)  -> exit 0
       `-- subprocess PROBE   (python e10rp1_restore_probe.py ...)     -> refused=true

The PRE-REGISTERED expectations are written durably BEFORE any cycle runs
(order §4 discipline — fixed before observing outcomes). The runner
witnesses OS-level facts (PIDs, exit codes, wall times) from OUTSIDE every
participant process. Exit code 0 == E10RP1_CHAIN_PROVEN.

Prints one '[RUNNER] session=<path>' line for the test-matrix fixture.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

from e10rp1_common import (  # noqa: E402
    PRE_REGISTERED_EXPECTATIONS, durable_write_json,
)


def run_stage(name: str, cmd: list, session: Path) -> dict:
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    pid = proc.pid
    out, _ = proc.communicate()
    rc = proc.returncode
    wall = round(time.time() - t0, 3)
    print(f"\n{'=' * 78}\n[{name}] pid={pid} exit={rc} wall={wall}s\n{'=' * 78}")
    print(out[-6000:])
    return {"name": name, "pid": pid, "exit": rc, "wall_s": wall,
            "rc_as_expected": rc == 0}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    session = (Path(args.out).resolve() if args.out
               else HERE / "evidence_rp1" / datetime.now(timezone.utc).strftime("rp1-%Y%m%dT%H%M%SZ"))
    session.mkdir(parents=True, exist_ok=True)
    ev_dir = session / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)

    # Pre-registration FIRST (durably, before any participant runs)
    pre = dict(PRE_REGISTERED_EXPECTATIONS)
    pre["written_at"] = datetime.now(timezone.utc).isoformat()
    pre["written_before_any_cycle"] = True
    durable_write_json(ev_dir / "pre_registered.json", pre)

    stages = [
        run_stage("FULL", [sys.executable, str(HERE / "e10rp1_cycle.py"),
                           "--mode", "full", "--out", str(session / "full"),
                           "--expectations", str(ev_dir / "pre_registered.json")], session),
        run_stage("BLOCKED", [sys.executable, str(HERE / "e10rp1_cycle.py"),
                              "--mode", "blocked", "--out", str(session / "blocked"),
                              "--expectations", str(ev_dir / "pre_registered.json")], session),
    ]

    # §4 fresh-process restoration probe against the FULL cycle's durable state
    facts = json.loads((session / "full" / "facts.json").read_text(encoding="utf-8"))
    probe = run_stage("RESTORE_PROBE", [
        sys.executable, str(HERE / "e10rp1_restore_probe.py"),
        str(session / "full"), facts["mission_id"], facts["run_id"],
    ], session)
    try:
        probe_payload = json.loads((session / "full" / "restore_probe.json").read_text(encoding="utf-8"))
    except Exception:
        probe_payload = {}
    probe["refused_fail_closed"] = bool(probe_payload.get("continuation", {}).get("refused"))
    probe["durable_ledger_on_disk"] = probe_payload.get("durable_ledger_on_disk", {})
    probe["fresh_controller_state"] = probe_payload.get("fresh_controller_state", {})

    distinct_pids = {s["pid"] for s in stages} | {probe["pid"]}
    ok = all(s["rc_as_expected"] for s in stages) and probe["refused_fail_closed"]
    runner = {
        "session": str(session),
        "started_at": pre["written_at"],
        "stages": stages,
        "distinct_pids": sorted(distinct_pids),
        "verdict": "E10RP1_CHAIN_PROVEN" if ok else "E10RP1_CHAIN_FAILED",
    }
    durable_write_json(ev_dir / "runner.json", runner)
    print(f"\n[RUNNER] session={session}")
    print(f"[RUNNER] verdict={runner['verdict']} stages={[s['exit'] for s in stages]} "
          f"probe_refused={probe['refused_fail_closed']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
