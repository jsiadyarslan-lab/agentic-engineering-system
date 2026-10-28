#!/usr/bin/env python3
# W2-T21 (part 3): proper E2E chat test — save SSE stream to file, parse with
# real multi-line python, then confirm the conversation/messages in DB.
import json, time, base64, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EVDIR = "/home/z/my-project/download/aes-remediation/W2-T21"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T21 part3 — E2E محادثة (تصحيح التحليل)",
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=150, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:120], "rc": rc, "out": out.strip()[:4000],
            "err": err.strip()[:400]}

chat_q = "ما آخر أخبار انتخابات الكنيست اليوم؟ اذكر نتيجة الفرز واستطلاعات الخروج"
body64 = base64.b64encode(json.dumps({"message": chat_q, "web": "auto"}, ensure_ascii=False).encode()).decode()

ev["chat_stream"] = run(
    f"echo {body64} | base64 -d > /tmp/w2t21_chat.json && "
    "curl -s -N --max-time 120 -X POST http://127.0.0.1:8010/api/chat/stream "
    "-H 'Content-Type: application/json' --data-binary @/tmp/w2t21_chat.json "
    "-o /tmp/w2t21_chat.sse -w 'http=%{{http_code}} time=%{{time_total}}s\\n'; "
    "wc -c /tmp/w2t21_chat.sse; head -c 200 /tmp/w2t21_chat.sse",
    150, "chat E2E stream to file")

PARSE = r'''
import json
kinds = []
answer_parts = []
research = None
unavail = None
for raw in open("/tmp/w2t21_chat.sse", encoding="utf-8", errors="replace"):
    line = raw.strip()
    if not line.startswith("data:"):
        continue
    payload = line[5:].strip()
    try:
        e = json.loads(payload)
    except Exception:
        continue
    k = e.get("kind", "?")
    kinds.append(k)
    if k == "research.results":
        research = e
    if k == "research.unavailable":
        unavail = e
    if k in ("message_delta", "message_completed"):
        t = e.get("text") or e.get("delta") or ""
        if t:
            answer_parts.append(t)
answer = "".join(answer_parts)
print("kinds:", kinds[:30])
if research is not None:
    det = research.get("details") or {}
    res = det.get("results") or research.get("results") or []
    print("research.results count:", len(res))
    for r in res[:5]:
        print("  -", (r.get("title") or "")[:70], "|", (r.get("url") or "")[:60])
if unavail is not None:
    print("research.unavailable:", str(unavail)[:300])
print("ANSWER_LEN:", len(answer))
print("ANSWER_HEAD:", answer[:700])
'''
ev["chat_parse"] = run(
    "python3 - <<'PYEOF'\n" + PARSE + "\nPYEOF", 60, "parse SSE")

# confirm DB state: latest conversation + messages
ev["db_check"] = run(
    "cd /opt/agentic-engineering-system && python3 - <<'PYEOF'\n"
    "import sqlite3, json\n"
    "db = sqlite3.connect('file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro', uri=True)\n"
    "db.row_factory = sqlite3.Row\n"
    "for r in db.execute(\"SELECT id,title,mode,created_at,updated_at FROM conversations ORDER BY id DESC LIMIT 2\"):\n"
    "    print('conv:', dict(r))\n"
    "for r in db.execute(\"SELECT id,conversation_id,role,substr(coalesce(content,''),1) c,created_at FROM messages WHERE conversation_id=(SELECT MAX(id) FROM conversations) ORDER BY id\"):\n"
    "    print('msg:', r['id'], r['role'], r['created_at'], 'len=', len(r['c']), 'head=', r['c'][:120].replace(chr(10),' '))\n"
    "PYEOF", 60, "db conversations/messages")

ev["health_after"] = run(
    "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health",
    15, "health")["out"]

ssh.close()
with open(f"{EVDIR}/chat_e2e.json", "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2)[:7000])
