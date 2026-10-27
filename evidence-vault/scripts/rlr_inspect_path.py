#!/usr/bin/env python3
"""RLR-001 — inspect preview unit, router path, recent runs (READ-ONLY)."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
APP = "/opt/agentic-engineering-system"

CHECKS = [
    ("vis unit", "systemctl cat agentic-vis.service 2>/dev/null | head -25"),
    ("shim unit", "systemctl cat aes-shim.service 2>/dev/null | head -25"),
    ("shim listener", "ss -tlnp 2>/dev/null | grep -v ':(8010|8011)' | grep python | head -8"),
    ("vis working dir", "sudo -n readlink /proc/458095/cwd 2>/dev/null; ls -la /opt/ 2>/dev/null | head -10"),
    ("runs recent", f"cd {APP} && ./.venv/bin/python -c \""
     "import sqlite3, json;"
     "db = sqlite3.connect('runtime/agent_hub_v2.db');"
     "db.row_factory = sqlite3.Row;"
     "tabs = [r[0] for r in db.execute(\\\"select name from sqlite_master where type='table'\\\").fetchall()];"
     "print('tables:', tabs);"
     "for t in tabs:"
     "    if 'run' in t or 'exec' in t or 'task' in t:"
     "        try:"
     "            cols = [c[1] for c in db.execute(f'pragma table_info({t})').fetchall()];"
     "            print(t, 'cols:', cols[:12]);"
     "            rows = db.execute(f'select * from {t} order by rowid desc limit 3').fetchall();"
     "            [print(dict(r)) for r in rows]"
     "        except Exception as ex: print(t, 'ERR', ex)"
     "\""),
    ("z-ai-config keys only", "sudo -n python3 -c \"import json;d=json.load(open('/etc/.z-ai-config'));print(list(d.keys()));print({k:(v[:24]+'...' if isinstance(v,str) and len(v)>24 else v) for k,v in d.items() if k!='apiKey'})\" 2>/dev/null || echo 'no read access as opc'"),
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
