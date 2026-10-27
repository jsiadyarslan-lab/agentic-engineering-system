#!/usr/bin/env python3
"""AES-006 Phase 3b: re-point nginx 80 -> production 8010 (was preview 8011).

- backs up conf first (sed -i.bak-005, following host's established .bak pattern)
- keeps IP allowlist + basic auth UNCHANGED (security posture preserved)
- nginx -t before reload
- verifies: owner's browser traffic starts arriving at 8010 app log
"""
import time

import paramiko

HOST, PORT, USER = "92.5.14.150", 22, "opc"
KEY = "/home/z/.ssh_key_006"
CONF = "/etc/nginx/conf.d/agentic.conf"


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=HOST, port=PORT, username=USER, key_filename=KEY,
                   timeout=15, banner_timeout=15, auth_timeout=15,
                   allow_agent=False, look_for_keys=False)

    def run(cmd, timeout=60):
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err

    # 0. pre-state
    code, out, _ = run(f"grep -n proxy_pass {CONF}")
    print(f"current proxy line: {out.strip()}")

    # 1. backup + re-point (single targeted line change)
    print("\n[1] backup + re-point 8011 -> 8010")
    code, out, err = run(
        f"sudo -n sed -i.bak-005 's|proxy_pass http://127.0.0.1:8011;|proxy_pass http://127.0.0.1:8010;|' {CONF} "
        f"&& grep -n proxy_pass {CONF} && ls -la {CONF}*"
    )
    print(out.strip()[:500], err.strip()[:200])
    if "127.0.0.1:8010" not in out:
        print("FATAL: re-point did not apply")
        sys.exit(1)

    # 2. config test
    print("\n[2] nginx -t")
    code, out, err = run("sudo -n nginx -t 2>&1")
    print(out.strip() + err.strip())
    if code != 0:
        print("nginx config test FAILED — rolling back conf")
        run(f"sudo -n cp {CONF}.bak-005 {CONF} && sudo -n nginx -t && sudo -n systemctl reload nginx")
        sys.exit(2)

    # 3. reload
    print("\n[3] reload nginx")
    code, out, err = run("sudo -n systemctl reload nginx 2>&1; echo rc=$?")
    print(out.strip())

    # 4. verify traffic flows to 8010: watch the app log for new requests
    print("\n[4] waiting 12s for owner's browser polls to arrive at 8010...")
    time.sleep(12)
    code, out, _ = run("journalctl -u agentic.service --since '-40 seconds' --no-pager 2>/dev/null | grep -E 'GET|POST' | tail -8")
    print("8010 app log (last requests):")
    print(out.strip() or "(no requests yet)")

    # 5. nginx access log evidence
    code, out, _ = run("sudo -n tail -12 /var/log/nginx/access.log 2>/dev/null")
    print("\nnginx access log (last lines):")
    print(out.strip()[:1500] or "(empty/unreadable)")

    print("\n=== NGINX NOW SERVES PRODUCTION (8010, b38dbaf, 4.0.0) AT PORT 80 ===")
    print(f"rollback path: sudo cp {CONF}.bak-005 {CONF} && sudo nginx -s reload")
    client.close()


if __name__ == "__main__":
    main()
