#!/usr/bin/env python3
"""AES-UI-PREMIUM-REDESIGN-006 — Oracle deployment via SSH (user opc).

Subcommands:
  diagnose   Phase 1 (READ-ONLY): host identity, listening ports, services,
             reverse proxy, app path, git state, deploy mechanism.
  verify     Phase 2: app repo checks + restorable backup (git bundle) +
             confirm origin/main == expected release SHA.
  deploy     Phase 3: fast-forward-only update to the approved release,
             service restart per discovered mechanism, local health check.

Usage:
  python3 deploy_oracle.py --key /path/to/private_key diagnose
  python3 deploy_oracle.py --key /path/to/private_key verify
  python3 deploy_oracle.py --key /path/to/private_key deploy

Safety rules baked in:
  - never prints secrets / env var values
  - never runs reset --hard, clean, or force operations
  - fast-forward only (merge --ff-only)
  - records previous release SHA before any change
"""
import argparse
import os
import sys
import time

import paramiko

HOST = "92.5.14.150"
PORT = 22
USER = "opc"
EXPECTED_MAIN = "b38dbafcf4160df469132d9e415ac931aad1a258"
EVIDENCE_DIR = "/home/z/my-project/download/oracle-deploy"
HOST_KEY_MD5 = "903419d8a7a6e25281f839ddc724c75a"

DIAG_COMMANDS = [
    ("host identity", "hostname; uptime; date -u; uname -a"),
    ("listening ports", "ss -tlnp 2>/dev/null | grep -E ':(80|443|8010|8011)\\b' || echo '(no matching listeners)'"),
    ("web processes", "ps aux | grep -E '[u]vicorn|[n]ginx' | head -20"),
    ("systemd units", "systemctl list-units --type=service --no-pager 2>/dev/null | grep -iE 'aes|uvicorn|nginx|gunicorn' || echo '(none matching)'"),
    ("user services", "systemctl --user list-units --type=service --no-pager 2>/dev/null | grep -iE 'aes|uvicorn|gunicorn' || echo '(none matching)'"),
    ("nginx configs", "ls /etc/nginx/conf.d/ 2>/dev/null && grep -rE 'listen|proxy_pass' /etc/nginx/conf.d/ 2>/dev/null | head -20 || echo '(no nginx conf.d readable)'"),
    ("uvicorn cwd", "for p in $(pgrep -f 'uvicorn' 2>/dev/null); do echo \"pid $p cwd: $(readlink /proc/$p/cwd 2>/dev/null) cmd: $(tr '\\0' ' ' < /proc/$p/cmdline 2>/dev/null | cut -c1-160)\"; done"),
    ("candidate app dirs", "ls -d /home/opc/aes* /home/opc/agentic* /opt/aes* 2>/dev/null || echo '(no candidate dirs)'"),
    ("git state of candidates", "for d in /home/opc/aes* /home/opc/agentic*; do [ -d \"$d/.git\" ] && echo \"== $d ==\" && git -C \"$d\" rev-parse HEAD 2>/dev/null && git -C \"$d\" status --short | head -5 && git -C \"$d\" remote -v | head -2; done 2>/dev/null || echo '(none)'"),
    ("recent service logs", "journalctl --no-pager -n 15 2>/dev/null | tail -15 || echo '(journalctl not accessible without privileges)'"),
]


def connect(key_path, passphrase=None):
    if not os.path.exists(key_path):
        raise SystemExit(f"private key not found: {key_path}")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=HOST, port=PORT, username=USER,
            key_filename=key_path, passphrase=passphrase,
            timeout=15, banner_timeout=15, auth_timeout=15,
            allow_agent=False, look_for_keys=False,
        )
    except paramiko.AuthenticationException as e:
        raise SystemExit(f"AUTH FAILED as {USER}@{HOST}: {e}")
    except Exception as e:
        raise SystemExit(f"CONNECT FAILED {HOST}:{PORT}: {type(e).__name__}: {e}")
    return client


