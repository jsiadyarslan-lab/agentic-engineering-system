#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3-TIFULL — قراءة فقط: السجل الكامل لاستدعاءات web_search الفاشلة في الخطوة 111."""
import json
import sys

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

DBPY = '''
import sqlite3, json
con = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
out = {}
rows = con.execute("SELECT id,tool,failure_reason,record_json FROM tool_invocations WHERE id IN (358,359,367,368)").fetchall()
for r in rows:
    d = dict(r)
    rec = {}
    try:
        rec = json.loads(d.pop("record_json") or "{}")
    except Exception as e:
        rec = {"parse_error": str(e)[:100]}
    d["record"] = rec
    out[str(d.pop("id"))] = d
print(json.dumps(out, ensure_ascii=False, indent=1))
'''

CMD = "sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % DBPY


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY, timeout=25,
                   look_for_keys=False, allow_agent=False)
    _, so, se = client.exec_command(CMD, timeout=60)
    raw = so.read().decode("utf-8", "replace")
    err = se.read().decode("utf-8", "replace")[:400]
    with open("/home/z/my-project/tool-results/p3_tifull.json", "w") as f:
        f.write(raw)
    print(raw[:9000])
    if err.strip():
        print("[stderr]", err)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
