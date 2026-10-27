#!/usr/bin/env python3
"""W1-T04 deploy — nightly automated SQLite backup + 7-day retention + restore drill.

Production changes (all gated, with auto-rollback on failure):
  1. /opt/aes-backups/{db,logs}          (owned by opc)
  2. /opt/agentic-engineering-system/scripts/ops/nightly_backup.sh
  3. /etc/systemd/system/aes-backup.{service,timer}
  4. enable --now timer; manual run; retention decoy test; restore drill

R6 gates: health/services before & after; any failure aborts remaining steps
and rolls back everything created.
"""
import base64
import json
import os
from datetime import datetime, timezone

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EV = "/home/z/my-project/download/aes-remediation/W1-T04"
TS = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
os.makedirs(EV, exist_ok=True)

DB = "/opt/agentic-engineering-system/runtime/agent_hub_v2.db"
SCRIPT_PATH = "/opt/agentic-engineering-system/scripts/ops/nightly_backup.sh"
BKP = "/opt/aes-backups"

BACKUP_SH = r"""#!/bin/bash
# AES nightly backup — safe SQLite online backup (W1-T04)
# Managed by aes-backup.service/timer. Rollback: see TRACKER W1-T04.
set -uo pipefail

SRC="/opt/agentic-engineering-system/runtime/agent_hub_v2.db"
DEST_DIR="/opt/aes-backups/db"
LOG_DIR="/opt/aes-backups/logs"
DATE=$(date +%Y%m%d)
DEST="${DEST_DIR}/nightly-${DATE}.db"
PY="__PYCHOICE__"

mkdir -p "$DEST_DIR" "$LOG_DIR"
LOG="${LOG_DIR}/backup-${DATE}.log"

{
  echo "=== aes-backup started $(date -Is) pid=$$ ==="
  if [ ! -r "$SRC" ]; then echo "FATAL: source $SRC not readable"; exit 1; fi

  "$PY" - "$SRC" "$DEST" <<'PYEOF'
import sqlite3, sys, os
src, dst = sys.argv[1], sys.argv[2]
if os.path.exists(dst):
    print(f"SKIP: {dst} already exists")
    sys.exit(0)
con = sqlite3.connect(src)
dcon = sqlite3.connect(dst)
with dcon:
    con.backup(dcon)
dcon.close(); con.close()
chk = sqlite3.connect(dst)
result = chk.execute("PRAGMA integrity_check").fetchone()[0]
chk.close()
print(f"integrity_check: {result}")
sys.exit(0 if result == "ok" else 2)
PYEOF
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "FATAL: backup failed rc=$rc — removing partial file"
    rm -f "$DEST"
    exit $rc
  fi

  # retention: delete nightly backups older than 7 days
  find "$DEST_DIR" -name 'nightly-*.db' -mtime +7 -print -delete

  echo "=== done $(date -Is) size=$(stat -c%s "$DEST" 2>/dev/null) ==="
} >> "$LOG" 2>&1
exit 0
"""

SERVICE = """[Unit]
Description=AES nightly SQLite backup (safe online backup, W1-T04)
After=agentic.service

[Service]
Type=oneshot
User=opc
Group=opc
ExecStart=__SCRIPT_PATH__
"""

TIMER = """[Unit]
Description=Run aes-backup daily at 03:30 (W1-T04)

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true

[Install]
WantedBy=timers.target
"""

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)


def run(cmd, timeout=60):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    rc = stdout.channel.recv_exit_status()
    return out.strip(), err.strip(), rc


log = {"timestamp": TS, "gates": {}, "steps": {}, "rollback": None}


def gate(name, ok, detail=""):
    log["gates"][name] = {"ok": bool(ok), "detail": detail[:2000]}
    print(f"[GATE:{name}] {'PASS' if ok else 'FAIL'} {detail[:300]}")
    if not ok:
        raise RuntimeError(f"gate {name} failed: {detail[:500]}")


def rollback(reason):
    """R7 — full rollback of everything this deploy created."""
    rb = []
    for cmd in [
        "sudo -n systemctl disable --now aes-backup.timer 2>&1",
        "sudo -n systemctl stop aes-backup.service 2>&1",
        f"sudo -n rm -f /etc/systemd/system/aes-backup.service /etc/systemd/system/aes-backup.timer",
        f"sudo -n rm -f {SCRIPT_PATH}",
        f"sudo -n rm -rf {BKP}",
        "sudo -n systemctl daemon-reload",
        "rm -f /tmp/restore-drill.db /tmp/retention-decoy.db",
    ]:
        o, e, rc = run(cmd)
        rb.append({"cmd": cmd, "rc": rc, "out": (o or e)[:200]})
    log["rollback"] = {"reason": reason, "actions": rb}
    ssh.close()
    with open(os.path.join(EV, "20261027-deploy.json"), "w") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(json.dumps(log["rollback"], indent=2)[:1500])
    raise SystemExit(f"ROLLED BACK: {reason}")


