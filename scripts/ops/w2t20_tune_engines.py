#!/usr/bin/env python3
# W2-T20 step 2 (tune): engine pool tuning — enable bing (works from this
# host), disable broken ones (google cse sqlite crash, ddg captcha, qwant
# denied, yahoo crash). Restart + verify + re-probe providers.
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T20 step 2 tune: engine pool",
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=90, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:110], "rc": rc, "out": out.strip()[:2500],
            "err": err.strip()[:400]}

def health():
    return run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 "
               "http://127.0.0.1:8010/health", 15, "health")["out"]

ev["health_before"] = health()
assert ev["health_before"] == "200"

# (1) append engines tuning block
ev["engines_patch"] = run(
    "sudo -n tee -a /etc/searxng/settings.yml > /dev/null <<'YEOF'\n"
    "engines:\n"
    "  # W2-T20 2026-10-28: قياسات فردية من هذا المضيف —\n"
    "  # bing: 10 نتائج/صفر أعطال (ممكَّن هنا؛ الافتراضي معطل)\n"
    "  - name: bing\n"
    "    disabled: false\n"
    "  # google cse: انهيار sqlite3.OperationalError عند كل استعلام (مكتبة 3.34)\n"
    "  - name: google cse\n"
    "    disabled: true\n"
    "  # duckduckgo: CAPTCHA دائم لهذا المضيف (موثق في مزود التطبيق أيضًا)\n"
    "  - name: duckduckgo\n"
    "    disabled: true\n"
    "  # qwant: access denied لهذا المضيف · yahoo: انهيار غير متوقع\n"
    "  - name: qwant\n"
    "    disabled: true\n"
    "  - name: yahoo\n"
    "    disabled: true\n"
    "YEOF\n"
    "sudo -n tail -8 /etc/searxng/settings.yml", 20, "append engines block")

# (2) restart searxng
ev["restart"] = run(
    "sudo -n systemctl restart searxng; sleep 7; sudo -n systemctl is-active searxng", 60, "restart")

# (3) probe query directly (engine composition)
ev["probe_query_direct"] = run(
    "curl -s --max-time 30 'http://127.0.0.1:8888/search?q=agentic+engineering+system+software&format=json&language=en' | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "res={};"
    "map(lambda r: res.__setitem__(r.get('engine','?'), res.get(r.get('engine','?'),0)+1), d.get('results',[]));"
    "print('results:',len(d.get('results',[])),'by engine:',res);"
    "print('unresponsive:',str(d.get('unresponsive_engines',[]))[:250])\" 2>&1 | head -4",
    60, "probe query direct")

# (4) the exact #207 query
ev["q207_direct"] = run(
    "curl -s --max-time 30 'http://127.0.0.1:8888/search?q=news+website+page+structure+homepage+world+politics+business+technology+sports+entertainment+article+detail+search+results+best+practices&format=json&language=en' | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "print('results:',len(d.get('results',[])));"
    "print('first:',(d.get('results') or [{}])[0].get('title','')[:70]);"
    "print('unresponsive:',str(d.get('unresponsive_engines',[]))[:250])\" 2>&1 | head -4",
    60, "#207 query direct")

# (5) re-probe both providers via app API
ev["reprobe_searx"] = run(
    "curl -s --max-time 60 -X POST http://127.0.0.1:8010/api/research/providers/4/probe | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "print('status:',d.get('status'),'| latency:',d.get('latency_ms'),'| reason:',(d.get('reason') or '')[:100]);"
    "det=d.get('details') or {};print('results:',det.get('results'),'| first:',(det.get('first') or '')[:60])\" 2>&1 | head -3",
    90, "re-probe SearXNG provider")

ev["reprobe_api"] = run(
    "curl -s --max-time 60 -X POST http://127.0.0.1:8010/api/research/providers/5/probe | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "print('status:',d.get('status'),'| latency:',d.get('latency_ms'),'| reason:',(d.get('reason') or '')[:100]);"
    "det=d.get('details') or {};print('results:',det.get('results'),'| first:',(det.get('first') or '')[:60])\" 2>&1 | head -3",
    90, "re-probe Search API provider")

# (6) providers final state
ev["providers_final"] = run(
    "curl -s --max-time 15 http://127.0.0.1:8010/api/research/providers | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "print([{k:p.get(k) for k in ('id','name','enabled','effective_status')} for p in d.get('providers',[])])\"",
    30, "providers final")

ev["health_after"] = health()

path = "/home/z/my-project/download/aes-remediation/W2-T20/step2_tune_engines.json"
with open(path, "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2))
ssh.close()
