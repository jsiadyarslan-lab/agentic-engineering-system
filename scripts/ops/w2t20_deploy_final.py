#!/usr/bin/env python3
# W2-T20: deploy be56bf2 (synonym strong rule) + FINAL verification.
# Restart takes ~2 min (slow graceful stop) -> long timeout + post-checks.
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T20 deploy be56bf2 + final verify",
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=120, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:110], "rc": rc, "out": out.strip()[:2400],
            "err": err.strip()[:400]}

def health():
    return run("curl -s -o /dev/null -w '%{http_code}' --max-time 10 "
               "http://127.0.0.1:8010/health", 15, "health")["out"]

ev["health_before"] = health()
assert ev["health_before"] == "200"

ev["git_pull"] = run(
    "cd /opt/agentic-engineering-system && git fetch origin main 2>&1 | tail -1; "
    "git merge --ff-only origin/main 2>&1 | tail -1; git rev-parse --short=9 HEAD",
    120, "pull be56bf2")
ev["py_compile"] = run(
    "cd /opt/agentic-engineering-system && .venv/bin/python -m py_compile "
    "src/research/providers.py && echo COMPILE_OK", 30, "py_compile")
assert ev["py_compile"]["out"].endswith("COMPILE_OK")

# restart — issue and DON'T wait inline (slow stop); poll afterwards
try:
    run("sudo -n systemctl restart agentic", t=15, label="issue restart")
except Exception:  # noqa: BLE001 — channel read timeout while unit stops
    ev["restart_issued"] = "issued (channel closed during slow stop — expected)"
for attempt in range(14):
    time.sleep(15)
    state = run("sudo -n systemctl is-active agentic", 10, "poll")["out"]
    h = health()
    if state == "active" and h == "200":
        ev["restart"] = {"rc": 0, "out": f"active + health 200 after {(attempt+1)*15}s"}
        break
else:
    ev["restart"] = {"rc": 1, "out": f"STUCK: {state} health={h}"}

# fix lines present?
ev["fix_lines"] = run(
    "grep -n 'len(hit) >= 2' /opt/agentic-engineering-system/src/research/providers.py | head -2", 15, "fix lines")

# ---- FINAL: exact failing queries through the app ----
def app_search(query, label, t=100):
    payload = json.dumps({"query": query}, ensure_ascii=False).replace("'", "'\\''")
    return run(
        f"curl -s -w '__HTTP:%{{http_code}}' --max-time {t} -X POST "
        f"http://127.0.0.1:8010/api/research/search "
        f"-H 'Content-Type: application/json' -d '{payload}' | "
        "python3 -c \"import json,sys;raw=sys.stdin.read();parts=raw.rsplit('__HTTP:',1);"
        "code=parts[1].strip() if len(parts)>1 else '?';"
        "d={};\n"
        "try: d=json.loads(parts[0])\n"
        "except Exception: pass\n"
        "r=d.get('results',[]);"
        "print('HTTP',code,'| provider:',d.get('provider'),'| results:',len(r));"
        "print('titles:',[x.get('title','')[:45] for x in r[:4]]);"
        "print('attempts:',[a.get('provider') for a in d.get('attempts',[])])\" 2>&1 | head -5",
        t + 25, label)

ev["q207"] = app_search(
    "news website page structure homepage world politics business technology "
    "sports entertainment article detail search results best practices", "#207 en-long")
ev["q193"] = app_search(
    "هيكل صفحات موقع أخبار الرئيسية العالم السياسة الأعمال التكنولوجيا الرياضة الترفيه", "#193 ar-long")
ev["q201"] = app_search(
    "متطلبات وصولية موقع أخبار WCAG 2.1 AA", "#201 ar-short")
ev["q192"] = app_search(
    "مواصفات موقع أخبار vanilla HTML CSS JS dark theme responsive accessible", "#192 mixed")
ev["q199"] = app_search(
    "مواصفات موقع أخبار هيكل الصفحات المتطلبات التقنية", "#199 ar-tech")

# providers + capability + services
ev["providers"] = run(
    "curl -s --max-time 15 http://127.0.0.1:8010/api/research/providers | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "print([{k:p.get(k) for k in ('id','name','enabled','effective_status')} for p in d.get('providers',[])])\"",
    30, "providers")
ev["capability"] = run(
    "curl -s --max-time 15 http://127.0.0.1:8010/api/environment/readiness | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "c=[x for x in d.get('capabilities',[]) if x.get('capability_id')=='web_search'];"
    "print((c[0].get('stored_status'),c[0].get('readiness_status')) if c else 'MISSING')\"",
    30, "web_search capability")
ev["services"] = run(
    "sudo -n systemctl is-active agentic nginx searxng search-api | tr '\\n' ' '", 15, "services")
ev["journal_err"] = run(
    "sudo -n journalctl -u agentic -p err --since '5 minutes ago' --no-pager 2>/dev/null | tail -3",
    30, "journal errors")
ev["health_after"] = health()

path = "/home/z/my-project/download/aes-remediation/W2-T20/final_verification_v4.json"
with open(path, "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2))
ssh.close()
