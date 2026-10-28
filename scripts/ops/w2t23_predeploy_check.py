# -*- coding: utf-8 -*-
"""W2T23-PREDEPLOY — التحقق من حالة git الإنتاجية الحقيقية قبل النشر (قراءة فقط)."""
import sys

import paramiko

HOST = "92.5.14.150"
USER = "opc"
KEY = "/tmp/oracle_key"

CMDS = [
    ("log10", "cd /opt/agentic-engineering-system && sudo -n git log --oneline -10"),
    ("has_ad371b6", "cd /opt/agentic-engineering-system && sudo -n git cat-file -t ad371b6 2>&1; sudo -n git cat-file -t ad371b66 2>&1; true"),
    ("branch_head", "cd /opt/agentic-engineering-system && sudo -n git rev-parse HEAD && sudo -n git branch -a | head -5"),
    ("status_full", "cd /opt/agentic-engineering-system && sudo -n git status --short | head -20"),
    ("w2t22_marker", "cd /opt/agentic-engineering-system && sudo -n grep -rn 'followup_retry' src/api/routes.py src/research/api.py 2>/dev/null | head -8"),
    ("service_since", "systemctl show agentic -p ActiveEnterTimestamp -p MainPID"),
    ("reflog", "cd /opt/agentic-engineering-system && sudo -n git reflog -12 2>&1 | head -14"),
]


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY, timeout=25)
    for name, cmd in CMDS:
        _, so, se = client.exec_command(cmd, timeout=40)
        print("=== %s ===" % name)
        print(so.read().decode("utf-8", "replace")[:2200])
        err = se.read().decode("utf-8", "replace")[:300]
        if err.strip():
            print("[stderr]", err)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