# ---------------------------------------------------------------- gate: before
o, e, rc = run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
gate("health_before", o == "200", f"/health={o}")
o, e, rc = run("systemctl is-active agentic nginx firewalld")
gate("services_before", o.split() == ["active"] * 3, o.replace("\n", " "))
o, e, rc = run(f"test -r {DB} && echo READABLE || echo NOTREADABLE")
gate("db_readable_by_opc", o == "READABLE", o)
o, e, rc = run(f"stat -c '%U %G %a %s' {DB}")
log["steps"]["db_stat"] = o

# choose python: venv if usable by opc, else system python3 (both stdlib sqlite3)
o, e, rc = run("/opt/agentic-engineering-system/.venv/bin/python -c 'import sqlite3; print(\"VENV_OK\")' 2>&1")
py = "/opt/agentic-engineering-system/.venv/bin/python" if o.strip() == "VENV_OK" else "/usr/bin/python3"
log["steps"]["python_choice"] = py + ("" if py.endswith(".venv/bin/python") else " (venv not usable by opc — system python3 stdlib verified)")
BACKUP_SH = BACKUP_SH.replace("__PYCHOICE__", py)

# rowcounts BEFORE (for restore drill comparison)
o, e, rc = run("sudo -n /usr/bin/python3 -c \"import sqlite3; con=sqlite3.connect('%s');"
               "print(';'.join(f'{t}={con.execute(chr(83)+chr(69)+chr(76)+chr(69)+chr(67)+chr(84)+chr(32)+chr(67)+chr(79)+chr(85)+chr(78)+chr(84)+chr(40)+chr(42)+chr(41)+chr(32)+chr(70)+chr(82)+chr(79)+chr(77)+chr(32)+t).fetchone()[0]}' for t in ('projects','conversations','messages')))\"" % DB)
log["steps"]["rowcounts_before"] = o or e

