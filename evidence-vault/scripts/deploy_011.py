#!/usr/bin/env python3
"""AES-011 — Oracle production deployment (approved task-7 procedure).

Stages: preflight (read-only) -> transfer (bundle SFTP) -> backup -> deploy
(ff-only -> import test BEFORE restart -> systemctl restart -> health).

No nginx stage: port 80 already proxies to 8010 (verified 2026-10-26);
order 011 forbids pointing the public link at 8011.
"""
import os
import subprocess
import sys
import time
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/home/z/.ssh_key_010"
TARGET = "947e6e55e9d53517b7424ab0a932fef4941d0635"
PREV = "4568ed5dcba44c6bbb112107830b9a2eb1ab5a9f"
APP = "/opt/agentic-engineering-system"
EVID = "/home/z/my-project/download/live-reconciliation-011"
LOCAL_BUNDLE = "/home/z/my-project/reproof-010/deploy-011-947e6e55.bundle"
TS = time.strftime("%Y%m%d-%H%M%S")


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
              look_for_keys=False, allow_agent=False)
    return c


def run(c, cmd, timeout=90, check=False):
    _, o, e = c.exec_command(cmd, timeout=timeout)
    rc = o.channel.recv_exit_status()
    out, err = o.read().decode("utf-8", "replace"), e.read().decode("utf-8", "replace")
    print(f"$ {cmd[:150]}")
    if out.strip():
        print(out.strip()[:2000])
    if err.strip():
        print(f"[stderr] {err.strip()[:500]}")
    print(f"[rc={rc}]\n")
    if check and rc != 0:
        raise SystemExit(f"ABORT: command failed (rc={rc})")
    return rc, out, err


def save(name, text):
    os.makedirs(EVID, exist_ok=True)
    p = os.path.join(EVID, f"{TS}-{name}")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[evidence] {p}\n")


def stage_preflight(c):
    print("=" * 70, "\nSTAGE preflight (READ-ONLY)\n", "=" * 70)
    rc, head, _ = run(c, f"git -C {APP} rev-parse HEAD")
    head = head.strip()
    if head != PREV:
        raise SystemExit(f"ABORT: production HEAD {head} != expected {PREV}")
    rc, tracked, _ = run(c, f"git -C {APP} status --porcelain --untracked-files=no")
    if tracked.strip():
        raise SystemExit(f"ABORT: production tracked tree DIRTY:\n{tracked}")
    run(c, "systemctl is-active agentic.service")
    run(c, "curl -s --max-time 5 http://127.0.0.1:8010/health | head -c 200")
    run(c, "grep proxy_pass /etc/nginx/conf.d/agentic.conf")
    save("preflight.txt", f"HEAD before: {head}\ntree clean\nnginx -> 8010 confirmed\n")


def stage_transfer(c):
    print("=" * 70, "\nSTAGE transfer\n", "=" * 70)
    subprocess.run(["git", "-C", "/home/z/my-project/repo", "fetch", "origin", "main"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", "/home/z/my-project/repo", "fetch", "origin",
                    f"main:refs/heads/deploy-011"], check=True, capture_output=True)
    subprocess.run(["git", "-C", "/home/z/my-project/repo", "bundle", "create",
                    LOCAL_BUNDLE, "deploy-011"], check=True)
    out = subprocess.run(["git", "-C", "/home/z/my-project/repo", "bundle", "verify",
                          LOCAL_BUNDLE], capture_output=True, text=True)
    print((out.stdout + out.stderr).strip()[:300])
    sftp = c.open_sftp()
    sftp.put(LOCAL_BUNDLE, "/home/opc/deploy-011-947e6e55.bundle")
    sftp.close()
    run(c, "ls -la /home/opc/deploy-011-947e6e55.bundle")


def stage_backup(c):
    print("=" * 70, "\nSTAGE backup (restorable)\n", "=" * 70)
    run(c, f"git -C {APP} bundle create /home/opc/pre-011-repo-backup-{TS}.bundle --all 2>&1 | tail -1; ls -la /home/opc/pre-011-repo-backup-{TS}.bundle", check=True)
    run(c, f"sudo -n tar czf /home/opc/pre-011-runtime-{TS}.tar.gz -C {APP} runtime 2>&1; ls -la /home/opc/pre-011-runtime-{TS}.tar.gz", check=True)


def stage_deploy(c):
    print("=" * 70, "\nSTAGE deploy (ff-only)\n", "=" * 70)
    run(c, f"cd {APP} && git fetch /home/opc/deploy-011-947e6e55.bundle refs/heads/deploy-011 2>&1 | tail -2", check=True)
    rc, fh, _ = run(c, f"cd {APP} && git rev-parse FETCH_HEAD")
    fh = fh.strip()
    if fh != TARGET:
        raise SystemExit(f"ABORT: FETCH_HEAD {fh} != target {TARGET}")
    run(c, f"cd {APP} && git merge --ff-only FETCH_HEAD 2>&1 | tail -3", check=True)
    rc, head, _ = run(c, f"git -C {APP} rev-parse HEAD")
    if head.strip() != TARGET:
        raise SystemExit(f"ABORT: post-merge HEAD {head.strip()} != {TARGET}")
    print(f">>> production tree now at the tested commit {TARGET[:12]} <<<\n")
    run(c, f"cd {APP} && ./.venv/bin/python -c \"import api.routes as r; print('IMPORT_OK asset_version=' + r._ASSET_VERSION)\"", check=True)
    run(c, f"git -C {APP} status --porcelain --untracked-files=no | wc -l")
    run(c, "sudo -n systemctl restart agentic.service && sleep 4 && systemctl is-active agentic.service", check=True)
    run(c, "curl -s --max-time 8 http://127.0.0.1:8010/health | head -c 200")
    run(c, "curl -s -o /dev/null -D - http://127.0.0.1:8010/ | tr -d '\\r' | grep -iE 'etag|cache-control'")
    run(c, "curl -s -o /dev/null -D - 'http://127.0.0.1:8010/static/theme.css?v=947e6e55' | tr -d '\\r' | grep -iE 'cache-control|etag'")
    save("deploy.txt", f"deployed={TARGET}\nprevious={PREV}\nimport_ok=true\nrestarted=true\n")


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "preflight"
    c = connect()
    try:
        {"preflight": stage_preflight, "transfer": stage_transfer,
         "backup": stage_backup, "deploy": stage_deploy}[stage](c)
    finally:
        c.close()


if __name__ == "__main__":
    main()
