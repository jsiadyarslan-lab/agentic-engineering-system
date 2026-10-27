#!/usr/bin/env python3
"""RLR-001 continuation — READ-ONLY live server state check.

Checks: production HEAD vs GitHub main (58d4341), service health, ports
8010/8011, preview mechanism on 8011, recent factory run outcomes,
model egress path. NO modifications anywhere.
"""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
APP = "/opt/agentic-engineering-system"

CHECKS = [
    ("prod HEAD", f"git -C {APP} rev-parse HEAD"),
    ("prod branch", f"git -C {APP} branch --show-current"),
    ("tree clean", f"git -C {APP} status --porcelain --untracked-files=no | wc -l"),
    ("service active", "systemctl is-active agentic.service"),
    ("health 8010", "curl -s --max-time 5 http://127.0.0.1:8010/health | head -c 200"),
    ("asset version 8010", "curl -s --max-time 5 http://127.0.0.1:8010/ | grep -oE 'v=[0-9a-f]{{8,40}}' | sort -u | head -5"),
    ("nginx proxy", "grep -H proxy_pass /etc/nginx/conf.d/agentic.conf 2>/dev/null; sudo -n grep -H proxy_pass /etc/nginx/conf.d/*.conf 2>/dev/null | head -5"),
    ("listeners 8010/8011", "ss -tlnp 2>/dev/null | grep -E ':(8010|8011)' | head -5"),
    ("8011 responder", "curl -s --max-time 5 -o /dev/null -w '%{{http_code}}' http://127.0.0.1:8011/ ; echo"),
    ("8011 health", "curl -s --max-time 5 http://127.0.0.1:8011/health | head -c 200"),
    ("8011 service unit", "systemctl list-units --all --no-pager 2>/dev/null | grep -iE 'agentic|aes|preview' | head -5"),
    ("agentic unit file", "systemctl cat agentic.service 2>/dev/null | grep -E 'ExecStart|WorkingDir|Environment' | head -8"),
    ("all app units", "sudo -n systemctl list-unit-files --no-pager 2>/dev/null | grep -iE 'agentic|aes' | head -8"),
    ("secrets store exists", f"ls -la {APP}/runtime/secrets/ 2>/dev/null | head -5; sudo -n ls -la /etc/.z-ai-config 2>/dev/null | head -3"),
    ("direct egress 443", "curl -s --max-time 6 -o /dev/null -w '%{{http_code}}' https://integrate.api.nvidia.com/ ; echo ' <- 000=fail (expected VCN block)'"),
    ("recent service errors", "sudo -n journalctl -u agentic.service --since '2 hours ago' --no-pager 2>/dev/null | grep -iE 'error|refused|timeout|blocked|retry' | tail -12"),
    ("runs db", f"ls -la {APP}/runtime/*.db 2>/dev/null | head -5"),
]


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
              look_for_keys=False, allow_agent=False)
    try:
        for title, cmd in CHECKS:
            _, o, e = c.exec_command(cmd, timeout=30)
            rc = o.channel.recv_exit_status()
            out = o.read().decode("utf-8", "replace").strip()
            err = e.read().decode("utf-8", "replace").strip()
            print(f"### {title}")
            if out:
                print(out[:1200])
            if err and not out:
                print(f"[stderr] {err[:300]}")
            print()
    finally:
        c.close()


if __name__ == "__main__":
    main()
