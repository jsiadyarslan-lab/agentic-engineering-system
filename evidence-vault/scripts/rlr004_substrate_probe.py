#!/usr/bin/env python3
"""RLR-004 — diagnose substrate availability with a REAL bwrap launch probe."""
import paramiko

HOST, USER, SSHKEY = "92.5.14.150", "opc", "/tmp/oracle_key"

REMOTE = r'''
import sys
sys.path.insert(0, "/opt/agentic-engineering-system/src")
from substrate.factory import substrate_available, select_substrate

sel = select_substrate(force=True)
print("selection:", {k: v for k, v in sel.items() if k != "capabilities"})
print("capabilities:", sel.get("capabilities"))
print("substrate_available():", substrate_available())
'''

CHECKS = [
    ("real probe", "cd /opt/agentic-engineering-system && .venv/bin/python /tmp/rlr004_probe.py 2>&1"),
    ("bwrap unprivileged test",
     "bwrap --ro-bind /usr /usr --symlink usr/bin /bin --proc /proc --dev /dev "
     "--unshare-all /bin/true 2>&1; echo rc=$?"),
]


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=SSHKEY, timeout=25,
              look_for_keys=False, allow_agent=False)
    try:
        sftp = c.open_sftp()
        with sftp.file("/tmp/rlr004_probe.py", "w") as f:
            f.write(REMOTE)
        sftp.close()
        for title, cmd in CHECKS:
            _, o, e = c.exec_command(cmd, timeout=90)
            o.channel.recv_exit_status()
            out = o.read().decode("utf-8", "replace").strip()
            err = e.read().decode("utf-8", "replace").strip()
            print(f"### {title}")
            print((out or err)[:2000])
            print(flush=True)
    finally:
        c.close()


if __name__ == "__main__":
    main()
