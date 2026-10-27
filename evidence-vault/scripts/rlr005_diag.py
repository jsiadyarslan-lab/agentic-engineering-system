#!/usr/bin/env python3
"""RLR-005 — investigate the lying web badge: what really happened in that chat."""
import json

import paramiko

HOST, USER, SSHKEY = "92.5.14.150", "opc", "/tmp/oracle_key"

REMOTE = r'''
import sqlite3, json
db = sqlite3.connect("/opt/agentic-engineering-system/runtime/agent_hub_v2.db")
db.row_factory = sqlite3.Row

print("== research events (latest 6) ==")
for r in db.execute("""select id, kind, created_at, payload from events
    where kind like 'research%' order by rowid desc limit 6""").fetchall():
    p = r["payload"] or ""
    try:
        d = json.loads(p)
    except Exception:
        d = {}
    print(f"- #{r['id']} {r['kind']} @ {r['created_at']}")
    print("  details:", json.dumps(d.get("details", d), ensure_ascii=False)[:600])

print()
print("== chat messages of the latest conversation ==")
for r in db.execute("""select id, conversation_id, role, substr(content,1,300) c,
        created_at from chat_messages order by id desc limit 8""").fetchall():
    print(f"- msg#{r['id']} conv={r['conversation_id']} {r['role']} @ {r['created_at']}")
    print("  ", (r["c"] or "").replace("\n", " ")[:280])

print()
print("== research chat log table? ==")
tabs = [r[0] for r in db.execute("select name from sqlite_master where type='table'").fetchall()]
print([t for t in tabs if any(k in t for k in ("research", "chat", "search"))])
'''

REMOTE2 = r'''
import sys
sys.path.insert(0, "/opt/agentic-engineering-system/src")
from research import chat_research

# 1) what does decide_web_mode do with the exact user question?
q = "ما هو اليوم؟"
d = chat_research.decide_web_mode(q, setting="auto")
print("decide_web_mode:", d)

# 2) what search query is built?
sq = chat_research.build_search_query(q)
print("build_search_query:", repr(sq))

# 3) what does denied_context look like?
print("denied_context:", repr(chat_research.denied_context("test reason"))[:400])

# 4) what does build_sources_context produce for sample sources?
sample = [{"title": "خبر تجريبي", "url": "https://example.com/x", "snippet": "نص تجريبي"}]
print("sources_context:", repr(chat_research.build_sources_context(sample, []))[:600])
'''


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=SSHKEY, timeout=25,
              look_for_keys=False, allow_agent=False)
    try:
        sftp = c.open_sftp()
        with sftp.file("/tmp/rlr005_diag.py", "w") as f:
            f.write(REMOTE)
        with sftp.file("/tmp/rlr005_unit.py", "w") as f:
            f.write(REMOTE2)
        sftp.close()

        _, o, e = c.exec_command(
            "cd /opt/agentic-engineering-system && .venv/bin/python /tmp/rlr005_diag.py",
            timeout=60)
        o.channel.recv_exit_status()
        print(o.read().decode("utf-8", "replace")[:5000])
        err = e.read().decode("utf-8", "replace")
        if err:
            print("[stderr]", err[:400])

        print("=" * 60)
        _, o, e = c.exec_command(
            "cd /opt/agentic-engineering-system && .venv/bin/python /tmp/rlr005_unit.py",
            timeout=60)
        o.channel.recv_exit_status()
        print(o.read().decode("utf-8", "replace")[:3000])
        err = e.read().decode("utf-8", "replace")
        if err:
            print("[stderr]", err[:400])
    finally:
        c.close()


if __name__ == "__main__":
    main()
