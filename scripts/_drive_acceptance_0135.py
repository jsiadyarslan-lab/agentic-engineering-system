#!/usr/bin/env python3
"""Drive the live 013.5 acceptance: own the server, then run the harness.

Why this file exists
====================
The acceptance harness (§P) refuses to run without a live server, and it must
not fake a result. Starting the server as a separate shell job proved fragile
here (the DSH sandbox restart killed it mid-run), so this driver starts the
server, waits for a real ``/health`` 200, runs the harness, and always tears
the server down.

Child stdout/stderr go to *files*, never pipes: the file sandbox denies
opening named pipes for piped stdio.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VENV_PY = REPO / ".venv" / "Scripts" / "python.exe"
LOGS = REPO / "runtime" / "logs"


def wait_for_health(base_url: str, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=3) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(1.0)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--planning-timeout", type=float, default=900.0)
    args = ap.parse_args()

    base_url = f"http://127.0.0.1:{args.port}"
    LOGS.mkdir(parents=True, exist_ok=True)
    srv_out = (LOGS / "srv-driver.out.log").open("w", encoding="utf-8", errors="replace")
    srv_err = (LOGS / "srv-driver.err.log").open("w", encoding="utf-8", errors="replace")

    server = subprocess.Popen(
        [str(VENV_PY), "-m", "uvicorn", "api.routes:app",
         "--host", "127.0.0.1", "--port", str(args.port)],
        cwd=str(REPO), stdout=srv_out, stderr=srv_err,
        env={**__import__("os").environ, "PYTHONUTF8": "1"},
    )
    print(f"[driver] server pid={server.pid} — waiting for health ...", flush=True)

    code = 1
    try:
        if not wait_for_health(base_url):
            print("[driver] server never became healthy — aborting", flush=True)
            return 4
        print("[driver] server healthy — running acceptance", flush=True)

        acc_out = (LOGS / "accept-driver.log").open("w", encoding="utf-8", errors="replace")
        proc = subprocess.run(
            [str(VENV_PY), str(REPO / "scripts" / "order0135_acceptance.py"),
             "--base-url", base_url, "--planning-timeout", str(args.planning_timeout)],
            cwd=str(REPO), stdout=acc_out, stderr=subprocess.STDOUT,
            env={**__import__("os").environ, "PYTHONUTF8": "1"},
        )
        acc_out.close()
        code = proc.returncode
        print(f"[driver] acceptance exit={code}", flush=True)
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
        srv_out.close()
        srv_err.close()
        print("[driver] server stopped", flush=True)

    # Echo the acceptance log so the caller sees the verdict in-band.
    log = REPO / "runtime" / "logs" / "accept-driver.log"
    if log.exists():
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(log.read_text(encoding="utf-8", errors="replace"))
    return code


if __name__ == "__main__":
    sys.exit(main())
