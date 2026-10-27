#!/usr/bin/env python3
"""W1-T03 — نشر مسار المراقبة السري /healthz-<TOKEN> (خطوات 0-2 من البطاقة).

بوابة R6: قراءة-فقط قبل (تمت في w1t03_preflight.py) + نسخة احتياطية +
nginx -t قبل reload + تراجع تلقائي عند أي فشل + تحقق بعد (داخلي وخارجي).
التوكن: يُولد محليًا، يُحفظ لملف المالك (لا يدخل المستودع)، ويُحجب في كل المخرجات المطبوعة.
"""
import os
import secrets
import stat
import sys
import time
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EVID = "/home/z/my-project/download/aes-remediation/W1-T03"
TOKEN_FILE = os.path.join(EVID, "owner-token.txt")
TS = time.strftime("%Y%m%d-%H%M%S")

LOCATION_TMPL = """
    # W1-T03 (2026-10-27): secret external monitoring path — 32-hex token.
    # Bypasses IP allowlist + Basic Auth by design; proxies ONLY /health
    # liveness (no app data). Rollback: restore agentic.conf.pre-w1t03.
    location = /healthz-{token} {{
        allow all;
        auth_basic off;
        proxy_pass http://127.0.0.1:8010/health;
    }}
"""


def log(name, text, mask=None):
    os.makedirs(EVID, exist_ok=True)
    p = os.path.join(EVID, f"{TS}-{name}")
    if mask:
        text = text.replace(mask, "<TOKEN>")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    if mask:
        text = text.replace("<TOKEN>", mask[:8] + "…")  # مطبوع جزئيًا فقط
    print(text)
    print(f"[evidence] {p}\n")
    return p


