#!/usr/bin/env python3
"""RLR-001 — find the live egress path on the server RIGHT NOW (READ-ONLY)."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

CHECKS = [
    ("proxy value", "grep -E '^(https_proxy|HTTPS_PROXY|no_proxy|NO_PROXY)' /opt/aes-vis/.env-vis | head -4"),
    ("tunnel listeners", "ss -tlnp 2>/dev/null | grep -E '18500|1080|8080|3128|8118' | head -5"),
    ("established sshd", "ss -tnp 2>/dev/null | grep sshd | grep ESTAB | head -8"),
    ("who", "who; echo ---; last -8 2>/dev/null | head -10"),
    ("ssh sessions of opc", "ps aux | grep -E 'sshd.*opc' | grep -v grep | head -5"),
    ("rlr-001 full log", "git -C /opt/aes-vis log --oneline 947e6e5..HEAD 2>/dev/null | head -30"),
    ("rlr-001 ahead count", "git -C /opt/aes-vis rev-list --count 947e6e5..HEAD 2>/dev/null"),
    ("project 21", "/opt/aes-vis/.venv/bin/python -c \"import sqlite3;db=sqlite3.connect('/opt/aes-vis/runtime/agent_hub_v2.db');db.row_factory=sqlite3.Row;[print(dict(r)) for r in db.execute('select id,name,status,created_at from projects where id=21').fetchall()]\""),
    ("vis jobs/steps/execs", "/opt/aes-vis/.venv/bin/python -c \"import sqlite3;db=sqlite3.connect('/opt/aes-vis/runtime/agent_hub_v2.db');db.row_factory=sqlite3.Row;"
     "for t in ('engineering_jobs','steps','executions','phases','plans'):"
     "    n=db.execute(f'select count(*) from {t}').fetchone()[0];print(t,n)"
     "\""),
    ("vis recent steps", "/opt/aes-vis/.venv/bin/python -c \"import sqlite3;db=sqlite3.connect('/opt/aes-vis/runtime/agent_hub_v2.db');db.row_factory=sqlite3.Row;cols=[c[1] for c in db.execute('pragma table_info(steps)')];print(cols[:14]);[print(dict(r)) for r in db.execute('select * from steps order by rowid desc limit 5').fetchall()]\" 2>/dev/null | head -12"),
    ("vis recent events kinds", "/opt/aes-vis/.venv/bin/python -c \"import sqlite3;db=sqlite3.connect('/opt/aes-vis/runtime/agent_hub_v2.db');db.row_factory=sqlite3.Row;[print(r['kind'], r['created_at']) for r in db.execute(\\\"select kind,created_at from events where kind like 'provider%' or kind like 'failover%' or kind like 'router%' order by rowid desc limit 12\\\").fetchall()]\" 2>/dev/null | head -14"),
    ("vis service env live", "sudo -n cat /proc/$(pgrep -f 'uvicorn api.routes:app.*8011' | head -1)/environ 2>/dev/null | tr '\\0' '\\n' | grep -iE 'proxy|bridge|AES_FAILOVER|AES_LLM' | head -8"),
    ("retry loop process", "ps aux | grep -iE 'python.*(loop|retry|factory|rlr)' | grep -v grep | head -5"),
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
                print(out[:2500])
            if err and not out:
                print(f"[stderr] {err[:300]}")
            print()
    finally:
        c.close()


if __name__ == "__main__":
    main()
