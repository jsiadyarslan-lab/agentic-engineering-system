#!/usr/bin/env python3
"""W1-T05 steps 0-1 — READ-ONLY proof of outbound port 80 blocking + mgmt path check.

No production changes. Evidence -> download/aes-remediation/W1-T05/20261027-steps01.json
"""
import json
import os
from datetime import datetime, timezone

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EV = "/home/z/my-project/download/aes-remediation/W1-T05"
TS = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
os.makedirs(EV, exist_ok=True)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)


def run(cmd, timeout=40):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    return out, err


out = {}

# ---- step 0: prove the block (http:80 fails, https:443 works = contrast) ----
o, e = run("curl -s -o /dev/null -w '%{http_code} %{time_total} %{errormsg}' --max-time 8 http://example.com/ 2>&1; echo RC=$?")
out["http80_example_com"] = o or e
o, e = run("curl -s -o /dev/null -w '%{http_code} %{time_total} %{errormsg}' --max-time 8 https://example.com/ 2>&1; echo RC=$?")
out["https443_example_com"] = o or e
o, e = run("curl -s -o /dev/null -w '%{http_code} %{time_total} %{errormsg}' --max-time 8 http://neverssl.com/ 2>&1; echo RC=$?")
out["http80_neverssl_com"] = o or e

# ---- step 1: management path ----
o, e = run("ls -la ~/.oci 2>/dev/null; which oci 2>/dev/null; echo '---'; oci --version 2>&1 | head -1")
out["oci_cli"] = o or e or "(absent)"

# ---- context evidence (read-only) ----
o, e = run("sudo -n firewall-cmd --list-all 2>/dev/null | head -12")
out["firewalld_zone"] = o  # outbound not restricted by firewalld (no rich egress rules expected)
o, e = run("curl -s --max-time 10 http://127.0.0.1:8010/api/environment/readiness 2>/dev/null | /usr/bin/python3 -c \"import sys, json; d=json.load(sys.stdin); items=d.get('items') or d.get('capabilities') or d; import re; s=json.dumps(items, ensure_ascii=False); m=[x for x in re.findall(r'\\\"(network_http|network_https|network_dns|network)\\\"[^}]*?\\\"status\\\"\\s*:\\s*\\\"(\\w+)\\\"', s)]; print(m if m else s[:600])\" 2>&1 || echo PROBE_PARSE_FAILED")
out["readiness_now"] = o or e
o, e = run("systemctl is-active agentic nginx firewalld")
out["services"] = o
o, e = run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
out["health"] = o

ssh.close()

out["_meta"] = {"timestamp": TS, "mode": "READ-ONLY steps 0-1"}
with open(os.path.join(EV, "20261027-steps01.json"), "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

for k in ("http80_example_com", "https443_example_com", "http80_neverssl_com",
          "oci_cli", "readiness_now", "services", "health"):
    print(f"== {k} ==\n{out[k]}\n")
