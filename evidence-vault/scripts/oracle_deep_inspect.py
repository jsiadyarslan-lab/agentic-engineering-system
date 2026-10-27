#!/usr/bin/env python3
"""Deep inspection of the two app dirs + deploy scripts on Oracle."""
import paramiko

HOST, PORT, USER = "92.5.14.150", 22, "opc"
KEY = "/home/z/.ssh_key_006"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname=HOST, port=PORT, username=USER, key_filename=KEY,
               timeout=15, banner_timeout=15, auth_timeout=15,
               allow_agent=False, look_for_keys=False)

CMDS = [
    ("git state /opt/agentic-engineering-system",
     "cd /opt/agentic-engineering-system && git rev-parse HEAD 2>&1 && git status --short 2>&1 | head -10 && git remote -v 2>&1 | head -2 && git log --oneline -3 2>&1"),
    ("git state /opt/aes-vis",
     "cd /opt/aes-vis && git rev-parse HEAD 2>&1 && git status --short 2>&1 | head -15 && git remote -v 2>&1 | head -2 && git log --oneline -3 2>&1"),
    ("aes_vis_deploy.sh",
     "cat /home/opc/aes_vis_deploy.sh 2>&1 | head -60"),
    ("aes_vis_relocate.sh",
     "cat /home/opc/aes_vis_relocate.sh 2>&1 | head -40"),
    ("nginx conf full",
     "cat /etc/nginx/conf.d/agentic.conf 2>&1"),
    ("nginx conf timestamps",
     "ls -la --time-style=full-iso /etc/nginx/conf.d/ 2>&1"),
    ("aes-vis-backups content",
     "ls -la /opt/aes-vis-backups/ 2>&1 | head -10"),
    ("agentic.service unit",
     "systemctl cat agentic.service 2>&1 | head -30"),
    ("health 8010",
     "curl -s --max-time 8 http://127.0.0.1:8010/health 2>&1 | head -c 200"),
    ("health 8011",
     "curl -s --max-time 8 http://127.0.0.1:8011/health 2>&1 | head -c 200"),
    ("version 8010 vs 8011",
     "echo '--- 8010 index.html version refs:'; curl -s --max-time 8 http://127.0.0.1:8010/ | grep -oE 'v=[0-9.]+' | sort | uniq -c | head -5; echo '--- 8011 index.html version refs:'; curl -s --max-time 8 http://127.0.0.1:8011/ | grep -oE 'v=[0-9.]+' | sort | uniq -c | head -5"),
    ("external check from host",
     "curl -s --max-time 8 http://92.5.14.150/ -o /dev/null -w 'external HTTP %{http_code}\\n' 2>&1"),
    ("other ssh sessions now",
     "who 2>&1"),
]

for title, cmd in CMDS:
    stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    print(f"\n===== {title} =====")
    print(out.strip()[:2500])
    if err.strip():
        print(f"[stderr] {err.strip()[:300]}")

client.close()
