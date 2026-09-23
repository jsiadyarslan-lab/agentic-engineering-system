"""Which conversation holds the A15 content? (diagnostics only)"""
import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else "runtime/agent_hub_v2.db"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
for row in con.execute(
        "select id, conversation_id, role, substr(content,1,120) as head, "
        "created_at from messages where content like '%A15%' or "
        "content like '%Confirmation of Completion%' or "
        "content like '%HASH-MANIFEST%' order by id"):
    print(f"msg={row['id']} conv={row['conversation_id']} role={row['role']} "
          f"at={row['created_at']}")
    print("   ", row["head"].replace("\n", " "))

print("=" * 70)
print("messages per conversation:")
for row in con.execute(
        "select conversation_id, count(*) c, min(created_at) a, max(created_at) b "
        "from messages group by conversation_id order by conversation_id"):
    print(f"  conv={row['conversation_id']} n={row['c']} {row['a']} -> {row['b']}")
