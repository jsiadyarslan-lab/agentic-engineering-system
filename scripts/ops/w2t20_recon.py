#!/usr/bin/env python3
# W2-T20 recon (read-only): server resources, container runtime, research
# providers state, production code version — before enabling SearXNG+SearchAPI.
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=45):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    return so.read().decode(errors="replace").strip(), se.read().decode(errors="replace").strip()

checks = {}

# (A) health gate (R6 before)
checks["health"] = run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")[0]

# (B) resources
for name, cmd in [
    ("mem", "free -m | sed -n '2p'"),
    ("disk_root", "df -h / | tail -1"),
    ("cpu_cores", "nproc"),
    ("os", "cat /etc/oracle-release 2>/dev/null || cat /etc/redhat-release"),
]:
    checks[name] = run(cmd)[0]

# (C) container runtimes available?
for name, cmd in [
    ("docker", "command -v docker && docker --version 2>/dev/null; sudo -n docker ps 2>&1 | head -2"),
    ("podman", "command -v podman && podman --version 2>/dev/null"),
    ("python3", "python3 --version"),
    ("pip_uv", "command -v pip3; command -v uv"),
]:
    checks[name] = run(cmd)[0]

# (D) production code: does it have SearxJsonSearchProvider + ApiSearchProvider + research API?
checks["prod_providers_code"] = run(
    "grep -c 'class SearxJsonSearchProvider' /opt/agentic-engineering-system/src/research/providers.py; "
    "grep -c 'class ApiSearchProvider' /opt/agentic-engineering-system/src/research/providers.py; "
    "grep -c 'configure' /opt/agentic-engineering-system/src/research/api.py; "
    "git -C /opt/agentic-engineering-system rev-parse --short=9 HEAD")[0]
checks["prod_git_status"] = run("git -C /opt/agentic-engineering-system status --porcelain | head -5")[0]

# (E) current research providers state via app API
raw, err = run("curl -s --max-time 12 http://127.0.0.1:8010/api/research/providers")
try:
    d = json.loads(raw)
    provs = []
    for p in d.get("providers", []):
        provs.append({
            "id": p.get("id"), "kind": p.get("kind"), "name": p.get("name"),
            "enabled": p.get("enabled"),
            "effective_status": p.get("effective_status"),
            "config": p.get("config"),
            "reason": (p.get("state_reason") or "")[:120],
        })
    checks["providers"] = provs
except Exception:
    checks["providers_raw"] = raw[:400]; checks["providers_err"] = err[:200]

# (F) ports in use around 8888/8098 + nginx footprint
checks["ports"] = run("sudo -n ss -tlnp | grep -E ':(8888|8098|8010|8011|8099)\\b' || echo NONE")[0]

# (G) searxng dir / existing install attempts
checks["existing_searx"] = run("ls -d /opt/searxng /srv/searxng ~/searxng 2>/dev/null; command -v searxng-run 2>/dev/null; echo DONE")[0]

# (H) egress still healthy (quick https check)
checks["egress"] = run("curl -s -o /dev/null -w '%{http_code} %{time_total}s' --max-time 8 https://example.com")[0]

# (I) health after recon (R6 after)
checks["health_after"] = run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")[0]

out = {"_meta": {"task": "W2-T20 recon SearXNG + Search API enablement",
                 "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "mode": "READ-ONLY"},
       **checks}
path = "/home/z/my-project/download/aes-remediation/W2-T20/recon.json"
import os
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2, default=str)
print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
ssh.close()
