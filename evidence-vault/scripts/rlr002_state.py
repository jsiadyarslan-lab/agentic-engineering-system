#!/usr/bin/env python3
"""RLR-002 — READ-ONLY live state of the server: egress, tunnel, services, production model path."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

CHECKS = [
    # 1) THE decisive question: did direct egress get unblocked (VCN rule by owner)?
    ("direct HTTPS egress (owner VCN rule?)",
     "timeout 12 curl -sS -o /dev/null -w '%{http_code} %{time_total}s' https://example.com 2>&1 | head -2"),
    ("direct DNS", "timeout 8 getent hosts integrate.api.nvidia.com 2>&1 | head -2"),
    ("direct NVIDIA api reachability",
     "timeout 12 curl -sS -o /dev/null -w '%{http_code} %{time_total}s' https://integrate.api.nvidia.com/v1/models 2>&1 | head -2"),
    # 2) bridge/tunnel state on server
    ("tunnel 18500 listener", "ss -tlnp 2>/dev/null | grep 18500 | head -3"),
    ("bridge alive via TCP connect",
     "timeout 5 bash -c '</dev/tcp/127.0.0.1/18500' 2>&1 && echo TCP_18500_OPEN || echo TCP_18500_CLOSED"),
    ("established sshd sessions", "ss -tnp 2>/dev/null | grep sshd | grep ESTAB | head -8"),
    # 3) services
    ("services", "systemctl is-active agentic.service agentic-vis.service nginx 2>&1; systemctl list-units --type=service --state=running 2>/dev/null | grep -iE 'agentic|aes' | head -6"),
    ("ports 8010/8011/80", "ss -tlnp 2>/dev/null | grep -E ':80 |:8010|:8011' | head -6"),
    # 4) production model path / proxy config
    ("prod 8010 process env (proxy?)",
     "sudo -n cat /proc/$(pgrep -f 'uvicorn.*8010' | head -1)/environ 2>/dev/null | tr '\\0' '\\n' | grep -iE 'proxy|bridge' | head -6; echo EXIT=$?"),
    ("prod env file", "cat /opt/aes/.env 2>/dev/null | grep -iE 'proxy|bridge' | head -4; ls /opt/aes/ 2>/dev/null | head -8"),
    ("prod recent model events",
     "cd /opt/aes && .venv/bin/python -c \"import sqlite3;db=sqlite3.connect('runtime/agent_hub_v2.db');db.row_factory=sqlite3.Row;"
     "[print(r['kind'], r['created_at']) for r in db.execute(\\\"select kind,created_at from events where kind like '%provider%' or kind like '%failover%' or kind like '%router%' or kind like '%model%' order by rowid desc limit 8\\\").fetchall()]\" 2>&1 | head -10"),
    # 5) vis service (8011) state + proxy
    ("vis 8011 env (proxy?)",
     "sudo -n cat /proc/$(pgrep -f 'uvicorn.*8011' | head -1)/environ 2>/dev/null | tr '\\0' '\\n' | grep -iE 'proxy|bridge' | head -4"),
    ("git states", "echo PROD:; git -C /opt/aes log --oneline -1 2>/dev/null; echo VIS:; git -C /opt/aes-vis log --oneline -1 2>/dev/null; git -C /opt/aes-vis branch --show-current 2>/dev/null"),
]


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=25,
              look_for_keys=False, allow_agent=False)
    try:
        for title, cmd in CHECKS:
            _, o, e = c.exec_command(cmd, timeout=45)
            o.channel.recv_exit_status()
            out = o.read().decode("utf-8", "replace").strip()
            err = e.read().decode("utf-8", "replace").strip()
            print(f"### {title}")
            if out:
                print(out[:1800])
            if err and not out:
                print(f"[stderr] {err[:300]}")
            print(flush=True)
    finally:
        c.close()


if __name__ == "__main__":
    main()
