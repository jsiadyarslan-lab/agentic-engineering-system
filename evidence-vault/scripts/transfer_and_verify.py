#!/usr/bin/env python3
"""AES-006 Phase 2: transfer verified release bundle to Oracle + host-side
pre-merge verification + full backups. NO merge, NO restart in this step.

Local side: create git bundle from verified b38dbaf.
Host side (all safe ops):
  1. backup: git bundle --all  +  runtime/ tarball  (restorable points)
  2. git fetch from uploaded bundle
  3. verify FETCH_HEAD == b38dbafcf4160df469132d9e415ac931aad1a258
  4. verify ff-ancestry: current HEAD is ancestor of target
  5. verify tree clean
Prints everything; exits non-zero on any failed verification.
"""
import subprocess
import sys

import paramiko

HOST, PORT, USER = "92.5.14.150", 22, "opc"
KEY = "/home/z/.ssh_key_006"
LOCAL_REPO = "/home/z/my-project/repo"
RELEASE_SHA = "b38dbafcf4160df469132d9e415ac931aad1a258"
LOCAL_BUNDLE = "/home/z/my-project/scripts/release-005.bundle"
REMOTE_BUNDLE = "/home/opc/release-005.bundle"
TS = "20261025-0245"


def run_local(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"LOCAL FAILED: {cmd}\n{r.stderr[:500]}")
        sys.exit(1)
    return r.stdout.strip()


def main():
    # ---- local: build bundle ----
    print("[local] creating temp branch + bundle for", RELEASE_SHA[:12])
    run_local(f"git -C {LOCAL_REPO} branch -f release-005 {RELEASE_SHA}")
    out = run_local(f"git -C {LOCAL_REPO} bundle create {LOCAL_BUNDLE} release-005")
    print("[local] bundle:", out.splitlines()[0] if out else "(ok)")
    # verify bundle contains exactly the release sha
    out = run_local(f"git -C {LOCAL_REPO} bundle list-heads {LOCAL_BUNDLE}")
    print("[local] bundle heads:\n", out)
    if RELEASE_SHA not in out:
        print("FATAL: bundle does not contain release SHA")
        sys.exit(2)
    size = run_local(f"stat -c %s {LOCAL_BUNDLE}")
    print(f"[local] bundle size: {int(size)//1024} KB")

    # ---- connect + upload ----
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=HOST, port=PORT, username=USER, key_filename=KEY,
                   timeout=15, banner_timeout=15, auth_timeout=15,
                   allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()
    print(f"[sftp] uploading {LOCAL_BUNDLE} -> {REMOTE_BUNDLE}")
    sftp.put(LOCAL_BUNDLE, REMOTE_BUNDLE)
    st = sftp.stat(REMOTE_BUNDLE)
    print(f"[sftp] uploaded, {st.st_size//1024} KB on host")
    sftp.close()

    def run(cmd, timeout=180):
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err

    APP = "/opt/agentic-engineering-system"

    # ---- host: backups ----
    print("\n[host] recording current state + creating restorable backups")
    code, out, err = run(f"git -C {APP} rev-parse HEAD")
    current = out.strip()
    print(f"[host] current deployed HEAD: {current}")
    if current != "0a26fc70ce13e69932db7fe54c810fcbf0f99d3f":
        print(f"WARNING: expected 0a26fc70, found {current} — proceeding but recording actual")

    code, out, err = run(f"git -C {APP} bundle create /home/opc/pre-005-prod-{TS}.bundle --all 2>&1 && echo BUNDLE-OK")
    print(f"[host] git backup bundle: {'OK' if 'BUNDLE-OK' in out else 'FAILED'} {err.strip()[:200]}")
    if "BUNDLE-OK" not in out:
        sys.exit(3)

    code, out, err = run(f"tar -czf /home/opc/pre-005-runtime-{TS}.tar.gz -C {APP} runtime && ls -la /home/opc/pre-005-runtime-{TS}.tar.gz")
    print(f"[host] runtime backup tar: {'OK' if code == 0 else 'FAILED'}\n{out.strip()[:200]}")
    if code != 0:
        sys.exit(4)

    # ---- host: fetch from bundle ----
    print("\n[host] fetching release from uploaded bundle")
    code, out, err = run(f"git -C {APP} fetch {REMOTE_BUNDLE} release-005 2>&1 && git -C {APP} rev-parse FETCH_HEAD")
    fetched = out.strip().splitlines()[-1] if out.strip() else ""
    print(f"[host] FETCH_HEAD: {fetched}")
    if fetched != RELEASE_SHA:
        print(f"FATAL: fetched SHA {fetched} != expected {RELEASE_SHA}")
        sys.exit(5)

    # ---- host: verify ff ancestry + clean tree ----
    code, out, err = run(f"git -C {APP} merge-base --is-ancestor {current} {RELEASE_SHA} && echo FF-OK")
    print(f"[host] fast-forwardable: {'YES' if 'FF-OK' in out else 'NO'}")
    if "FF-OK" not in out:
        sys.exit(6)

    code, out, _ = run(f"git -C {APP} status --short | grep -v egg-info")
    unexpected = out.strip()
    print(f"[host] tree clean (excl egg-info): {'YES' if not unexpected else 'NO: ' + unexpected[:300]}")
    if unexpected:
        sys.exit(7)

    # ---- summary of what WOULD change ----
    code, out, err = run(f"git -C {APP} diff --stat {current} {RELEASE_SHA} | tail -3")
    print(f"[host] deploy diff vs current:\n{out.strip()}")

    print("\n=== PRE-MERGE VERIFICATION: ALL PASSED ===")
    print(f"next step: git -C {APP} merge --ff-only FETCH_HEAD  (target {RELEASE_SHA[:12]})")
    client.close()


if __name__ == "__main__":
    main()
