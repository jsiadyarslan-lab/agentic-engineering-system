#!/usr/bin/env python3
"""RLR-004-b — REAL provision run (STRICT_ISOLATED) + sandbox barrier check for project 1 (OSINT)."""
import json
import time

import paramiko

HOST, USER, SSHKEY = "92.5.14.150", "opc", "/tmp/oracle_key"


def run(c, cmd, timeout=120):
    _, o, e = c.exec_command(cmd, timeout=timeout)
    o.channel.recv_exit_status()
    return o.read().decode("utf-8", "replace"), e.read().decode("utf-8", "replace")


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=SSHKEY, timeout=25,
              look_for_keys=False, allow_agent=False)
    try:
        # 1) current canonical state BEFORE
        o, _ = run(c,
            "curl -s -m 20 http://127.0.0.1:8010/api/environment/provision/heartbeat")
        print("### provision heartbeat (قبل):")
        print(o.strip()[:800])

        # 2) REAL provision
        print("\n### POST /api/environment/provision (STRICT_ISOLATED) — الدورة الحقيقية")
        o, e = run(c,
            "curl -s -m 240 -X POST http://127.0.0.1:8010/api/environment/provision "
            "-H 'Content-Type: application/json' -d '{\"policy\":\"STRICT_ISOLATED\"}'",
            timeout=280)
        body = o.strip()
        try:
            d = json.loads(body)
            print("verdict:", d.get("verdict"), "| code:", d.get("code"))
            print("state:", d.get("state"), "| reason:", str(d.get("reason", ""))[:200])
            steps = d.get("steps") or []
            print("steps (%d):" % len(steps))
            for s in steps:
                if isinstance(s, dict):
                    print("  - %-16s %-6s %s" % (s.get("name"), s.get("ok"),
                                                 str(s.get("detail", ""))[:120]))
            env = d.get("environment") or {}
            if env:
                print("environment:", json.dumps(
                    {k: env.get(k) for k in ("id", "name", "backend", "status",
                                             "sandboxed")}, ensure_ascii=False))
        except Exception as ex:
            print("raw (%d chars): %s" % (len(body), body[:2000]))
            print("parse:", ex, e[:200])

        # 3) execution environments now
        o, _ = run(c, "curl -s -m 20 http://127.0.0.1:8010/api/execution/environments")
        try:
            d = json.loads(o)
            print("\n### execution environments بعد التجهيز:")
            for env in d.get("environments", []):
                print("  - id=%s %-14s backend=%-8s status=%-7s sandboxed=%s"
                      % (env.get("id"), env.get("name"), env.get("backend"),
                         env.get("status"), env.get("sandboxed")))
        except Exception as ex:
            print("env parse:", ex, o[:500])

        # 4) project 1 live state — the sandbox barrier
        o, _ = run(c, "curl -s -m 30 http://127.0.0.1:8010/api/projects/1")
        try:
            d = json.loads(o)
            job = d.get("job") or {}
            eg = d.get("execution_gate") or {}
            print("\n### مشروع OSINT (#1) الآن:")
            print("project status:", d.get("status"),
                  "| completion:", d.get("completion_state"))
            print("job:", json.dumps({k: job.get(k) for k in
                  ("status", "waiting_kind", "current_step_id", "last_error")},
                  ensure_ascii=False))
            print("execution_gate:", json.dumps(
                {k: eg.get(k) for k in ("state", "reason", "sandbox",
                                        "barriers")}, ensure_ascii=False)[:600])
            envb = d.get("environment") or {}
            print("environment block:", json.dumps(
                {k: envb.get(k) for k in ("state", "reason")},
                ensure_ascii=False)[:400])
        except Exception as ex:
            print("project parse:", ex, o[:600])

        # 5) recheck endpoint (the button the UI offers)
        o, _ = run(c,
            "curl -s -m 120 -X POST http://127.0.0.1:8010/api/projects/1/environment/recheck "
            "-H 'Content-Type: application/json' -d '{}' 2>&1 | head -c 800")
        print("\n### project recheck:", o.strip()[:800])
    finally:
        c.close()


if __name__ == "__main__":
    main()
