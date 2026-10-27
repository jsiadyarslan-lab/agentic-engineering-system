#!/usr/bin/env python3
"""W1-T01 — emergency state check (read-only). What phase did the timed-out run reach?"""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
          look_for_keys=False, allow_agent=False)

CMDS = [
    ("states", "for s in agentic agentic-vis aes-shim nginx; do printf '%s active=' $s; systemctl is-active $s 2>&1; printf '  enabled='; systemctl is-enabled $s 2>&1; done"),
    ("ports", "sudo -n ss -tln | grep -E ':8010|:8011|:8099'; echo EXIT_$?"),
    ("dirs", "ls -d /opt/aes-vis /opt/aes-shim /opt/aes-archive /opt/aes-archive/* 2>&1"),
    ("health", "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health"),
    ("procs", "ps aux | grep -E 'aes-vis|aes-shim|8011|8099' | grep -v grep | head -5; echo EXIT_$?"),
    ("mem", "free -m | head -2"),
]
for name, cmd in CMDS:
    _, o, e = c.exec_command(cmd, timeout=30)
    rc = o.channel.recv_exit_status()
    out = o.read().decode(errors="replace").strip()
    print(f"===== {name} [rc={rc}] =====\n{out}\n")
c.close()
