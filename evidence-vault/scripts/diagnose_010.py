#!/usr/bin/env python3
"""AES-UI-PREMIUM-REDESIGN-010 — Oracle diagnosis (READ-ONLY).

Checks the qualified host: bwrap capability, python availability,
PyPI reachability, production independence (service/nginx/repo state),
disk/memory headroom. No writes of any kind.
"""
import sys
import paramiko

HOST = "92.5.14.150"
USER = "opc"
KEY = "/home/z/.ssh_key_010"

CMDS = [
    ("identity", "id && uname -a && head -2 /etc/os-release"),
    ("selinux", "getenforce 2>/dev/null || echo unknown"),
    ("bwrap", "which bwrap && bwrap --version"),
    ("bwrap_loopback_probe", "bwrap --unshare-all --die-with-parent --new-session "
     "--ro-bind / / --tmpfs /proc --dev /dev --tmpfs /tmp --clearenv "
     "--setenv PATH /usr/bin:/bin -- /bin/sh -c 'echo BWRAP_HOST_PROBE_OK' 2>&1; "
     "echo bwrap_probe_exit=$?"),
    ("python", "python3 --version; ls /usr/bin/python3.1* /usr/local/bin/python3* 2>/dev/null; "
     "ls /opt/agentic-engineering-system/.venv/bin/python* 2>/dev/null || true"),
    ("service", "systemctl is-active agentic.service; systemctl show agentic.service -p User -p ExecMainPID -p ActiveState 2>/dev/null | head -5"),
    ("health_local_8010", "curl -s --max-time 5 http://127.0.0.1:8010/health"),
    ("nginx", "systemctl is-active nginx; grep -h proxy_pass /etc/nginx/conf.d/agentic.conf 2>/dev/null"),
    ("prod_repo_state", "cd /opt/agentic-engineering-system && git rev-parse HEAD && git status --porcelain | head -5 && echo PROD_TREE_CHECK_DONE"),
    ("disk", "df -h /home /opt | tail -3"),
    ("mem", "free -h | head -2; nproc"),
    ("pypi_reach", "curl -sI --max-time 10 https://pypi.org/simple/ 2>&1 | head -1"),
    ("github_reach", "curl -sI --max-time 10 https://github.com 2>&1 | head -1"),
    ("home_contents", "ls /home/opc/ | head -20"),
    ("cpu_arch", "lscpu | grep -E 'Architecture|Model name' | head -2"),
]

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY, timeout=20, look_for_keys=False,
                   allow_agent=False)
    # record host key fingerprint for the audit trail
    tkey = client.get_transport().get_remote_server_key()
    import hashlib
    print(f"[host-key] {tkey.get_name()} md5={hashlib.md5(tkey.asbytes()).hexdigest()}")
    print()
    for name, cmd in CMDS:
        stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
        out = stdout.read().decode("utf-8", "replace").strip()
        err = stderr.read().decode("utf-8", "replace").strip()
        print(f"===== {name} =====")
        if out:
            print(out[:2000])
        if err:
            print(f"[stderr] {err[:500]}")
        print()
    client.close()

if __name__ == "__main__":
    main()
