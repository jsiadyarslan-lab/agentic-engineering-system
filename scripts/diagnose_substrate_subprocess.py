# -*- coding: utf-8 -*-
"""تشخيص مباشر: هل يعمل subprocess داخل ركيزة العامل؟ (013.16)

يقارن بين المسارين بنفس السكربت: ركيزة محلية مباشرة (LocalSandboxBackend)
وعبر عامل حي (وضع substrate) — لعزل مصدر Errno 11 في جلسة E11.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

WORK = Path("/home/z/my-project/order01316_work")
sys.path.insert(0, str(WORK / "src"))
sys.path.insert(0, str(WORK))

TOKEN_FILE = Path("/home/z/my-project/.order01316_worker_token")

SUBPROCESS_PROBE = """
import subprocess, sys
try:
    proc = subprocess.run(
        [sys.executable, "-c", "print('child ok')"],
        capture_output=True, text=True, timeout=20,
    )
    print("SUBPROCESS_OK rc=", proc.returncode, "out=", proc.stdout.strip())
except OSError as error:
    print("SUBPROCESS_FAIL errno=", error.errno, "msg=", error)
"""

SPAWN_PROBE = """
import os
try:
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)
    print("FORK_OK")
except OSError as error:
    print("FORK_FAIL errno=", error.errno, "msg=", error)
"""


def local_path() -> None:
    print("=== local substrate (LocalSandboxBackend) ===")
    from execution.backends import LocalSandboxBackend

    backend = LocalSandboxBackend()
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        for name, code in (("subprocess", SUBPROCESS_PROBE),
                           ("fork", SPAWN_PROBE)):
            out = backend.run_code(
                code, workspace=Path(tmp) / "ws",
                artifacts=Path(tmp) / "art", timeout_s=60,
            )
            print(f"[local:{name}] exit={out.exit_code} "
                  f"stdout={out.stdout.strip()[:120]!r}")


def worker_path() -> None:
    print("=== worker substrate (REMOTE /run) ===")
    import urllib.request

    token = TOKEN_FILE.read_text().strip()
    worker = subprocess.Popen(
        [str(WORK / ".venv/bin/python"), "scripts/execution_worker.py",
         "--port", "8901", "--host", "127.0.0.1", "--token", token],
        cwd=WORK, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(2)
        for name, code in (("subprocess", SUBPROCESS_PROBE),
                           ("fork", SPAWN_PROBE)):
            req = urllib.request.Request(
                "http://127.0.0.1:8901/run",
                data=json.dumps({"run_id": f"probe-{name}", "code": code,
                                 "timeout_s": 60}).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {token}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                result = json.loads(resp.read().decode())
            print(f"[worker:{name}] exit={result.get('exit_code')} "
                  f"stdout={str(result.get('stdout', '')).strip()[:120]!r} "
                  f"stderr_head={str(result.get('stderr', ''))[:100]!r}")
    finally:
        worker.terminate()
        worker.wait(timeout=10)


if __name__ == "__main__":
    local_path()
    worker_path()
