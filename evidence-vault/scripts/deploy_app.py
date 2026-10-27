#!/usr/bin/env python3
"""AES-006 Phase 3a: ff-merge to release, import smoke test, restart service.

Order of operations (fail-safe):
  1. merge --ff-only FETCH_HEAD, verify HEAD == b38dbaf
  2. import smoke test in service-equivalent env (BEFORE touching service)
     - if it fails: auto-rollback the merge via checkout of previous SHA (detached),
       service never restarted, exit with error
  3. sudo systemctl restart agentic.service
  4. verify active + health endpoint (expect version 4.0.0) + journal tail
"""
import sys
import time

import paramiko

HOST, PORT, USER = "92.5.14.150", 22, "opc"
KEY = "/home/z/.ssh_key_006"
APP = "/opt/agentic-engineering-system"
RELEASE = "b38dbafcf4160df469132d9e415ac931aad1a258"
PREVIOUS = "0a26fc70ce13e69932db7fe54c810fcbf0f99d3f"


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=HOST, port=PORT, username=USER, key_filename=KEY,
                   timeout=15, banner_timeout=15, auth_timeout=15,
                   allow_agent=False, look_for_keys=False)

    def run(cmd, timeout=180):
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err

    # 1. merge
    print("=== [1] merge --ff-only ===")
    code, out, err = run(f"git -C {APP} merge --ff-only FETCH_HEAD 2>&1 && git -C {APP} rev-parse HEAD")
    print(out.strip()[:500], err.strip()[:300])
    head = out.strip().splitlines()[-1] if out.strip() else ""
    if head != RELEASE:
        print(f"FATAL: HEAD after merge = {head}, expected {RELEASE}")
        sys.exit(1)
    print(f"OK: HEAD == {RELEASE[:12]}")

    # 2. import smoke test (service-equivalent env: cwd = app root)
    print("\n=== [2] import smoke test (service-equivalent) ===")
    code, out, err = run(
        f"cd {APP} && {APP}/.venv/bin/python -c 'import api.routes; import core.config as c; print(\"IMPORT-OK APP_VERSION:\", c.APP_VERSION)' 2>&1 | tail -3"
    )
    print(out.strip()[:600])
    if "IMPORT-OK" not in out:
        print("IMPORT FAILED — rolling back merge (service NOT touched)")
        code2, out2, err2 = run(f"git -C {APP} checkout {PREVIOUS} 2>&1 && git -C {APP} rev-parse HEAD")
        print(f"rollback: {out2.strip()} {err2.strip()[:200]}")
        sys.exit(2)
    print("import OK")

    # 3. restart service
    print("\n=== [3] restart agentic.service ===")
    code, out, err = run("sudo -n systemctl restart agentic.service 2>&1; echo rc=$?")
    print(f"restart rc: {out.strip()}")
    time.sleep(5)

    # 4. verify
    print("\n=== [4] verify service + health ===")
    code, out, err = run("systemctl is-active agentic.service")
    print(f"service state: {out.strip()}")
    if out.strip() != "active":
        code, out, err = run("systemctl status agentic.service --no-pager -l | head -20; journalctl -u agentic.service -n 30 --no-pager | tail -30")
        print(out.strip()[:2000])
        sys.exit(3)

    code, out, err = run("curl -s --max-time 10 http://127.0.0.1:8010/health")
    print(f"health: {out.strip()[:400]}")
    if '"4.0.0"' not in out:
        print("FATAL: health does not report 4.0.0")
        sys.exit(4)

    code, out, err = run("journalctl -u agentic.service -n 15 --no-pager 2>&1 | tail -15")
    print(f"\njournal tail:\n{out.strip()[:1200]}")

    print("\n=== APP DEPLOYED: b38dbaf LIVE ON 8010 (version 4.0.0) ===")
    client.close()


if __name__ == "__main__":
    main()
