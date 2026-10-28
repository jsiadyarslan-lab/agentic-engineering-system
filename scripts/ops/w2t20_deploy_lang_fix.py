#!/usr/bin/env python3
# W2-T20: deploy language fix (097c391) to production + update search-api
# wrapper with same detection + full final verification.
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T20: deploy language fix + final verify",
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=90, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:110], "rc": rc, "out": out.strip()[:2400],
            "err": err.strip()[:400]}

def health():
    return run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 "
               "http://127.0.0.1:8010/health", 15, "health")["out"]

ev["health_before"] = health()
assert ev["health_before"] == "200"

# ---- (1) pull + compile + restart agentic ----
ev["git_pull"] = run(
    "cd /opt/agentic-engineering-system && git fetch origin main 2>&1 | tail -1; "
    "git merge --ff-only origin/main 2>&1 | tail -1; git rev-parse --short=9 HEAD",
    120, "pull 097c391")
ev["py_compile"] = run(
    "cd /opt/agentic-engineering-system && .venv/bin/python -m py_compile "
    "src/research/providers.py && echo COMPILE_OK", 30, "py_compile")
if ev["py_compile"]["out"].endswith("COMPILE_OK"):
    ev["restart_agentic"] = run(
        "sudo -n systemctl restart agentic; sleep 6; sudo -n systemctl is-active agentic",
        60, "restart agentic")

# ---- (2) update search-api wrapper ----
sftp = ssh.open_sftp()
sftp.put("/home/z/my-project/scripts/search_api_service.py", "/tmp/search_api_new.py")
sftp.close()
ev["wrapper_update"] = run(
    "sudo -n mv /tmp/search_api_new.py /opt/search-api/search_api.py && "
    "sudo -n chown searchapi:searchapi /opt/search-api/search_api.py && "
    "sudo -n chmod 640 /opt/search-api/search_api.py && "
    "sudo -n systemctl restart search-api; sleep 2; "
    "sudo -n systemctl is-active search-api && echo WRAPPER_UPDATED", 30, "update wrapper")

# ---- (3) final verification: exact failing queries through the app ----
def app_search(query, label, t=90):
    payload = json.dumps({"query": query}, ensure_ascii=False).replace("'", "'\\''")
    return run(
        f"curl -s -w '\\n__HTTP:%{http_code}' --max-time {t} -X POST "
        f"http://127.0.0.1:8010/api/research/search "
        f"-H 'Content-Type: application/json' -d '{payload}' | "
        "python3 -c \"import json,sys;raw=sys.stdin.read();http=raw.rsplit('__HTTP:',1);"
        "d=json.loads(http[0]) if http[0].strip() else {};"
        "r=d.get('results',[]);"
        "print('HTTP',http[1].strip() if len(http)>1 else '?','| provider:',d.get('provider'),'| results:',len(r));"
        "print('titles:',[x.get('title','')[:45] for x in r[:4]]);"
        "att=d.get('attempts',[]);"
        "print('failed_before:',[(a.get('provider')) for a in att])\" 2>&1 | head -5",
        t + 20, label)

ev["search_207_en"] = app_search(
    "news website page structure homepage world politics business technology "
    "sports entertainment article detail search results best practices",
    "#207 english long")
ev["search_193_ar"] = app_search(
    "هيكل صفحات موقع أخبار الرئيسية العالم السياسة الأعمال التكنولوجيا الرياضة الترفيه",
    "#193 arabic long")
ev["search_201_ar"] = app_search(
    "متطلبات وصولية موقع أخبار WCAG 2.1 AA",
    "#201 arabic short")
ev["search_192_mix"] = app_search(
    "مواصفات موقع أخبار vanilla HTML CSS JS dark theme responsive accessible",
    "#192 mixed")

# ---- (4) capability + providers + services ----
ev["providers_state"] = run(
    "curl -s --max-time 15 http://127.0.0.1:8010/api/research/providers | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "print([{k:p.get(k) for k in ('id','name','enabled','effective_status')} for p in d.get('providers',[])])\"",
    30, "providers state")
ev["services"] = run(
    "sudo -n systemctl is-active agentic nginx searxng search-api | tr '\\n' ' '", 15, "services")
ev["journal_err"] = run(
    "sudo -n journalctl -u agentic -u searxng -u search-api -p err --since '5 minutes ago' "
    "--no-pager 2>/dev/null | tail -5", 30, "journal errors")

ev["health_after"] = health()

path = "/home/z/my-project/download/aes-remediation/W2-T20/final_verification_v2.json"
with open(path, "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2))
ssh.close()
