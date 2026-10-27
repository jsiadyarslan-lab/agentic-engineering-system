#!/usr/bin/env python3
# W1-T05 step 3: owner's OCI egress rule is NOW LIVE (curl 200s + TCP rc=0).
# (1) documents egress evidence, (2) R6 health gate, (3) POST probe network_http
# (the designed step-3 action), (4) readiness snapshot before/after.
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=40):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    return so.read().decode(errors="replace").strip(), se.read().decode(errors="replace").strip()

WATCH = ("network_http", "network_https", "network_dns", "web_search", "web_fetch")

def readiness_snapshot():
    raw, _ = run("curl -s --max-time 8 http://127.0.0.1:8010/api/environment/readiness")
    try:
        d = json.loads(raw)
    except Exception:
        return {"raw_prefix": raw[:300]}
    caps = {}
    for c in d.get("capabilities", []):
        if c.get("capability_id") in WATCH:
            caps[c["capability_id"]] = {
                "stored": c.get("stored_status"), "readiness": c.get("readiness_status"),
                "last_success": c.get("last_success_at"),
                "failure": (c.get("failure_reason") or "")[:90]}
    return caps

ev = {"_meta": {"mode": "steps 2-3 verification after owner OCI egress rule",
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

# (1) egress evidence
for name, cmd in [
    ("http_example",  "curl -s -o /dev/null -w '%{http_code} rc=%{exitcode} t=%{time_total}' --max-time 8 http://example.com"),
    ("http_httpbin",  "curl -s -o /dev/null -w '%{http_code} rc=%{exitcode} t=%{time_total}' --max-time 8 http://httpbin.org/get"),
    ("http_iana",     "curl -s -o /dev/null -w '%{http_code} rc=%{exitcode} t=%{time_total}' --max-time 8 http://www.iana.org"),
    ("tcp80_raw",     "timeout 5 bash -c 'echo > /dev/tcp/example.com/80' 2>&1; echo rc=$?"),
    ("https_google",  "curl -s -o /dev/null -w '%{http_code} rc=%{exitcode} t=%{time_total}' --max-time 8 https://www.google.com"),
    ("https_iana",    "curl -s -o /dev/null -w '%{http_code} rc=%{exitcode} t=%{time_total}' --max-time 8 https://www.iana.org"),
    ("dns_check",     "getent ahostsv4 example.com | head -2"),
]:
    o, _ = run(cmd)
    ev[name] = o
    print(f"{name}: {o}")

# (2) R6 pre-gate
h, _ = run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
ev["health_pre_probe"] = h
print("health_pre:", h)
assert h == "200", "R6 pre-gate failed"

# (3) readiness BEFORE
ev["readiness_before"] = readiness_snapshot()
print("--- readiness BEFORE ---")
for k, v in ev["readiness_before"].items():
    print(f"  {k}: stored={v['stored']} readiness={v['readiness']} {v['failure']}")

# (4) POST probe network_http (the designed step-3 action)
o, e = run("curl -s --max-time 30 -X POST http://127.0.0.1:8010/api/environment/probe "
           "-H 'Content-Type: application/json' -d '{\"capability_id\": \"network_http\"}'")
ev["probe_network_http"] = o[:800]
print("--- probe network_http ---\n" + o[:800])

# (5) readiness AFTER
time.sleep(1)
ev["readiness_after"] = readiness_snapshot()
print("--- readiness AFTER ---")
for k, v in ev["readiness_after"].items():
    print(f"  {k}: stored={v['stored']} readiness={v['readiness']} last_success={v['last_success']} {v['failure']}")

# (6) R6 post-gate
h, _ = run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
ev["health_post_probe"] = h
print("health_post:", h)

with open("/home/z/my-project/download/aes-remediation/W1-T05/20261028-steps23.json", "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
ssh.close()
print("\nSAVED: download/aes-remediation/W1-T05/20261028-steps23.json")
