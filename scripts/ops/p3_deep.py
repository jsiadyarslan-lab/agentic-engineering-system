#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3-DEEP — قراءة فقط: تفاصيل عميقة للمشروع #3 (بوابات/خطة/وظيفة/قدرات معطلة)."""
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
out["gates_p3"] = q("SELECT id,kind,status,details,reason,created_at,resolved_at FROM owner_gates WHERE project_id=3 ORDER BY id DESC LIMIT 6")
out["plans_p3"] = q("SELECT id,version,status,substr(COALESCE(revision_reason,''),1,200) as rev_reason,approved_by_owner,approved_at,created_at FROM plans WHERE project_id=3 ORDER BY id DESC LIMIT 5")
out["job_p3"] = q("SELECT id,status,waiting_kind,waiting_detail,current_step_id,current_execution_id,retries,attempt,last_error,note,heartbeat_at,updated_at FROM engineering_jobs WHERE project_id=3 ORDER BY id DESC LIMIT 2")
out["execs_recent"] = q("SELECT id,step_id,attempt,status,agent_role,substr(COALESCE(error,''),1,200) as err,started_at,finished_at FROM executions WHERE step_id IN (SELECT id FROM steps WHERE phase_id IN (SELECT id FROM phases WHERE project_id=3)) ORDER BY id DESC LIMIT 10")
out["cap_pm"] = q("SELECT capability_id,readiness_status,failure_class,failure_stage,failure_reason,substr(COALESCE(details,''),1,700) as details,last_probe_at,last_success_at,last_failure_at FROM capability_records WHERE capability_id IN ('package_management','testing','build','shell')")
out["phases_p3"] = q("SELECT id,ordinal,title,status,current_step_id,review_status FROM phases WHERE project_id=3 ORDER BY ordinal")
out["steps_all"] = q("SELECT s.id,s.ordinal,s.phase_id,p.ordinal as phase_ord,s.status,s.attempts,substr(COALESCE(s.objective,''),1,70) as obj FROM steps s JOIN phases p ON s.phase_id=p.id WHERE p.project_id=3 ORDER BY p.ordinal, s.ordinal")
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
    with open("/home/z/my-project/tool-results/p3_deep.json", "w") as f:
        f.write(raw)
    try:
        d = json.loads(raw)
        for k, v in d.items():
            print("\\n=== %s (%s) ===" % (k, len(v)))
            print(json.dumps(v, ensure_ascii=False, indent=1)[:3500])
    except Exception as e:
        print("PARSE FAIL:", e)
        print(raw[:3000])
    if err.strip():
        print("[stderr]", err)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
