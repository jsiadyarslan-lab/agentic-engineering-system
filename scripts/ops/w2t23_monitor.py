#!/usr/bin/env python3
# W2-T23 step 5 — monitor: job/step 102 execution state + files on disk (read-only)
import json, time, paramiko, os, sys

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EVDIR = "/home/z/my-project/download/aes-remediation/W2-T23"
os.makedirs(EVDIR, exist_ok=True)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

MONITOR_PY = r'''
import sqlite3, json
con = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
o = {}
try:
    cols = [r[1] for r in con.execute("PRAGMA table_info(projects)")]
    o["projects_cols"] = cols
except Exception as e:
    o["projects_cols_err"] = str(e)
p = con.execute("SELECT * FROM projects WHERE id=3").fetchone()
o["project"] = {k: p[k] for k in p.keys() if k in ("id","name","status","current_plan_id","current_phase_id","current_step_id","updated_at","last_error","completion_state")} if p else None
try:
    j = con.execute("SELECT * FROM jobs WHERE project_id=3 ORDER BY id DESC LIMIT 2").fetchall()
    keys = [k for k in (j[0].keys() if j else []) if k in ("id","status","current_step_id","attempt","created_at","updated_at","stopped_at","error")]
    o["jobs"] = [{k: r[k] for k in keys} for r in j]
except Exception as e:
    o["jobs_err"] = str(e)
try:
    g = con.execute("SELECT id,kind,status,reason,created_at,resolved_at FROM gates WHERE project_id=3 ORDER BY id DESC LIMIT 4").fetchall()
    o["recent_gates"] = [dict(r) for r in g]
except Exception as e:
    o["gates_err"] = str(e)
try:
    s = con.execute("SELECT id,ordinal,status,attempt,execution_id FROM steps WHERE id=102").fetchone()
    o["step102"] = dict(s) if s else None
except Exception as e:
    o["step102_err"] = str(e)
print("MON-JSON:" + json.dumps(o, ensure_ascii=False, default=str))
'''

def run(cmd, t=90, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:160], "rc": rc, "out": out.strip()[:6000],
            "err": err.strip()[:500]}

out = run("sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % MONITOR_PY, 60, "monitor db state")
print(out["out"])
if out["err"]:
    print("[stderr]", out["err"][:300])

# workspace files for project 3
ws = run("sudo -n ls -la /opt/agentic-engineering-system/runtime/projects/3/ 2>/dev/null; "
         "sudo -n find /opt/agentic-engineering-system/runtime/projects/3 -maxdepth 3 -type f "
         "2>/dev/null | head -25", 40, "workspace files")
print("=== workspace ===")
print(ws["out"])

# active runs via API
ar = run("curl -s -m 15 http://127.0.0.1:8010/api/projects/runs/active | head -c 2500", 30, "runs active")
print("=== runs/active ===")
print(ar["out"])

ssh.close()
