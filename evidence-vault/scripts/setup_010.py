#!/usr/bin/env python3
"""AES-010 Phase 2 — transfer + isolated setup + substrate pre-check + suite launch.

Creates /home/opc/aes-reproof-010 (NEVER touches /opt/agentic-engineering-system,
/opt/aes-vis, the production venv, service, or its runtime DB).
"""
import sys
import time
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/home/z/.ssh_key_010"
LOCAL = "/home/z/my-project/reproof-010"
REMOTE = "/home/opc/aes-reproof-010"
HEAD = "4568ed5dcba44c6bbb112107830b9a2eb1ab5a9f"


def run(c, cmd, timeout=120, check=True):
    _, o, e = c.exec_command(cmd, timeout=timeout)
    rc = o.channel.recv_exit_status()
    out = o.read().decode("utf-8", "replace").strip()
    err = e.read().decode("utf-8", "replace").strip()
    print(f"$ {cmd[:160]}")
    if out:
        print(out[:3000])
    if err:
        print(f"[stderr] {err[:800]}")
    print(f"[rc={rc}]\n")
    if check and rc != 0:
        print(f"!!! FAILED (rc={rc}) — aborting")
        sys.exit(rc)
    return rc, out


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=20, look_for_keys=False, allow_agent=False)

    print("### 1. fresh isolated dir (fail if exists — never overwrite)")
    run(c, f"test ! -e {REMOTE} && mkdir -p {REMOTE} && echo DIR_CREATED || echo DIR_ALREADY_EXISTS")

    print("### 2. SFTP transfer: bundle + wheels")
    sftp = c.open_sftp()
    t0 = time.time()
    sftp.put(f"{LOCAL}/aes-4568ed5.bundle", f"{REMOTE}/aes-4568ed5.bundle")
    print(f"bundle transferred ({time.time()-t0:.1f}s)")
    sftp.mkdir(f"{REMOTE}/wheels")
    import os
    n = 0
    for f in sorted(os.listdir(f"{LOCAL}/wheels")):
        sftp.put(f"{LOCAL}/wheels/{f}", f"{REMOTE}/wheels/{f}")
        n += 1
    print(f"{n} wheels transferred ({time.time()-t0:.1f}s total)")
    sftp.close()
    run(c, f"ls -la {REMOTE} && du -sh {REMOTE}/wheels")

    print("### 3. clone from bundle + verify exact commit")
    run(c, f"cd {REMOTE} && git clone aes-4568ed5.bundle repo 2>&1 | tail -2")
    run(c, f"cd {REMOTE}/repo && git rev-parse HEAD && test \"$(git rev-parse HEAD)\" = \"{HEAD}\" && echo HEAD_MATCHES_4568ed5")
    run(c, f"cd {REMOTE}/repo && git status --porcelain | wc -l && git log --oneline -1")

    print("### 4. fresh venv from system python3.12 (no production venv)")
    run(c, f"/usr/bin/python3.12 -m venv {REMOTE}/venv 2>&1 | tail -2; {REMOTE}/venv/bin/pip --version 2>&1 || echo PIP_MISSING")

    print("### 5. offline install from transferred wheels (CI-identical versions)")
    rc, _ = run(c, f"{REMOTE}/venv/bin/pip --version", check=False)
    if rc != 0:
        print("### 5b. ensurepip fallback: pip wheel bootstrap")
        run(c, f"{REMOTE}/venv/bin/python {REMOTE}/wheels/pip-26.2.2-py3-none-any.whl/pip install --no-index --find-links {REMOTE}/wheels pip 2>&1 | tail -1")
    run(c, f"{REMOTE}/venv/bin/pip install --no-index --find-links {REMOTE}/wheels "
            f"{REMOTE}/wheels/agentic_engineering_system-4.0.0-py3-none-any.whl pytest-asyncio pytest-timeout 2>&1 | tail -2")

    print("### 6. environment record (raw)")
    run(c, f"cd {REMOTE} && {{ echo '=== ENV RECORD $(date -u +%Y-%m-%dT%H:%M:%SZ) ==='; "
            f"uname -a; head -2 /etc/os-release; echo 'cpu: $(nproc) x $(lscpu | grep 'Model name' | cut -d: -f2 | xargs)'; "
            f"free -h | head -2; df -h {REMOTE} | tail -1; getenforce; "
            f"bwrap --version; /usr/bin/python3.12 --version; "
            f"{REMOTE}/venv/bin/python --version; echo; {REMOTE}/venv/bin/pip list --format=freeze; }} > env-record.txt 2>&1; head -20 env-record.txt")

    print("### 7. PRE-CHECK: project's own substrate probe (raw JSON) on the qualified host")
    run(c, f"cd {REMOTE}/repo && PYTHONPATH=src {REMOTE}/venv/bin/python -c \""
            f"import json; from substrate.bwrap_substrate import bwrap_capabilities; "
            f"caps = bwrap_capabilities(force=True); "
            f"print(json.dumps(caps, ensure_ascii=False, indent=1)); "
            f"raise SystemExit(0 if caps.get('supported') is True else 3)\" > {REMOTE}/bwrap-probe-host.json 2>&1; "
            f"echo probe_exit=$?; cat {REMOTE}/bwrap-probe-host.json")

    print("### 8. PRE-CHECK: raw loopback evidence inside bwrap netns")
    run(c, "bwrap --unshare-all --die-with-parent --new-session --ro-bind / / "
            "--tmpfs /proc --dev /dev --tmpfs /tmp --clearenv "
            "--setenv PATH /usr/bin:/bin:/usr/sbin -- "
            "/usr/sbin/ip -o link show lo 2>&1; echo loopback_cmd_exit=$?", check=False)

    c.close()
    print("SETUP COMPLETE")


if __name__ == "__main__":
    main()
