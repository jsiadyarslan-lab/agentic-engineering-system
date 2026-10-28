#!/usr/bin/env python3
# W2-T22 deploy follow-up: fix the two checks that failed due to shell
# quoting (py_compile + readiness). Read-only + compile check only.
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EVDIR = "/home/z/my-project/download/aes-remediation/W2-T22"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=120, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:140], "rc": rc, "out": out.strip()[:2500],
            "err": err.strip()[:400]}

ev = {"_meta": {"task": "W2-T22 deploy followup checks", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

# py_compile with the app venv python (explicit path)
ev["py_compile"] = run(
    "cd /opt/agentic-engineering-system && .venv/bin/python -m py_compile "
    "src/research/providers.py src/research/chat_research.py src/api/routes.py "
    "&& echo COMPILE_OK", 120, "py_compile app venv")

# readiness via a heredoc python (no nested quoting issues)
READINESS = r'''
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:8010/api/environment/readiness", timeout=12) as r:
    d = json.loads(r.read().decode("utf-8", "replace"))
caps = d.get("capabilities") or d.get("items") or []
out = {"count": len(caps), "not_ready": [], "web_search": "?"}
for c in caps:
    cid = str(c.get("capability_id") or c.get("id") or c.get("name") or "")
    status = c.get("readiness_status") or c.get("status")
    if status == "NOT_READY":
        out["not_ready"].append(cid)
    if "web_search" in cid:
        out["web_search"] = status
print("@@J@@")
print(json.dumps(out, ensure_ascii=False))
'''
ev["readiness"] = run("python3 - <<'PYEOF'\n" + READINESS + "\nPYEOF", 60, "readiness")

# import smoke test of the new functions on the server (in the app venv)
SMOKE = r'''
import sys
sys.path.insert(0, "/opt/agentic-engineering-system/src")
from research.chat_research import build_contextual_search_query, is_followup_urge
r1 = build_contextual_search_query("ابحث انت واعطني ملخص", ["اخبار انتخابات الكنسيت اليوم"])
r2 = build_contextual_search_query("؟", ["اخبار انتخابات الكنسيت اليوم", "ابحث انت واعطني ملخص"])
print("@@J@@")
print(__import__("json").dumps({"turn2": r1, "turn3": r2, "urge_q": is_followup_urge("؟")}, ensure_ascii=False))
'''
ev["smoke_new_functions"] = run("cd /opt/agentic-engineering-system && .venv/bin/python - <<'PYEOF'\n" + SMOKE + "\nPYEOF", 60, "smoke")

# providers STALE after restart is expected (TTL) — probe 4/5 via the app's
# legitimate API to refresh (authorized: same probe pattern as W2-T21 audits)
ev["probe_4"] = run("curl -s -X POST -m 30 http://127.0.0.1:8010/api/research/providers/4/probe -H 'Content-Type: application/json' -d '{}' | head -c 600", 60, "probe searxng")
ev["probe_5"] = run("curl -s -X POST -m 30 http://127.0.0.1:8010/api/research/providers/5/probe -H 'Content-Type: application/json' -d '{}' | head -c 600", 60, "probe search api")
ev["providers_after"] = run("curl -s -m 10 http://127.0.0.1:8010/api/research/providers | head -c 900", 30, "providers after probe")

ssh.close()

path = f"{EVDIR}/deploy_followup.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=1)[:3000])
print("\nsaved:", path)
