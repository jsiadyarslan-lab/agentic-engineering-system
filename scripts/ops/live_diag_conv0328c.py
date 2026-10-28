#!/usr/bin/env python3
# LIVE-DIAG-0328-C (read-only): chat-15 non-delta events only (turns 2 & 3),
# plus providers table state. Read-only.
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

# chat-15 non-delta events
out["chat15_events"] = [dict(r) for r in db.execute(
    "SELECT id,kind,created_at,payload FROM events WHERE cycle_id='chat-15' AND kind NOT IN ('message_delta') ORDER BY id")]

# providers state (chain order!)
try:
    out["providers"] = [dict(r) for r in db.execute("SELECT * FROM research_providers ORDER BY id")]
except Exception as e:
    out["providers_err"] = str(e)

# any events at all after 02:28 (any stream)
out["events_after_0228"] = [dict(r) for r in db.execute(
    "SELECT id,kind,cycle_id,created_at,substr(payload,1,700) AS payload_head FROM events WHERE created_at > '2026-10-28 02:28:00' AND kind NOT IN ('message_delta') ORDER BY id")]

print("@@JSON@@")
print(json.dumps(out, ensure_ascii=False, default=str))
'''

cmd = "python3 - <<'PYEOF'\n" + DB_PY + "\nPYEOF"
out, err = run(cmd)
if err:
    print("STDERR:", err[:1500])
payload = json.loads(out.split("@@JSON@@", 1)[1])

print("== chat-15 non-delta events ==")
for e in payload.get("chat15_events", []):
    p = str(e["payload"])
    # skip pure delta noise
    print(f"--- [{e['id']}] {e['kind']} @ {e['created_at']}")
    print(f"    {p[:1200]}")

print("\n== research_providers (chain order) ==")
for p in payload.get("providers", []):
    slim = {k: (str(v)[:120] if v is not None else None) for k, v in p.items()}
    print(f"  {json.dumps(slim, ensure_ascii=False)[:700]}")

print("\n== events after 02:28 (non-delta, all streams) ==")
for e in payload.get("events_after_0228", []):
    print(f"--- [{e['id']}] {e['kind']} cycle={e['cycle_id']} @ {e['created_at']}")
    print(f"    {str(e['payload_head'])[:800]}")

ssh.close()
