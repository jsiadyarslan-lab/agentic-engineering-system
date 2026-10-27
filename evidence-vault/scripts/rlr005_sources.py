#!/usr/bin/env python3
"""RLR-005 (resume 2) — source inspection: query builder, wikipedia provider, web_used logic."""
import paramiko

HOST, USER, SSHKEY = "92.5.14.150", "opc", "/tmp/oracle_key"

REMOTE = r'''
import sqlite3, sys, inspect, json
sys.path.insert(0, "/opt/agentic-engineering-system/src")

print("== A) real table names ==")
db = sqlite3.connect("/opt/agentic-engineering-system/runtime/agent_hub_v2.db")
tabs = [r[0] for r in db.execute("select name from sqlite_master where type='table'").fetchall()]
print([t for t in tabs if any(k in t.lower() for k in ("message", "chat", "research", "event"))])

print()
print("== B) build_search_query source ==")
from research import chat_research
print(inspect.getsource(chat_research.build_search_query))
print("== C) decide_web_mode source ==")
print(inspect.getsource(chat_research.decide_web_mode)[:2200])
print("== D) search_for_chat source (first 2500) ==")
print(inspect.getsource(chat_research.search_for_chat)[:2500])
'''

REMOTE2 = r'''
import sys, inspect
sys.path.insert(0, "/opt/agentic-engineering-system/src")

print("== E) wikipedia provider: where does 'صفر نتائج' come from ==")
from research import providers as rp
src = inspect.getsource(rp)
i = src.find("صفر نتائج")
print("...context around 'صفر نتائج'...")
print(src[max(0,i-1800):i+600])
'''

REMOTE3 = r'''
import sys, json, urllib.request, urllib.parse
sys.path.insert(0, "/opt/agentic-engineering-system/src")

print("== F) arabic wikipedia direct (ar.wikipedia.org) ==")
q = urllib.parse.quote("برج إيفل")
url = ("https://ar.wikipedia.org/w/api.php?action=query&list=search"
       "&srsearch=" + q + "&format=json&srlimit=5")
req = urllib.request.Request(url, headers={"User-Agent": "AES/1.0 (research probe)"})
try:
    r = urllib.request.urlopen(req, timeout=25)
    d = json.loads(r.read())
    hits = d.get("query", {}).get("search", [])
    print("HTTP", r.status, "| hits:", len(hits))
    for h in hits[:3]:
        print("  -", h.get("title"))
except Exception as e:
    print("FAILED:", type(e).__name__, str(e)[:250])

print()
print("== G) call the actual wikipedia provider function with arabic query ==")
from research import providers as rp
cands = [n for n, f in vars(rp).items() if callable(f) and "wiki" in str(getattr(f, "__name__", "")).lower()]
print("wiki funcs:", cands)
try:
    res = rp.search_wikipedia("برج إيفل", k=5)
    print("search_wikipedia('برج إيفل') ->", json.dumps(res, ensure_ascii=False)[:600])
except Exception as e:
    print("call err:", type(e).__name__, str(e)[:300])
'''

REMOTE4 = r'''
import sys, inspect
sys.path.insert(0, "/opt/agentic-engineering-system/src")

print("== H) where web_used is set in the chat stream ==")
import api.chat as ac  # guess
src = inspect.getsource(ac)
i = src.find("web_used")
while i != -1 and i < len(src):
    print("...at", i, "...")
    print(src[max(0,i-500):i+300])
    print("-" * 40)
    ni = src.find("web_used", i + 1)
    if ni == -1 or ni > i + 4000:
        break
    i = ni
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
        for name, body in [("rlr005r2a.py", REMOTE), ("rlr005r2b.py", REMOTE2),
                           ("rlr005r2c.py", REMOTE3), ("rlr005r2d.py", REMOTE4)]:
            with sftp.file("/tmp/" + name, "w") as f:
                f.write(body)
        sftp.close()
        base = "cd /opt/agentic-engineering-system && .venv/bin/python"
        for name, lim in [("rlr005r2a.py", 5500), ("rlr005r2b.py", 3200),
                          ("rlr005r2c.py", 1800), ("rlr005r2d.py", 3000)]:
            o, e = run(c, "%s /tmp/%s" % (base, name))
            print("#" * 30, name)
            print(o[:lim])
            if e.strip():
                print("[stderr]", e[:400])
    finally:
        c.close()


if __name__ == "__main__":
    main()
