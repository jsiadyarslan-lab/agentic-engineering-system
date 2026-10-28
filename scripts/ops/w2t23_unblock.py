#!/usr/bin/env python3
# W2-T23 step 4 — unblock: probe web_search -> preflight project #3 -> auto launch
# R6: read-only BEFORE state documented; every POST result captured; read-only AFTER.
import json, time, paramiko, os

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EVDIR = "/home/z/my-project/download/aes-remediation/W2-T23"
os.makedirs(EVDIR, exist_ok=True)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T23 unblock (probe web_search -> preflight P3)",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=180, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:160], "rc": rc, "out": out.strip()[:6000],
            "err": err.strip()[:500]}

# ---------- BEFORE (read-only) ----------
BEFORE_PY = r'''
import sqlite3, json
con = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
o = {}
p = con.execute("SELECT id,name,status,health FROM projects WHERE id=3").fetchone()
o["project"] = dict(p) if p else None
j = con.execute("SELECT id,status,current_step_id,attempt,updated_at FROM jobs WHERE project_id=3 ORDER BY id DESC LIMIT 2").fetchall()
o["jobs"] = [dict(r) for r in j]
g = con.execute("SELECT id,kind,status,reason,created_at,resolved_at FROM gates WHERE project_id=3 AND status='BLOCKED' ORDER BY id DESC LIMIT 3").fetchall()
o["blocked_gates"] = [dict(r) for r in g]
g30 = con.execute("SELECT id,kind,status,reason,created_at,resolved_at FROM gates WHERE id=30").fetchone()
o["gate30"] = dict(g30) if g30 else None
s102 = con.execute("SELECT id,ordinal,status,attempt FROM steps WHERE id=102").fetchone()
o["step102"] = dict(s102) if s102 else None
pr = con.execute("SELECT capability_id,readiness_status,probed_at FROM capability_state ORDER BY capability_id").fetchall()
o["capabilities"] = [dict(r) for r in pr]
print("BEFORE-JSON:" + json.dumps(o, ensure_ascii=False, default=str))
'''
ev["before_db"] = run("sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % BEFORE_PY, 60, "before db state")

# ---------- POST probe web_search ----------
ev["probe_web_search"] = run(
    "curl -s -m 60 -X POST http://127.0.0.1:8010/api/environment/probe "
    "-H 'Content-Type: application/json' -d '{\"capability_id\": \"web_search\"}'", 90,
    "POST probe web_search")

# ---------- readiness view after probe ----------
ev["readiness_after_probe"] = run(
    "curl -s -m 20 http://127.0.0.1:8010/api/environment/capabilities "
    "| sudo -n python3 -c \"import sys,json; d=json.load(sys.stdin); "
    "print(json.dumps({'summary': d.get('summary'), "
    "'web_search': [c for c in d.get('capabilities',[]) if c.get('capability_id')=='web_search']}, "
    "ensure_ascii=False))\"", 40, "readiness after probe")

# ---------- POST preflight project 3 (auto-launch on PASS) ----------
ev["preflight_p3"] = run(
    "curl -s -m 120 -X POST http://127.0.0.1:8010/api/projects/3/preflight", 150,
    "POST preflight P3")

# settle a few seconds for the launch to materialize
time.sleep(8)

# ---------- AFTER (read-only) ----------
AFTER_PY = r'''
import sqlite3, json
con = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
o = {}
p = con.execute("SELECT id,name,status,health FROM projects WHERE id=3").fetchone()
o["project"] = dict(p) if p else None
j = con.execute("SELECT id,status,current_step_id,attempt,updated_at FROM jobs WHERE project_id=3 ORDER BY id DESC LIMIT 2").fetchall()
o["jobs"] = [dict(r) for r in j]
g30 = con.execute("SELECT id,kind,status,reason,created_at,resolved_at FROM gates WHERE id=30").fetchone()
o["gate30"] = dict(g30) if g30 else None
s102 = con.execute("SELECT id,ordinal,status,attempt FROM steps WHERE id=102").fetchone()
o["step102"] = dict(s102) if s102 else None
gl = con.execute("SELECT id,kind,status,resolved_at,reason FROM gates WHERE project_id=3 ORDER BY id DESC LIMIT 4").fetchall()
o["recent_gates"] = [dict(r) for r in gl]
print("AFTER-JSON:" + json.dumps(o, ensure_ascii=False, default=str))
'''
ev["after_db"] = run("sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % AFTER_PY, 60, "after db state")

ev["health_final"] = run("curl -s -o /dev/null -w '%{http_code}' -m 8 http://127.0.0.1:8010/health", 20, "health final")
ev["journal_err"] = run("sudo -n journalctl -u agentic -p err --since '-10 minutes' --no-pager | tail -6", 30, "journal errors")

with open(os.path.join(EVDIR, "unblock.json"), "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=1)

for k in ("before_db", "probe_web_search", "readiness_after_probe", "preflight_p3", "after_db", "health_final"):
    print("=== %s ===" % k)
    print(ev[k]["out"][:1600])
print("=== journal_err ===")
print(repr(ev["journal_err"]["out"][:300]))
print("EVIDENCE:", os.path.join(EVDIR, "unblock.json"))
ssh.close()
