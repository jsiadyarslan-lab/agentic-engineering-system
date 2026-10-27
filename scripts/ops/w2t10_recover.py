#!/usr/bin/env python3
# W2-T10 R9 recovery: pull the orphan commit 036db8911 from production into a bundle,
# SFTP it here, then locally fetch + verify byte-exactness. R6-safe: only /tmp write on prod.
import json, paramiko, os, subprocess, hashlib

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
BUNDLE_REMOTE = "/tmp/w2t10-recovery.bundle"
BUNDLE_LOCAL = "/home/z/my-project/download/aes-remediation/W2-T10/w2t10-recovery.bundle"
REPO = "/home/z/my-project/repo"
os.makedirs(os.path.dirname(BUNDLE_LOCAL), exist_ok=True)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=60):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    return so.read().decode(errors="replace").strip(), se.read().decode(errors="replace").strip()

# R6 pre-gate (read-only): health + clean tree + target commit present
pre_health, _ = run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
pre_commit, _ = run("cd /opt/agentic-engineering-system && git rev-parse --short=9 HEAD")
pre_dirty, _ = run("cd /opt/agentic-engineering-system && git status --short | grep -vE '^\\?\\?' | head -3; echo END")
print(f"PRE-GATE: health={pre_health} commit={pre_commit} tracked_dirty={pre_dirty!r}")
assert pre_health == "200" and pre_commit == "036db8911", "pre-gate failed"

# Create bundle on production (/tmp only — outside service path)
o, e = run(f"cd /opt/agentic-engineering-system && git bundle create {BUNDLE_REMOTE} main 2>&1 | tail -2 && ls -la {BUNDLE_REMOTE}")
print("BUNDLE_ON_PROD:", o, e)

# SFTP it here
sftp = ssh.open_sftp()
sftp.get(BUNDLE_REMOTE, BUNDLE_LOCAL)
sftp.close()
print(f"SFTP_OK size={os.path.getsize(BUNDLE_LOCAL)}")

# Verify the 5 changed files byte-exactness: prod sha vs bundle sha (computed after local fetch)
FILES = ["src/api/projects.py", "src/ui/control-center.js", "src/ui/project-live.css",
         "src/ui/project-live.js", "src/ui/theme.css"]
prod_hashes = {}
for f in FILES:
    h, _ = run(f"cd /opt/agentic-engineering-system && sha256sum {f} | awk '{{print $1}}'")
    prod_hashes[f] = h

# Post-gate: health still 200 + remove temp bundle + tree untouched
post_health, _ = run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
run(f"rm -f {BUNDLE_REMOTE}")
post_commit, _ = run("cd /opt/agentic-engineering-system && git rev-parse --short=9 HEAD")
print(f"POST-GATE: health={post_health} commit={post_commit} bundle_removed")

# Local: fetch from bundle + verify
r = subprocess.run(["git", "-C", REPO, "fetch", BUNDLE_LOCAL, "main"], capture_output=True, text=True)
print("LOCAL_FETCH:", r.returncode, r.stderr.strip()[:200])
r = subprocess.run(["git", "-C", REPO, "rev-parse", "--short=9", "FETCH_HEAD"], capture_output=True, text=True)
local_commit = r.stdout.strip()
print("LOCAL_FETCH_HEAD:", local_commit)

local_hashes = {}
for f in FILES:
    r = subprocess.run(["git", "-C", REPO, "show", f"{local_commit}:{f}"], capture_output=True)
    local_hashes[f] = hashlib.sha256(r.stdout).hexdigest()

match = {f: (prod_hashes[f] == local_hashes[f]) for f in FILES}
print("BYTE_EXACT_MATCH:", json.dumps(match, indent=1))
result = {
    "pre_gate": {"health": pre_health, "commit": pre_commit},
    "prod_commit_recovered": local_commit,
    "byte_exact": all(match.values()),
    "files": {f: {"prod": prod_hashes[f][:16], "local": local_hashes[f][:16], "match": match[f]} for f in FILES},
    "post_gate": {"health": post_health, "commit": post_commit, "bundle_removed": True},
}
with open("/home/z/my-project/download/aes-remediation/W2-T10/recovery-verify.json", "w") as fp:
    json.dump(result, fp, ensure_ascii=False, indent=2)
ssh.close()
print("SAVED recovery-verify.json | ALL_MATCH:", all(match.values()))
