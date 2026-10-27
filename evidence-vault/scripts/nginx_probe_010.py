#!/usr/bin/env python3
"""AES-010 — nginx routing investigation (READ-ONLY)."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/home/z/.ssh_key_010"

CMDS = [
    ("agentic_conf_full", "cat /etc/nginx/conf.d/agentic.conf"),
    ("conf_backups", "ls -la /etc/nginx/conf.d/ | grep -i agentic"),
    ("conf_mtime", "stat -c '%y %n' /etc/nginx/conf.d/agentic.conf /etc/nginx/conf.d/agentic.conf.bak-005 2>/dev/null"),
    ("diff_bak", "diff /etc/nginx/conf.d/agentic.conf.bak-005 /etc/nginx/conf.d/agentic.conf 2>/dev/null || echo 'no bak-005 or differs'"),
    ("listening_ports", "ss -tlnp 2>/dev/null | grep -E ':80 |:443 |:8010|:8011' || ss -tln | grep -E ':80 |:443 |:8010|:8011'"),
    ("health_8011_preview", "curl -s --max-time 5 http://127.0.0.1:8011/health 2>&1 | head -c 400"),
    ("health_8010_prod", "curl -s --max-time 5 http://127.0.0.1:8010/health 2>&1 | head -c 400"),
    ("preview_repo", "cd /opt/aes-vis 2>/dev/null && git rev-parse HEAD 2>/dev/null && git log --oneline -2 2>/dev/null && git status --porcelain 2>/dev/null | head -3 || echo 'no /opt/aes-vis git'"),
    ("preview_service", "systemctl list-units --type=service --state=running 2>/dev/null | grep -iE 'aes|vis|uvicorn' ; ps aux | grep -E 'uvicorn|8011|8010' | grep -v grep | head -6"),
    ("nginx_access_tail", "tail -5 /var/log/nginx/access.log 2>/dev/null | sed 's/\\t/ /g' | cut -c1-160"),
    ("prod_app_since", "systemctl show agentic.service -p ActiveEnterTimestamp"),
]

def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=20, look_for_keys=False, allow_agent=False)
    for name, cmd in CMDS:
        _, o, e = c.exec_command(cmd, timeout=30)
        out, err = o.read().decode("utf-8", "replace").strip(), e.read().decode("utf-8", "replace").strip()
        print(f"===== {name} =====")
        if out: print(out[:2500])
        if err: print(f"[stderr] {err[:400]}")
        print()
    c.close()

if __name__ == "__main__":
    main()
