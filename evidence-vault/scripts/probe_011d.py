#!/usr/bin/env python3
"""AES-011 — Phase 4: complete owner timeline 19:22-20:10 + the two 502s + 401s on /."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/home/z/.ssh_key_010"

def sh(c, cmd, t=60):
    _, o, e = c.exec_command(cmd, timeout=t)
    return (o.read().decode("utf-8", "replace").strip(),
            e.read().decode("utf-8", "replace").strip())

def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
              look_for_keys=False, allow_agent=False)

    print("===== A. nginx access log: EVERYTHING from 2.215.157.88 between 19:22 and 20:10 (non-200 first) =====")
    out, _ = sh(c, "sudo -n awk '$1==\"2.215.157.88\" && $4 >= \"[25/Oct/2026:19:22\" && $4 <= \"[25/Oct/2026:20:10\"' "
                   "/var/log/nginx/access.log | grep -vE '\" 200 |\" 304 ' | head -40")
    print(out or "(all 200/304)")

    print("\n===== B. the two 502s — full lines =====")
    out, _ = sh(c, "sudo -n grep ' 502 ' /var/log/nginx/access.log | tail -5")
    print(out or "(none)")

    print("\n===== C. uvicorn journal 19:22:00-19:57:00 — owner's first post-deploy visit? =====")
    out, _ = sh(c, "sudo -n journalctl -u agentic.service --since '2026-10-25 19:22' --until '2026-10-25 19:57' "
                   "--no-pager 2>/dev/null | grep '2.215.157.88' | head -50")
    print(out[:3500] or "(NO owner requests reached uvicorn between restart and 19:57)")

    print("\n===== D. uvicorn journal 19:57-20:09 — owner GET / with timestamps =====")
    out, _ = sh(c, "sudo -n journalctl -u agentic.service --since '2026-10-25 19:56' --until '2026-10-25 20:10' "
                   "--no-pager 2>/dev/null | grep '2.215.157.88' | grep '\"GET / HTTP\"' ")
    print(out or "(none)")

    print("\n===== E. nginx: ALL '/' requests by owner today (status + time) =====")
    out, _ = sh(c, "sudo -n awk '$1==\"2.215.157.88\" && $7==\"/\"' /var/log/nginx/access.log | awk '{print $4, $9}'")
    print(out or "(none)")

    print("\n===== F. journal errors 19:22-19:57 (any tracebacks/50x from app) =====")
    out, _ = sh(c, "sudo -n journalctl -u agentic.service --since '2026-10-25 19:22' --until '2026-10-25 19:57' "
                   "--no-pager 2>/dev/null | grep -iE 'error|traceback|exception|500 ' | head -15")
    print(out[:2000] or "(no errors)")
    c.close()

if __name__ == "__main__":
    main()
