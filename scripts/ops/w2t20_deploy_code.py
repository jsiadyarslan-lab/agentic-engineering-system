#!/usr/bin/env python3
# W2-T20 step 4: deploy relevance-gate fix (2447f4a) to production with R6 gates.
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T20 step 4: deploy code fix 2447f4a",
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=90, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:110], "rc": rc, "out": out.strip()[:2000],
            "err": err.strip()[:400]}

def health():
    return run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 "
               "http://127.0.0.1:8010/health", 15, "health")["out"]

# ---- R6 BEFORE ----
ev["health_before"] = health()
ev["service_before"] = run("sudo -n systemctl is-active agentic", 15, "svc")["out"]
ev["branch_before"] = run("git -C /opt/agentic-engineering-system branch --show-current; "
                          "git -C /opt/agentic-engineering-system rev-parse --short=9 HEAD", 15, "branch")["out"]
assert ev["health_before"] == "200" and ev["service_before"] == "active"

# ---- fetch + ff-only pull ----
ev["git_pull"] = run(
    "cd /opt/agentic-engineering-system && "
    "git fetch origin main 2>&1 | tail -2; "
    "git merge --ff-only origin/main 2>&1 | tail -2; "
    "git rev-parse --short=9 HEAD", 120, "fetch + ff-only merge")

# ---- verify the fix is in the tree ----
ev["fix_present"] = run(
    "grep -n 'len(tokens) > 5' /opt/agentic-engineering-system/src/research/providers.py | head -3; "
    "git -C /opt/agentic-engineering-system log --oneline -1", 15, "fix present")

# ---- py_compile before restart (RLR-005 pattern) ----
ev["py_compile"] = run(
    "cd /opt/agentic-engineering-system && .venv/bin/python -m py_compile "
    "src/research/providers.py src/research/service.py && echo COMPILE_OK", 30, "py_compile")

# ---- restart with gates ----
if ev["py_compile"]["out"].endswith("COMPILE_OK"):
    ev["restart"] = run(
        "sudo -n systemctl restart agentic; sleep 6; "
        "sudo -n systemctl is-active agentic", 60, "restart agentic")
    ev["health_after_restart"] = health()
    ev["journal_errors"] = run(
        "sudo -n journalctl -u agentic -p err --since '2 minutes ago' --no-pager 2>/dev/null | tail -6",
        30, "journal errors after restart")
    # readiness snapshot (web_search related caps)
    ev["readiness_websearch"] = run(
        "curl -s --max-time 12 http://127.0.0.1:8010/api/environment/readiness | "
        "python3 -c \"import json,sys;d=json.load(sys.stdin);"
        "c=[x for x in d.get('capabilities',[]) if x.get('capability_id') in ('web_search','web_fetch','llm')];"
        "print([{k:x.get(k) for k in ('capability_id','stored_status','readiness_status')} for x in c])\"",
        30, "readiness snapshot")
else:
    ev["restart"] = {"rc": 1, "out": "SKIPPED — py_compile failed"}

ev["health_after"] = health()

path = "/home/z/my-project/download/aes-remediation/W2-T20/step4_code_deploy.json"
with open(path, "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2))
ssh.close()
