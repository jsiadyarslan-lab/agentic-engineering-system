#!/usr/bin/env python3
# LIVE-DIAG-001 (read-only): why does the factory agent still say search is broken
# after W2-T20 (deployed ~01:00Z, closed 01:12Z) — complaint timestamped 01:21Z.
import json, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=90):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    return so.read().decode(errors="replace").strip(), se.read().decode(errors="replace").strip()

print("=== 1. server time + services + health ===")
o, e = run("date -u '+%Y-%m-%d %H:%M:%S UTC'; uptime -s; "
           "systemctl is-active agentic searxng search-api nginx | tr '\\n' ' '; echo; "
           "curl -s -o /dev/null -w 'health=%{http_code}\\n' http://127.0.0.1:8010/health; "
           "curl -s -o /dev/null -w 'searx=%{http_code}\\n' 'http://127.0.0.1:8888/search?q=test&format=json&language=en'")
print(o, e[:300])

print("\n=== 2. readiness (web_search capability) ===")
o, e = run("curl -s http://127.0.0.1:8010/api/environment/readiness | head -c 3000")
print(o[:3000], e[:200])

PY = r'''
import sqlite3, json
db = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row
cur = db.cursor()

def safe(q, label, width=850):
    print("=== %s ===" % label)
    try:
        rows = cur.execute(q).fetchall()
        if not rows: print("(empty)")
        for r in rows:
            print(json.dumps(dict(r), ensure_ascii=False)[:width])
    except Exception as ex:
        print("ERR:", ex)
    print()

tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
print("=== TABLES ===")
print(json.dumps(tabs))
print()

for t in tabs:
    if any(k in t for k in ("message","conversation","invocation","step","cycle","gate","approval","project")):
        cols = [c[1] for c in cur.execute("PRAGMA table_info(%s)" % t).fetchall()]
        print("SCHEMA %s: %s" % (t, cols))
print()

safe("SELECT id,name,status,substr(coalesce(goal,''),1,100) goal,created_at,updated_at FROM projects ORDER BY id DESC LIMIT 4",
     "projects (last 4)", 600)

safe("""SELECT id,cycle_id,tool,status,transport_status,result_status,failure_class,failure_stage,
 substr(coalesce(failure_reason,''),1,180) fr, substr(coalesce(query,''),1,100) q, result_count
 FROM tool_invocations WHERE tool LIKE '%search%' ORDER BY id DESC LIMIT 15""",
     "search tool_invocations (last 15 — #207 was last pre-fix failure)")

safe("""SELECT id,cycle_id,tool,status,failure_class,substr(coalesce(failure_reason,''),1,150) fr,
 substr(coalesce(query,''),1,80) q, result_count
 FROM tool_invocations WHERE id > 207 ORDER BY id ASC LIMIT 30""",
     "ALL tool invocations after #207 (any tool)")

safe("""SELECT id,kind,state,cycle_id,duration_ms,substr(coalesce(payload,''),1,220) p,created_at
 FROM events WHERE created_at >= '2026-10-28 00:40' ORDER BY id DESC LIMIT 40""",
     "events since 00:40Z (last 40)")
'''

print("\n=== 3. DB state ===")
o, e = run("cd /opt/agentic-engineering-system && python3 - <<'PYEOF'\n" + PY + "\nPYEOF")
print(o[:14000])
print("STDERR:", e[:600])

print("\n=== 4. agentic journal: search/provider/error lines since 01:00Z ===")
o, e = run("sudo -n journalctl -u agentic --since '2026-10-28 01:00:00' --no-pager 2>/dev/null | "
           "grep -iE 'search|provider|research|error|warn|fail' | tail -50")
print(o[:6000] if o else "(no matching lines)")
o2, e2 = run("sudo -n journalctl -u agentic --since '2026-10-28 01:00:00' --no-pager 2>/dev/null | tail -25")
print("\n--- journal tail (last 25 lines) ---")
print(o2[:4000])

ssh.close()
print("\nDIAG DONE")
