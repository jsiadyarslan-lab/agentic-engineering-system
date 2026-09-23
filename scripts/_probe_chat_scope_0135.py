"""افحص نطاق (scope) أحداث المحادثة المحفوظة — §E."""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter

DB = "runtime/agent_hub_v2.db"
cid = int(sys.argv[1]) if len(sys.argv) > 1 else 12
stream = f"chat-{cid}"

con = sqlite3.connect(DB)
rows = con.execute(
    "SELECT seq, kind, payload FROM events WHERE cycle_id = ? ORDER BY seq",
    (stream,),
).fetchall()
print(f"stream={stream} events={len(rows)}")

missing: list[tuple] = []
scopes: Counter = Counter()
for seq, kind, payload in rows:
    try:
        data = json.loads(payload or "{}")
    except ValueError:
        data = {}
    scope = data.get("scope") or {}
    if scope.get("conversation_id"):
        scopes[kind] += 1
    else:
        missing.append((seq, kind, scope, sorted(data.keys())))

print("kinds with scope:", dict(scopes))
print(f"kinds WITHOUT scope: {len(missing)}")
for item in missing[:10]:
    print("  seq", item[0], item[1], "scope=", json.dumps(item[2], ensure_ascii=False),
          "keys=", item[3])
