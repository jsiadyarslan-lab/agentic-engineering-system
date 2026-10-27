#!/usr/bin/env python3
"""AES-011 — re-derive expected SHA-256 of UI files at commit 947e6e55 from the SERVER repo
(git blobs), and compare with the locally stored expected-sha256-947e6e55.txt."""
import hashlib
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/home/z/.ssh_key_010"
FILES = ["theme.css", "styles.css", "app.js", "app-shell.css",
         "factory-control.css", "factory-control.js", "index.html"]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
          look_for_keys=False, allow_agent=False)

def run(cmd, t=30):
    _, o, e = c.exec_command(cmd, timeout=t)
    rc = o.channel.recv_exit_status()
    out, err = o.read().decode(), e.read().decode()
    if err.strip():
        print(f"[stderr] {err.strip()[:200]}")
    return rc, out

# fetch each blob's sha256 computed on the server from git at HEAD (must be 947e6e55)
rc, head = run("git -C /opt/agentic-engineering-system rev-parse HEAD")
head = head.strip()
print(f"server HEAD: {head}")

expected = {}
for f in FILES:
    rc, out = run(f"git -C /opt/agentic-engineering-system show HEAD:src/ui/{f} | sha256sum | cut -d' ' -f1")
    expected[f] = out.strip()

print("\nserver git-blob sha256 @ HEAD:")
for k, v in expected.items():
    print(f"  {k:26s} {v}")

# compare with local expected file
local_path = "/home/z/my-project/download/live-reconciliation-011/expected-sha256-947e6e55.txt"
try:
    local = {}
    for line in open(local_path):
        parts = line.split()
        if len(parts) == 2:
            local[parts[1] if not parts[1].startswith("static") else parts[1]] = parts[0]
    print("\nlocal expected file present — cross-check:")
    for k, v in expected.items():
        lv = local.get(k) or local.get(f"/static/{k}") or local.get(f"static/{k}")
        status = "MATCH" if lv == v else f"DIFFERS (local={lv})"
        print(f"  {k:26s} {status}")
except FileNotFoundError:
    print("\nno local expected file — writing fresh one")
    with open(local_path, "w") as fh:
        for k, v in expected.items():
            fh.write(f"{v}  {k}\n")
    print(f"written {local_path}")

c.close()
print("EXPECTED-DONE")
