#!/usr/bin/env python3
"""RLR-005 (resume 3) — noise word lists, wikipedia provider lang, web_used, full wiki error."""
import paramiko

HOST, USER, SSHKEY = "92.5.14.150", "opc", "/tmp/oracle_key"

REMOTE = r'''
import sys, inspect, sqlite3, json
sys.path.insert(0, "/opt/agentic-engineering-system/src")
from research import chat_research as cr

print("== A) _QUERY_NOISE ==")
print(inspect.getsource(cr._QUERY_NOISE) if hasattr(cr._QUERY_NOISE, "__len__") else cr._QUERY_NOISE)
print()
print("== B) _QUERY_STOP ==")
try:
    print(inspect.getsource(cr._QUERY_STOP))
except Exception:
    print(cr._QUERY_STOP)

print()
print("== C) live distill test on the two real messages ==")
for m in ["ابحث لي في الويب عن برج إيفل في باريس واذكر ارتفاعه",
          "ابحث في ويكيبيديا عن برج إيفل واذكر ارتفاعه",
          "ابحث لي في الويب عن برج إيفل واذكر ارتفاعه مع مصادرك"]:
    print(repr(m[:50]), "->", repr(cr.build_search_query(m)))
'''

REMOTE2 = r'''
import sys, inspect
sys.path.insert(0, "/opt/agentic-engineering-system/src")
from research.providers import WikipediaSearchProvider

print("== D) WikipediaSearchProvider full source ==")
print(inspect.getsource(WikipediaSearchProvider)[:4000])
'''

REMOTE3 = r'''
import sqlite3, json
db = sqlite3.connect("/opt/agentic-engineering-system/runtime/agent_hub_v2.db")
db.row_factory = sqlite3.Row
print("== E) full research.unavailable #3629 error ==")
r = db.execute("select payload from events where id=3629").fetchone()
d = json.loads(r["payload"])
print(d.get("error", "")[:1400])

print()
print("== F) messages of conversations 10/11 (what user saw) ==")
for r in db.execute("""select id, conversation_id, role, substr(content,1,220) c,
        created_at from messages where conversation_id in (10,11)
        order by id limit 12""").fetchall():
    print(f"- msg#{r['id']} conv={r['conversation_id']} {r['role']} @ {r['created_at']}")
    print("   ", (r["c"] or "").replace("\n", " ")[:210])
'''

REMOTE4 = r'''
import subprocess
print("== G) grep web_used in src ==")
out = subprocess.run(
    ["grep", "-rn", "web_used", "/opt/agentic-engineering-system/src"],
    capture_output=True, text=True).stdout
lines = out.splitlines()
print("total:", len(lines))
for l in lines[:25]:
    print(l[:180])
print()
print("== H) grep 'web-badge' / WEB_UNAVAILABLE in static ==")
out2 = subprocess.run(
    ["grep", "-rln", "web", "/opt/agentic-engineering-system/static"],
    capture_output=True, text=True).stdout
print(out2[:400])
'''


def run(c, cmd, timeout=90):
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
        for name, body in [("rlr005r3a.py", REMOTE), ("rlr005r3b.py", REMOTE2),
                           ("rlr005r3c.py", REMOTE3), ("rlr005r3d.py", REMOTE4)]:
            with sftp.file("/tmp/" + name, "w") as f:
                f.write(body)
        sftp.close()
        base = "cd /opt/agentic-engineering-system && .venv/bin/python"
        for name, lim in [("rlr005r3a.py", 3000), ("rlr005r3b.py", 4200),
                          ("rlr005r3c.py", 3600), ("rlr005r3d.py", 2200)]:
            o, e = run(c, "%s /tmp/%s" % (base, name))
            print("#" * 30, name)
            print(o[:lim])
            if e.strip():
                print("[stderr]", e[:400])
    finally:
        c.close()


if __name__ == "__main__":
    main()
