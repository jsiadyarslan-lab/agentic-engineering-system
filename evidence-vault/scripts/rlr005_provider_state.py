#!/usr/bin/env python3
"""RLR-005-e — inspect research provider state + direct Wikipedia test."""
import json

import paramiko

HOST, USER, SSHKEY = "92.5.14.150", "opc", "/tmp/oracle_key"

REMOTE = r'''
import sqlite3, json, sys
sys.path.insert(0, "/opt/agentic-engineering-system/src")
db = sqlite3.connect("/opt/agentic-engineering-system/runtime/agent_hub_v2.db")
db.row_factory = sqlite3.Row

print("== research_providers table ==")
try:
    for r in db.execute("select * from research_providers").fetchall():
        d = dict(r)
        # mask any key/token columns
        for k in list(d):
            if k and any(w in k.lower() for w in ("key", "token", "secret")):
                d[k] = "MASKED"
        print(json.dumps(d, ensure_ascii=False, default=str)[:400])
except Exception as e:
    print("(no table)", e)

print()
print("== direct Wikipedia search test (provider code path) ==")
try:
    from research import providers as rp
    names = [n for n in dir(rp) if "wiki" in n.lower()]
    print("wiki symbols:", names[:6])
except Exception as e:
    print("import:", e)

# direct wikipedia api call — the same thing the provider does
import urllib.request, urllib.parse
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
    print("FAILED:", type(e).__name__, str(e)[:200])
'''


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=SSHKEY, timeout=25,
              look_for_keys=False, allow_agent=False)
    try:
        sftp = c.open_sftp()
        with sftp.file("/tmp/rlr005e.py", "w") as f:
            f.write(REMOTE)
        sftp.close()
        _, o, e = c.exec_command(
            "cd /opt/agentic-engineering-system && .venv/bin/python /tmp/rlr005e.py",
            timeout=90)
        o.channel.recv_exit_status()
        print(o.read().decode("utf-8", "replace")[:3000])
        err = e.read().decode("utf-8", "replace")
        if err:
            print("[stderr]", err[:300])
    finally:
        c.close()


if __name__ == "__main__":
    main()
