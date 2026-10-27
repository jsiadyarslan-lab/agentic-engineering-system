#!/usr/bin/env python3
"""RLR-001 — who drives the service restarts + tunnel holder (READ-ONLY)."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

CHECKS = [
    ("timers", "systemctl list-timers --all --no-pager 2>/dev/null | head -12"),
    ("cron opc", "crontab -l 2>/dev/null | head -10"),
    ("cron root", "sudo -n crontab -l 2>/dev/null | head -10"),
    ("cron dirs", "ls /etc/cron.d/ 2>/dev/null; sudo -n ls /etc/cron.d/ 2>/dev/null | head -8"),
    ("tunnel holder conn", "sudo -n ss -tnp 2>/dev/null | grep -E 'sshd' | head -10"),
    ("sshd proc detail", "ps -o pid,lstart,cmd -p 427201 2>/dev/null; sudo -n cat /proc/427201/cmdline 2>/dev/null | tr '\\0' ' '; echo"),
    ("tunnel session env", "sudo -n ls -la /proc/427201/fd 2>/dev/null | wc -l"),
    ("who restarted (journal)", "sudo -n journalctl --since '05:14' --until '05:24' --no-pager 2>/dev/null | grep -iE 'systemd\\[1\\].*(agentic-vis|Started|Stopp)' | head -12"),
    ("sudo usage recent", "sudo -n journalctl --since '05:00' --no-pager 2>/dev/null | grep -iE 'sudo|sshd.*Accepted|session opened' | grep -vE 'ioreport|audit' | tail -15"),
    ("accepted connections", "sudo -n journalctl --since '04:30' --no-pager 2>/dev/null | grep -i 'accepted' | tail -10"),
    ("new executions now", "/opt/aes-vis/.venv/bin/python -c \"import sqlite3;db=sqlite3.connect('/opt/aes-vis/runtime/agent_hub_v2.db');db.row_factory=sqlite3.Row;[print(dict(r)) for r in db.execute('select id,step_id,attempt,status,substr(error,1,50) err,started_at,finished_at from executions where id>147 order by id').fetchall()]\""),
    ("project 21 now", "/opt/aes-vis/.venv/bin/python -c \"import sqlite3;db=sqlite3.connect('/opt/aes-vis/runtime/agent_hub_v2.db');db.row_factory=sqlite3.Row;[print(dict(r)) for r in db.execute('select id,status,current_plan_id,current_phase_id,current_step_id,completion_state,updated_at from projects where id=21').fetchall()]\""),
    ("steps 312/313 status", "/opt/aes-vis/.venv/bin/python -c \"import sqlite3;db=sqlite3.connect('/opt/aes-vis/runtime/agent_hub_v2.db');db.row_factory=sqlite3.Row;[print(dict(r)) for r in db.execute('select id,ordinal,status,attempts,substr(objective,1,60) obj from steps where id in (311,312,313) order by id').fetchall()]\""),
]


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
              look_for_keys=False, allow_agent=False)
    try:
        for title, cmd in CHECKS:
            _, o, e = c.exec_command(cmd, timeout=40)
            o.channel.recv_exit_status()
            out = o.read().decode("utf-8", "replace").strip()
            err = e.read().decode("utf-8", "replace").strip()
            print(f"### {title}")
            if out:
                print(out[:2000])
            if err and not out:
                print(f"[stderr] {err[:200]}")
            print()
    finally:
        c.close()


if __name__ == "__main__":
    main()
