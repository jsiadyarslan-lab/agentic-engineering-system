#!/usr/bin/env python3
"""RLR-001 — read recent factory runs from agent_hub_v2.db (READ-ONLY)."""
import sqlite3
import sys

APP = "/opt/agentic-engineering-system"
db = sqlite3.connect(f"{APP}/runtime/agent_hub_v2.db")
db.row_factory = sqlite3.Row

tabs = [r[0] for r in db.execute("select name from sqlite_master where type='table'").fetchall()]
print("tables:", tabs)

for t in tabs:
    tl = t.lower()
    if any(k in tl for k in ("run", "exec", "task", "job", "turn", "message", "session")):
        try:
            cols = [c[1] for c in db.execute(f"pragma table_info({t})").fetchall()]
            n = db.execute(f"select count(*) from {t}").fetchone()[0]
            print(f"\n== {t} ({n} rows) cols: {cols[:14]}")
            if n and any(k in tl for k in ("run", "exec", "task", "job")):
                for r in db.execute(f"select * from {t} order by rowid desc limit 4").fetchall():
                    d = dict(r)
                    for k, v in list(d.items()):
                        if isinstance(v, str) and len(v) > 110:
                            d[k] = v[:110] + "..."
                    print(d)
        except Exception as ex:
            print(t, "ERR", ex)
