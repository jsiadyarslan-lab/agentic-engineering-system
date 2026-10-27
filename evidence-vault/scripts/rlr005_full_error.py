#!/usr/bin/env python3
"""RLR-005-f — full error of recent research.unavailable + search_for_chat logic."""
import paramiko

HOST, USER, SSHKEY = "92.5.14.150", "opc", "/tmp/oracle_key"

REMOTE = r'''
import sqlite3, json
db = sqlite3.connect("/opt/agentic-engineering-system/runtime/agent_hub_v2.db")
db.row_factory = sqlite3.Row

print("== last 3 research.unavailable events (FULL) ==")
for r in db.execute("""select id, created_at, payload from events
    where kind = 'research.unavailable' order by rowid desc limit 3""").fetchall():
    d = json.loads(r["payload"])
    det = d.get("details", {})
    print(f"--- #{r['id']} @ {r['created_at']}")
    print("query:", det.get("query", "")[:80])
    print("providers_tried:", det.get("providers_tried"))
    print("error:", det.get("error", "")[:700])
    print()
'''

REMOTE2 = r'''
import sys
sys.path.insert(0, "/opt/agentic-engineering-system/src")
import inspect
from research import chat_research

src = inspect.getsource(chat_research.search_for_chat)
print(src[:3000])
'''


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=SSHKEY, timeout=25,
              look_for_keys=False, allow_agent=False)
    try:
        sftp = c.open_sftp()
        with sftp.file("/tmp/rlr005f.py", "w") as f:
            f.write(REMOTE)
        with sftp.file("/tmp/rlr005f2.py", "w") as f:
            f.write(REMOTE2)
        sftp.close()
        _, o, _ = c.exec_command(
            "cd /opt/agentic-engineering-system && .venv/bin/python /tmp/rlr005f.py",
            timeout=60)
        o.channel.recv_exit_status()
        print(o.read().decode("utf-8", "replace")[:3500])

        print("=" * 60)
        _, o, _ = c.exec_command(
            "cd /opt/agentic-engineering-system && .venv/bin/python /tmp/rlr005f2.py",
            timeout=60)
        o.channel.recv_exit_status()
        print(o.read().decode("utf-8", "replace")[:3500])
    finally:
        c.close()


if __name__ == "__main__":
    main()
