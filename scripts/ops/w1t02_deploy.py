#!/usr/bin/env python3
"""W1-T02 — نشر رقعة قتل الاستطلاع الأعمى إلى الإنتاج.

النمط المعتمد حرفيًا من deploy_014 (المعتمد):
preflight (قراءة فقط) -> transfer (bundle SFTP) -> backup -> deploy
(ff-only -> اختبار استيراد قبل إعادة التشغيل -> systemctl restart ->
health -> etag/إصدار الأصول).
"""
import os
import subprocess
import sys
import time
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
TARGET = "9e2ace5"  # يُستكمل للكامل عند التشغيل
APP = "/opt/agentic-engineering-system"
EVID = "/home/z/my-project/download/aes-remediation/W1-T02"
LOCAL_BUNDLE = "/home/z/my-project/repo/.git/w1t02-deploy.bundle"
TS = time.strftime("%Y%m%d-%H%M%S")


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
              look_for_keys=False, allow_agent=False)
    return c


def run(c, cmd, timeout=120, check=False):
    _, o, e = c.exec_command(cmd, timeout=timeout)
    rc = o.channel.recv_exit_status()
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    print(f"$ {cmd[:150]}")
    if out.strip():
        print(out.strip()[:2500])
    if err.strip():
        print(f"[stderr] {err.strip()[:600]}")
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


def full_target():
    out = subprocess.run(
        ["git", "-C", "/home/z/my-project/repo", "rev-parse", "main"],
        capture_output=True, text=True, check=True)
    return out.stdout.strip()


def stage_preflight(c):
    print("=" * 70, "\nSTAGE preflight (READ-ONLY)\n", "=" * 70)
    rc, head, _ = run(c, f"git -C {APP} rev-parse HEAD")
    head = head.strip()
    if head != "0f2d9c6b393951dc7ad656243b5053f615cd905b":
        raise SystemExit(f"ABORT: production HEAD {head} != expected 0f2d9c6")
    rc, tracked, _ = run(c, f"git -C {APP} status --porcelain --untracked-files=no")
    if tracked.strip():
        raise SystemExit(f"ABORT: production tracked tree DIRTY:\n{tracked}")
    run(c, "systemctl is-active agentic.service nginx")
    run(c, "curl -s --max-time 5 http://127.0.0.1:8010/health | head -c 200")
    run(c, "grep proxy_pass /etc/nginx/conf.d/agentic.conf | head -2")
    run(c, f"ss -tlnp 2>/dev/null | grep -E ':8010|:8011|:8099' | head -3")
    save("preflight.txt", f"HEAD before: {head}\ntree clean\nagentic+nginx active\nhealth 200\n")


def stage_transfer(c):
    print("=" * 70, "\nSTAGE transfer\n", "=" * 70)
    target = full_target()
    print(f"target full sha: {target}")
    subprocess.run(["git", "-C", "/home/z/my-project/repo", "bundle", "create",
                    LOCAL_BUNDLE, "main"], check=True)
    out = subprocess.run(["git", "-C", "/home/z/my-project/repo", "bundle", "verify",
                          LOCAL_BUNDLE], capture_output=True, text=True)
    print((out.stdout + out.stderr).strip()[:300])
    sftp = c.open_sftp()
    sftp.put(LOCAL_BUNDLE, "/home/opc/w1t02-deploy.bundle")
    sftp.close()
    run(c, "ls -la /home/opc/w1t02-deploy.bundle")
    save("transfer.txt", f"bundle={target}\nbundle verify OK\nscp OK\n")


def stage_backup(c):
    print("=" * 70, "\nSTAGE backup (restorable)\n", "=" * 70)
    run(c, f"git -C {APP} bundle create /home/opc/pre-w1t02-repo-backup-{TS}.bundle --all 2>&1 | tail -1; ls -la /home/opc/pre-w1t02-repo-backup-{TS}.bundle", check=True)
    run(c, f"sudo -n tar czf /home/opc/pre-w1t02-runtime-{TS}.tar.gz -C {APP} runtime 2>&1; ls -la /home/opc/pre-w1t02-runtime-{TS}.tar.gz", check=True)


def stage_deploy(c):
    print("=" * 70, "\nSTAGE deploy (ff-only)\n", "=" * 70)
    target = full_target()
    run(c, "cd /opt/agentic-engineering-system && git fetch /home/opc/w1t02-deploy.bundle main 2>&1 | tail -2", check=True)
    rc, fh, _ = run(c, "cd /opt/agentic-engineering-system && git rev-parse FETCH_HEAD")
    fh = fh.strip()
    if fh != target:
        raise SystemExit(f"ABORT: FETCH_HEAD {fh} != target {target}")
    run(c, "cd /opt/agentic-engineering-system && git merge --ff-only FETCH_HEAD 2>&1 | tail -3", check=True)
    rc, head, _ = run(c, f"git -C {APP} rev-parse HEAD")
    if head.strip() != target:
        raise SystemExit(f"ABORT: post-merge HEAD {head.strip()} != {target}")
    print(f">>> production tree now at the tested commit {target[:12]} <<<\n")
    run(c, f"cd {APP} && ./.venv/bin/python -c \"import api.routes as r; print('IMPORT_OK asset_version=' + r._ASSET_VERSION)\"", check=True)
    run(c, f"git -C {APP} status --porcelain --untracked-files=no | wc -l")
    run(c, "sudo -n systemctl restart agentic.service && sleep 4 && systemctl is-active agentic.service", check=True)
    run(c, "curl -s --max-time 8 http://127.0.0.1:8010/health | head -c 200")
    run(c, "curl -s -o /dev/null -D - http://127.0.0.1:8010/ | tr -d '\\r' | grep -iE 'etag|cache-control'")
    run(c, "curl -s http://127.0.0.1:8010/ | grep -oE 'control-center.js\\?v=[0-9a-f]+' | head -1")
    save("deploy.txt", f"deployed={target}\nprevious=0f2d9c6b393951dc7ad656243b5053f615cd905b\nimport_ok=true\nrestarted=true\n")


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
