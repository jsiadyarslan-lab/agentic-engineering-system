# -*- coding: utf-8 -*-
"""P3-STALE-DIAG-3 — سجل الخطوة 102 الكامل + معايير القبول + التنفيذات + الأحداث."""
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

def dump(q, limit=900):
    try:
        cols = [d[0] for d in con.execute(q).description]
        return [dict(zip(cols, [str(v)[:limit] if v is not None else None for v in r])) for r in con.execute(q).fetchall()]
    except Exception as e:
        return [{"error": str(e)}]

out = {
 "step102": dump("SELECT id,ordinal,objective,expected_output,acceptance_criteria,dependencies,status,attempts,current_execution_id,evidence_id,last_error,updated_at FROM steps WHERE id=102"),
 "plan_steps": dump("SELECT s.id,s.ordinal,s.status,s.attempts,substr(s.objective,1,90) obj FROM steps s JOIN phases p ON s.phase_id=p.id WHERE p.project_id=3 ORDER BY s.id", 200),
 "execs102": dump("SELECT id,attempt,status,agent_role,provider,model,workspace,error,command_type,started_at,finished_at FROM executions WHERE step_id=102 ORDER BY id", 400),
 "evid102": dump("SELECT * FROM evidence_records WHERE step_id=102 ORDER BY id DESC LIMIT 3", 400),
 "events15": dump("SELECT * FROM events ORDER BY id DESC LIMIT 15", 350),
 "audits102": dump("SELECT * FROM audit_records WHERE execution_id IN (SELECT id FROM executions WHERE step_id=102) ORDER BY id DESC LIMIT 4", 600),
}
print("DIAG3-JSON:" + json.dumps(out, ensure_ascii=False, default=str))
'''


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY, timeout=25)
    _, stdout, _ = client.exec_command(
        "sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % REMOTE_PY, timeout=90)
    dbout = stdout.read().decode("utf-8", "replace")
    client.close()
    m = dbout.find("DIAG3-JSON:")
    data = json.loads(dbout[m + 11:]) if m >= 0 else {"error": dbout[-2000:]}

    import os
    dest = "/home/z/my-project/download/aes-remediation/P3-STALE-DIAG/diag3_step102_full.json"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, default=str)

    for s in data.get("step102", []):
        print("== STEP#102 ord=%s status=%s attempts=%s" % (s.get("ordinal"), s.get("status"), s.get("attempts")))
        print("   objective:", (s.get("objective") or "")[:400])
        print("   expected_output:", (s.get("expected_output") or "")[:400])
        print("   acceptance:", (s.get("acceptance_criteria") or "")[:700])
        print("   last_error:", (s.get("last_error") or "")[:200])
    print("\n== PLAN STEPS (project 3):")
    for s in data.get("plan_steps", []):
        print("  #%s ord%s %-12s attempts=%s %s" % (s.get("id"), s.get("ordinal"), s.get("status"), s.get("attempts"), s.get("obj")))
    print("\n== EXECUTIONS (step 102):")
    for e in data.get("execs102", []):
        print("  #%s att=%s %-10s role=%s ws=%s err=%.150s" % (
            e.get("id"), e.get("attempt"), e.get("status"), e.get("agent_role"),
            (e.get("workspace") or "")[:60], (e.get("error") or "").replace("\n", " ")))
    print("\n== EVIDENCE (step 102):")
    for e in data.get("evid102", []):
        print("  ", json.dumps(e, ensure_ascii=False)[:400])
    print("\n== AUDITS (step 102 executions):")
    for a in data.get("audits102", []):
        print("  ", json.dumps(a, ensure_ascii=False)[:600])
    print("\n== EVENTS (last 15, kind only):")
    for ev in data.get("events15", []):
        keys = list(ev.keys())
        kind = ev.get("kind") or ev.get("event_type") or ""
        print("  #%s %s %s" % (ev.get("id"), kind, str({k: v for k, v in ev.items() if k in ("created_at", "project_id", "step_id")})[:120]))
    print("\nFULL JSON →", dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
