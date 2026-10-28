#!/usr/bin/env python3
# LIVE-DIAG-002 (read-only): full failure detail (record_json/error) of post-fix
# web_search invocations + provider table state + last events for project-3.
import json, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=90):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    return so.read().decode(errors="replace").strip(), se.read().decode(errors="replace").strip()

PY = r'''
import sqlite3, json
db = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row
cur = db.cursor()

print("=== full record_json for FAILED web_search #219,226,237 + SUCCEEDED #217 ===")
for rid in (217, 219, 226, 237):
    r = cur.execute("SELECT id,record_json,error,query,duration_ms,execution_site,created_at FROM tool_invocations WHERE id=?", (rid,)).fetchone()
    if r:
        print("--- id=%s status_field query=%r created=%s dur=%sms site=%s" % (r["id"], r["query"][:70], r["created_at"], r["duration_ms"], r["execution_site"]))
        print("error:", (r["error"] or "")[:400])
        try:
            rec = json.loads(r["record_json"])
            print("record_json keys:", list(rec.keys())[:20])
            print(json.dumps(rec, ensure_ascii=False)[:1600])
        except Exception as ex:
            print("record_json parse ERR:", ex, (r["record_json"] or "")[:600])
        print()

print("=== research_providers full state ===")
for r in cur.execute("SELECT id,kind,name,enabled,last_probe_status,failure_reason,last_probe_at,config_json FROM research_providers ORDER BY id").fetchall():
    print(json.dumps(dict(r), ensure_ascii=False)[:500])

print()
print("=== project 3 + its steps state ===")
for r in cur.execute("SELECT id,name,status,current_step_id,last_error,stop_requested,completion_state,updated_at FROM projects WHERE id IN (2,3)").fetchall():
    print(json.dumps(dict(r), ensure_ascii=False)[:400])
for r in cur.execute("SELECT id,phase_id,ordinal,status,attempts,substr(coalesce(last_error,''),1,200) le,updated_at FROM steps WHERE phase_id IN (SELECT id FROM phases WHERE project_id=3) ORDER BY ordinal DESC LIMIT 6").fetchall():
    print(json.dumps(dict(r), ensure_ascii=False)[:400])

print()
print("=== owner_gates open ===")
for r in cur.execute("SELECT id,project_id,kind,status,substr(coalesce(reason,''),1,150) reason,substr(coalesce(details,''),1,250) details,created_at FROM owner_gates WHERE status NOT IN ('resolved','approved','rejected') ORDER BY id DESC LIMIT 8").fetchall():
    print(json.dumps(dict(r), ensure_ascii=False)[:600])

print()
print("=== last messages (chat with agent) ===")
for r in cur.execute("""SELECT m.id,m.conversation_id,m.role,substr(coalesce(m.content,''),1,500) c,m.created_at
 FROM messages m WHERE m.created_at >= '2026-10-28 00:30' ORDER BY m.id DESC LIMIT 12""").fetchall():
    print(json.dumps(dict(r), ensure_ascii=False)[:700])
print()
print("=== conversations ===")
for r in cur.execute("SELECT id,title,mode,project_id,created_at,updated_at FROM conversations ORDER BY id DESC LIMIT 5").fetchall():
    print(json.dumps(dict(r), ensure_ascii=False)[:300])
'''

o, e = run("cd /opt/agentic-engineering-system && python3 - <<'PYEOF'\n" + PY + "\nPYEOF")
print(o[:16000])
print("STDERR:", e[:500])
ssh.close()
print("\nDIAG2 DONE")
