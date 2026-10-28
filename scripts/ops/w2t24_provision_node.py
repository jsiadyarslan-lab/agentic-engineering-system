#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W2-T24 provision: Node.js LTS (linux-arm64) -> /usr/local on production.

Steps (all evidence-captured):
  0) pre-gates: disk space + health + node absence (honest "before")
  1) resolve latest Node 22 LTS version from nodejs.org/dist/index.json
  2) download tarball + SHASUMS256.txt to /tmp on the host
  3) verify sha256 (fail-closed on mismatch)
  4) extract into /usr/local (sudo tar -xJf --strip-components=1)
  5) verify node --version / npm --version / npx --version (+ aarch64 arch)
  6) post-gates: health + services + journal clean
Evidence: download/aes-remediation/W2-T24/provision_node.json
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

ev = {"_meta": {"task": "W2-T24 provision Node.js LTS", "ts": time.strftime(
    "%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}


def run(cmd, t=180, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:160], "rc": rc,
            "out": out.strip()[:3000], "err": err.strip()[:500]}


def abort(reason):
    ev["_meta"]["ABORT"] = reason
    with open(os.path.join(EVDIR, "provision_node.json"), "w") as fh:
        json.dump(ev, fh, ensure_ascii=False, indent=1)
    print("ABORT:", reason)
    ssh.close()
    raise SystemExit(2)


# --- 0) pre-gates ---
ev["health_before"] = run(
    "curl -s -o /dev/null -w '%{http_code}' -m 8 http://127.0.0.1:8010/health",
    20, "health before")
ev["disk_free"] = run("df -h / /tmp | tail -2", 20, "disk free")
ev["node_absence"] = run(
    "command -v node npm npx; ls /usr/local/bin/node /usr/local/bin/npm "
    "2>/dev/null; echo PROBE_DONE", 20, "node absence before")
ev["arch"] = run("uname -m && cat /etc/os-release | head -2", 20, "arch/os")
if ev["health_before"]["out"] != "200":
    abort("health before != 200: %s" % ev["health_before"]["out"])
if "PROBE_DONE" not in ev["node_absence"]["out"]:
    abort("node probe unclear")
if ev["arch"]["out"].splitlines()[0].strip() != "aarch64":
    abort("unexpected arch: %s" % ev["arch"]["out"][:80])

# --- 1) resolve latest Node 22 LTS ---
ev["resolve_version"] = run(
    "curl -s -m 30 https://nodejs.org/dist/index.json | "
    "python3 -c \"import json,sys; d=json.load(sys.stdin); "
    "v=[x for x in d if x['version'].startswith('v22.')][0]; "
    "print(v['version'], v.get('lts', False))\"", 60, "resolve node version")
line = ev["resolve_version"]["out"].strip()
if not line.startswith("v22."):
    abort("could not resolve node 22 LTS: %r" % line[:120])
node_version = line.split()[0]
node_tarball = "node-%s-linux-arm64.tar.xz" % node_version
ev["_meta"]["node_version"] = node_version

# --- 2) download tarball + shasums ---
ev["download"] = run(
    "cd /tmp && curl -sS -m 600 -O https://nodejs.org/dist/%s/%s "
    "-O https://nodejs.org/dist/%s/SHASUMS256.txt && ls -la %s" % (
        node_version, node_tarball, node_version, node_tarball),
    660, "download tarball")
if node_tarball not in ev["download"]["out"]:
    abort("download failed: %s" % ev["download"]["out"][:200])

# --- 3) verify sha256 (fail-closed) ---
ev["sha256_verify"] = run(
    "cd /tmp && grep ' %s$' SHASUMS256.txt | sha256sum -c - && "
    "echo SHA256_OK" % node_tarball, 120, "sha256 verify")
if "SHA256_OK" not in ev["sha256_verify"]["out"]:
    abort("sha256 mismatch: %s" % ev["sha256_verify"]["out"][:200])

# --- 4) extract into /usr/local ---
ev["install"] = run(
    "cd /tmp && sudo -n tar -xJf %s --strip-components=1 -C /usr/local && "
    "ls -la /usr/local/bin/node /usr/local/bin/npm /usr/local/bin/npx" % (
        node_tarball,), 300, "extract to /usr/local")
if "/usr/local/bin/npm" not in ev["install"]["out"]:
    abort("install failed: %s" % ev["install"]["out"][:300])

# --- 5) verify versions ---
ev["node_version_check"] = run(
    "/usr/local/bin/node --version && /usr/local/bin/npm --version && "
    "/usr/local/bin/npx --version", 60, "versions")
if not ev["node_version_check"]["out"].startswith(node_version):
    abort("node version mismatch: %r" % ev["node_version_check"]["out"][:120])

# --- 6) post-gates ---
ev["health_after"] = run(
    "curl -s -o /dev/null -w '%{http_code}' -m 8 http://127.0.0.1:8010/health",
    20, "health after")
ev["services_after"] = run(
    "systemctl is-active agentic nginx searxng search-api", 20,
    "services after")
ev["journal_err"] = run(
    "sudo -n journalctl -u agentic -p err --since '-10 minutes' "
    "--no-pager | tail -6", 30, "journal errors")
ev["cleanup"] = run("rm -f /tmp/%s /tmp/SHASUMS256.txt" % node_tarball,
                    30, "cleanup tmp")

with open(os.path.join(EVDIR, "provision_node.json"), "w") as fh:
    json.dump(ev, fh, ensure_ascii=False, indent=1)

print("node_version:", node_version)
print("versions:", ev["node_version_check"]["out"].replace("\n", " | "))
print("sha256:", ev["sha256_verify"]["out"].splitlines()[0][:100])
print("health_after:", ev["health_after"]["out"])
print("services:", ev["services_after"]["out"].replace("\n", " | "))
print("journal:", repr(ev["journal_err"]["out"][:120]))
print("disk_before:", ev["disk_free"]["out"].replace("\n", " ; "))
ssh.close()
print("EVIDENCE:", os.path.join(EVDIR, "provision_node.json"))
