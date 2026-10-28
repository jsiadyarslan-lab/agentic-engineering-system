#!/usr/bin/env python3
# W2-T21 (part 2): app-level search verification (base64 bodies — Arabic-safe)
# + E2E chat test with web-intent Arabic news question.
import json, time, base64, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EVDIR = "/home/z/my-project/download/aes-remediation/W2-T21"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T21 part2 — تحقق بحث التطبيق + E2E محادثة",
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=120, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:120], "rc": rc, "out": out.strip()[:2600],
            "err": err.strip()[:400]}

def app_search(query, tag):
    body64 = base64.b64encode(json.dumps({"query": query}, ensure_ascii=False).encode()).decode()
    return run(
        f"echo {body64} | base64 -d > /tmp/w2t21_q.json && "
        "curl -s --max-time 45 -X POST http://127.0.0.1:8010/api/research/search "
        "-H 'Content-Type: application/json' --data-binary @/tmp/w2t21_q.json | "
        "python3 -c \"import json,sys;d=json.load(sys.stdin);"
        "res=d.get('results') or [];"
        "print('provider:',d.get('provider'),'| n:',len(res));"
        "print('titles:',[(r.get('title') or '')[:65] for r in res[:4]]);"
        "print('error:',(d.get('detail') or d.get('error') or '')[:260])\" 2>&1 | head -6; "
        "rm -f /tmp/w2t21_q.json",
        75, tag)

ev["search_knesset_en"] = app_search("knesset election results", "app: en news")
ev["search_knesset_ar"] = app_search("نتائج انتخابات الكنيست اليوم", "app: ar news")
ev["search_207"] = app_search(
    "news website page structure homepage world politics business technology sports entertainment article detail search results best practices",
    "app: #207 query")
ev["search_news_structure_ar"] = app_search(
    "هيكل صفحات موقع أخبار الرئيسية العالم السياسة الأعمال التكنولوجيا الرياضة الترفيه",
    "app: ar news-structure")
ev["search_astro"] = app_search(
    "Astro TypeScript setup guide official documentation", "app: astro (doc expected fail)")

# ---- E2E chat: web-intent Arabic news question ----
chat_q = "ما آخر أخبار انتخابات الكنيست اليوم؟ نتيجة الفرز واستطلاعات الخروج"
body64 = base64.b64encode(json.dumps({"message": chat_q, "web": "auto"}, ensure_ascii=False).encode()).decode()
ev["chat_e2e"] = run(
    f"echo {body64} | base64 -d > /tmp/w2t21_chat.json && "
    "curl -s -N --max-time 120 -X POST http://127.0.0.1:8010/api/chat/stream "
    "-H 'Content-Type: application/json' --data-binary @/tmp/w2t21_chat.json | "
    "python3 -c \"import sys,re;"
    "kinds=[];answer=[];research=None;"
    "for line in sys.stdin:"
    " line=line.strip();"
    " if not line.startswith('data:'):continue;"
    " try:import json;e=json.loads(line[5:].strip())"
    " except Exception:continue;"
    " k=e.get('kind','?');kinds.append(k);"
    " if k=='research.results':research=e;"
    " if k in ('message_delta','message_completed'):"
    "  t=(e.get('text') or e.get('delta') or '');"
    "  if t:answer.append(t);"
    "print('kinds:',kinds[:24]);"
    "det=(research or {}).get('details') or (research or {}).get('results') or {};print('research_keys:',list((research or {}).keys()));print('research:',str(research)[:400]);"
    "print('ANSWER_HEAD:', ''.join(answer)[:600])\" 2>&1 | head -12; "
    "rm -f /tmp/w2t21_chat.json",
    150, "chat E2E web-intent ar")

ev["health_after"] = run(
    "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health",
    15, "health")["out"]
ev["journal_err"] = run(
    "sudo -n journalctl -u agentic --since '-15 minutes' --no-pager -p err 2>/dev/null | tail -6",
    30, "journal err")

ssh.close()
with open(f"{EVDIR}/verify.json", "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2)[:9000])
