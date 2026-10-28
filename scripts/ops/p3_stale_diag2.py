# -*- coding: utf-8 -*-
"""P3-STALE-DIAG-2 — تفاصيل الخطوة 102: لماذا لم ينتج package.json؟ + سجل البوابة والوقت."""
import json
import sys

import paramiko

HOST = "92.5.14.150"
USER = "opc"
KEY = "/tmp/oracle_key"

CMD_LIST = [
    ("now_utc", "date -u '+%Y-%m-%d %H:%M:%S UTC'"),
    ("stderr_542d", "sudo -n cat /opt/agentic-engineering-system/runtime/projects/3/steps/102/stderr-tool-542d3c7a.txt 2>&1 | head -60"),
    ("stdout_others", "for f in b9dd8cf3 e2343873 f077fa62; do echo \"--- $f\"; sudo -n cat /opt/agentic-engineering-system/runtime/projects/3/steps/102/stdout-tool-$f.txt 2>&1; done"),
    ("t1_report", "sudo -n cat /opt/agentic-engineering-system/runtime/projects/3/steps/102/T1-report.md 2>&1 | head -40"),
    ("sources", "sudo -n cat /opt/agentic-engineering-system/runtime/projects/3/steps/102/sources.json 2>&1"),
    ("evidence_json_head", "sudo -n head -c 3000 /opt/agentic-engineering-system/runtime/projects/3/steps/102/evidence.json 2>&1"),
    ("step102_db", None),
    ("tools_263_264_db", None),
    ("gate30_db", None),
    ("events_run_db", None),
]

REMOTE_PY = r'''
import sqlite3, json
con = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row

def dump(q, limit=400):
    try:
        cols = [d[0] for d in con.execute(q).description]
        return [dict(zip(cols, [str(v)[:limit] if v is not None else None for v in r])) for r in con.execute(q).fetchall()]
    except Exception as e:
        return [{"error": str(e)}]

out = {
 "step_102_105": dump("SELECT id,title,status,success_criteria,attempt_count,evidence_count,review_status,verifier_status,updated_at FROM steps WHERE id BETWEEN 102 AND 105"),
 "tools_263_266": dump("SELECT id,tool,status,transport_status,result_status,failure_class,failure_stage,failure_reason,query,result_count,analyzable,error,duration_ms,execution_site,record_json,created_at FROM tool_invocations WHERE id IN (263,264,265,266)"),
 "gate_30": dump("SELECT * FROM owner_gates WHERE id=30"),
 "job_3": dump("SELECT id,status,waiting_kind,waiting_detail,checkpoints,last_error,note,tick_count,retries,attempt,updated_at FROM engineering_jobs WHERE id=3"),
 "events_recent": dump("SELECT id,kind,payload_json,created_at FROM events ORDER BY id DESC LIMIT 18", 500),
 "executions_step102": dump("SELECT id,step_id,status,termination,exit_code,substr(stdout,1,300) stdout_head,substr(stderr,1,600) stderr_head,environment_id,backend,created_at FROM executions WHERE step_id=102 ORDER BY id DESC LIMIT 5"),
}
print("DIAG2-JSON:" + json.dumps(out, ensure_ascii=False, default=str))
'''


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY, timeout=25)
    collected = {}
    for name, cmd in CMD_LIST:
        if cmd is None:
            continue
        try:
            _, stdout, stderr = client.exec_command(cmd, timeout=60)
            collected[name] = (stdout.read().decode("utf-8", "replace")[:6000],
                               stderr.read().decode("utf-8", "replace")[:500])
        except Exception as exc:  # noqa: BLE001
            collected[name] = ("", "SSH-ERROR: %s" % exc)
    try:
        _, stdout, _ = client.exec_command(
            "sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % REMOTE_PY, timeout=90)
        dbout = stdout.read().decode("utf-8", "replace")
        m = dbout.find("DIAG2-JSON:")
        collected["db2"] = json.loads(dbout[m + 11:]) if m >= 0 else {"error": dbout[-3000:]}
    except Exception as exc:  # noqa: BLE001
        collected["db2"] = {"error": "SSH-ERROR: %s" % exc}
    client.close()

    import os
    dest = "/home/z/my-project/download/aes-remediation/P3-STALE-DIAG/diag2_step102.json"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump({k: (v if isinstance(v, (dict, list)) else {"out": v[0], "err": v[1]})
                   for k, v in collected.items()}, fh, ensure_ascii=False, indent=1, default=str)

    print("== NOW(UTC):", collected["now_utc"][0].strip())
    print("\n== STDERR-542d (first 40 lines):")
    print("\n".join(collected["stderr_542d"][0].splitlines()[:40]))
    print("\n== STDOUT others:")
    print(collected["stdout_others"][0][:800])
    print("\n== T1-REPORT (first 25 lines):")
    print("\n".join(collected["t1_report"][0].splitlines()[:25]))
    db2 = collected.get("db2", {})
    if isinstance(db2, dict) and "error" not in db2:
        print("\n== STEPS 102-105:")
        for s in db2.get("step_102_105", []):
            print("  #%s %s | status=%s | attempts=%s evid=%s review=%s verifier=%s" % (
                s.get("id"), (s.get("title") or "")[:50], s.get("status"),
                s.get("attempt_count"), s.get("evidence_count"),
                s.get("review_status"), s.get("verifier_status")))
        print("\n== TOOLS 263-266:")
        for t in db2.get("tools_263_266", []):
            print("  #%s %s %s cls=%s stage=%s err=%.200s" % (
                t.get("id"), t.get("tool"), t.get("status"),
                t.get("failure_class"), t.get("failure_stage"),
                (t.get("error") or "").replace("\n", " ")))
        print("\n== GATE 30:")
        for g in db2.get("gate_30", []):
            print("  ", json.dumps(g, ensure_ascii=False)[:700])
        print("\n== JOB 3 (waiting/checkpoints/error):")
        for j in db2.get("job_3", []):
            print("  waiting:", (j.get("waiting_detail") or "")[:300])
            print("  last_error:", (j.get("last_error") or "")[:300])
            print("  note:", (j.get("note") or "")[:200])
        print("\n== EXECUTIONS for step 102:")
        for e in db2.get("executions_step102", []):
            print("  #%s status=%s term=%s exit=%s env=%s/%s created=%s" % (
                e.get("id"), e.get("status"), e.get("termination"),
                e.get("exit_code"), e.get("environment_id"), e.get("backend"),
                (e.get("created_at") or "")[:19]))
            print("     stderr_head:", (e.get("stderr_head") or "")[:300].replace("\n", " ⏎ "))
        print("\n== EVENTS (last 12):")
        for ev in db2.get("events_recent", []):
            print("  #%s %s %s" % (ev.get("id"), (ev.get("created_at") or "")[:19],
                                   (ev.get("kind") or "")))
    else:
        print("== DB2 ERROR:", str(db2.get("error"))[:600])
    print("\nFULL JSON →", dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
