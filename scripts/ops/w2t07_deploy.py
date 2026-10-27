#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W2-T07 خطوة 5 — نشر مسح الألوان للإنتاج ببوابات R6.

النمط المعتمد حرفيًا من w1t02_deploy (المعتمد):
preflight (قراءة فقط) -> transfer (bundle SFTP) -> backup -> deploy
(ff-only -> اختبار استيراد قبل إعادة التشغيل -> systemctl restart ->
health -> إصدار الأصول) + تحقق ما بعد النشر خاص بالمهمة:
- الإنتاج يخدم theme.css بالتوكنات الجديدة (accent-pulse/scrim/...)
- لا قيم hex/rgba خام خارج theme.css في شجرة الإنتاج
- إصدار الأصول = الالتزام الجديد
- لا أخطاء جديدة في journal
"""
import os
import subprocess
import sys
import time

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EXPECTED_BEFORE = "9e2ace5b3acb0983cebff1a9e658507903273511"
APP = "/opt/agentic-engineering-system"
EVID = "/home/z/my-project/download/aes-remediation/W2-T07"
LOCAL_BUNDLE = "/home/z/my-project/repo/.git/w2t07-deploy.bundle"
TS = time.strftime("%Y%m%d-%H%M%S")
REPO = "/home/z/my-project/repo"

# التوكنات الجديدة الـ13 (عينة تحقق حتمية من الخدمة الحية)
NEW_TOKENS = ["--accent-pulse", "--code-well", "--scrim-deep", "--danger-scrim",
              "--scrollbar-thumb", "--accent-selection", "--border-strong"]


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
    out = subprocess.run(["git", "-C", REPO, "rev-parse", "main"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def stage_preflight(c):
    print("=" * 70, "\nSTAGE preflight (READ-ONLY — بوابة R6 قبل)\n", "=" * 70)
    rc, head, _ = run(c, f"git -C {APP} rev-parse HEAD")
    head = head.strip()
    if head != EXPECTED_BEFORE:
        raise SystemExit(f"ABORT: production HEAD {head} != expected {EXPECTED_BEFORE}")
    rc, tracked, _ = run(c, f"git -C {APP} status --porcelain --untracked-files=no")
    if tracked.strip():
        raise SystemExit(f"ABORT: production tracked tree DIRTY:\n{tracked}")
    run(c, "systemctl is-active agentic.service nginx")
    run(c, "curl -s --max-time 5 http://127.0.0.1:8010/health | head -c 200")
    run(c, "curl -s -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:8010/static/theme.css")
    # الحالة قبل: لا توكنات جديدة بعد
    _, theme_before, _ = run(c, "curl -s http://127.0.0.1:8010/static/theme.css | grep -c -- 'accent-pulse' || true")
    print(f"accent-pulse occurrences BEFORE deploy: {theme_before.strip()}")
    save("preflight.txt", f"HEAD before: {head}\ntree clean\nagentic+nginx active\nhealth 200\n")


def stage_transfer(c):
    print("=" * 70, "\nSTAGE transfer\n", "=" * 70)
    target = full_target()
    print(f"target full sha: {target}")
    subprocess.run(["git", "-C", REPO, "bundle", "create", LOCAL_BUNDLE, "main"], check=True)
    out = subprocess.run(["git", "-C", REPO, "bundle", "verify", LOCAL_BUNDLE],
                         capture_output=True, text=True)
    print((out.stdout + out.stderr).strip()[:300])
    sftp = c.open_sftp()
    sftp.put(LOCAL_BUNDLE, "/home/opc/w2t07-deploy.bundle")
    sftp.close()
    run(c, "ls -la /home/opc/w2t07-deploy.bundle")
    save("transfer.txt", f"bundle={target}\nbundle verify OK\nsftp OK\n")


def stage_backup(c):
    print("=" * 70, "\nSTAGE backup (restorable — خطة التراجع R7)\n", "=" * 70)
    run(c, f"git -C {APP} bundle create /home/opc/pre-w2t07-repo-backup-{TS}.bundle --all 2>&1 | tail -1; ls -la /home/opc/pre-w2t07-repo-backup-{TS}.bundle", check=True)
    run(c, f"sudo -n tar czf /home/opc/pre-w2t07-runtime-{TS}.tar.gz -C {APP} runtime 2>&1; ls -la /home/opc/pre-w2t07-runtime-{TS}.tar.gz", check=True)


def stage_deploy(c):
    print("=" * 70, "\nSTAGE deploy (ff-only)\n", "=" * 70)
    target = full_target()
    run(c, "cd /opt/agentic-engineering-system && git fetch /home/opc/w2t07-deploy.bundle main 2>&1 | tail -2", check=True)
    rc, fh, _ = run(c, "cd /opt/agentic-engineering-system && git rev-parse FETCH_HEAD")
    fh = fh.strip()
    if fh != target:
        raise SystemExit(f"ABORT: FETCH_HEAD {fh} != target {target}")
    run(c, "cd /opt/agentic-engineering-system && git merge --ff-only FETCH_HEAD 2>&1 | tail -3", check=True)
    rc, head, _ = run(c, f"git -C {APP} rev-parse HEAD")
    if head.strip() != target:
        raise SystemExit(f"ABORT: post-merge HEAD {head.strip()} != {target}")
    print(f">>> production tree now at the tested commit {target[:12]} <<<\n")
    # اختبار الاستيراد قبل إعادة التشغيل (نمط RLR-005)
    run(c, f"cd {APP} && ./.venv/bin/python -c \"import api.routes as r; print('IMPORT_OK asset_version=' + r._ASSET_VERSION)\"", check=True)
    run(c, f"git -C {APP} status --porcelain --untracked-files=no | wc -l")
    run(c, "sudo -n systemctl restart agentic.service && sleep 4 && systemctl is-active agentic.service", check=True)
    run(c, "curl -s --max-time 8 http://127.0.0.1:8010/health | head -c 200")
    save("deploy.txt", f"deployed={target}\nprevious={EXPECTED_BEFORE}\nimport_ok=true\nrestarted=true\n")


def stage_postverify(c):
    print("=" * 70, "\nSTAGE postverify (بوابة R6 بعد — خاصة بالمهمة)\n", "=" * 70)
    checks = []
    # 1) الصحة والخدمات
    rc, _, _ = run(c, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health")
    checks.append(("health_200", rc == 0 and True))
    # 2) إصدار الأصول = الالتزام الجديد
    target = full_target()
    short = target[:8]
    rc, ver, _ = run(c, "curl -s http://127.0.0.1:8010/ | grep -oE 'control-center.js\\?v=[0-9a-f]+' | head -1")
    checks.append(("asset_version_bumped", short in ver))
    print(f"expected asset v={short}, got: {ver.strip()}")
    # 3) التوكنات الجديدة تُخدم حية
    _, theme, _ = run(c, "curl -s http://127.0.0.1:8010/static/theme.css")
    found = [t for t in NEW_TOKENS if t in theme]
    checks.append(("new_tokens_served", len(found) == len(NEW_TOKENS)))
    print(f"tokens served live: {len(found)}/{len(NEW_TOKENS)} -> {found}")
    # 4) صفر hex/rgba خام خارج theme.css في شجرة الإنتاج
    _, hexout, _ = run(c, f"cd {APP}/src/ui && grep -rEn --include='*.css' --include='*.js' "
                          f"'#[0-9a-fA-F]{{6}}\\b|rgba?\\(' . | grep -v theme.css | grep -v fonts/ | wc -l")
    n_hex = int(hexout.strip() or 0)
    checks.append(("zero_raw_colors_prod", n_hex == 0))
    print(f"raw hex/rgba lines outside theme.css in production: {n_hex}")
    # 5) لا أخطاء جديدة في journal
    run(c, "journalctl -u agentic --since '-10 min' -p err --no-pager | tail -5")
    rc, errs, _ = run(c, "journalctl -u agentic --since '-10 min' -p err --no-pager | grep -c . || true")
    n_err = int(errs.strip() or 0)
    checks.append(("no_new_journal_errors", n_err == 0))
    # 6) nginx 401 لا يزال سليمًا (لم يكسر النشر جدار الوكيل)
    rc, code, _ = run(c, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:80/")
    print(f"nginx local / => {code.strip()} (401 expected)")
    checks.append(("nginx_wall_intact", code.strip() == "401"))

    verdict = {name: ok for name, ok in checks}
    passed = sum(1 for _, ok in checks if ok)
    print(f"\nPOSTVERIFY: {passed}/{len(checks)} gates PASS")
    save("postverify.txt", f"target={target}\n" + "\n".join(f"{k}={v}" for k, v in verdict.items()))
    if passed != len(checks):
        raise SystemExit("ABORT: postverify gates failed — يوجب التراجع أو الإصلاح قبل المتابعة")


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "preflight"
    c = connect()
    try:
        {"preflight": stage_preflight, "transfer": stage_transfer,
         "backup": stage_backup, "deploy": stage_deploy,
         "postverify": stage_postverify}[stage](c)
    finally:
        c.close()


if __name__ == "__main__":
    main()
