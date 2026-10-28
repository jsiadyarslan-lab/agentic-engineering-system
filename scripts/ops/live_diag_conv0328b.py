#!/usr/bin/env python3
# LIVE-DIAG-0328-B (read-only): deep dive into conversation 15 (the owner's
# "03:28" complaint = 02:28:35 UTC update), its research events, projects/steps
# state, and agentic journal errors in the 01:49->02:35 window. Read-only.
import json, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=120):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    return so.read().decode(errors="replace").strip(), se.read().decode(errors="replace").strip()

DB_PY = r'''
import sqlite3, json
db = sqlite3.connect('file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro', uri=True)
db.row_factory = sqlite3.Row
out = {}

# 1) ALL messages of conversation 15, full-ish content
out["conv15_messages"] = [dict(r) for r in db.execute(
    "SELECT id,role,created_at,length(content) AS clen,substr(content,1,2600) AS body FROM messages WHERE conversation_id=15 ORDER BY id")]

# 2) ALL research/tool events for chat-15
out["chat15_events"] = [dict(r) for r in db.execute(
    "SELECT id,kind,created_at,payload FROM events WHERE cycle_id='chat-15' ORDER BY id")]

# 3) tables list (find turns/step tables)
out["tables"] = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

# 4) projects overview
try:
    out["projects"] = [dict(r) for r in db.execute(
        "SELECT id,title,status,created_at,updated_at FROM projects ORDER BY id DESC LIMIT 8")]
except Exception as e:
    out["projects_err"] = str(e)

# 5) recent steps of each recent project
try:
    out["recent_steps"] = [dict(r) for r in db.execute(
        "SELECT * FROM steps ORDER BY id DESC LIMIT 12")]
except Exception as e:
    try:
        out["recent_steps"] = [dict(r) for r in db.execute(
            "SELECT id,project_id,step_index,title,status,verdict,created_at,updated_at FROM steps ORDER BY id DESC LIMIT 12")]
    except Exception as e2:
        out["recent_steps_err"] = str(e2)

print("@@JSON@@")
print(json.dumps(out, ensure_ascii=False, default=str))
'''

cmd = "python3 - <<'PYEOF'\n" + DB_PY + "\nPYEOF"
out, err = run(cmd)
if err:
    print("STDERR:", err[:1500])
payload = json.loads(out.split("@@JSON@@", 1)[1])

print("== tables ==")
print(payload.get("tables"))

print("\n== conv15 messages ==")
for m in payload.get("conv15_messages", []):
    print(f"--- [{m['id']}] {m['role']} @ {m['created_at']} len={m['clen']}")
    print(str(m["body"])[:2400])
    print()

print("\n== chat-15 research events ==")
for e in payload.get("chat15_events", []):
    print(f"--- [{e['id']}] {e['kind']} @ {e['created_at']}")
    print(str(e["payload"])[:1500])
    print()

print("\n== projects ==")
for p in payload.get("projects", []):
    print(f"  id={p.get('id')} status={p.get('status')} created={p.get('created_at')} updated={p.get('updated_at')} title={str(p.get('title'))[:70]}")

print("\n== recent steps (newest first) ==")
for s in payload.get("recent_steps", []):
    slim = {k: (str(v)[:160] if v is not None else None) for k, v in s.items() if k in
            ("id","project_id","step_index","title","status","verdict","state","gate","created_at","updated_at","name")}
    print(f"  {json.dumps(slim, ensure_ascii=False)[:500]}")

# journal errors in the window
print("\n== journalctl agentic errors 01:45->02:40 ==")
jout, jerr = run("sudo -n journalctl -u agentic --since '2026-10-28 01:45:00' --until '2026-10-28 02:40:00' -p warning --no-pager 2>&1 | tail -60")
print(jout[:6000] if jout else "(no output)")

ssh.close()
