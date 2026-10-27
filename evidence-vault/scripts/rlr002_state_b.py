#!/usr/bin/env python3
"""RLR-002-b — locate production deployment, inspect shim, recent prod model failures."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

CHECKS = [
    ("server time", "date; uptime"),
    ("prod 8010 process details",
     "PID=$(pgrep -f 'uvicorn.*8010' | head -1); echo PID=$PID; sudo -n readlink /proc/$PID/cwd 2>&1; sudo -n cat /proc/$PID/cmdline 2>/dev/null | tr '\\0' ' '; echo"),
    ("agentic.service unit", "systemctl cat agentic.service 2>/dev/null | head -30"),
    ("shim unit", "systemctl cat aes-shim.service 2>/dev/null | head -25"),
    ("shim port", "ss -tlnp 2>/dev/null | grep -E '8099|shim' | head -3"),
    ("shim quick probe", "timeout 6 curl -sS http://127.0.0.1:8099/v1/models 2>&1 | head -c 400"),
    ("prod dir guess", "ls -d /opt/aes* 2>/dev/null; ls /opt/ 2>/dev/null"),
    ("prod recent events (model failures)",
     "PROD=$(sudo -n readlink /proc/$(pgrep -f 'uvicorn.*8010' | head -1)/cwd 2>/dev/null); echo PRODDIR=$PROD; "
     "sudo -n ls $PROD/runtime/*.db 2>/dev/null | head -3"),
    ("nginx routing", "sudo -n grep -rE 'proxy_pass|listen|server_name' /etc/nginx/conf.d/ /etc/nginx/sites-enabled/ 2>/dev/null | grep -vE '^\\s*#' | head -15"),
]


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=25,
              look_for_keys=False, allow_agent=False)
    try:
        for title, cmd in CHECKS:
            _, o, e = c.exec_command(cmd, timeout=45)
            o.channel.recv_exit_status()
            out = o.read().decode("utf-8", "replace").strip()
            err = e.read().decode("utf-8", "replace").strip()
            print(f"### {title}")
            if out:
                print(out[:2200])
            if err and not out:
                print(f"[stderr] {err[:300]}")
            print(flush=True)
    finally:
        c.close()


if __name__ == "__main__":
    main()
