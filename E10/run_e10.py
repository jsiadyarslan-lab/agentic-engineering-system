#!/usr/bin/env python3
"""E10 RUNNER — orchestrates the full cross-process proof as REAL OS processes:

    [RUNNER pid R]
       |-- subprocess A  (python e10_process_a.py workdir)  -> SIGKILLed (-9)
       |-- subprocess B  (python e10_process_b.py workdir)  -> exit 0
       |-- subprocess T  (python e10_tamper.py tamperdir)   -> exit 0 (rejection proven)
       `-- subprocess V  (python e10_verifier.py workdir)   -> exit 0 (VERIFIED)

Every stage records its own PID and timestamps; the runner additionally
witnesses the OS-level facts (PIDs, exit codes, wall times) from OUTSIDE any
of the participant processes. Exit code 0 == full E10 chain proven.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from e10_common import durable_write_json  # noqa: E402


def run_stage(name: str, script: str, workdir: Path, expect_rc: int):
    cmd = [sys.executable, str(HERE / script), str(workdir)]
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    pid = proc.pid
    out, _ = proc.communicate()
    rc = proc.returncode
    wall = round(time.time() - t0, 3)
    print(f"\n{'=' * 78}\n[{name}] pid={pid} exit={rc} wall={wall}s\n{'=' * 78}")
    print(out)
    return {
        "stage": name,
        "script": script,
        "command": cmd,
        "runner_observed_pid": pid,
        "exit_code": rc,
        "wall_seconds": wall,
        "stdout_tail": out[-2500:],
    }


def main() -> int:
    t0 = time.time()
    workdir = Path(tempfile.mkdtemp(prefix="e10_proof_"))
    evidence_dir = workdir / "evidence"
    print(f"[RUNNER] workdir={workdir}")

    stages = []

    # ---- PROCESS A: execute A/B/C, durable checkpoint, SIGKILL ----
    a = run_stage("PROCESS_A", "e10_process_a.py", workdir, expect_rc=-9)
    stages.append(a)
    if a["exit_code"] != -9:
        print(f"[RUNNER] FATAL: Process A did not die by SIGKILL (exit={a['exit_code']})")
        return 2

    # The OS-level death is witnessed here, from OUTSIDE process A.
    pa_pid = a["runner_observed_pid"]
    print(f"[RUNNER] Process A (pid {pa_pid}) terminated by SIGKILL — witnessed by runner")

    # ---- PROCESS B: new OS process, restore + resume ----
    b = run_stage("PROCESS_B", "e10_process_b.py", workdir, expect_rc=0)
    stages.append(b)
    if b["exit_code"] != 0:
        return 3
    pb_pid = b["runner_observed_pid"]
    if pb_pid == pa_pid:
        print("[RUNNER] FATAL: PID reuse across sequential processes is not plausible here")
        return 4

    # ---- TAMPER TEST on a copy of the post-A durable tree ----
    tamper_dir = workdir / "_tamper_copy"
    shutil.copytree(workdir / "artifacts", tamper_dir / "artifacts")
    shutil.copytree(evidence_dir, tamper_dir / "evidence")
    t = run_stage("TAMPER", "e10_tamper.py", tamper_dir, expect_rc=0)
    stages.append(t)
    if t["exit_code"] != 0:
        return 5
    # consolidate tamper evidence into the main evidence directory
    shutil.copy2(tamper_dir / "evidence" / "tamper.json", evidence_dir / "tamper.json")

    # ---- INDEPENDENT VERIFIER: separate OS process, persistent state only ----
    v = run_stage("VERIFIER", "e10_verifier.py", workdir, expect_rc=0)
    stages.append(v)
    if v["exit_code"] != 0:
        return 6

    # ---- collect runner-level evidence ----
    resume_info = json.loads((evidence_dir / "resume_info.json").read_text())
    pb = json.loads((evidence_dir / "process_b.json").read_text())
    runner_evidence = {
        "status": "E10_CHAIN_COMPLETE",
        "runner_pid": os.getpid(),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "workdir": str(workdir),
        "process_a": {
            "runner_observed_pid": pa_pid,
            "self_reported_pid": resume_info["process_a_pid"],
            "pid_match": pa_pid == resume_info["process_a_pid"],
            "start": resume_info["process_a_started_at"],
            "end": resume_info["process_a_ended_at"],
            "termination": "SIGKILL (runner observed exit code -9)",
        },
        "process_b": {
            "runner_observed_pid": pb_pid,
            "self_reported_pid": pb["process_b_pid"],
            "pid_match": pb_pid == pb["process_b_pid"],
            "start": pb["process_b_start_time"],
            "end": pb["process_b_end_time"],
        },
        "pid_difference": pb_pid != pa_pid,
        "stage_exit_codes": {s["stage"]: s["exit_code"] for s in stages},
        "stages": stages,
        "total_wall_seconds": round(time.time() - t0, 3),
    }
    durable_write_json(evidence_dir / "runner.json", runner_evidence)

    print(f"\n[RUNNER] E10 CHAIN COMPLETE: A(SIGKILL) -> B(resume) -> TAMPER(rejected) -> VERIFIER(verified)")
    print(f"[RUNNER] PID_A={pa_pid} PID_B={pb_pid} different={pb_pid != pa_pid}")
    return 0


if __name__ == "__main__":
    rc = main()
    sys.exit(rc)
