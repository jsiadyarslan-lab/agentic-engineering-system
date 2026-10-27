#!/usr/bin/env python3
"""RLR-005 (resume 6) — server git state + user's actual complaint conversation."""
import paramiko

HOST, USER, SSHKEY = "92.5.14.150", "opc", "/tmp/oracle_key"

REMOTE = r'''
import sqlite3, json
db = sqlite3.connect("/opt/agentic-engineering-system/runtime/agent_hub_v2.db")
db.row_factory = sqlite3.Row

print("== A) conversations list ==")
try:
    for r in db.execute("""select id, substr(title,1,60) t, created_at
            from conversations order by id desc limit 12""").fetchall():
        print(f"conv#{r['id']}: {r['t']} @ {r['created_at']}")
except Exception as e:
    tabs = [x[0] for x in db.execute("select name from sqlite_master where type='table'")]
    print("no conversations table:", e, "| tables:", tabs)

print()
print("== B) messages of conv 8-9 (user's complaint chats, before my E2E) ==")
for r in db.execute("""select id, conversation_id, role, substr(content,1,400) c,
        created_at, state_badge from messages where conversation_id in (8,9)
        order by id""").fetchall():
    print(f"--- msg#{r['id']} conv={r['conversation_id']} {r['role']} [{r['state_badge']}] @ {r['created_at']}")
    print((r["c"] or "").replace("\n", " ")[:380])
    print()

print("== C) any message-level web metadata columns? ==")
cols = [r[1] for r in db.execute("pragma table_info(messages)").fetchall()]
print(cols)
'''

REMOTE2 = r'''
import subprocess
print("== D) server git state ==")
for cmd in ["git -C /opt/agentic-engineering-system log --oneline -4",
            "git -C /opt/agentic-engineering-system status -sb | head -3"]:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(cmd.split("git -C ")[1][:40], "=>")
    print(r.stdout.strip()[:400])
    if r.stderr.strip():
        print("[err]", r.stderr.strip()[:200])
print()
print("== E) what did 422a279 change ==")
r = subprocess.run("git -C /opt/agentic-engineering-system show 422a279 --stat",
                   shell=True, capture_output=True, text=True)
print(r.stdout[:900])
'''

REMOTE3 = r'''
import sqlite3, json
db = sqlite3.connect("/opt/agentic-engineering-system/runtime/agent_hub_v2.db")
db.row_factory = sqlite3.Row
print("== F) ALL events of conv 9 (or last user conv before 10) — research + clock ==")
for r in db.execute("""select id, kind, created_at, substr(payload,1,300) p from events
    where payload like '%"conversation_id": 9%' or payload like '%"conversation_id":9%'
    order by rowid limit 40""").fetchall():
    print(f"- #{r['id']} {r['kind']} @ {r['created_at']}")
    print("   ", (r["p"] or "").replace("\n", " ")[:280])
print()
print("== G) events mentioning clock ==")
for r in db.execute("""select id, kind, created_at, substr(payload,1,240) p from events
    where kind like '%clock%' order by rowid desc limit 8""").fetchall():
    print(f"- #{r['id']} {r['kind']} @ {r['created_at']}")
    print("   ", (r["p"] or "").replace("\n", " ")[:220])
'''


def run(c, cmd, timeout=60):
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
        for name, body in [("rlr005r6a.py", REMOTE), ("rlr005r6b.py", REMOTE2),
                           ("rlr005r6c.py", REMOTE3)]:
            with sftp.file("/tmp/" + name, "w") as f:
                f.write(body)
        sftp.close()
        base = "cd /opt/agentic-engineering-system && .venv/bin/python"
        for name, lim in [("rlr005r6a.py", 4200), ("rlr005r6b.py", 1400),
                          ("rlr005r6c.py", 3800)]:
            o, e = run(c, "%s /tmp/%s" % (base, name))
            print("#" * 30, name)
            print(o[:lim])
            if e.strip():
                print("[stderr]", e[:400])
    finally:
        c.close()


if __name__ == "__main__":
    main()
