#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3-STATE — قراءة فقط: الحالة الحية للمصنع والمشروع #3 (بوابات/خطوات/تنفيذات/قدرات)."""
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
out["project3"] = q("SELECT id,name,status,current_step_id,completion_state,substr(COALESCE(last_error,''),1,180) as err,updated_at FROM projects WHERE id=3")
out["steps"] = q("SELECT id,ordinal,status,attempts,substr(COALESCE(objective,''),1,90) as obj,substr(COALESCE(last_error,''),1,150) as err,completed_at FROM steps WHERE phase_id IN (SELECT id FROM phases WHERE project_id=3) ORDER BY id DESC LIMIT 16")
out["gates"] = q("SELECT id,kind,status,substr(COALESCE(reason,''),1,110) as reason,resolved_at,created_at FROM owner_gates WHERE project_id=3 ORDER BY id DESC LIMIT 8")
out["execs"] = q("SELECT id,step_id,attempt,status,substr(COALESCE(error,''),1,130) as err,started_at,finished_at FROM executions WHERE step_id IN (SELECT id FROM steps WHERE phase_id IN (SELECT id FROM phases WHERE project_id=3)) ORDER BY id DESC LIMIT 14")
out["jobs"] = q("SELECT id,status,waiting_kind,substr(COALESCE(waiting_detail,''),1,90) as wdetail,current_step_id,retries,substr(COALESCE(last_error,''),1,130) as err,heartbeat_at,updated_at FROM engineering_jobs WHERE project_id=3 ORDER BY id DESC LIMIT 3")
out["ws_inv"] = q("SELECT id,tool,status,failure_class,substr(COALESCE(failure_reason,''),1,110) as err,created_at FROM tool_invocations WHERE tool LIKE '%search%' OR tool LIKE '%fetch%' ORDER BY id DESC LIMIT 10")
print(json.dumps(out, ensure_ascii=False, indent=1))
'''

CMDS = [
    ("health", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health"),
    ("services", "systemctl is-active agentic nginx searxng 2>/dev/null; systemctl list-units --type=service --state=running | grep -E 'agentic|searx|nginx' | head -6"),
    ("git_head", "cd /opt/agentic-engineering-system && sudo -n git rev-parse HEAD && sudo -n git status --short | head -5"),
    ("node", "/usr/local/bin/node --version 2>&1; /usr/local/bin/npm --version 2>&1; which node npm 2>&1"),
    ("db_state", "sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % DBPY),
    # readiness summary
    ("readiness_summary", "curl -s http://127.0.0.1:8010/api/environment/readiness | python3 -c \"import sys,json; d=json.load(sys.stdin); caps=d.get('capabilities',[]); print(json.dumps([{ 'id':c.get('capability_id'), 'status':c.get('readiness_status'), 'fail':c.get('failure_class','') } for c in caps], ensure_ascii=False))\""),
]


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY, timeout=25,
                   look_for_keys=False, allow_agent=False)
    for name, cmd in CMDS:
        _, so, se = client.exec_command(cmd, timeout=40)
        print("=== %s ===" % name)
        print(so.read().decode("utf-8", "replace")[:2600])
        err = se.read().decode("utf-8", "replace")[:200]
        if err.strip():
            print("[stderr]", err)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
