"""Dump project + planning session + provider state (diagnostics only)."""
import json
import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else "runtime/agent_hub_v2.db"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row


def cols(t):
    return [r[1] for r in con.execute(f"PRAGMA table_info({t})")]


for t in ("projects", "planning_sessions", "provider_configurations",
          "providers", "role_provider_mappings", "conversations",
          "engineering_jobs"):
    print("=" * 70)
    print("TABLE", t, cols(t))
    c = cols(t)
    for row in con.execute(f"select * from {t}"):
        d = dict(row)
        out = {}
        for k, v in d.items():
            s = str(v)
            out[k] = s[:160] + ("..." if len(s) > 160 else "")
        print(json.dumps(out, ensure_ascii=False, indent=1))
