#!/usr/bin/env python3
"""RLR-001 — run e2e state script on server (READ-ONLY)."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
LOCAL = "/home/z/my-project/scripts/rlr_e2e_state.py"
REMOTE = "/tmp/rlr_e2e_state.py"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
          look_for_keys=False, allow_agent=False)
try:
    sftp = c.open_sftp()
    sftp.put(LOCAL, REMOTE)
    sftp.close()
    _, o, e = c.exec_command(f"/opt/aes-vis/.venv/bin/python {REMOTE}", timeout=60)
    o.channel.recv_exit_status()
    print(o.read().decode("utf-8", "replace")[:7000])
    err = e.read().decode("utf-8", "replace").strip()
    if err:
        print("[stderr]", err[:400])
    c.exec_command(f"rm -f {REMOTE}")
finally:
    c.close()
