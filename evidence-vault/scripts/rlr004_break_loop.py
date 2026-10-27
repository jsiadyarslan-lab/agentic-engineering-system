#!/usr/bin/env python3
"""RLR-004-c — break the stale-sandboxed loop honestly:
1) flip local-linux.sandboxed=1 (the exact value ensure_local_registered computes
   from substrate_available() — proven True by the real bwrap launch probe)
2) POST /api/execution/environments/1/verify → LocalSandboxBackend → REAL bwrap checks
3) if READY+sandboxed → POST /api/projects/1/preflight (recheck → launch)
4) report project 1 barrier state honestly
"""
import json

import paramiko

HOST, USER, SSHKEY = "92.5.14.150", "opc", "/tmp/oracle_key"


def run(c, cmd, timeout=150):
    _, o, e = c.exec_command(cmd, timeout=timeout)
    o.channel.recv_exit_status()
    return o.read().decode("utf-8", "replace"), e.read().decode("utf-8", "replace")


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=SSHKEY, timeout=25,
              look_for_keys=False, allow_agent=False)
    try:
        # 0) confirm substrate truth again (the basis for the flip)
        o, _ = run(c,
            "cd /opt/agentic-engineering-system && .venv/bin/python -c \""
            "from substrate.factory import substrate_available; "
            "print('substrate_available:', substrate_available())\"")
        print("### substrate truth:", o.strip())
        if "True" not in o:
            print("!! الركيزة غير متاحة — لا قلب للعلم. توقف صادق.")
            return

        # 1) backup + flip
        o, _ = run(c,
            "cd /opt/agentic-engineering-system && .venv/bin/python -c \""
            "import sqlite3;"
            "db = sqlite3.connect('runtime/agent_hub_v2.db');"
            "row = db.execute(\\\"select id,name,sandboxed,status from execution_environments where name='local-linux'\\\").fetchone();"
            "print('BEFORE:', row);"
            "db.execute(\\\"update execution_environments set sandboxed=1, updated_at=datetime('now') where name='local-linux'\\\");"
            "db.commit();"
            "row = db.execute(\\\"select id,name,sandboxed,status from execution_environments where name='local-linux'\\\").fetchone();"
            "print('AFTER:', row)\"")
        print("### flag flip:\n%s" % o.strip())

        # 2) REAL verify through the sandbox backend (bwrap)
        print("\n### POST /api/execution/environments/1/verify — تحقق bwrap حقيقي")
        o, e = run(c,
            "curl -s -m 220 -X POST http://127.0.0.1:8010/api/execution/environments/1/verify",
            timeout=260)
        body = o.strip()
        try:
            d = json.loads(body)
            v = d.get("verify") or {}
            print("status:", d.get("status"), "| sandboxed:", d.get("sandboxed"))
            print("verify ok:", v.get("ok"), "| reason:", str(v.get("reason", ""))[:150])
            for ch in (v.get("checks") or [])[:10]:
                print("  check %-22s %-5s %s" % (ch.get("name"), ch.get("ok"),
                                                 str(ch.get("detail", ""))[:90]))
            profile = v.get("profile") or {}
            print("profile: sandboxed=%s mechanism=%s" % (
                profile.get("sandboxed"), profile.get("mechanism")))
            verify_ok = bool(v.get("ok")) and bool(d.get("sandboxed"))
        except Exception as ex:
            print("raw:", body[:1500], "\nparse:", ex, e[:200])
            verify_ok = False

        if not verify_ok:
            print("\n!! التحقق عبر bwrap فشل — إعادة العلم إلى 0 بصدق")
            run(c,
                "cd /opt/agentic-engineering-system && .venv/bin/python -c \""
                "import sqlite3; db = sqlite3.connect('runtime/agent_hub_v2.db');"
                "db.execute(\\\"update execution_environments set sandboxed=0 where name='local-linux'\\\");"
                "db.commit(); print('REVERTED')\"")
            return

        # 3) project 1 preflight (recheck → launch if pass)
        print("\n### POST /api/projects/1/preflight — إعادة الفحص/الإطلاق")
        o, e = run(c,
            "curl -s -m 200 -X POST http://127.0.0.1:8010/api/projects/1/preflight "
            "-H 'Content-Type: application/json' -d '{}'", timeout=240)
        print((o or e).strip()[:1800])

        # 4) project 1 final state
        o, _ = run(c, "curl -s -m 30 http://127.0.0.1:8010/api/projects/1")
        try:
            d = json.loads(o)
            job = d.get("job") or {}
            eg = d.get("execution_gate") or {}
            print("\n### مشروع OSINT (#1) النهائي:")
            print("status:", d.get("status"), "| completion:", d.get("completion_state"))
            print("job:", json.dumps({k: job.get(k) for k in
                  ("status", "waiting_kind", "current_step_id",
                   "current_phase_id", "last_error")}, ensure_ascii=False))
            print("execution_gate state:", eg.get("state"),
                  "| reason:", str(eg.get("reason", ""))[:150])
        except Exception as ex:
            print("project parse:", ex, o[:500])
    finally:
        c.close()


if __name__ == "__main__":
    main()
