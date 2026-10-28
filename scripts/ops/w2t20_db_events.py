#!/usr/bin/env python3
# W2-T20: last web_search tool invocations + events (READ-ONLY)
import json, paramiko

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

print("=== tool_invocations: web_search (last 12) ===")
for r in cur.execute("""
  SELECT id, cycle_id, tool, status, transport_status, result_status,
         failure_class, failure_stage, failure_reason, query, result_count
  FROM tool_invocations WHERE tool LIKE '%search%' ORDER BY id DESC LIMIT 12
""").fetchall():
    print(json.dumps(dict(r), ensure_ascii=False)[:700])

print()
print("=== events: tool failures last 6h (last 15) ===")
for r in cur.execute("""
  SELECT id, cycle_id, kind, state, duration_ms, created_at, substr(payload,1,500) AS payload
  FROM events WHERE kind LIKE 'tool%' AND state LIKE '%fail%'
  AND created_at > datetime('now','-6 hours') ORDER BY id DESC LIMIT 15
""").fetchall():
    print(json.dumps(dict(r), ensure_ascii=False)[:700])

print()
print("=== latest active project (news website?) ===")
for r in cur.execute("""
  SELECT id, name, status, substr(coalesce(goal,''),1,120) AS goal, created_at, updated_at
  FROM projects ORDER BY id DESC LIMIT 3
""").fetchall():
    print(json.dumps(dict(r), ensure_ascii=False)[:400])

print()
print("=== research_providers table state ===")
for r in cur.execute("""
  SELECT id, kind, name, enabled, last_probe_status, failure_reason, config_json,
         last_probe_at FROM research_providers ORDER BY id
""").fetchall():
    print(json.dumps(dict(r), ensure_ascii=False)[:500])
'''

o, e = run("cd /opt/agentic-engineering-system && python3 - <<'PYEOF'\n" + PY + "\nPYEOF")
print(o[:7000])
print("STDERR:", e[:500])
ssh.close()
