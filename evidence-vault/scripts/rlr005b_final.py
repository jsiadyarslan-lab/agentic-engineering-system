#!/usr/bin/env python3
"""RLR-005 (final) — refresh web_fetch probe, readiness snapshot, clock regression."""
import json

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
        sftp = c.open_sftp()
        with sftp.file("/tmp/rlr005b_wf.json", "w") as f:
            f.write('{"capability_id":"web_fetch"}')
        with sftp.file("/tmp/rlr005b_ws.json", "w") as f:
            f.write('{"capability_id":"web_search"}')
        sftp.close()

        o, _ = run(c, "curl -s -m 60 -X POST http://127.0.0.1:8010/api/environment/probe "
                      "-H 'Content-Type: application/json' --data-binary @/tmp/rlr005b_wf.json")
        try:
            d = json.loads(o)
            print("web_fetch probe:", d.get("readiness_status"),
                  "| reason:", str(d.get("failure_reason", ""))[:100])
        except Exception as ex:
            print("web_fetch parse:", ex, o[:300])

        o, _ = run(c, "curl -s -m 90 -X POST http://127.0.0.1:8010/api/environment/probe "
                      "-H 'Content-Type: application/json' --data-binary @/tmp/rlr005b_ws.json")
        try:
            d = json.loads(o)
            print("web_search probe:", d.get("readiness_status"))
            det = (d.get("details") or {}).get("per_provider") or []
            for p in det:
                print("  - %-12s %-11s %s" % (p.get("name"), p.get("status"),
                                              str(p.get("reason", ""))[:100]))
        except Exception as ex:
            print("web_search parse:", ex, o[:300])

        print()
        o, _ = run(c, "curl -s -m 30 http://127.0.0.1:8010/api/environment/readiness")
        try:
            d = json.loads(o)
            caps = d.get("capabilities", d) or []
            ready = []
            if isinstance(caps, list):
                for cap in caps:
                    cid = cap.get("capability_id")
                    st = cap.get("readiness_status")
                    if st == "READY":
                        ready.append(cid)
                    elif cid in ("llm", "web_search", "web_fetch", "model_inference",
                                 "browser", "sandbox", "network_http"):
                        print("  notable:", cid, "->", st)
            print("READY %d/%d" % (len(ready), len(caps) if isinstance(caps, list) else "?"))
            not_ready = [x.get("capability_id") for x in caps
                         if isinstance(x, dict) and x.get("readiness_status") != "READY"] \
                if isinstance(caps, list) else []
            print("not-ready:", not_ready)
        except Exception as ex:
            print("readiness parse:", ex, o[:300])

        # quick clock regression (service restarted after 0f2d9c6)
        payload = json.dumps({"message": "ما هو اليوم؟", "conversation_id": None,
                              "web": "on"}, ensure_ascii=False)
        sftp = c.open_sftp()
        with sftp.file("/tmp/rlr005b_clock.json", "w") as f:
            f.write(payload)
        sftp.close()
        o, _ = run(c, "curl -N -s -m 60 -X POST http://127.0.0.1:8010/api/chat/stream "
                      "-H 'Content-Type: application/json' "
                      "--data-binary @/tmp/rlr005b_clock.json", timeout=90)
        deltas, clock_hit = [], False
        for line in o.splitlines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            if ev.get("kind") == "message_delta":
                d = ev.get("data") if isinstance(ev.get("data"), dict) else {}
                t = d.get("delta") if isinstance(d.get("delta"), str) else ev.get("delta")
                if isinstance(t, str):
                    deltas.append(t)
            if ev.get("status") == "clock_context":
                clock_hit = True
        reply = "".join(deltas)
        print()
        print("clock regression: routed=%s | reply: %s" % (clock_hit, reply[:120]))
    finally:
        c.close()


if __name__ == "__main__":
    main()