# ================================================================ gated sequence
try:
    # ---------------------------------------------------------------- step 0: dirs + script
    o, e, rc = run(f"sudo -n mkdir -p {BKP}/db {BKP}/logs && sudo -n chown opc:opc {BKP} {BKP}/db {BKP}/logs && echo DIRS_OK")
    gate("dirs_created", "DIRS_OK" in o, o or e)

    b64 = base64.b64encode(BACKUP_SH.encode()).decode()
    o, e, rc = run(f"sudo -n mkdir -p $(dirname {SCRIPT_PATH}) && sudo -n test -f {SCRIPT_PATH} && sudo -n cp {SCRIPT_PATH} {SCRIPT_PATH}.pre-w1t04 2>/dev/null; echo {b64} | sudo -n base64 -d > /tmp/nightly_backup.sh && sudo -n cp /tmp/nightly_backup.sh {SCRIPT_PATH} && sudo -n chown root:opc {SCRIPT_PATH} && sudo -n chmod 750 {SCRIPT_PATH} && rm -f /tmp/nightly_backup.sh && echo SCRIPT_OK")
    gate("script_installed", "SCRIPT_OK" in o, (o or e))
    o, e, rc = run(f"sudo -n test -x {SCRIPT_PATH} && sudo -n head -3 {SCRIPT_PATH}")
    log["steps"]["script_head"] = o
    # opc must be able to read+execute (lesson from 203/EXEC failure on first attempt)
    o, e, rc = run(f"test -r {SCRIPT_PATH} && test -x {SCRIPT_PATH} && echo OPC_RX_OK || echo OPC_RX_MISSING")
    gate("script_opc_rx", "OPC_RX_OK" in o, o)

    # ---------------------------------------------------------------- step 1: systemd units
    for name, content in [("aes-backup.service", SERVICE.replace("__SCRIPT_PATH__", SCRIPT_PATH)),
                          ("aes-backup.timer", TIMER)]:
        b64u = base64.b64encode(content.encode()).decode()
        o, e, rc = run(f"echo {b64u} | sudo -n base64 -d > /tmp/{name} && sudo -n cp /tmp/{name} /etc/systemd/system/{name} && rm -f /tmp/{name} && echo UNIT_{name.split('.')[0].upper()}_OK")
        gate(f"unit_{name}", "OK" in o, (o or e))
    o, e, rc = run("sudo -n systemctl daemon-reload && echo RELOAD_OK")
    gate("daemon_reload", "RELOAD_OK" in o, o or e)
    o, e, rc = run("sudo -n systemctl enable --now aes-backup.timer 2>&1 && echo ENABLE_OK")
    gate("timer_enabled", "ENABLE_OK" in o, o or e)

    # ---------------------------------------------------------------- step 2: manual run
    o, e, rc = run("sudo -n systemctl start aes-backup.service 2>&1; echo RC=$?", timeout=120)
    log["steps"]["manual_run"] = o or e
    o, e, rc = run(f"ls -la {BKP}/db/ && echo --- && cat {BKP}/logs/backup-$(date +%Y%m%d).log 2>/dev/null | tail -8")
    log["steps"]["backup_listing"] = o
    o, e, rc = run(f"test -f {BKP}/db/nightly-$(date +%Y%m%d).db && echo FILE_OK || echo FILE_MISSING")
    gate("manual_backup_file", "FILE_OK" in o, o)

    # external integrity check (independent of the script's own check)
    o, e, rc = run(f"/usr/bin/python3 -c \"import sqlite3; con=sqlite3.connect('{BKP}/db/nightly-' + __import__('datetime').date.today().strftime('%Y%m%d') + '.db'); print(con.execute('PRAGMA integrity_check').fetchone()[0]); print('tables:', con.execute(\\\"SELECT COUNT(*) FROM sqlite_master WHERE type='table'\\\").fetchone()[0])\"")
    gate("integrity_external", o.splitlines()[0] == "ok" if o else False, o or e)
    log["steps"]["integrity_external"] = o

    # ---------------------------------------------------------------- step 3: retention decoy test
    o, e, rc = run(f"echo decoy > {BKP}/db/nightly-20261019.db && touch -d '2026-10-18 03:30' {BKP}/db/nightly-20261019.db && echo DECOY_OK")
    gate("decoy_created", "DECOY_OK" in o, o or e)
    o, e, rc = run(f"find {BKP}/db -name 'nightly-*.db' -mtime +7 -print -delete; echo ---; ls {BKP}/db/")
    log["steps"]["retention_test"] = o
    gate("retention_deletes_old_keeps_new",
         "nightly-20261019.db" in o.split("---")[0] and "nightly-20261019.db" not in o.split("---")[1],
         o)

    # ---------------------------------------------------------------- step 4: restore drill
    o, e, rc = run(f"cp {BKP}/db/nightly-$(date +%Y%m%d).db /tmp/restore-drill.db && /usr/bin/python3 -c \"import sqlite3; con=sqlite3.connect('/tmp/restore-drill.db'); print('integrity:', con.execute('PRAGMA integrity_check').fetchone()[0]); print(';'.join(f'{{t}}={{con.execute(\\\"SELECT COUNT(*) FROM {{t}}\\\").fetchone()[0]}}' for t in ('projects','conversations','messages')))\"")
    log["steps"]["restore_drill"] = o or e
    gate("restore_drill", "integrity: ok" in (o or e), o or e)
    o, e, rc = run("rm -f /tmp/restore-drill.db && echo DRILL_CLEANED")
    log["steps"]["restore_drill_cleanup"] = o

    # ---------------------------------------------------------------- step 5: timer scheduled
    o, e, rc = run("systemctl list-timers aes-backup.timer --no-pager 2>&1 | head -4")
    log["steps"]["list_timers"] = o
    gate("timer_scheduled", "aes-backup.timer" in o and "03:30" in o.replace("2026", ""), o)

    # ---------------------------------------------------------------- gate: after (R6)
    o, e, rc = run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
    gate("health_after", o == "200", f"/health={o}")
    o, e, rc = run("systemctl is-active agentic nginx firewalld")
    gate("services_after", o.split() == ["active"] * 3, o.replace("\n", " "))
    o, e, rc = run("sudo -n journalctl -u agentic --since '-10 min' -p err --no-pager 2>&1 | tail -5")
    log["steps"]["journal_err_after"] = o or "(no error lines)"
    o, e, rc = run("systemctl is-active agentic nginx firewalld aes-backup.timer | tr '\\n' ' '")
    log["steps"]["final_services"] = o

except (RuntimeError, SystemExit) as ex:
    if not isinstance(ex, SystemExit):
        rollback(str(ex))
    raise

ssh.close()

log["verdict"] = "PASS"
with open(os.path.join(EV, "20261027-deploy.json"), "w") as f:
    json.dump(log, f, ensure_ascii=False, indent=2)
print("\n=== DEPLOY PASS — all gates green ===")
print(json.dumps({k: v for k, v in log["steps"].items() if k in (
    "python_choice", "rowcounts_before", "backup_listing", "integrity_external",
    "retention_test", "restore_drill", "list_timers", "final_services")},
    ensure_ascii=False, indent=2))
