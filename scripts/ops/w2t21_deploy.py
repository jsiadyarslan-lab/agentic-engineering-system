#!/usr/bin/env python3
# W2-T21 (search resilience after W2-T20): enable `bing news` engine in SearXNG
# (the only engine proving real results from this host — Arabic+English news),
# route it into the general category so default searches use it, disable brave
# (permanent 429 suspension), disable the app-level direct Bing provider (id=2,
# bing.com serves canned SERPs to this IP — Chess.com page for "climate
# conference" documented). R6 gates: health before/after, backup + rollback.
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EVDIR = "/home/z/my-project/download/aes-remediation/W2-T21"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {
    "task": "W2-T21 — استقرار البحث: محرك bing news + فصل الحظر الناعم",
    "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "root_cause": ("www.bing.com يقدم صفحات نتائج معلبة لهذا المضيف "
                    "(Chess.com لاستعلام climate conference — حظر ناعم)؛ "
                    "bing news + Wikipedia هما العاملان الحقيقيان"),
}}

def run(cmd, t=90, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:120], "rc": rc, "out": out.strip()[:2600],
            "err": err.strip()[:400]}

def health():
    return run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 "
               "http://127.0.0.1:8010/health", 15, "health")["out"]

# ---- R6 pre-flight (read-only) ----
ev["health_before"] = health()
ev["services_before"] = run(
    "systemctl is-active agentic nginx searxng search-api | tr '\\n' ' '", 15, "services")
ev["git_head"] = run("cd /opt/agentic-engineering-system && git rev-parse --short=9 HEAD", 15, "git head")
ev["providers_before"] = run(
    "curl -s --max-time 15 http://127.0.0.1:8010/api/research/providers | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "print([{k:p.get(k) for k in ('id','name','enabled','effective_status')} for p in d.get('providers',[])])\"",
    30, "providers before")
assert ev["health_before"] == "200", "R6 gate: health not 200 — abort"

# ---- step 1: backup settings + append engine overrides ----
ev["backup"] = run(
    "sudo -n cp /etc/searxng/settings.yml /etc/searxng/settings.yml.pre-w2t21 && "
    "sudo -n ls -la /etc/searxng/settings.yml.pre-w2t21", 20, "backup settings")

ENGINE_BLOCK = """  # W2-T21 2026-10-28: bing news — المحرك الوحيد الذي أثبت نتائج حقيقية
  # من هذا المضيف بعد الحظر الناعم لـwww.bing.com (صفحات معلبة موثقة:
  # Chess.com لاستعلام climate conference). أخبار حقيقية عربية وإنجليزية.
  # أُدرج في فئة general أيضًا حتى يُستعلم في البحث الافتراضي (أصله news).
  - name: bing news
    disabled: false
    categories:
      - general
      - news
  # W2-T21: brave — 429 \"Suspended: too many requests\" دائم لهذا المضيف؛
  # إيقافه يوقف ضجيج السجل والطلبات المهدورة (كان يُستعلم كافتراضي غير معرّف)
  - name: brave
    disabled: true
"""
ev["engine_patch"] = run(
    "sudo -n tee -a /etc/searxng/settings.yml > /dev/null <<'YEOF'\n" + ENGINE_BLOCK + "YEOF\n"
    "sudo -n tail -14 /etc/searxng/settings.yml", 20, "append engine block")

# ---- step 2: restart searxng + R6 gate ----
ev["restart_searxng"] = run(
    "sudo -n systemctl restart searxng; sleep 7; sudo -n systemctl is-active searxng", 60, "restart searxng")
if "active" not in ev["restart_searxng"]["out"]:
    ev["ROLLBACK"] = run(
        "sudo -n cp /etc/searxng/settings.yml.pre-w2t21 /etc/searxng/settings.yml && "
        "sudo -n systemctl restart searxng; sleep 7; sudo -n systemctl is-active searxng",
        90, "ROLLBACK restore")
    ev["health_after"] = health()
    path = f"{EVDIR}/deploy.json"
    with open(path, "w") as f:
        json.dump(ev, f, ensure_ascii=False, indent=2)
    print(json.dumps(ev, ensure_ascii=False, indent=2)[:4000])
    ssh.close()
    raise SystemExit("searxng failed after patch — rolled back, evidence saved")

