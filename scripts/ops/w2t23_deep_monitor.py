#!/usr/bin/env python3
# W2-T23 step 5b — deep monitor: executions of step 102, evidence, verdict reasons.
import json, paramiko, sys

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

REMOTE_PY = r'''
import sqlite3, json
con = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
o = {}
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
o["tables"] = tables

# executions-like tables
for t in tables:
    if "exec" in t or "run" in t or "attempt" in t:
        cols = [r[1] for r in con.execute("PRAGMA table_info(%s)" % t)]
        o.setdefault("exec_tables", {})[t] = cols

# step 102 row (all columns)
s = con.execute("SELECT * FROM steps WHERE id=102").fetchone()
if s:
    o["step102"] = {k: s[k] for k in s.keys()}

# executions for step 102 if table exists
for t in ("executions", "step_executions", "execution_records"):
    if t in tables:
        try:
            rows = con.execute(
                "SELECT * FROM %s WHERE step_id=102 ORDER BY id DESC LIMIT 3" % t).fetchall()
            o["recent_executions"] = [{k: r[k] for k in r.keys()} for r in rows]
        except Exception as e:
            o["exec_err_%s" % t] = str(e)

# project 3 gates recent (gates table?)
for t in ("gates", "project_gates", "approval_gates"):
    if t in tables:
        try:
            rows = con.execute(
                "SELECT * FROM %s WHERE project_id=3 ORDER BY id DESC LIMIT 3" % t).fetchall()
            o["recent_gates"] = [{k: r[k] for k in r.keys()} for r in rows]
        except Exception as e:
            o["gates_err_%s" % t] = str(e)

print("DEEP-JSON:" + json.dumps(o, ensure_ascii=False, default=str))
'''

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=60, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    return out.strip(), err.strip()

out, err = run("sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % REMOTE_PY, 60)
if out:
    try:
        i = out.find("DEEP-JSON:")
        d = json.loads(out[i + 10:])
        print("TABLES:", d.get("tables"))
        print("\nSTEP102:", json.dumps(d.get("step102"), ensure_ascii=False, indent=1)[:1500])
        if "recent_executions" in d:
            print("\nRECENT EXECUTIONS:")
            for r in d["recent_executions"]:
                print(json.dumps(r, ensure_ascii=False, default=str)[:800])
        if "recent_gates" in d:
            print("\nRECENT GATES:")
            for r in d["recent_gates"]:
                print(json.dumps(r, ensure_ascii=False, default=str)[:600])
    except Exception as ex:
        print("PARSE ERR:", ex)
        print(out[:2000])
else:
    print("[no stdout]", err[:400])

# journal tail for the retry reason
out, err = run("sudo -n journalctl -u agentic --since '13:50' --no-pager | grep -iE 'retry|verdict|insufficient|102|failed|create_files|build' | tail -25", 40)
print("\n=== JOURNAL (filtered) ===")
print(out[:2500])
ssh.close()
