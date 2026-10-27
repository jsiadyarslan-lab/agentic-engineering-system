#!/usr/bin/env python3
# READ-ONLY diagnostic: (1) did owner's OCI egress rule open port 80?
# (2) why is PLAN_REVISION_APPROVAL still blocking despite ~50 approvals?
import json, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

CMDS = [
    # 1) Egress port 80 — the exact same probes as W1-T05 evidence
    ("http80_example",   "curl -s -o /dev/null -w '%{http_code} rc=%{exitcode} t=%{time_total}' --max-time 8 http://example.com"),
    ("http80_neverssl",  "curl -s -o /dev/null -w '%{http_code} rc=%{exitcode} t=%{time_total}' --max-time 8 http://neverssl.com"),
    ("http80_httpbin",   "curl -s -o /dev/null -w '%{http_code} rc=%{exitcode} t=%{time_total}' --max-time 8 http://httpbin.org/get"),
    ("tcp80_raw",        "timeout 5 bash -c 'echo > /dev/tcp/example.com/80' 2>&1; echo \"rc=$?\""),
    ("https443_ctrl",    "curl -s -o /dev/null -w '%{http_code} t=%{time_total}' --max-time 8 https://example.com"),
    # 2) Gate loop forensics — did his 50 clicks even reach the backend?
    ("gate_posts_owner", "sudo -n tail -20000 /var/log/nginx/access.log 2>/dev/null | grep '2.215.157.88' | grep -oE '(GET|POST|PUT) /api/[^ ?]+' | sort | uniq -c | sort -rn | head -15"),
    ("approve_hits",     "sudo -n tail -20000 /var/log/nginx/access.log 2>/dev/null | grep '2.215.157.88' | grep -iE 'gate|approv|decision|resume' | tail -15"),
    # 3) journal: what does the backend say about the gate cycle?
    ("journal_gate",     "journalctl -u agentic --since '-26 hours' --no-pager 2>/dev/null | grep -iE 'gate|approv|PLAN_REVISION|escalat' | tail -25"),
    # 4) current run state
    ("runs_active",      "curl -s --max-time 8 http://127.0.0.1:8010/api/projects/runs/active | head -c 700"),
    # 5) readiness now (stored)
    ("readiness_net",    "curl -s --max-time 8 http://127.0.0.1:8010/api/environment/readiness | python3 -c \"import sys,json; d=json.load(sys.stdin); [print(c['capability_id'], c['stored_status'], c['readiness_status'], (c.get('failure_reason') or '')[:80]) for c in d.get('capabilities',[])]\" 2>/dev/null | head -10"),
    # 6) health + services
    ("health",           "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health"),
]
out = {}
for name, cmd in CMDS:
    try:
        _, so, se = ssh.exec_command(cmd, timeout=60)
        out[name] = so.read().decode(errors="replace").strip()[:2200]
        err = se.read().decode(errors="replace").strip()[:150]
    except Exception as e:
        out[name], err = "", str(e)
    print(f"=== {name} ===\n{out[name]}\n{'[err] ' + err if err else ''}")

with open("/home/z/my-project/download/aes-remediation/owner-complaint-forensics.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
ssh.close()
print("\nSAVED: owner-complaint-forensics.json")
