#!/usr/bin/env python3
# W2-T20 steps 5+6: configure providers via sanctioned API + full verification.
# - SearXNG (id=4): base_url -> http://127.0.0.1:8888, enabled
# - Search API (id=5): endpoint -> http://127.0.0.1:8098/search + key, enabled
# - DDG (id=1): disabled (host blocked - documented anomaly evidence)
# Then: probe/all + real search with exact failing query #207 + web_search capability.
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

APIKEY = open("/home/z/my-project/download/aes-remediation/W2-T20/.search_api_key.local").read().strip()

ev = {"_meta": {"task": "W2-T20 steps 5+6: configure + final verification",
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=120, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:110], "rc": rc, "out": out.strip()[:2600],
            "err": err.strip()[:400]}

def health():
    return run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 "
               "http://127.0.0.1:8010/health", 15, "health")["out"]

ev["health_before"] = health()
assert ev["health_before"] == "200"

def jpost(path, body, t=150):
    payload = json.dumps(body, ensure_ascii=False).replace("'", "'\\''")
    return run(
        f"curl -s --max-time {t} -X POST http://127.0.0.1:8010{path} "
        f"-H 'Content-Type: application/json' -d '{payload}'", t + 20, f"POST {path}")

# ---- (5a) configure SearXNG provider ----
ev["cfg_searx"] = jpost("/api/research/providers/4/configure",
                        {"config": {"base_url": "http://127.0.0.1:8888"},
                         "enabled": True})

# ---- (5b) configure Search API provider (key -> secrets_store) ----
ev["cfg_api"] = jpost("/api/research/providers/5/configure",
                      {"config": {"endpoint": "http://127.0.0.1:8098/search",
                                  "style": "generic_results"},
                       "enabled": True, "api_key": APIKEY})

# ---- (5c) disable DDG (blocked host — anomaly page evidence) ----
ev["cfg_ddg_off"] = jpost("/api/research/providers/1/configure",
                          {"enabled": False})

# ---- (6a) probe all providers ----
ev["probe_all"] = jpost("/api/research/providers/probe/all", {}, t=180)

# ---- (6b) REAL search with the exact failing query #207 ----
q207 = ("news website page structure homepage world politics business "
        "technology sports entertainment article detail search results "
        "best practices")
ev["search_207"] = jpost("/api/research/search", {"query": q207}, t=90)

# ---- (6c) Arabic real query (from #199) ----
ev["search_arabic"] = jpost("/api/research/search",
                            {"query": "مواصفات موقع أخبار هيكل الصفحات المتطلبات التقنية"}, t=90)

# ---- (6d) web_search capability probe (readiness) ----
ev["probe_websearch_cap"] = jpost("/api/environment/probe",
                                  {"capability_id": "web_search"}, t=120)

# ---- (6e) readiness snapshot ----
ev["readiness"] = run(
    "curl -s --max-time 15 http://127.0.0.1:8010/api/environment/readiness | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "c=[x for x in d.get('capabilities',[]) if x.get('capability_id') in "
    "('web_search','web_fetch','llm','network_http','network_https')];"
    "print([{k:x.get(k) for k in ('capability_id','stored_status','readiness_status')} for x in c])\"",
    30, "readiness")

# ---- (6f) providers list final state ----
ev["providers_final"] = run(
    "curl -s --max-time 15 http://127.0.0.1:8010/api/research/providers | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "print([{k:p.get(k) for k in ('id','name','enabled','effective_status')} for p in d.get('providers',[])])\"",
    30, "providers final")

ev["health_after"] = health()

path = "/home/z/my-project/download/aes-remediation/W2-T20/step5_6_configure_verify.json"
with open(path, "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2))
ssh.close()
