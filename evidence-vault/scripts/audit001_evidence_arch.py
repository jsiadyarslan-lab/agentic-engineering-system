#!/usr/bin/env python3
"""AES-AUDIT-001 — Evidence pack 1: architecture + ops + code inventory.
READ-ONLY. No writes, no restarts, no config changes.
Collects: services, nginx, git state, code inventory, repo hygiene, DB size,
memory/CPU/disk, logs sample, /opt/aes-vis state, secrets layout (names only).
"""
import json
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
OUT = "/home/z/my-project/download/aes-audit-001/evidence1_architecture.json"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, key_filename=KEY, timeout=25,
          look_for_keys=False, allow_agent=False)

CMDS = [
    ("services", "systemctl list-units --type=service --all | grep -iE 'aes|agentic|nginx' ; echo '---STATES---'; for s in agentic agentic-vis aes-shim nginx; do printf '%s: ' $s; systemctl is-active $s 2>&1; done"),
    ("git_state", "cd /opt/agentic-engineering-system && git rev-parse HEAD && git log --oneline -8 && echo '---STATUS---' && git status -s | head -10 && echo '---BRANCH---' && git branch --show-current"),
    ("git_repo_size", "cd /opt/agentic-engineering-system && du -sh .git 2>/dev/null && git count-objects -vH | grep -E 'size-pack|count'"),
    ("code_inventory", "cd /opt/agentic-engineering-system && echo '---SRC TREE---' && git ls-files | grep -vE '^(docs|E10|tests)/' | grep -E '\\.(py|js|css|html|toml|rs)$' | awk -F/ '{print $1\"/\"$2}' | sort | uniq -c | sort -rn | head -25 && echo '---UI LOC---' && git ls-files src/ui/ | grep -E '\\.(js|css|html)$' | xargs wc -l | tail -1 && echo '---PY LOC (no tests/docs)---' && git ls-files '*.py' | grep -vE '^(tests|docs|E10)/' | xargs wc -l | tail -1"),
    ("repo_hygiene", "cd /opt/agentic-engineering-system && echo '---TOP LEVEL---' && git ls-files | awk -F/ '{print $1}' | sort | uniq -c | sort -rn | head -20 && echo '---E10 evidence files count---' && git ls-files E10/ | wc -l && echo '---docs files---' && git ls-files docs/ | wc -l"),
    ("backend_layout", "cd /opt/agentic-engineering-system && git ls-files 'src/**/*.py' | grep -v src/ui | head -50"),
    ("app_entry", "cd /opt/agentic-engineering-system && systemctl cat agentic 2>/dev/null | head -30"),
    ("nginx_conf", "cat /etc/nginx/conf.d/agentic.conf 2>/dev/null || sudo -n cat /etc/nginx/conf.d/agentic.conf 2>/dev/null"),
    ("nginx_full", "sudo -n nginx -T 2>/dev/null | grep -vE '^\\s*#|^$' | head -60"),
    ("ports", "sudo -n ss -tlnp 2>/dev/null | head -20 || ss -tln | head -20"),
    ("resources", "free -h && echo '---' && df -h / /opt 2>/dev/null && echo '---' && nproc && uname -m && cat /etc/oracle-release 2>/dev/null || cat /etc/os-release | head -2"),
    ("db_state", "ls -la /opt/agentic-engineering-system/runtime/*.db 2>/dev/null; sudo -n du -sh /opt/agentic-engineering-system/runtime/ 2>/dev/null || du -sh /opt/agentic-engineering-system/runtime/ 2>/dev/null"),
    ("secrets_layout", "ls -la /opt/agentic-engineering-system/runtime/secrets/ 2>/dev/null && sudo -n ls -la /opt/agentic-engineering-system/runtime/secrets/ 2>/dev/null"),
    ("env_files", "ls -la /opt/agentic-engineering-system/.env* 2>/dev/null; echo '---VIS---'; ls -la /opt/aes-vis/.env* 2>/dev/null"),
    ("vis_state", "cd /opt/aes-vis 2>/dev/null && git rev-parse HEAD 2>/dev/null && git log --oneline -3 2>/dev/null && git status -s | head -5 && echo '---DIRS---' && du -sh /opt/aes-vis 2>/dev/null"),
    ("processes", "ps aux | grep -E 'uvicorn|gunicorn|python' | grep -v grep | head -10"),
    ("log_sample", "sudo -n journalctl -u agentic --since '-2h' --no-pager 2>/dev/null | tail -25 || journalctl -u agentic --since '-2h' --no-pager 2>/dev/null | tail -25"),
    ("nginx_access_sample", "sudo -n tail -n 12 /var/log/nginx/access.log 2>/dev/null"),
    ("nginx_error_sample", "sudo -n tail -n 8 /var/log/nginx/error.log 2>/dev/null"),
    ("health", "curl -s --max-time 8 http://127.0.0.1:8010/health | head -c 500"),
    ("tls_check", "sudo -n ls /etc/letsencrypt/live 2>/dev/null; echo '---'; curl -sk -o /dev/null -w '%{http_code}' --max-time 6 https://127.0.0.1/ 2>&1; echo ' <- https self'"),
    ("firewall", "sudo -n iptables -L INPUT -n 2>/dev/null | head -15 || echo 'no iptables access'"),
    ("backup_state", "ls -la /home/opc/ 2>/dev/null | grep -E 'pre-|bak-|bundle' | head -15"),
    ("timers_cron", "systemctl list-timers --no-pager 2>/dev/null | head -10; echo '---CRON---'; crontab -l 2>/dev/null | head -10"),
    ("vis_service_cat", "systemctl cat agentic-vis 2>/dev/null | head -25"),
    ("shim_service_cat", "systemctl cat aes-shim 2>/dev/null | head -20"),
]

results = {}
for name, cmd in CMDS:
    try:
        _, o, e = c.exec_command(cmd, timeout=45)
        rc = o.channel.recv_exit_status()
        out, err = o.read().decode(errors="replace").strip(), e.read().decode(errors="replace").strip()
        results[name] = {"rc": rc, "out": out[:4000], "err": err[:800]}
        print(f"===== {name} [rc={rc}] =====")
        print(out[:2000])
        if err:
            print(f"[stderr] {err[:300]}")
        print()
    except Exception as ex:
        results[name] = {"rc": -1, "out": "", "err": str(ex)}
        print(f"===== {name} [FAILED: {ex}] =====\n")

c.close()

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
print(f"SAVED -> {OUT}")