def main():
    token = secrets.token_hex(16)  # 32 hex
    os.makedirs(EVID, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        f.write(token + "\n")
    os.chmod(TOKEN_FILE, 0o600)

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
              look_for_keys=False, allow_agent=False)

    out_all = []

    def run(cmd, t=60, check=False):
        _, o, e = c.exec_command(cmd, timeout=t)
        rc = o.channel.recv_exit_status()
        out, err = o.read().decode("utf-8", "replace"), e.read().decode("utf-8", "replace")
        shown = f"$ {cmd[:150]}\n{out.strip()[:800]}{('[stderr] ' + err.strip()[:300]) if err.strip() else ''}\n[rc={rc}]"
        print(shown.replace(token, "<TOKEN>"))
        out_all.append(shown)
        if check and rc != 0:
            raise RuntimeError(f"ABORT: rc={rc} for: {cmd[:100]}")
        return rc, out, err

    # 0) قراءة الإعداد الحالي وبناء الجديد محليًا (إدراج قبل آخر قوس)
    rc, conf, _ = run("sudo -n cat /etc/nginx/conf.d/agentic.conf")
    marker = "    location = /healthz-"
    if marker in conf:
        print("ABORT: healthz location موجود مسبقًا")
        sys.exit(1)
    idx = conf.rstrip().rfind("\n}")
    if idx < 0:
        print("ABORT: بنية conf غير متوقعة (لا قوس إغلاق نهائي)")
        sys.exit(1)
    new_conf = conf.rstrip()[:idx] + LOCATION_TMPL.format(token=token) + "}\n"

    # 1) رفع الجديد + نسخة احتياطية ثم استبدال + فحص nginx -t
    sftp = c.open_sftp()
    with sftp.open("/home/opc/agentic.conf.new", "w") as f:
        f.write(new_conf)
    sftp.close()
    run(f"sudo -n cp /etc/nginx/conf.d/agentic.conf /home/opc/agentic.conf.pre-w1t03 && "
        f"sudo -n sha256sum /home/opc/agentic.conf.pre-w1t03", check=True)
    run("sudo -n cp /home/opc/agentic.conf.new /etc/nginx/conf.d/agentic.conf && "
        "sudo -n restorecon -v /etc/nginx/conf.d/agentic.conf 2>/dev/null; "
        "sudo -n nginx -t 2>&1", check=True)

    # 2) reload (لا restart — صفر انقطاع)
    run("sudo -n systemctl reload nginx && echo RELOAD_OK", check=True)
    time.sleep(2)

    # 3) تحققات داخلية
    rc, hz_loc, _ = run(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 8 http://127.0.0.1/healthz-{token}")
    rc, wall, _ = run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1/")
    rc, app_h, _ = run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
    rc, svcs, _ = run("systemctl is-active nginx agentic.service")
    rc, hz_body, _ = run(f"curl -s --max-time 8 http://127.0.0.1/healthz-{token} | head -c 120")

    ok_local = (hz_loc.strip() == "200" and wall.strip() == "401"
                and app_h.strip() == "200" and "active" in svcs)
    print(f"LOCAL GATE: healthz={hz_loc.strip()} wall={wall.strip()} app={app_h.strip()} svcs={svcs.strip()} → {'OK' if ok_local else 'FAIL'}")

    if not ok_local:
        print("!! بوتقة داخلية فاشلة — تراجع تلقائي")
        run("sudo -n cp /home/opc/agentic.conf.pre-w1t03 /etc/nginx/conf.d/agentic.conf && "
            "sudo -n nginx -t 2>&1 && sudo -n systemctl reload nginx && echo ROLLBACK_DONE", check=True)
        run("curl -s -o /dev/null -w '%{http_code}\\n' --max-time 8 http://127.0.0.1/")
        log("rollback.txt", "\n".join(out_all), mask=token)
        sys.exit(2)

    log("deploy_internal.txt", "\n".join(out_all), mask=token)
    c.close()

    # 4) التحقق الخارجي من بيئة التنفيذ (IP خارجي — ليس المالك ولا الخادم)
    import urllib.request
    import urllib.error
    ext = {}
    for label, url in [
        ("healthz_ext", f"http://92.5.14.150/healthz-{token}"),
        ("root_ext", "http://92.5.14.150/"),
        ("other_path_ext", "http://92.5.14.150/api/projects"),
    ]:
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                body = r.read(120).decode("utf-8", "replace")
                ext[label] = {"code": r.status, "body_head": body}
        except urllib.error.HTTPError as ex:
            ext[label] = {"code": ex.code, "body_head": ex.read(80).decode("utf-8", "replace")}
        except Exception as ex:
            ext[label] = {"error": str(ex)[:200]}

    print("EXTERNAL:", {k: v.get("code", v.get("error")) for k, v in ext.items()})
    ok_ext = ext["healthz_ext"].get("code") == 200 and ext["root_ext"].get("code") in (401, 403)
    summary = {
        "ts": TS,
        "local": {"healthz": hz_loc.strip(), "wall_401": wall.strip(),
                  "app_health": app_h.strip(), "services": svcs.strip(),
                  "healthz_body_head": hz_body.strip()[:120]},
        "external": ext,
        "token_prefix": token[:8],
        "token_saved": TOKEN_FILE,
        "verdict_local": "PASS" if ok_local else "FAIL",
        "verdict_external": "PASS" if ok_ext else "FAIL",
        "rollback": "sudo -n cp /home/opc/agentic.conf.pre-w1t03 /etc/nginx/conf.d/agentic.conf && sudo -n nginx -t && sudo -n systemctl reload nginx",
        "owner_step_pending": "خطوة 3 (بطاقة W1-T03): حساب UptimeRobot/BetterStack + فاحص HTTP 60ث على http://92.5.14.150/healthz-<TOKEN> + تنبيه بريد عند فشلين — تتطلب بريد المالك",
    }
    import json
    log("results.json", json.dumps(summary, ensure_ascii=False, indent=2), mask=token)
    print(f"\nFINAL: local={summary['verdict_local']} external={summary['verdict_external']}")
    sys.exit(0 if (ok_local and ok_ext) else 3)


if __name__ == "__main__":
    main()
