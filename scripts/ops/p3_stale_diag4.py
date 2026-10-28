# -*- coding: utf-8 -*-
"""P3-STALE-DIAG-4 — معايير الخطوات 103-110 + توفر node/npm على المضيف."""
import json
import sys

import paramiko

HOST = "92.5.14.150"
USER = "opc"
KEY = "/tmp/oracle_key"

REMOTE_PY = r'''
import sqlite3, json
con = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
rows = []
for r in con.execute("SELECT id, ordinal, objective, acceptance_criteria FROM steps WHERE id BETWEEN 103 AND 110 ORDER BY id"):
    rows.append({"id": r["id"], "ord": r["ordinal"], "obj": r["objective"][:120],
                 "criteria": r["acceptance_criteria"][:900]})
print("DIAG4-JSON:" + json.dumps(rows, ensure_ascii=False))
'''

LOCAL_GREP = [
    ("node", "which node npm npx 2>/dev/null; node --version 2>/dev/null; npm --version 2>/dev/null; echo ---; ls /usr/local/bin/ 2>/dev/null | head; echo ---; ls /opt/agentic-engineering-system/.venv/bin | head -5"),
    ("prod_head", "cd /opt/agentic-engineering-system && sudo -n git log --oneline -3 && sudo -n git status --short | head -5"),
]


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY, timeout=25)
    _, stdout, _ = client.exec_command(
        "sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % REMOTE_PY, timeout=60)
    dbout = stdout.read().decode("utf-8", "replace")
    node_out = ""
    for name, cmd in LOCAL_GREP:
        _, so, se = client.exec_command(cmd, timeout=30)
        node_out += "=== %s ===\n%s\n%s\n" % (
            name, so.read().decode("utf-8", "replace")[:1500],
            se.read().decode("utf-8", "replace")[:300])
    client.close()
    m = dbout.find("DIAG4-JSON:")
    data = json.loads(dbout[m + 11:]) if m >= 0 else []
    print(node_out)
    for s in data:
        print("STEP#%s ord%s: %s" % (s["id"], s["ord"], s["obj"]))
        print("   criteria:", s["criteria"][:600].replace("\n", " "))
        print()
    import os
    dest = "/home/z/my-project/download/aes-remediation/P3-STALE-DIAG/diag4_steps103_110.json"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump({"steps": data, "host": node_out}, fh, ensure_ascii=False, indent=1)
    print("FULL JSON →", dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
