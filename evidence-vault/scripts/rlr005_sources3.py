#!/usr/bin/env python3
"""RLR-005 (resume 4) — noise lists values, wiki provider tail, badge JS, routes context."""
import paramiko

HOST, USER, SSHKEY = "92.5.14.150", "opc", "/tmp/oracle_key"

REMOTE = r'''
import sys
sys.path.insert(0, "/opt/agentic-engineering-system/src")
from research import chat_research as cr

print("== A) _QUERY_NOISE value ==")
print(repr(cr._QUERY_NOISE))
print()
print("== B) _QUERY_STOP value ==")
print(repr(cr._QUERY_STOP))
print()
print("== C) distill test ==")
for m in ["ابحث لي في الويب عن برج إيفل في باريس واذكر ارتفاعه",
          "ابحث في ويكيبيديا عن برج إيفل واذكر ارتفاعه"]:
    print(repr(cr.build_search_query(m)))
'''

REMOTE2 = r'''
import sys, inspect
sys.path.insert(0, "/opt/agentic-engineering-system/src")
from research.providers import WikipediaSearchProvider
src = inspect.getsource(WikipediaSearchProvider)
print("== D) provider source tail (search method, from 'def search') ==")
i = src.find("def search")
print(src[i:i+3500])
'''

REMOTE3 = r'''
print("== E) chat-stream.js around web badge ==")
with open("/opt/agentic-engineering-system/src/ui/chat-stream.js") as f:
    js = f.read()
i = js.find("web_used")
print(js[max(0,i-2200):i+1800])
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
        for name, body in [("rlr005r4a.py", REMOTE), ("rlr005r4b.py", REMOTE2),
                           ("rlr005r4c.py", REMOTE3)]:
            with sftp.file("/tmp/" + name, "w") as f:
                f.write(body)
        sftp.close()
        base = "cd /opt/agentic-engineering-system && .venv/bin/python"
        for name, lim in [("rlr005r4a.py", 2600), ("rlr005r4b.py", 3700),
                          ("rlr005r4c.py", 4200)]:
            o, e = run(c, "%s /tmp/%s" % (base, name))
            print("#" * 30, name)
            print(o[:lim])
            if e.strip():
                print("[stderr]", e[:400])
    finally:
        c.close()


if __name__ == "__main__":
    main()
