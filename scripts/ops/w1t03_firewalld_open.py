#!/usr/bin/env python3
"""W1-T03 — فتح منفذ 80 في firewalld (استعادة افتراض بطاقة W1-T03: المراقب الخارجي يصل nginx).

R6: حالة قبل (موثقة في evidence) → تغيير → تحقق بعد (داخلي + خارجي).
التراجع: sudo -n firewall-cmd --permanent --remove-port=80/tcp && sudo -n firewall-cmd --reload
"""
import json
import os
import time
import urllib.error
import urllib.request
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EVID = "/home/z/my-project/download/aes-remediation/W1-T03"
TOKEN_FILE = os.path.join(EVID, "owner-token.txt")
TS = time.strftime("%Y%m%d-%H%M%S")

with open(TOKEN_FILE) as f:
    TOKEN = f.read().strip()

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
          look_for_keys=False, allow_agent=False)


def run(cmd, t=60, check=False):
    _, o, e = c.exec_command(cmd, timeout=t)
    rc = o.channel.recv_exit_status()
    out, err = o.read().decode("utf-8", "replace"), e.read().decode("utf-8", "replace")
    print(f"$ {cmd[:130]}\n{out.strip()[:900]}{('[stderr] ' + err.strip()[:250]) if err.strip() else ''}\n[rc={rc}]")
    if check and rc != 0:
        raise RuntimeError(f"ABORT rc={rc}: {cmd[:100]}")
    return rc, out, err


print("===== BEFORE (R6) =====")
run("systemctl is-active firewalld nginx agentic.service")
run("sudo -n firewall-cmd --list-all | head -14")
run("curl -s -o /dev/null -w '%{http_code}\\n' --max-time 5 http://127.0.0.1/healthz-" + TOKEN)

print("===== CHANGE =====")
run("sudo -n firewall-cmd --permanent --add-port=80/tcp && sudo -n firewall-cmd --reload", check=True)

print("===== AFTER (داخلي) =====")
run("sudo -n firewall-cmd --list-all | head -14")
run("systemctl is-active firewalld nginx agentic.service")
run("sudo -n nginx -t 2>&1 | tail -2")
run("curl -s -o /dev/null -w '%{http_code}\\n' --max-time 5 http://127.0.0.1/healthz-" + TOKEN)
run("curl -s -o /dev/null -w '%{http_code}\\n' --max-time 5 http://127.0.0.1/")
c.close()

print("===== AFTER (خارجي — من بيئة التنفيذ، IP غير المالك) =====")
ext = {}
for label, url in [
    ("healthz_ext", f"http://92.5.14.150/healthz-{TOKEN}"),
    ("root_ext", "http://92.5.14.150/"),
    ("api_ext", "http://92.5.14.150/api/projects"),
    ("fake_token_ext", "http://92.5.14.150/healthz-00000000000000000000000000000000"),
]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=12) as r:
            ext[label] = {"code": r.status, "body_head": r.read(100).decode("utf-8", "replace")}
    except urllib.error.HTTPError as ex:
        ext[label] = {"code": ex.code}
    except Exception as ex:
        ext[label] = {"error": str(ex)[:160]}
    print(f"{label}: {ext[label]}")

ok = (ext["healthz_ext"].get("code") == 200
      and ext["root_ext"].get("code") in (401, 403)
      and ext["api_ext"].get("code") in (401, 403)
      and ext["fake_token_ext"].get("code") in (401, 403))
print(f"\nEXTERNAL GATE: {'PASS' if ok else 'FAIL'}")

summary = {
    "ts": TS,
    "discovery": "firewalld rich rule قصر دخول 80 على 2.215.157.88 فقط — مخالف لافتراض بطاقة W1-T03 (المراقب الخارجي يصل nginx)؛ الفتح يستعيد التصميم المعتمد والحماية الفعلية تبقى allowlist nginx + Basic Auth",
    "change": "firewall-cmd --permanent --add-port=80/tcp + reload",
    "rollback": "sudo -n firewall-cmd --permanent --remove-port=80/tcp && sudo -n firewall-cmd --reload",
    "external": ext,
    "verdict_external": "PASS" if ok else "FAIL",
    "token_prefix": TOKEN[:8],
}
os.makedirs(EVID, exist_ok=True)
with open(os.path.join(EVID, f"{TS}-firewalld_results.json"), "w") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(f"[evidence] {EVID}/{TS}-firewalld_results.json")
