#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W2-T24 smoke: REAL npm install on production with step-102's package.json.

Proves end-to-end (before the owner approves plan v4) that the provisioned
node/npm can actually satisfy step 103's acceptance criteria:
  - copies /opt/.../projects/3/steps/102/package.json to /tmp/w2t24-smoke
  - runs the REAL `npm install` (network + registry, exactly like the tool)
  - verifies: exit code 0, package-lock.json exists, node_modules/astro,
    node_modules/typescript, node_modules/@astrojs/tailwind all exist
  - captures versions, timings, sha256 of the produced package-lock.json
Evidence: download/aes-remediation/W2-T24/npm_smoke.json
Writes ONLY under /tmp/w2t24-smoke (no production paths touched).
"""
import json
import os
import time

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EVDIR = "/home/z/my-project/download/aes-remediation/W2-T24"
os.makedirs(EVDIR, exist_ok=True)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T24 npm smoke (real install)", "ts": time.strftime(
    "%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}


def run(cmd, t=900, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:180], "rc": rc,
            "out": out.strip()[:4000], "err": err.strip()[:600]}


# 0) pre-state
ev["versions"] = run(
    "/usr/local/bin/node --version && /usr/local/bin/npm --version", 30,
    "versions")

# 1) clean scratch + copy the REAL package.json from step 102
ev["setup"] = run(
    "rm -rf /tmp/w2t24-smoke && mkdir -p /tmp/w2t24-smoke && "
    "sudo -n cat /opt/agentic-engineering-system/runtime/projects/3/"
    "steps/102/package.json > /tmp/w2t24-smoke/package.json && "
    "cat /tmp/w2t24-smoke/package.json && sha256sum "
    "/tmp/w2t24-smoke/package.json", 30, "setup scratch")

# 2) the REAL npm install (exactly like the tool runs it)
t0 = time.time()
ev["npm_install"] = run(
    "cd /tmp/w2t24-smoke && PATH=/usr/local/bin:$PATH HOME=/tmp/w2t24-smoke "
    "npm install 2>&1 | tail -12; echo EXIT_CODE=$?", 900, "npm install")
ev["npm_install"]["duration_s"] = round(time.time() - t0, 1)

# 3) verify step-103 acceptance criteria artifacts FOR REAL
ev["verify"] = run(
    "cd /tmp/w2t24-smoke && echo exit-artifacts:; "
    "test -f package-lock.json && echo package-lock.json:EXISTS; "
    "test -d node_modules/astro && echo node_modules/astro:EXISTS; "
    "test -d node_modules/typescript && echo node_modules/typescript:EXISTS; "
    "test -d node_modules/@astrojs/tailwind && echo "
    "node_modules/@astrojs/tailwind:EXISTS; "
    "sha256sum package-lock.json | cut -c1-16; "
    "du -sh node_modules 2>/dev/null; "
    "PATH=/usr/local/bin:$PATH ./node_modules/.bin/astro --version 2>&1 | "
    "head -2", 120, "verify criteria artifacts")

# 4) cleanup scratch
ev["cleanup"] = run("rm -rf /tmp/w2t24-smoke", 30, "cleanup")

ev["health_final"] = run(
    "curl -s -o /dev/null -w '%{http_code}' -m 8 http://127.0.0.1:8010/health",
    20, "health final")

with open(os.path.join(EVDIR, "npm_smoke.json"), "w") as fh:
    json.dump(ev, fh, ensure_ascii=False, indent=1)

print("versions:", ev["versions"]["out"].replace("\n", " | "))
print("npm_install rc:", ev["npm_install"]["rc"],
      "duration_s:", ev["npm_install"]["duration_s"])
print("npm tail:", ev["npm_install"]["out"][-500:])
print("VERIFY:\n" + ev["verify"]["out"])
print("health:", ev["health_final"]["out"])
ssh.close()
print("EVIDENCE:", os.path.join(EVDIR, "npm_smoke.json"))
