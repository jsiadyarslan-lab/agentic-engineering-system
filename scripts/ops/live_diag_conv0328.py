#!/usr/bin/env python3
# LIVE-DIAG-0328 (read-only): locate the conversation where the factory agent
# claimed "لا أملك إنترنت مباشر" (~03:28 per owner) and trace what web_search
# actually did in it. Read-only DB (mode=ro) + GET endpoints only. No writes.
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

# 1) schema hint for tool_invocations
try:
    cols = [dict(r) for r in db.execute("PRAGMA table_info(tool_invocations)")]
    out["ti_columns"] = [c["name"] for c in cols]
except Exception as e:
    out["ti_columns_err"] = str(e)

# 2) recent conversations (all, newest 15)
try:
    out["conversations"] = [dict(r) for r in db.execute(
        "SELECT id,title,mode,created_at,updated_at FROM conversations ORDER BY updated_at DESC LIMIT 15")]
except Exception as e:
    out["conversations_err"] = str(e)

# 3) recent messages (newest 40) — find the 03:28 "؟" and the no-internet reply
try:
    out["messages"] = [dict(r) for r in db.execute(
        "SELECT id,conversation_id,role,created_at,length(content) AS clen,substr(content,1,700) AS head FROM messages ORDER BY id DESC LIMIT 40")]
except Exception as e:
    out["messages_err"] = str(e)

# 4) tool_invocations newest 30 (web_search etc)
try:
    out["tool_invocations"] = [dict(r) for r in db.execute(
        "SELECT * FROM tool_invocations ORDER BY id DESC LIMIT 30")]
except Exception as e:
    out["ti_err"] = str(e)

# 5) research/tool events newest 40
try:
    out["events"] = [dict(r) for r in db.execute(
        "SELECT id,kind,created_at,cycle_id,substr(payload,1,500) AS payload_head FROM events WHERE kind LIKE 'research%' OR kind LIKE 'tool%' OR kind LIKE 'environment%' ORDER BY id DESC LIMIT 40")]
except Exception as e:
    out["events_err"] = str(e)

print("@@JSON@@")
print(json.dumps(out, ensure_ascii=False, default=str))
'''

cmd = "python3 - <<'PYEOF'\n" + DB_PY + "\nPYEOF"
out, err = run(cmd)
if err:
    print("STDERR:", err[:2000])
try:
    payload = json.loads(out.split("@@JSON@@", 1)[1])
except Exception as e:
    print("PARSE ERROR:", e)
    print(out[:3000])
    raise SystemExit

print("== tool_invocations columns ==")
print(payload.get("ti_columns"))

print("\n== recent conversations ==")
for c in payload.get("conversations", []):
    print(f"  id={c['id']} mode={c.get('mode')} created={c.get('created_at')} updated={c.get('updated_at')} title={str(c.get('title'))[:80]}")

print("\n== recent messages (newest first) ==")
for m in payload.get("messages", []):
    print(f"  [{m['id']}] conv={m['conversation_id']} {m['role']} @ {m['created_at']} len={m['clen']}")
    print(f"      {str(m['head'])[:280].replace(chr(10),' | ')}")

print("\n== recent tool_invocations (newest first) ==")
for t in payload.get("tool_invocations", []):
    ti = {k: (str(v)[:200] if v is not None else None) for k, v in t.items()}
    print(f"  [{t.get('id')}] {json.dumps(ti, ensure_ascii=False)[:600]}")

print("\n== recent events (newest first) ==")
for e in payload.get("events", []):
    print(f"  [{e.get('id')}] {e.get('kind')} @ {e.get('created_at')} cycle={e.get('cycle_id')}")
    print(f"      {str(e.get('payload_head'))[:300]}")

ssh.close()
