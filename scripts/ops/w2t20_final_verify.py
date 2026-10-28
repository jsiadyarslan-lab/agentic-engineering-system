#!/usr/bin/env python3
# W2-T20 final verification (after engine tuning):
# app-level searches (exact failing queries from DB), capability probe,
# providers state, engine composition. All through the app's sanctioned API.
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T20 final verification",
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=120, label=""):
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

def app_search(query, label, t=90):
    payload = json.dumps({"query": query}, ensure_ascii=False).replace("'", "'\\''")
    return run(
        f"curl -s --max-time {t} -X POST http://127.0.0.1:8010/api/research/search "
        f"-H 'Content-Type: application/json' -d '{payload}' | "
        "python3 -c \"import json,sys;d=json.load(sys.stdin);"
        "r=d.get('results',[]);"
        "print('provider:',d.get('provider'),'| results:',len(r));"
        "print('titles:',[x.get('title','')[:48] for x in r[:4]]);"
        "att=d.get('attempts',[]);"
        "print('failed_before:',[(a.get('provider'),a.get('error','')[:60]) for a in att])\" 2>&1 | head -6",
        t + 20, label)

# exact failing queries from tool_invocations (project-2-step-77)
ev["search_207"] = app_search(
    "news website page structure homepage world politics business technology "
    "sports entertainment article detail search results best practices",
    "search #207 (english long)")
ev["search_193"] = app_search(
    "هيكل صفحات موقع أخبار الرئيسية العالم السياسة الأعمال التكنولوجيا الرياضة الترفيه",
    "search #193 (arabic long)")
ev["search_201"] = app_search(
    "متطلبات وصولية موقع أخبار WCAG 2.1 AA",
    "search #201 (arabic short)")
ev["search_192"] = app_search(
    "مواصفات موقع أخبار vanilla HTML CSS JS dark theme responsive accessible",
    "search #192 (mixed)")

# capability probe + readiness
ev["probe_websearch_cap"] = run(
    "curl -s --max-time 90 -X POST http://127.0.0.1:8010/api/environment/probe "
    "-H 'Content-Type: application/json' -d '{\"capability_id\": \"web_search\"}' | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "print('capability:',d.get('capability_id'),'| readiness:',d.get('readiness_status'),"
    "'| stored:',d.get('stored_status'),'| latency:',d.get('probe_latency_ms'));"
    "pp=(d.get('details') or {}).get('per_provider',[]);"
    "print('per_provider:',[(p.get('name'),p.get('status')) for p in pp if isinstance(p,dict) and p.get('name')])\" 2>&1 | head -4",
    120, "web_search capability probe")

ev["readiness_final"] = run(
    "curl -s --max-time 15 http://127.0.0.1:8010/api/environment/readiness | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "c=[x for x in d.get('capabilities',[]) if x.get('capability_id') in "
    "('web_search','web_fetch','llm')];"
    "print([{k:x.get(k) for k in ('capability_id','stored_status','readiness_status')} for x in c])\"",
    30, "readiness final")

# engine composition after tuning (brave suspension should have lifted)
ev["engine_comp"] = run(
    "curl -s --max-time 30 'http://127.0.0.1:8888/search?q=news+website+design&format=json&language=en' | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "res={};"
    "for r in d.get('results',[]):"
    " res[r.get('engine','?')]=res.get(r.get('engine','?'),0)+1;"
    "print('total:',len(d.get('results',[])),'by engine:',res);"
    "print('unresponsive:',str(d.get('unresponsive_engines',[]))[:200])\" 2>&1 | head -4",
    60, "engine composition")

ev["health_after"] = health()

path = "/home/z/my-project/download/aes-remediation/W2-T20/final_verification.json"
with open(path, "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2))
ssh.close()
