"""Dump conversations + recent messages (diagnostics only)."""
import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else "runtime/agent_hub_v2.db"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row


def cols(t):
    return [r[1] for r in con.execute(f"PRAGMA table_info({t})")]


print("conversations cols:", cols("conversations"))
for row in con.execute("select * from conversations order by id"):
    d = dict(row)
    print({k: (str(v)[:80]) for k, v in d.items()})

print("=" * 70)
print("messages cols:", cols("messages"))
for row in con.execute("select * from messages order by id desc limit 40"):
    d = dict(row)
    print("-" * 60)
    for k, v in d.items():
        s = str(v)
        if len(s) > 600:
            s = s[:600] + f"...[{len(s)} chars]"
        print(f"  {k}: {s}")
