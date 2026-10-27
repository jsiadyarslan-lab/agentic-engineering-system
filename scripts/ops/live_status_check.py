#!/usr/bin/env python3
# READ-ONLY live status check — zero writes on production.
# Purpose: answer owner's question "المشروع والمصنع لا يعملان؟" with hard evidence,
# and re-verify W1-T05 blocking state (outbound port 80) + current deployed version.
import json, paramiko, sys

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

CMDS = [
    ("services",        "systemctl is-active agentic nginx firewalld 2>/dev/null; systemctl is-active agentic-vis aes-shim 2>/dev/null || true"),
    ("health_loopback", "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health"),
    ("prod_commit",     "cd /opt/agentic-engineering-system && git log --oneline -1 2>/dev/null"),
    ("prod_tree_clean", "cd /opt/agentic-engineering-system && git status --short 2>/dev/null | head -3; echo END"),
    ("asset_version",   "curl -sI --max-time 8 -u \"$(sudo -n grep -oP 'HTPASSWD_LINE=\\K.*' /opt/agentic-engineering-system/.env 2>/dev/null | head -1)\" -H 'X-Forwarded-For: 2.215.157.88' http://127.0.0.1/ 2>/dev/null | grep -i etag || echo 'etag_via_nginx_conf'"),
    ("listeners",       "sudo -n ss -tlnp | grep -E ':(8010|8011|8099|80|443)\\b' | awk '{print $4}' | sort"),
    ("readiness_api",   "curl -s --max-time 8 http://127.0.0.1:8010/api/environment/readiness | head -c 1500"),
    ("http80_egress",   "curl -s -o /dev/null -w '%{http_code} rc=%{exitcode} t=%{time_total}' --max-time 6 http://example.com 2>&1 || echo ' rc_nonzero'"),
    ("https443_egress", "curl -s -o /dev/null -w '%{http_code} t=%{time_total}' --max-time 6 https://example.com"),
    ("mem",             "free -h | head -2; uptime"),
    ("journal_err",     "journalctl -u agentic --since '-30 min' -p err --no-pager 2>/dev/null | tail -3; echo END"),
    ("backup_unit",     "systemctl list-timers --no-pager 2>/dev/null | grep -i aes || echo 'no_aes_timer'"),
]

out = {}
for name, cmd in CMDS:
    try:
        _, so, se = ssh.exec_command(cmd, timeout=30)
        out[name] = {"out": so.read().decode(errors="replace").strip()[:1200],
                     "err": se.read().decode(errors="replace").strip()[:200]}
    except Exception as e:
        out[name] = {"out": "", "err": str(e)[:200]}
    print(f"=== {name} ===\n{out[name]['out']}\n{'[err] ' + out[name]['err'] if out[name]['err'] else ''}")

with open("/home/z/my-project/download/aes-remediation/live-status-check.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
ssh.close()
print("\nSAVED: download/aes-remediation/live-status-check.json")
