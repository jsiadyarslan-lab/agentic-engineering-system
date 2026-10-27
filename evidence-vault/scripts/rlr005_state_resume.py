#!/usr/bin/env python3
"""RLR-005 (resume) — consolidated state: research events + providers + probe + unit logic."""
import json

import paramiko

HOST, USER, SSHKEY = "92.5.14.150", "opc", "/tmp/oracle_key"

REMOTE = r'''
import sqlite3, json, sys
sys.path.insert(0, "/opt/agentic-engineering-system/src")
db = sqlite3.connect("/opt/agentic-engineering-system/runtime/agent_hub_v2.db")
db.row_factory = sqlite3.Row

print("== A) last 4 research.* events (FULL details) ==")
for r in db.execute("""select id, kind, created_at, payload from events
    where kind like 'research.%' order by rowid desc limit 4""").fetchall():
    p = r["payload"] or "{}"
    try:
        d = json.loads(p)
    except Exception:
        d = {"raw": p}
    det = d.get("details", d)
    print(f"--- #{r['id']} {r['kind']} @ {r['created_at']}")
    print(json.dumps(det, ensure_ascii=False, default=str)[:800])

print()
print("== B) research_providers table ==")
try:
    for r in db.execute("select * from research_providers").fetchall():
        d = dict(r)
        for k in list(d):
            if k and any(w in k.lower() for w in ("key", "token", "secret")):
                d[k] = "MASKED"
        print(json.dumps(d, ensure_ascii=False, default=str)[:400])
except Exception as e:
    print("(no table)", e)

print()
print("== C) last 6 chat messages (role/web meta) ==")
for r in db.execute("""select id, conversation_id, role, substr(content,1,180) c,
        created_at from chat_messages order by id desc limit 6""").fetchall():
    print(f"- msg#{r['id']} conv={r['conversation_id']} {r['role']} @ {r['created_at']}")
    print("   ", (r["c"] or "").replace("\n", " ")[:170])

print()
print("== D) unit: decide_web_mode / build_search_query ==")
from research import chat_research
for q in ["ما هو اليوم؟", "ابحث لي في الويب عن برج إيفل واذكر ارتفاعه مع مصادرك"]:
    try:
        print(repr(q[:40]), "->", chat_research.decide_web_mode(q, setting="auto"))
        print("   query:", repr(chat_research.build_search_query(q))[:200])
    except Exception as e:
        print("unit err:", type(e).__name__, str(e)[:200])

print()
print("== E) direct provider call test (from chat path) ==")
try:
    src = chat_research.search_for_chat
    print("search_for_chat OK:", callable(src))
except Exception as e:
    print("import err:", e)
import urllib.request, urllib.parse
q = urllib.parse.quote("برج إيفل")
url = ("https://ar.wikipedia.org/w/api.php?action=query&list=search"
       "&srsearch=" + q + "&format=json&srlimit=5")
req = urllib.request.Request(url, headers={"User-Agent": "AES/1.0 (research probe)"})
try:
    r = urllib.request.urlopen(req, timeout=25)
    d = json.loads(r.read())
    hits = d.get("query", {}).get("search", [])
    print("Wikipedia direct: HTTP", r.status, "| hits:", len(hits))
except Exception as e:
    print("Wikipedia direct FAILED:", type(e).__name__, str(e)[:250])
'''

REMOTE2 = r'''
import json, urllib.request
req = urllib.request.Request(
    "http://127.0.0.1:8010/api/environment/readiness", method="GET")
with urllib.request.urlopen(req, timeout=30) as r:
    d = json.loads(r.read())
caps = d.get("capabilities", d) or {}
if isinstance(caps, dict):
    for cid in ("web_search", "web_fetch", "llm"):
        c = caps.get(cid) or {}
        print(cid, "->", c.get("readiness_status") or c.get("status"),
              "|", str(c.get("failure_reason", ""))[:120])
elif isinstance(caps, list):
    for c in caps:
        if c.get("capability_id") in ("web_search", "web_fetch", "llm"):
            print(c.get("capability_id"), "->", c.get("readiness_status"),
                  "|", str(c.get("failure_reason", ""))[:120])
'''


def run(c, cmd, timeout=120):
    _, o, e = c.exec_command(cmd, timeout=timeout)
    o.channel.recv_exit_status()
    return o.read().decode("utf-8", "replace"), e.read().decode("utf-8", "replace")


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=SSHKEY, timeout=25,
              look_for_keys=False, allow_agent=False)
    try:
        sftp = c.open_sftp()
        with sftp.file("/tmp/rlr005r.py", "w") as f:
            f.write(REMOTE)
        with sftp.file("/tmp/rlr005r2.py", "w") as f:
            f.write(REMOTE2)
        sftp.close()
        o, e = run(c, "cd /opt/agentic-engineering-system && .venv/bin/python /tmp/rlr005r.py", 120)
        print(o[:6000])
        if e.strip():
            print("[stderr]", e[:500])
        print("=" * 62)
        o, e = run(c, ".venv/bin/python /tmp/rlr005r2.py 2>/dev/null || cd /opt/agentic-engineering-system && .venv/bin/python /tmp/rlr005r2.py", 60)
        print("readiness now:")
        print(o[:1500])
        if e.strip():
            print("[stderr]", e[:300])
    finally:
        c.close()


if __name__ == "__main__":
    main()
