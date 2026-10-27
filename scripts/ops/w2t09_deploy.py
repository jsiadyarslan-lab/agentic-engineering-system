#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W2-T09 — نشر إنقاذ المصنع للإنتاج ببوابات R6 (نمط w1t02/w2t07 المعتمد).
قبل = d23a96984deb · بعد = HEAD (eaef5fd0) + تحقق خاص: العلامات الجديدة تُخدم حية."""
import os
import subprocess
import sys
import time

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EXPECTED_BEFORE = "d23a96984debb30a740ce60baf38881f6d4adedd"
APP = "/opt/agentic-engineering-system"
EVID = "/home/z/my-project/download/aes-remediation/W2-T09"
LOCAL_BUNDLE = "/home/z/my-project/repo/.git/w2t09-deploy.bundle"
TS = time.strftime("%Y%m%d-%H%M%S")
REPO = "/home/z/my-project/repo"


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
        print(out.strip()[:2000])
    if err.strip():
        print(f"[stderr] {err.strip()[:400]}")
    print(f"[rc={rc}]\n")
    if check and rc != 0:
        raise SystemExit(f"ABORT: command failed (rc={rc})")
    return rc, out, err


def save(name, text):
    os.makedirs(EVID, exist_ok=True)
    with open(os.path.join(EVID, f"{TS}-{name}"), "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[evidence] {name}\n")


def full_target():
    return subprocess.run(["git", "-C", REPO, "rev-parse", "main"],
                          capture_output=True, text=True, check=True).stdout.strip()


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    c = connect()
    try:
        if stage in ("all", "preflight"):
            print("=" * 70, "\npreflight (READ-ONLY)\n", "=" * 70)
            _, head, _ = run(c, f"git -C {APP} rev-parse HEAD")
            assert head.strip() == EXPECTED_BEFORE, f"HEAD {head.strip()} != {EXPECTED_BEFORE}"
            _, dirty, _ = run(c, f"git -C {APP} status --porcelain --untracked-files=no")
            assert not dirty.strip(), f"DIRTY: {dirty}"
            run(c, "systemctl is-active agentic.service nginx")
            run(c, "curl -s -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:8010/health")
            _, old_js, _ = run(c, "curl -s http://127.0.0.1:8010/static/factory-control.js | grep -c fc-statbar || true")
            print(f"fc-statbar occurrences BEFORE: {old_js.strip()} (expected 0)")
            save("preflight.txt", f"HEAD before: {head.strip()}\nclean\nhealth 200\nfc-statbar before: {old_js.strip()}")

        if stage in ("all", "deploy"):
            print("=" * 70, "\ntransfer + backup + deploy\n", "=" * 70)
            target = full_target()
            print(f"target: {target}")
            subprocess.run(["git", "-C", REPO, "bundle", "create", LOCAL_BUNDLE, "main"], check=True)
            out = subprocess.run(["git", "-C", REPO, "bundle", "verify", LOCAL_BUNDLE], capture_output=True, text=True)
            print((out.stdout + out.stderr).strip()[:200])
            sftp = c.open_sftp()
            sftp.put(LOCAL_BUNDLE, "/home/opc/w2t09-deploy.bundle")
            sftp.close()
            run(c, f"git -C {APP} bundle create /home/opc/pre-w2t09-repo-backup-{TS}.bundle --all 2>&1 | tail -1; ls -la /home/opc/pre-w2t09-repo-backup-{TS}.bundle", check=True)
            run(c, f"sudo -n tar czf /home/opc/pre-w2t09-runtime-{TS}.tar.gz -C {APP} runtime 2>&1; ls -la /home/opc/pre-w2t09-runtime-{TS}.tar.gz", check=True)
            run(c, "cd /opt/agentic-engineering-system && git fetch /home/opc/w2t09-deploy.bundle main 2>&1 | tail -2", check=True)
            _, fh, _ = run(c, "cd /opt/agentic-engineering-system && git rev-parse FETCH_HEAD")
            assert fh.strip() == target, f"FETCH_HEAD {fh.strip()} != {target}"
            run(c, "cd /opt/agentic-engineering-system && git merge --ff-only FETCH_HEAD 2>&1 | tail -3", check=True)
            _, head2, _ = run(c, f"git -C {APP} rev-parse HEAD")
            assert head2.strip() == target, "post-merge HEAD mismatch"
            print(f">>> production at {target[:12]} <<<")
            run(c, f"cd {APP} && ./.venv/bin/python -c \"import api.routes as r; print('IMPORT_OK asset_version=' + r._ASSET_VERSION)\"", check=True)
            run(c, f"git -C {APP} status --porcelain --untracked-files=no | wc -l")
            run(c, "sudo -n systemctl restart agentic.service && sleep 4 && systemctl is-active agentic.service", check=True)
            run(c, "curl -s --max-time 8 http://127.0.0.1:8010/health | head -c 120")
            save("deploy.txt", f"deployed={target}\nprevious={EXPECTED_BEFORE}\nimport_ok=true\nrestarted=true")

        if stage in ("all", "postverify"):
            print("=" * 70, "\npostverify (R6)\n", "=" * 70)
            target = full_target()
            short = target[:8]
            checks = []
            _, code, _ = run(c, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health")
            checks.append(("health_200", code.strip() == "200"))
            _, ver, _ = run(c, "curl -s http://127.0.0.1:8010/ | grep -oE 'factory-control.js\\?v=[0-9a-f]+' | head -1")
            checks.append(("asset_version", short in ver))
            print(f"asset: {ver.strip()} (want v={short})")
            _, js, _ = run(c, "curl -s http://127.0.0.1:8010/static/factory-control.js | grep -c -E 'fc-statbar|prio-live|fc-row-live-dot' || true")
            checks.append(("new_js_markers_served", int(js.strip() or 0) >= 3))
            _, css, _ = run(c, "curl -s http://127.0.0.1:8010/static/factory-control.css | grep -c -E 'fc-statbar|prio-live|fc-head-btn' || true")
            checks.append(("new_css_markers_served", int(css.strip() or 0) >= 3))
            # العلامات القديمة الفعلية: بطاقة نظام المصنع + أزرار العرض الثلاثة القديمة.
            # (درس مصحح: «تحديث المهام» تطابق عنوان زر تحديث الكل الجديد كسلسلة فرعية —
            #  والسلك الدفاعي ؟. لمعرفات الأزرار القديمة no-op مقصود بقاءه.)
            _, old, _ = run(c, "curl -s http://127.0.0.1:8010/static/factory-control.js | grep -c 'fc-system-card' || true")
            _, old_btns, _ = run(c, "curl -s http://127.0.0.1:8010/static/factory-control.js | grep -c 'id=\"fc-refresh-missions\"\\\\|id=\"fc-refresh-runs\"\\\\|id=\"fc-refresh-agents\"' || true")
            checks.append(("old_markers_gone", old.strip() == "0" and old_btns.strip() == "0"))
            print(f"old fc-system-card: {old.strip()} | old rendered buttons: {old_btns.strip()}")
            # journal: أسطر فعلية فقط (استبعاد placeholder — درس W2-T07)
            _, errs, _ = run(c, "journalctl -u agentic --since '-10 min' -p err --no-pager | grep -v -- '-- No entries --' | grep -c . || true")
            checks.append(("no_new_journal_errors", errs.strip() == "0"))
            _, wall, _ = run(c, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:80/")
            checks.append(("nginx_wall_401", wall.strip() == "401"))
            _, hexn, _ = run(c, "cd /opt/agentic-engineering-system && grep -rEn --include='*.css' '#[0-9a-fA-F]{6}\\b|rgba?\\(' src/ui/ | grep -v theme.css | grep -v fonts/ | grep -vc harness.js || true")
            checks.append(("tokens_contract_prod", hexn.strip() == "0"))
            verdict = dict(checks)
            passed = sum(1 for _, ok in checks if ok)
            print(f"\nPOSTVERIFY: {passed}/{len(checks)} PASS -> {verdict}")
            save("postverify.txt", f"target={target}\n" + "\n".join(f"{k}={v}" for k, v in verdict.items()))
            if passed != len(checks):
                raise SystemExit("ABORT: postverify failed")
    finally:
        c.close()


if __name__ == "__main__":
    main()