def run(client, cmd, timeout=60):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def save_evidence(name, text):
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    path = os.path.join(EVIDENCE_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def find_app_dir(client):
    """Locate the production app directory from the uvicorn:8010 process."""
    code, out, _ = run(client, (
        "for p in $(pgrep -f 'uvicorn' 2>/dev/null); do "
        "cmd=$(tr '\\0' ' ' < /proc/$p/cmdline 2>/dev/null); "
        "case \"$cmd\" in *8010*) echo \"$(readlink /proc/$p/cwd 2>/dev/null)\";; esac; done"
    ))
    dirs = [d.strip() for d in out.strip().splitlines() if d.strip()]
    return dirs[0] if dirs else None


def cmd_diagnose(client):
    print("=" * 70)
    print("PHASE 1 — DIAGNOSIS (read-only)")
    print("=" * 70)
    report = []
    for title, cmd in DIAG_COMMANDS:
        code, out, err = run(client, cmd, timeout=45)
        section = f"\n----- {title} -----\n{out.strip()}"
        if err.strip():
            section += f"\n[stderr] {err.strip()[:300]}"
        print(section)
        report.append(section)
    path = save_evidence(
        f"diagnosis-{time.strftime('%Y%m%d-%H%M%S')}.txt",
        f"AES-UI-PREMIUM-REDESIGN-006 diagnosis\nhost={HOST} user={USER}\n" + "\n".join(report),
    )
    print(f"\n[evidence saved] {path}")
    app_dir = find_app_dir(client)
    found = app_dir if app_dir else "(not found - inspect evidence)"
    print(f"\n>>> detected production app dir (uvicorn:8010 cwd): {found}")


def cmd_verify(client):
    print("=" * 70)
    print("PHASE 2 — VERIFY DEPLOY CANDIDATE")
    print("=" * 70)
    app_dir = find_app_dir(client)
    if not app_dir:
        raise SystemExit("could not auto-detect app dir; run diagnose and extend find_app_dir")
    print(f"app dir: {app_dir}")

    code, out, err = run(client, f"git -C {app_dir} rev-parse HEAD")
    current = out.strip()
    print(f"deployed HEAD now : {current}")

    code, out, _ = run(client, f"git -C {app_dir} status --short")
    dirty = out.strip()
    print(f"working tree      : {'DIRTY:\n' + dirty if dirty else 'clean'}")
    if dirty:
        raise SystemExit("ABORT: app tree is dirty — owner must resolve; will not overwrite")

    code, out, _ = run(client, f"git -C {app_dir} remote get-url origin")
    print(f"origin            : {out.strip()}")

    code, out, err = run(client, f"git -C {app_dir} fetch origin 2>&1 && git -C {app_dir} rev-parse origin/main")
    fetched = out.strip().splitlines()[-1] if out.strip() else ""
    print(f"origin/main       : {fetched}")
    if fetched != EXPECTED_MAIN:
        raise SystemExit(f"ABORT: origin/main {fetched} != approved release {EXPECTED_MAIN}")

    code, out, _ = run(client, f"git -C {app_dir} merge-base --is-ancestor {current} {EXPECTED_MAIN} && echo FF-OK")
    print(f"fast-forwardable  : {'yes' if 'FF-OK' in out else 'NO — history diverged, stopping'}")
    if "FF-OK" not in out:
        raise SystemExit("ABORT: current HEAD is not an ancestor of the release")

    backup = f"{app_dir}/pre-005-backup.bundle"
    code, out, err = run(client, f"git -C {app_dir} bundle create {backup} --all 2>&1 && echo BUNDLE-OK; ls -la {backup}", timeout=120)
    print(f"backup bundle     : {'created' if 'BUNDLE-OK' in out else 'FAILED'}\n{out.strip()}{err.strip()}")
    if "BUNDLE-OK" not in out:
        raise SystemExit("ABORT: backup failed — refusing to proceed without restore point")
    print(f"\nrestore point: previous HEAD {current} + bundle {backup}")
    save_evidence("deploy-state.txt", f"app_dir={app_dir}\nprevious_head={current}\nbackup={backup}\ntarget={EXPECTED_MAIN}\n")
    return app_dir


def restart_service(client):
    """Restart per mechanism discovered during diagnose."""
    # try systemd system unit first, then user unit, then report manual restart
    for cmd, label in [
        ("sudo -n systemctl restart aes.service 2>&1 || sudo -n systemctl restart uvicorn.service 2>&1", "system systemd (sudo -n)"),
        ("systemctl --user restart aes.service 2>&1 || systemctl --user restart uvicorn.service 2>&1", "user systemd"),
    ]:
        code, out, err = run(client, cmd, timeout=60)
        print(f"[restart try: {label}] rc={code} {out.strip()[:200]}{err.strip()[:200]}")
        if code == 0:
            return label
    print("[restart] no managed unit identified — manual restart required (see diagnosis evidence)")
    return None


def cmd_deploy(client):
    print("=" * 70)
    print("PHASE 3 — CONTROLLED DEPLOY (fast-forward only)")
    print("=" * 70)
    app_dir = cmd_verify(client)
    print("\n--- updating ---")
    code, out, err = run(client, f"git -C {app_dir} merge --ff-only origin/main 2>&1 && git -C {app_dir} rev-parse HEAD")
    print(out.strip() + err.strip())
    final = out.strip().splitlines()[-1] if out.strip() else ""
    if final != EXPECTED_MAIN:
        raise SystemExit(f"ABORT: post-merge HEAD {final} != {EXPECTED_MAIN}")

    print("\n--- restarting service ---")
    restarted = restart_service(client)

    print("\n--- post-restart health check (from the host itself) ---")
    time.sleep(4)
    for url in ("http://127.0.0.1:8010/health", "http://127.0.0.1:8010/"):
        code, out, err = run(client, f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 {url}")
        print(f"{url} -> HTTP {out.strip()}")
    code, out, _ = run(client, "curl -s --max-time 10 http://127.0.0.1:8010/health | head -c 300")
    print(f"health body: {out.strip()[:300]}")
    save_evidence("deploy-result.txt", f"deployed={final}\nrestarted={restarted}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True, help="path to PRIVATE key (e.g. upload/ssh-key-2026-10-21.key)")
    ap.add_argument("--passphrase", default=None)
    ap.add_argument("command", choices=["diagnose", "verify", "deploy"])
    args = ap.parse_args()

    client = connect(args.key, args.passphrase)
    try:
        hk = client.get_transport().get_remote_server_key().get_fingerprint().hex()
        print(f"connected to {USER}@{HOST} — host key md5 {hk}")
        if hk != HOST_KEY_MD5:
            print(f"WARNING: host key changed! expected {HOST_KEY_MD5}")
        if args.command == "diagnose":
            cmd_diagnose(client)
        elif args.command == "verify":
            cmd_verify(client)
        elif args.command == "deploy":
            cmd_deploy(client)
    finally:
        client.close()


if __name__ == "__main__":
    main()
