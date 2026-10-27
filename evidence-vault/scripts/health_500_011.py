#!/usr/bin/env python3
"""AES-011 — remaining quick health checks (ausearch hung last run; skip it)."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/home/z/.ssh_key_010"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
          look_for_keys=False, allow_agent=False)

def run(cmd, t=25):
    _, o, e = c.exec_command(cmd, timeout=t)
    rc = o.channel.recv_exit_status()
    out, err = o.read().decode(), e.read().decode()
    print(f"$ {cmd[:120]}\n{out.strip()[:900]}{('[stderr] ' + err.strip()[:200]) if err.strip() else ''}\n[rc={rc}]\n")
    return rc, out, err

run("systemctl is-active agentic.service")
run("curl -s --max-time 6 http://127.0.0.1:8010/health | head -c 200")
run("git -C /opt/agentic-engineering-system rev-parse HEAD")
run("git -C /opt/agentic-engineering-system status --porcelain --untracked-files=no | wc -l")
run("grep -n 'proxy_pass\\|auth_basic_user_file\\|allow\\|deny' /etc/nginx/conf.d/agentic.conf")
run("curl -s -o /dev/null -w '%{http_code}' --max-time 6 http://127.0.0.1/ ; echo ' <- no-creds via nginx:80'")
run("grep -n '^user' /etc/nginx/nginx.conf")
run("sudo -n tail -n 6 /var/log/nginx/error.log")
c.close()
print("HEALTH-DONE")
