#!/usr/bin/env python3
# READ-ONLY: inspect W2-T10 commit on production + owner browser cache state.
import json, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

CMDS = [
    ("w2t10_commit",  "cd /opt/agentic-engineering-system && git log -3 --format='%h | %ci | %s' "),
    ("w2t10_stat",    "cd /opt/agentic-engineering-system && git show --stat --format='%h %s' 036db8911 | head -30"),
    ("deploy_time",   "systemctl show agentic -p ExecMainStartTimestamp"),
    ("etag_now",      "CONF=$(sudo -n cat /etc/nginx/conf.d/agentic.conf 2>/dev/null | grep -oP 'auth_basic_user_file\\s+\\K[^;]+' | head -1); CRED=$(sudo -n head -1 $CONF 2>/dev/null); curl -sI --max-time 8 -u \"$CRED\" -H 'X-Forwarded-For: 2.215.157.88' http://127.0.0.1/ | grep -iE 'etag|cache-control'"),
    ("owner_hits",    "sudo -n tail -2000 /var/log/nginx/access.log 2>/dev/null | grep '2.215.157.88' | tail -12"),
    ("owner_last_js", "sudo -n tail -3000 /var/log/nginx/access.log 2>/dev/null | grep '2.215.157.88' | grep -oE 'GET /[^ ]+\\?v=[a-f0-9]+' | sort | uniq -c | sort -rn | head -6"),
]
out = {}
for name, cmd in CMDS:
    try:
        _, so, se = ssh.exec_command(cmd, timeout=30)
        out[name] = so.read().decode(errors="replace").strip()[:1500]
        err = se.read().decode(errors="replace").strip()[:150]
    except Exception as e:
        out[name], err = "", str(e)
    print(f"=== {name} ===\n{out[name]}\n{'[err] ' + err if err else ''}")

with open("/home/z/my-project/download/aes-remediation/w2t10-recovery-inspect.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
ssh.close()
print("\nSAVED: download/aes-remediation/w2t10-recovery-inspect.json")
