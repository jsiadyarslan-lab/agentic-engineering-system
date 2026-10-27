#!/usr/bin/env python3
"""AES-010 Phase 4 — Oracle production deployment (approved task-7 procedure).

Stages (run one at a time via CLI arg):
  preflight  READ-ONLY: production repo state, service, health, preview note
  transfer   SFTP a fresh bundle of main@4568ed5 to /home/opc/
  backup     restorable backups: git bundle --all + runtime tar.gz
  deploy     fetch from bundle -> verify -> merge --ff-only -> verify HEAD
             -> import test (APP_VERSION) -> systemctl restart -> health 8010
  nginx      backup conf -> 8011->8010 -> nginx -t -> reload -> verify

Safety: ff-only, no reset/clean/force, tracked-tree must be clean,
        import test BEFORE touching the service, evidence at each step.
"""
import os
import subprocess
import sys
import time
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/home/z/.ssh_key_010"
TARGET = "4568ed5dcba44c6bbb112107830b9a2eb1ab5a9f"
PREV = "b38dbafcf4160df469132d9e415ac931aad1a258"
APP = "/opt/agentic-engineering-system"
EVID = "/home/z/my-project/download/oracle-deploy-010"
LOCAL_BUNDLE = "/home/z/my-project/reproof-010/deploy-010-4568ed5.bundle"
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
    p = os.path.join(EVID, f"{TS}-{name}" if name else f"{TS}.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[evidence] {p}\n")
    return p


def stage_preflight(c):
    print("=" * 70, "\nSTAGE preflight (READ-ONLY)\n", "=" * 70)
    rc, head, _ = run(c, f"git -C {APP} rev-parse HEAD")
    head = head.strip()
    if head != PREV:
        raise SystemExit(f"ABORT: production HEAD {head} != expected previous release {PREV}")
    rc, tracked, _ = run(c, f"git -C {APP} status --porcelain --untracked-files=no")
    if tracked.strip():
        raise SystemExit(f"ABORT: production tracked tree DIRTY:\n{tracked}")
    rc, untracked, _ = run(c, f"git -C {APP} status --porcelain")
    print(f"untracked (informational, non-blocking): {untracked.strip() or '(none)'}")
    run(c, "systemctl is-active agentic.service")
    run(c, "curl -s --max-time 5 http://127.0.0.1:8010/health | head -c 250")
    run(c, "systemctl is-active agentic-vis.service; ps -o pid,etime,%cpu,args -p $(pgrep -f 'uvicorn.*8011' | head -1) 2>/dev/null | tail -1", check=False)
    run(c, "grep proxy_pass /etc/nginx/conf.d/agentic.conf")
    save("preflight.txt", f"production HEAD before deploy: {head}\ntracked tree clean\npreview + nginx state recorded above\n")


def stage_transfer(c):
    print("=" * 70, "\nSTAGE transfer\n", "=" * 70)
    if not os.path.exists(LOCAL_BUNDLE):
        subprocess.run(["git", "-C", "/home/z/my-project/repo", "bundle", "create",
                        LOCAL_BUNDLE, "origin/main"], check=True)
    out = subprocess.run(["git", "-C", "/home/z/my-project/repo", "bundle", "verify",
                          LOCAL_BUNDLE], capture_output=True, text=True).stdout
    print(out.strip()[:400])
    sftp = c.open_sftp()
    sftp.put(LOCAL_BUNDLE, "/home/opc/deploy-010-4568ed5.bundle")
    sftp.close()
    run(c, "ls -la /home/opc/deploy-010-4568ed5.bundle")


def stage_backup(c):
    print("=" * 70, "\nSTAGE backup (restorable)\n", "=" * 70)
    run(c, f"git -C {APP} bundle create /home/opc/pre-010-repo-backup-{TS}.bundle --all 2>&1 | tail -1; ls -la /home/opc/pre-010-repo-backup-{TS}.bundle", check=True)
    run(c, f"sudo -n tar czf /home/opc/pre-010-runtime-{TS}.tar.gz -C {APP} runtime 2>&1; ls -la /home/opc/pre-010-runtime-{TS}.tar.gz", check=True)
    run(c, f"sudo -n cp /etc/nginx/conf.d/agentic.conf /etc/nginx/conf.d/agentic.conf.bak-010 && echo NGINX_BAK_OK", check=True)


def stage_deploy(c):
    print("=" * 70, "\nSTAGE deploy (ff-only)\n", "=" * 70)
    run(c, f"cd {APP} && git fetch /home/opc/deploy-010-4568ed5.bundle refs/remotes/origin/main 2>&1 | tail -2", check=True)
    rc, fh, _ = run(c, f"cd {APP} && git rev-parse FETCH_HEAD")
    fh = fh.strip()
    if fh != TARGET:
        raise SystemExit(f"ABORT: FETCH_HEAD {fh} != target {TARGET}")
    run(c, f"cd {APP} && git merge --ff-only FETCH_HEAD 2>&1 | tail -2", check=True)
    rc, head, _ = run(c, f"git -C {APP} rev-parse HEAD")
    if head.strip() != TARGET:
        raise SystemExit(f"ABORT: post-merge HEAD {head.strip()} != {TARGET}")
    print(f">>> production tree now at the tested commit {TARGET[:12]} <<<\n")
    # import test BEFORE touching the service
    run(c, f"cd {APP} && ./.venv/bin/python -c \"import api.routes as r; from core.config import APP_VERSION; print('IMPORT_OK APP_VERSION=' + str(APP_VERSION))\"", check=True)
    run(c, f"git -C {APP} status --porcelain --untracked-files=no | wc -l")
    # restart
    run(c, "sudo -n systemctl restart agentic.service && sleep 4 && systemctl is-active agentic.service", check=True)
    run(c, "curl -s --max-time 8 http://127.0.0.1:8010/health | head -c 300")
    run(c, "git -C {APP} rev-parse HEAD")
    save("deploy.txt", f"deployed={TARGET}\nprevious={PREV}\nimport_ok=true\nservice_restarted=true\n")


def stage_nginx(c):
    print("=" * 70, "\nSTAGE nginx (approved procedure: 8011 -> 8010)\n", "=" * 70)
    run(c, "grep -n proxy_pass /etc/nginx/conf.d/agentic.conf")
    run(c, "sudo -n sed -i 's|proxy_pass http://127.0.0.1:8011;|proxy_pass http://127.0.0.1:8010;|' /etc/nginx/conf.d/agentic.conf && echo SED_DONE", check=True)
    run(c, "grep -n proxy_pass /etc/nginx/conf.d/agentic.conf")
    run(c, "sudo -n nginx -t 2>&1", check=True)
    run(c, "sudo -n systemctl reload nginx && echo RELOAD_OK", check=True)
    run(c, "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1/ ; echo ' <- via nginx:80 (401=auth active, nginx serving)'", check=False)
    run(c, "curl -s --max-time 5 http://127.0.0.1:8010/health | head -c 200")
    save("nginx.txt", "proxy_pass switched 8011->8010, nginx -t OK, reloaded. backup: agentic.conf.bak-010\n")


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "preflight"
    c = connect()
    try:
        {"preflight": stage_preflight, "transfer": stage_transfer,
         "backup": stage_backup, "deploy": stage_deploy, "nginx": stage_nginx}[stage](c)
    finally:
        c.close()


if __name__ == "__main__":
    main()
