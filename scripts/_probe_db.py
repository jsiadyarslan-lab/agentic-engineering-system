"""Read-only probe of the live runtime DB (diagnostics only)."""
import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else "runtime/agent_hub_v2.db"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
tables = [r[0] for r in con.execute(
    "select name from sqlite_master where type='table' order by name")]
print("TABLES:", tables)
for t in tables:
    try:
        n = con.execute(f"select count(*) from {t}").fetchone()[0]
    except Exception as exc:  # noqa: BLE001
        n = f"ERR {exc}"
    print(f"  {t}: {n}")
