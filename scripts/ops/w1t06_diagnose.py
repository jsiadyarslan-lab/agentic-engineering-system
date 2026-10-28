#!/usr/bin/env python3
# W1-T06 diagnosis (read-only): current gates/projects/steps state for the
# blocked projects (2 and 3) + retry history + how gates resolve.
import json, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=90):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    return so.read().decode(errors="replace").strip(), se.read().decode(errors="replace").strip()

DB_PY = r'''
import sqlite3, json
db = sqlite3.connect('file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro', uri=True)
db.row_factory = sqlite3.Row
out = {}

def cols_of(t):
    return [c[1] for c in db.execute(f"PRAGMA table_info({t})")]

def pick(t, wanted):
    have = set(cols_of(t))
    return ", ".join(c for c in wanted if c in have)

out["schema"] = {t: cols_of(t) for t in ("projects","owner_gates","steps","retry_records","executions")}

pc = pick("projects", ("id","name","title","goal","status","created_at","updated_at","last_error"))
out["projects"] = [dict(r) for r in db.execute(f"SELECT {pc} FROM projects ORDER BY id DESC LIMIT 6")]

gc = pick("owner_gates", ("id","project_id","kind","type","status","reason","created_at","resolved_at","context_json","payload_json"))
out["gates"] = [dict(r) for r in db.execute(f"SELECT {gc} FROM owner_gates ORDER BY id DESC LIMIT 20")]

sc = pick("steps", ("id","project_id","phase_id","step_index","name","title","status","last_error","attempt_count"))
pid_col = "project_id" if "project_id" in set(cols_of("steps")) else None
if pid_col:
    out["steps_p2_p3"] = [dict(r) for r in db.execute(f"SELECT {sc} FROM steps WHERE project_id IN (2,3) ORDER BY id DESC LIMIT 15")]
else:
    # steps linked via phases -> projects
    fcols = set(cols_of("steps")) | set(cols_of("phases"))
    out["steps_p2_p3"] = [dict(r) for r in db.execute(
        f"SELECT s.{sc.replace(', ', ', s.')} FROM steps s JOIN phases p ON s.phase_id = p.id WHERE p.project_id IN (2,3) ORDER BY s.id DESC LIMIT 15")]

rc = pick("retry_records", ("id","step_id","decision","reason","diagnosis","created_at"))
out["retries"] = [dict(r) for r in db.execute(f"SELECT {rc} FROM retry_records ORDER BY id DESC LIMIT 15")]

ec = pick("executions", ("id","step_id","status","error","created_at"))
out["executions"] = [dict(r) for r in db.execute(f"SELECT {ec} FROM executions ORDER BY id DESC LIMIT 15")]

print("@@JSON@@")
print(json.dumps(out, ensure_ascii=False, default=str))
'''

out, err = run("python3 - <<'PYEOF'\n" + DB_PY + "\nPYEOF")
if err:
    print("STDERR:", err[:1000])
p = json.loads(out.split("@@JSON@@", 1)[1])

print("== projects ==")
for pr in p.get("projects", []):
    print(f"  id={pr['id']} status={pr['status']} updated={pr.get('updated_at')} title={str(pr.get('title'))[:60]}")
    if pr.get("last_error"):
        print(f"    last_error: {str(pr['last_error'])[:150]}")

print("\n== gates (newest 20) ==")
for g in p.get("gates", []):
    ctx = str(g.get("context_json") or "")[:150]
    print(f"  [{g['id']}] proj={g['project_id']} {g['kind']} status={g['status']} @ {g['created_at']}")
    print(f"      reason: {str(g.get('reason'))[:160]}")
    print(f"      ctx: {ctx}")

print("\n== steps of projects 2/3 (newest 15) ==")
for s in p.get("steps_p2_p3", []):
    print(f"  [{s['id']}] proj={s['project_id']} idx={s.get('step_index')} {s['status']} title={str(s.get('title'))[:50]}")
    if s.get("last_error"):
        print(f"      err: {str(s['last_error'])[:160]}")

print("\n== retries (newest 15) ==")
for r in p.get("retries", []):
    print(f"  [{r['id']}] step={r['step_id']} {r.get('decision')} @ {r.get('created_at')}")
    print(f"      reason: {str(r.get('reason'))[:180]}")

print("\n== executions (projects 2/3 steps, newest 12) ==")
for e in p.get("executions", []):
    print(f"  [{e['id']}] step={e['step_id']} {e['status']} @ {e['created_at']}")
    if e.get("error"):
        print(f"      err: {str(e['error'])[:200]}")

ssh.close()
