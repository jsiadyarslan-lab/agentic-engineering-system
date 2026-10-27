#!/usr/bin/env python3
"""AES-013 — fetch the DEPLOYED ui files (ground truth at 002cf4a) for code-level critique."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/aes_key"
OUT = "/home/z/my-project/download/design-critique-013/deployed-code"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
          look_for_keys=False, allow_agent=False)

BASE = "/opt/agentic-engineering-system/src/ui"
FILES = ["theme.css", "index.html", "styles.css", "app-shell.css"]

import os
os.makedirs(OUT, exist_ok=True)
sftp = c.open_sftp()
for f in FILES:
    try:
        sftp.get(f"{BASE}/{f}", f"{OUT}/{f}")
        print(f"fetched {f}: {os.path.getsize(f'{OUT}/{f}')} bytes")
    except Exception as e:
        print(f"FAIL {f}: {e}")
sftp.close()

# quick token dump from deployed theme.css
_, o, _ = c.exec_command(f"grep -n -E '(font-size|--fs|font-family|--font)' {BASE}/theme.css | head -40", timeout=30)
print("\n=== typography-related lines in deployed theme.css ===")
print(o.read().decode()[:3000])
c.close()
