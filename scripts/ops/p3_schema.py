#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3-SCHEMA — قراءة فقط: اكتشاف مخطط القاعدة الحقيقي."""
import sys

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

DBPY = '''
import sqlite3, json
con = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
out = {}
tables = [r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
out["tables"] = tables
schemas = {}
for t in tables:
    cols = [dict(r) for r in con.execute("PRAGMA table_info(%s)" % t)]
    schemas[t] = [c["name"] for c in cols]
out["schemas"] = schemas
print(json.dumps(out, ensure_ascii=False, indent=1))
'''

CMD = "sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % DBPY


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY, timeout=25,
                   look_for_keys=False, allow_agent=False)
    _, so, se = client.exec_command(CMD, timeout=40)
    print(so.read().decode("utf-8", "replace")[:8000])
    err = se.read().decode("utf-8", "replace")[:300]
    if err.strip():
        print("[stderr]", err)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
