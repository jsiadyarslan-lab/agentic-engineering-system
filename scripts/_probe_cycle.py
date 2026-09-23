"""Dump the chat-10 cycle timeline (diagnostics only)."""
import json
import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else "runtime/agent_hub_v2.db"
cycle = sys.argv[2] if len(sys.argv) > 2 else "chat-10"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
print("events cols:", [r[1] for r in con.execute("PRAGMA table_info(events)")])
rows = con.execute(
    "select * from events where cast(payload as text) like ? order by rowid",
    (f"%{cycle}%",)).fetchall()
print("rows:", len(rows))
for row in rows:
    d = dict(row)
    payload = d.get("payload")
    try:
        p = json.loads(payload)
    except Exception:  # noqa: BLE001
        p = {"raw": str(payload)[:200]}
    kind = p.get("kind") or d.get("kind")
    seq = p.get("seq")
    txt = p.get("delta") or p.get("text") or ""
    txt = str(txt).replace("\n", "\\n")[:140]
    print(f"seq={seq} kind={kind} msg={p.get('message_id','')} "
          f"conv={p.get('details',{}).get('conversation_id') if isinstance(p.get('details'), dict) else ''} "
          f"role={p.get('role','')} ts={p.get('timestamp','')} :: {txt}")
