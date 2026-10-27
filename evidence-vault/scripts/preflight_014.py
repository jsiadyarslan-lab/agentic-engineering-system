#!/usr/bin/env python3
"""AES-014 preflight — read-only health probe of Oracle production."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
APP = "/opt/agentic-engineering-system"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
          look_for_keys=False, allow_agent=False)

cmds = [
    ("service", "systemctl is-active agentic"),
    ("head", f"git -C {APP} rev-parse --short HEAD"),
    ("tree", f"git -C {APP} status --short | head -3"),
    ("health", "curl -s -m 8 http://127.0.0.1:8010/health"),
    ("nginx-auth", "curl -s -o /dev/null -w '%{http_code}' -m 8 http://127.0.0.1:80/"),
    ("crit", "sudo grep -c crit /var/log/nginx/error.log 2>/dev/null || grep -c crit /var/log/nginx/error.log"),
]
for name, cmd in cmds:
    _, o, e = c.exec_command(cmd, timeout=30)
    rc = o.channel.recv_exit_status()
    print(f"[{name}] rc={rc} :: {o.read().decode().strip()[:200]} {e.read().decode().strip()[:100]}")
c.close()
print("PREFLIGHT_DONE")
