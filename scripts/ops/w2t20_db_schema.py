#!/usr/bin/env python3
# W2-T20: query agent_hub_v2.db (READ-ONLY) for recent web_search tool events
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=60):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    return so.read().decode(errors="replace").strip(), se.read().decode(errors="replace").strip()

PY = r'''
import sqlite3, json
db = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row
cur = db.cursor()
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("TABLES:", tables[:40])
# find event/tool tables
for t in tables:
    cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})").fetchall()]
    if any('tool' in (c or '').lower() for c in cols) or 'event' in t.lower():
        print("TBL", t, cols[:12])
'''

out = {}
o, e = run("cd /opt/agentic-engineering-system && python3 - <<'PYEOF'\n" + PY + "\nPYEOF")
out["schema"] = o or e[:500]
print(json.dumps(out, ensure_ascii=False, indent=2))
ssh.close()
