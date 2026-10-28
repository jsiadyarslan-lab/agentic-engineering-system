#!/usr/bin/env python3
# W2-T20: read actual web_search failure evidence from production logs/DB (read-only)
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=45):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    return so.read().decode(errors="replace").strip(), se.read().decode(errors="replace").strip()

out = {}

# (1) journal: web_search mentions in last 12h
o, e = run("sudo -n journalctl -u agentic --since '12 hours ago' --no-pager 2>/dev/null | grep -iE 'web_search|web search|SEARCH_PROVIDER|TOOL_FAILURE|بحث' | tail -30")
out["journal_web_search"] = o[:4000]

# (2) journal: errors last 2h
o, e = run("sudo -n journalctl -u agentic -p err --since '2 hours ago' --no-pager 2>/dev/null | tail -15")
out["journal_errors_2h"] = o[:2000] or "(none)"

# (3) active/recent projects: find tool failure records
o, e = run("ls -lt /opt/agentic-engineering-system/runtime/projects/ 2>/dev/null | head -8")
out["projects_dir"] = o

o, e = run("find /opt/agentic-engineering-system/runtime/projects -maxdepth 3 -name '*.json' -mmin -600 2>/dev/null | head -20")
out["recent_json"] = o

# (4) tool failures in DB (events table) — last web_search events
o, e = run("cd /opt/agentic-engineering-system && sudo -n python3 - <<'PYEOF'\n"
           "import sqlite3, json\n"
           "import glob\n"
           "dbs = glob.glob('runtime/*.db') + glob.glob('runtime/**/*.db', recursive=True)\n"
           "print('DBS:', dbs)\n"
           "PYEOF", t=30)
out["dbs"] = o

# (5) check the engine's tool timeout for run_tool (harness)
o, e = run("grep -rn 'timeout' /opt/agentic-engineering-system/src/harness/coordinator.py | head -10; "
           "grep -rn 'TOOL.*TIMEOUT\\|tool_timeout' /opt/agentic-engineering-system/src/workflow/engine.py | head -10")
out["tool_timeouts_code"] = o

path = "/home/z/my-project/download/aes-remediation/W2-T20/failure_evidence.json"
import os
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2, default=str)
print(json.dumps(out, ensure_ascii=False, indent=2, default=str)[:6000])
ssh.close()
