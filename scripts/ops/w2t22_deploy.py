#!/usr/bin/env python3
# W2-T22 deploy: ff pull ad371b6 -> py_compile -> R6-gated graceful restart.
# All server operations via sudo -n (established pattern). Evidence JSON saved.
import json, time, base64, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EVDIR = "/home/z/my-project/download/aes-remediation/W2-T22"
import os
os.makedirs(EVDIR, exist_ok=True)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T22 deploy (ad371b6)", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=180, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:140], "rc": rc, "out": out.strip()[:3000],
            "err": err.strip()[:400]}

# --- R6 gate: health BEFORE ---
ev["health_before"] = run("curl -s -o /dev/null -w '%{http_code}' -m 8 http://127.0.0.1:8010/health", 20, "health before")
ev["head_before"] = run("sudo -n git -C /opt/agentic-engineering-system rev-parse HEAD", 20, "HEAD before")
ev["services_before"] = run("systemctl is-active agentic nginx searxng search-api", 20, "services before")

# --- discover app python (ExecStart) ---
ev["execstart"] = run("sudo -n systemctl cat agentic | grep -E 'ExecStart|WorkingDirectory' | head -3", 20, "ExecStart")

# --- ff pull ---
ev["git_pull"] = run("sudo -n git -C /opt/agentic-engineering-system pull --ff-only origin main 2>&1 | tail -5", 120, "git ff pull")
ev["head_after_pull"] = run("sudo -n git -C /opt/agentic-engineering-system rev-parse HEAD", 20, "HEAD after pull")
ev["git_status"] = run("sudo -n git -C /opt/agentic-engineering-system status --porcelain | head -10", 20, "git status")

# --- py_compile the three changed files (using the app's venv python) ---
compile_cmd = (
    "cd /opt/agentic-engineering-system && "
    "PY=$(sudo -n systemctl cat agentic | grep ExecStart | head -1 | awk '{print $1}' | sed 's/ .*//'); "
    "echo \"python=$PY\"; "
    "$PY -m py_compile src/research/providers.py src/research/chat_research.py src/api/routes.py && echo COMPILE_OK"
)
ev["py_compile"] = run(compile_cmd, 120, "py_compile")

# --- R6 gate: restart agentic gracefully, poll health ---
ev["restart"] = run("sudo -n systemctl restart agentic && echo RESTART_ISSUED", 120, "restart")
health_after = ""
for i in range(36):  # up to ~180s (graceful stop documented ~2min)
    time.sleep(5)
    code = run("curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:8010/health", 20, "health poll")
    if code.get("out") == "200":
        health_after = f"200 (after {(i+1)*5}s)"
        break
    if i % 6 == 5:
        print(f"  poll {i+1}: {code.get('out')}")
ev["health_after_restart"] = health_after or "NOT_200_WITHIN_180S"

# --- post checks ---
ev["head_final"] = run("sudo -n git -C /opt/agentic-engineering-system rev-parse HEAD", 20, "HEAD final")
ev["services_after"] = run("systemctl is-active agentic nginx searxng search-api", 20, "services after")
ev["journal_err"] = run("sudo -n journalctl -u agentic -p err --since '-5 minutes' --no-pager | tail -10", 30, "journal errors")
ev["readiness"] = run("curl -s -m 10 http://127.0.0.1:8010/api/environment/readiness | python3 -c \"import json,sys; d=json.load(sys.stdin); caps=d.get('capabilities') or d.get('items') or []; print(json.dumps({'count':len(caps),'not_ready':[c.get('capability_id',c.get('id')) for c in caps if (c.get('readiness_status') or c.get('status'))=='NOT_READY'],'web_search':next((c.get('readiness_status') or c.get('status') for c in caps if 'web_search' in str(c.get('capability_id',c.get('id',c.get('name')))),'?')}, ensure_ascii=False))\"", 30, "readiness")
ev["providers"] = run("curl -s -m 10 http://127.0.0.1:8010/api/research/providers | python3 -c \"import json,sys; d=json.load(sys.stdin); ps=d.get('providers') or d; print(json.dumps([{ 'id':p.get('id'),'name':p.get('name'),'enabled':p.get('enabled'),'status':p.get('effective_status')} for p in ps], ensure_ascii=False))\"", 30, "providers")

ssh.close()

out_path = f"{EVDIR}/deploy.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)

print(json.dumps({k: v for k, v in ev.items() if k != "_meta"}, ensure_ascii=False, indent=1)[:3500])
print("\nsaved:", out_path)