# ---- step 3: default query (no engines= param) — engine composition ----
def searx_probe(query, lang, tag):
    return run(
        "curl -s --max-time 30 'http://127.0.0.1:8888/search?q=" + query +
        "&format=json&language=" + lang + "' | "
        "python3 -c \"import json,sys;d=json.load(sys.stdin);"
        "res={};"
        "map(lambda r: res.__setitem__(r.get('engine','?'), res.get(r.get('engine','?'),0)+1), d.get('results',[]));"
        "print('n_results:',len(d.get('results',[])),'by_engine:',res);"
        "print('titles:',[ (r.get('title') or '')[:60] for r in (d.get('results') or [])[:4]]);"
        "print('unresponsive:',str(d.get('unresponsive_engines',[]))[:220])\" 2>&1 | head -5",
        60, tag)

ev["default_query_en"] = searx_probe("knesset+election+results", "en", "default en query")
ev["default_query_ar"] = searx_probe("%D9%86%D8%AA%D8%A7%D8%A6%D8%AC+%D8%A7%D9%86%D8%AA%D8%AE%D8%A7%D8%B1%D8%A7%D8%AA", "ar", "default ar query") if False else searx_probe(
    __import__("urllib.parse", fromlist=["quote"]).quote("نتائج انتخابات الكنيست"), "ar", "default ar query")

# ---- step 4: disable app direct Bing provider (id=2) via legitimate API ----
ev["disable_bing_direct"] = run(
    "curl -s --max-time 30 -X POST http://127.0.0.1:8010/api/research/providers/2/configure "
    "-H 'Content-Type: application/json' -d '{\"enabled\": false}' | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);p=d.get('provider') or d;"
    "print({k:p.get(k) for k in ('id','name','enabled','last_probe_status')})\" 2>&1 | head -3",
    45, "disable Bing id=2 (canned SERP evidence)")

# ---- step 5: re-probe providers 4/5 ----
for pid in (4, 5):
    ev[f"reprobe_{pid}"] = run(
        f"curl -s --max-time 60 -X POST http://127.0.0.1:8010/api/research/providers/{pid}/probe | "
        "python3 -c \"import json,sys;d=json.load(sys.stdin);"
        "print('status:',d.get('status'),'| reason:',(d.get('reason') or '')[:80]);"
        "det=d.get('details') or {};print('results:',det.get('results'),'| first:',(det.get('first') or '')[:70])\" 2>&1 | head -3",
        90, f"re-probe provider {pid}")

# ---- step 6: app-level searches (the legitimate interface) ----
def app_search(query, tag):
    body = json.dumps({"query": query}, ensure_ascii=False)
    return run(
        "curl -s --max-time 45 -X POST http://127.0.0.1:8010/api/research/search "
        "-H 'Content-Type: application/json' -d " + repr(body).replace("'", "'\\''") + " | "
        "python3 -c \"import json,sys;d=json.load(sys.stdin);"
        "res=d.get('results') or [];"
        "print('provider:',d.get('provider'),'| n:',len(res));"
        "print('titles:',[(r.get('title') or '')[:65] for r in res[:4]]);"
        "print('error:',(d.get('detail') or d.get('error') or '')[:250])\" 2>&1 | head -5",
        75, tag)

ev["app_search_knesset_en"] = app_search("knesset election results", "app search en news")
ev["app_search_knesset_ar"] = app_search("نتائج انتخابات الكنيست اليوم", "app search ar news")
ev["app_search_207"] = app_search(
    "news website page structure homepage world politics business technology sports entertainment article detail search results best practices",
    "app search #207 query")
ev["app_search_astro"] = app_search(
    "Astro TypeScript setup guide official documentation", "app search astro (doc)")

# ---- R6 post-flight ----
ev["health_after"] = health()
ev["journal_errors"] = run(
    "sudo -n journalctl -u agentic -u searxng --since '-10 minutes' --no-pager -p err 2>/dev/null | tail -8",
    30, "journal errors")
ev["providers_after"] = run(
    "curl -s --max-time 15 http://127.0.0.1:8010/api/research/providers | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "print([{k:p.get(k) for k in ('id','name','enabled','effective_status')} for p in d.get('providers',[])])\"",
    30, "providers after")

ssh.close()

import os
os.makedirs(EVDIR, exist_ok=True)
with open(f"{EVDIR}/deploy.json", "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2)[:9000])
