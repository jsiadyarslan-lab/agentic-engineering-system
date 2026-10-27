#!/usr/bin/env python3
"""W1-T02 — مستخدم اختبار مؤقت w1t02a (إضافة في المكان — درس 011-B: لا mv أبداً).
البيانات في /tmp فقط (لا تدخل الأدلة/المستودع أبداً)."""
import os
import secrets
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
USER_NAME = "w1t02a"
PW = "W1T02-" + secrets.token_hex(6)
LOCAL_CREDS = "/tmp/w1t02_creds.txt"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
          look_for_keys=False, allow_agent=False)


def run(cmd, t=30):
    _, o, e = c.exec_command(cmd, timeout=t)
    rc = o.channel.recv_exit_status()
    out, err = o.read().decode(), e.read().decode()
    print(f"$ {cmd[:110]}\n{out.strip()[:400]}"
          f"{('[stderr] ' + err.strip()[:200]) if err.strip() else ''}\n[rc={rc}]")
    return rc, out, err


# بصمة قبل (inode/size/sha256) للتحقق البايتي بعد التنظيف
run("sudo -n stat -c 'inode=%i size=%s' /etc/nginx/.htpasswd_vis && sudo -n sha256sum /etc/nginx/.htpasswd_vis && sudo -n wc -l /etc/nginx/.htpasswd_vis")
run(f"sudo -n sh -c \"printf '{USER_NAME}:' >> /etc/nginx/.htpasswd_vis && openssl passwd -apr1 '{PW}' | sudo -n tee -a /etc/nginx/.htpasswd_vis > /dev/null && echo APPEND_OK\"")
run(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 8 -u '{USER_NAME}:{PW}' http://127.0.0.1/ ; echo ' <- expect 200'")

with open(LOCAL_CREDS, "w") as f:
    f.write(f"{USER_NAME}:{PW}\n")
os.chmod(LOCAL_CREDS, 0o600)
print(f"[creds saved locally ONLY: {LOCAL_CREDS}]")
c.close()
