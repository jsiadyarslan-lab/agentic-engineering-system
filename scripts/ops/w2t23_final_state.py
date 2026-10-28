#!/usr/bin/env python3
# W2-T23 step 5c — final state: current step, gates, sha256 of the 3 files + evidence.
import json, time, paramiko, os

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EVDIR = "/home/z/my-project/download/aes-remediation/W2-T23"
os.makedirs(EVDIR, exist_ok=True)

REMOTE_PY = r'''
import sqlite3, json
con = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
o = {}
p = con.execute("SELECT id,name,status,current_step_id,updated_at FROM projects WHERE id=3").fetchone()
o["project"] = dict(p) if p else None
s = con.execute("SELECT id,ordinal,objective,status,attempts,completed_at FROM steps WHERE phase_id=37 ORDER BY ordinal LIMIT 4").fetchall()
o["steps"] = [dict(r) for r in s]
g = con.execute("SELECT * FROM owner_gates WHERE project_id=3 ORDER BY id DESC LIMIT 3").fetchall()
o["gates"] = [{k: r[k] for k in r.keys()} for r in g]
e = con.execute("SELECT * FROM executions WHERE step_id=102 AND id=28").fetchone()
o["exec28"] = {k: e[k] for k in e.keys() if k in ("id","attempt","status","started_at","finished_at","commit_sha","error")} if e else None
ev = con.execute("SELECT * FROM evidence_records WHERE id=1").fetchone()
o["evidence1"] = {k: ev[k] for k in ev.keys()} if ev else None
print("FINAL-JSON:" + json.dumps(o, ensure_ascii=False, default=str))
'''

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=60, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:160], "rc": rc, "out": out.strip()[:8000],
            "err": err.strip()[:400]}

ev = {"_meta": {"task": "W2-T23 final state", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

ev["db_state"] = run("sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % REMOTE_PY, 60, "db final state")
ev["files_sha256"] = run(
    "cd /opt/agentic-engineering-system/runtime/projects/3/steps/102 && "
    "sudo -n sha256sum package.json tsconfig.json astro.config.mjs 2>&1; "
    "echo ---; sudo -n ls -la package.json tsconfig.json astro.config.mjs T1-report.md sources.json", 40,
    "sha256 of created files")
ev["runs_active"] = run(
    "curl -s -m 12 http://127.0.0.1:8010/api/projects/runs/active "
    "| sudo -n python3 -c \"import sys,json; d=json.load(sys.stdin); "
    "r=[x for x in d['runs'] if x['project_id']==3]; "
    "print(json.dumps(r[0] if r else {}, ensure_ascii=False))\"", 30, "runs active p3")
ev["health"] = run("curl -s -o /dev/null -w '%{http_code}' -m 8 http://127.0.0.1:8010/health", 20, "health")
ev["journal_err"] = run("sudo -n journalctl -u agentic -p err --since '-30 minutes' --no-pager | tail -6", 30, "journal err")

with open(os.path.join(EVDIR, "final_state.json"), "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=1)

for k in ("db_state", "files_sha256", "runs_active", "health", "journal_err"):
    print("=== %s ===" % k)
    print(ev[k]["out"][:2200])
print("EVIDENCE:", os.path.join(EVDIR, "final_state.json"))
ssh.close()
