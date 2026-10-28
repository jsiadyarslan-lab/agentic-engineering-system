#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3-FAILDIAG — قراءة فقط: تشريح فشل الخطوة 111 (استدعاءات الأدوات + أحداث الدورة)."""
import json
import sys

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

DBPY = '''
import sqlite3, json
con = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
out = {}
def q(sql):
    try:
        return [dict(r) for r in con.execute(sql).fetchall()]
    except Exception as e:
        return [{"error": str(e)[:200]}]
# tool invocations during step 111 executions (ids 33,34,35)
out["ti_111"] = q("SELECT id,cycle_id,tool,status,transport_status,result_status,failure_class,failure_stage,substr(COALESCE(failure_reason,''),1,250) as freason,substr(COALESCE(query,''),1,80) as q,substr(COALESCE(error,''),1,250) as err,retryable,duration_ms,created_at FROM tool_invocations WHERE created_at >= '2026-10-28 16:34:00' ORDER BY id ASC LIMIT 30")
# events for the last execution cycle
out["events_35"] = q("SELECT id,cycle_id,seq,role,kind,state,substr(COALESCE(payload,''),1,180) as payload,duration_ms,created_at FROM events WHERE created_at >= '2026-10-28 16:51:00' AND created_at <= '2026-10-28 16:58:00' ORDER BY id ASC LIMIT 40")
# research providers state
out["research_providers"] = q("SELECT id,kind,name,enabled,last_probe_status,substr(COALESCE(failure_reason,''),1,150) as freason,last_probe_at FROM research_providers ORDER BY id")
# plan v5 content summary
out["plan_v5"] = q("SELECT id,version,objective,substr(COALESCE(phases,''),1,900) as phases FROM plans WHERE id=16")
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
    with open("/home/z/my-project/tool-results/p3_faildiag.json", "w") as f:
        f.write(raw)
    try:
        d = json.loads(raw)
        for k, v in d.items():
            print("\\n=== %s (%s) ===" % (k, len(v)))
            print(json.dumps(v, ensure_ascii=False, indent=1)[:6000])
    except Exception as e:
        print("PARSE FAIL:", e)
        print(raw[:3000])
    if err.strip():
        print("[stderr]", err)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
