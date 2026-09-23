"""Search every DB table for contamination text (diagnostics only)."""
import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else "runtime/agent_hub_v2.db"
needles = sys.argv[2:] or ["HASH-MANIFEST", "A15", "Confirmation of Completion"]
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
tables = [r[0] for r in con.execute(
    "select name from sqlite_master where type='table' order by name")]
for t in tables:
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
    for n in needles:
        for c in cols:
            try:
                rows = con.execute(
                    f"select rowid, * from {t} where cast({c} as text) like ? "
                    f"limit 5", (f"%{n}%",)).fetchall()
            except Exception:  # noqa: BLE001
                continue
            for row in rows:
                d = dict(row)
                for k, v in d.items():
                    s = str(v)
                    if n in s:
                        i = s.find(n)
                        print(f"[{t}.{c}] rowid={d.get('rowid')} "
                              f"field={k}: ...{s[max(0,i-200):i+300]}...")
