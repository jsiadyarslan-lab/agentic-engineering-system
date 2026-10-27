#!/usr/bin/env python3
"""W1-T03 — قراءة فقط: بنية agentic.conf الحالية + حالة الخدمات (بوابة R6 قبل التغيير)."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
          look_for_keys=False, allow_agent=False)


def run(cmd, t=30):
    _, o, e = c.exec_command(cmd, timeout=t)
    rc = o.channel.recv_exit_status()
    out, err = o.read().decode("utf-8", "replace"), e.read().decode("utf-8", "replace")
    print(f"$ {cmd[:120]}\n{out.strip()[:1800]}"
          f"{('[stderr] ' + err.strip()[:300]) if err.strip() else ''}\n[rc={rc}]")
    return rc, out, err


run("sudo -n nginx -t 2>&1")
run("systemctl is-active nginx agentic.service")
run("curl -s -o /dev/null -w '%{http_code}\\n' --max-time 5 http://127.0.0.1:8010/health")
run("curl -s -o /dev/null -w '%{http_code}\\n' --max-time 5 http://127.0.0.1/")
run("sudo -n sha256sum /etc/nginx/conf.d/agentic.conf && sudo -n wc -l /etc/nginx/conf.d/agentic.conf")
print("===== FULL CONF =====")
run("sudo -n cat /etc/nginx/conf.d/agentic.conf")
c.close()
