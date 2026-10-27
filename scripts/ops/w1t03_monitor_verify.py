#!/usr/bin/env python3
"""W1-T03 step 4 — verify external monitor is LIVE and polling /healthz-<TOKEN>.

Read-only everywhere:
  - SSH read-only: nginx access log analysis (grep healthz, mask token)
  - External GET requests only from this environment (not owner, not server)

Evidence -> download/aes-remediation/W1-T03/20261027-monitor-live.json
Owner notification email (forwarded by owner in chat) saved alongside.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EV = "/home/z/my-project/download/aes-remediation/W1-T03"
TOKEN_FILE = os.path.join(EV, "owner-token.txt")
OUT_JSON = os.path.join(EV, "20261027-monitor-live.json")
OWNER_IP = "2.215.157.88"
HEALTHZ_PATH_PREFIX = "/healthz-"
TS = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

os.makedirs(EV, exist_ok=True)

with open(TOKEN_FILE) as f:
    TOKEN = f.read().strip()


def mask(s: str) -> str:
    return s.replace(TOKEN, "<TOKEN>")


def run(ssh, cmd, timeout=30):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    return out, err


results = {"timestamp": TS, "checks": {}, "verdict": None}
checks = results["checks"]

# ---------------------------------------------------------------- SSH (read-only)
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

# 1) nginx access log: requests to healthz (token-masked) in last 1000 lines
out, _ = run(ssh, "sudo -n tail -n 1000 /var/log/nginx/access.log | grep -c healthz || true")
total_healthz = out.strip()
checks["access_log_healthz_count_last1000"] = total_healthz

# 2) source IPs hitting healthz (exclude owner + loopback) — the monitor's IPs
out, _ = run(ssh, "sudo -n tail -n 2000 /var/log/nginx/access.log | grep healthz | awk '{print $1}' | sort | uniq -c | sort -rn | head -10")
ip_counts = [mask(line) for line in out.strip().splitlines() if line.strip()]
checks["healthz_source_ips"] = ip_counts

# 3) sample of recent healthz requests (masked)
out, _ = run(ssh, "sudo -n tail -n 2000 /var/log/nginx/access.log | grep healthz | tail -15")
samples = [mask(line) for line in out.strip().splitlines() if line.strip()]
checks["healthz_recent_samples_masked"] = samples

# 4) polling frequency: timestamps of last 20 healthz requests from non-owner IPs
out, _ = run(ssh, "sudo -n tail -n 2000 /var/log/nginx/access.log | grep healthz | grep -v " + OWNER_IP + " | awk '{print $4}' | tail -20 | tr -d '['")
stamps = out.strip().splitlines()
checks["monitor_poll_timestamps_last20"] = stamps

# 5) verify a 200 status on those
out, _ = run(ssh, "sudo -n tail -n 2000 /var/log/nginx/access.log | grep healthz | grep -v " + OWNER_IP + " | awk '{print $9}' | sort | uniq -c | sort -rn")
status_dist = out.strip().splitlines()
checks["healthz_status_distribution_nonowner"] = status_dist

# 6) services still fine + health direct
out, _ = run(ssh, "systemctl is-active agentic nginx firewalld")
checks["services"] = [l for l in out.strip().splitlines() if l.strip()]
out, _ = run(ssh, "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
checks["app_health_direct"] = out.strip()

ssh.close()

# ---------------------------------------------------------------- external probes
def probe(url):
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read(300).decode("utf-8", "replace")
            return {"code": r.status, "body_head": body[:200]}
    except urllib.error.HTTPError as e:
        return {"code": e.code}
    except Exception as e:
        return {"code": None, "error": f"{type(e).__name__}: {e}"}


checks["external_secret_200"] = probe(f"http://{HOST}/healthz-{TOKEN}")
checks["external_root_403"] = probe(f"http://{HOST}/")
checks["external_wrongtoken_403"] = probe(f"http://{HOST}/healthz-{'0'*32}")

# ---------------------------------------------------------------- verdict
ok = (
    total_healthz.isdigit() and int(total_healthz) > 0
    and checks["external_secret_200"]["code"] == 200
    and checks["external_root_403"]["code"] == 403
    and checks["external_wrongtoken_403"]["code"] == 403
    and all(s == "active" for s in checks["services"])
    and checks["app_health_direct"] == "200"
    # monitor polling from a NON-owner external IP is the core claim
    and any(ip_counts) and all(OWNER_IP not in line.split()[1] for line in ip_counts if len(line.split()) > 1)
)
results["verdict"] = "PASS" if ok else "FAIL"

with open(OUT_JSON, "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(json.dumps({"verdict": results["verdict"],
                  "healthz_count": total_healthz,
                  "monitor_ips": ip_counts[:5],
                  "status_dist": status_dist,
                  "external": {k: v.get("code") for k, v in checks.items() if isinstance(v, dict)},
                  "poll_samples": stamps[-5:]}, ensure_ascii=False, indent=2))
sys.exit(0)
