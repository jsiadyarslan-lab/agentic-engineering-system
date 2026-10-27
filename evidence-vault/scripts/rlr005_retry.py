#!/usr/bin/env python3
"""RLR-005-d — probe web_search now + retry real web E2E once."""
import json
import time

import paramiko

HOST, USER, SSHKEY = "92.5.14.150", "opc", "/tmp/oracle_key"


def run(c, cmd, timeout=120):
    _, o, e = c.exec_command(cmd, timeout=timeout)
    o.channel.recv_exit_status()
    return o.read().decode("utf-8", "replace"), e.read().decode(
        "utf-8", "replace")


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=SSHKEY, timeout=25,
              look_for_keys=False, allow_agent=False)
    try:
        sftp = c.open_sftp()
        with sftp.file("/tmp/rlr005_probe_ws.json", "w") as f:
            f.write('{"capability_id":"web_search"}')
        sftp.close()
        o, _ = run(c,
            "curl -s -m 90 -X POST http://127.0.0.1:8010/api/environment/probe "
            "-H 'Content-Type: application/json' "
            "--data-binary @/tmp/rlr005_probe_ws.json")
        try:
            d = json.loads(o)
            print("web_search probe:", d.get("readiness_status"),
                  "| reason:", str(d.get("failure_reason", ""))[:150])
            det = (d.get("details") or {}).get("per_provider") or []
            for p in det:
                print("  - %-12s %-11s %s" % (p.get("name"), p.get("status"),
                                              str(p.get("reason", ""))[:110]))
        except Exception as ex:
            print("parse:", ex, o[:600])

        # retry the web E2E — query biased to Wikipedia vocabulary
        payload = json.dumps({
            "message": "ابحث لي في الويب عن برج إيفل في باريس واذكر ارتفاعه",
            "conversation_id": None, "web": "on",
        }, ensure_ascii=False)
        sftp = c.open_sftp()
        with sftp.file("/tmp/rlr005_payload2.json", "w") as f:
            f.write(payload)
        sftp.close()
        print("\n[RETRY E2E] web question once more…")
        o, e = run(c,
            "curl -N -s -m 230 -X POST http://127.0.0.1:8010/api/chat/stream "
            "-H 'Content-Type: application/json' "
            "--data-binary @/tmp/rlr005_payload2.json", timeout=260)
        body = o + e
        deltas, research, web_used = [], [], None
        for line in body.splitlines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            k = ev.get("kind", "")
            if k == "message_delta":
                d = ev.get("data") if isinstance(ev.get("data"), dict) else {}
                t = d.get("delta") if isinstance(d.get("delta"), str) else ev.get("delta")
                if isinstance(t, str):
                    deltas.append(t)
            elif k.startswith("research."):
                det = ev.get("details", {}) or {}
                extra = ""
                if k == "research.results":
                    extra = " [%s نتيجة — %s]" % (det.get("count"),
                                                   det.get("provider"))
                if k == "research.unavailable":
                    extra = " [سبب: %s]" % str(det.get("error", ""))[:180]
                research.append(k + extra)
            elif k == "message_completed":
                d = ev.get("data") if isinstance(ev.get("data"), dict) else {}
                web_used = d.get("web_used")
        reply = "".join(deltas)
        print("مسار الويب:")
        for r in research:
            print("   -", r[:220])
        print("web_used:", web_used)
        print("\n>>> الرد (أول 450 حرف):")
        print(reply[:450])
    finally:
        c.close()


if __name__ == "__main__":
    main()
