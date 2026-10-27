#!/usr/bin/env python3
"""W1-T04 preflight — READ-ONLY discovery on production 92.5.14.150.

Discovers: DB path/size/tables, python availability, venv, disk space,
existing manual backups, sudo -n capability, systemd state.
No changes whatsoever.
"""
import json
import os
from datetime import datetime, timezone

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EV = "/home/z/my-project/download/aes-remediation/W1-T04"
TS = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
os.makedirs(EV, exist_ok=True)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)


def run(cmd, timeout=40):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return stdout.read().decode("utf-8", "replace").strip(), stderr.read().decode("utf-8", "replace").strip()


out = {}

# 1) systemd unit of agentic → working dir, env, user
out["unit_agentic"], _ = run("systemctl cat agentic --no-pager 2>/dev/null | head -40")

# 2) find DB files under /opt/agentic-engineering-system
out["db_files"], _ = run("sudo -n find /opt/agentic-engineering-system -maxdepth 4 \\( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \\) -printf '%s %p\\n' 2>/dev/null | sort -rn | head -15")

# 3) python availability
out["python3"], _ = run("/usr/bin/python3 --version 2>&1; which python3")
out["python3_sqlite_backup_api"], _ = run("/usr/bin/python3 -c \"import sqlite3; c=sqlite3.connect(':memory:'); d=sqlite3.connect(':memory:'); c.backup(d); print('sqlite3.backup API OK')\"")

# 4) venv of the app (if any)
out["venv"], _ = run("sudo -n ls -d /opt/agentic-engineering-system/.venv /opt/agentic-engineering-system/venv 2>/dev/null; ls -d /home/opc/.venv 2>/dev/null; echo -")

# 5) disk space
out["disk"], _ = run("df -h /opt /home | sed 's/Mounted on/Mounted/'")

# 6) existing manual backups in /home/opc (the 14+ scattered)
out["manual_backups"], _ = run("sudo -n find /home/opc -maxdepth 2 \\( -name '*.db' -o -name '*.db.*' -o -name '*.tar*' -o -name '*.gz' \\) -printf '%TY-%Tm-%Td %s %p\\n' 2>/dev/null | sort | head -30")

# 7) /opt/aes-backups existence
out["aes_backups_dir"], _ = run("sudo -n ls -la /opt/aes-backups 2>&1 | head -5; echo -")

# 8) sudo -n capability check
out["sudo_n"], _ = run("sudo -n true 2>&1 && echo SUDO_OK")

# 9) timer state (should not exist yet)
out["aes_backup_units"], _ = run("systemctl status aes-backup.service aes-backup.timer --no-pager 2>&1 | head -6")

# 10) main tables of the primary DB (pick largest .db)
db_first_line = out["db_files"].splitlines()[0] if out["db_files"] else ""
out["db_primary_path"] = db_first_line
if db_first_line:
    db_path = db_first_line.split(maxsplit=1)[1] if " " in db_first_line else db_first_line
    out["db_primary_path"] = db_path
    out["db_tables"], _ = run(f"sudo -n /usr/bin/python3 -c \"import sqlite3; con=sqlite3.connect('{db_path}'); print([r[0] for r in con.execute(\\\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\\\")])\"")
    out["db_rowcounts"], _ = run(f"sudo -n /usr/bin/python3 -c \"import sqlite3; con=sqlite3.connect('{db_path}'); [print(t, con.execute(f'SELECT COUNT(*) FROM {{t}}').fetchone()[0]) for t in ('projects','conversations','messages') if t in [r[0] for r in con.execute(\\\"SELECT name FROM sqlite_master WHERE type='table'\\\")]\"")

# 11) health before (R6)
out["health_before"], _ = run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
out["services_before"], _ = run("systemctl is-active agentic nginx firewalld")

ssh.close()

out["_meta"] = {"timestamp": TS, "mode": "READ-ONLY preflight"}
with open(os.path.join(EV, "20261027-preflight.json"), "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(json.dumps({k: v for k, v in out.items() if k in (
    "db_files", "db_primary_path", "db_tables", "db_rowcounts", "python3",
    "python3_sqlite_backup_api", "venv", "disk", "sudo_n", "health_before",
    "services_before", "aes_backup_units", "manual_backups")}, ensure_ascii=False, indent=2))
