#!/usr/bin/env python3
"""W1-T02 — فحص قراءة فقط: حالات المشاريع الحالية (لتحديد مشروع خامل للاختبار)."""
import json
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
          look_for_keys=False, allow_agent=False)

cmd = ("curl -s --max-time 8 http://127.0.0.1:8010/api/projects "
       "| /opt/agentic-engineering-system/.venv/bin/python -c "
       "\"import json,sys; d=json.load(sys.stdin); "
       "print(json.dumps([{\\\"id\\\":p[\\\"id\\\"],\\\"name\\\":p[\\\"name\\\"],"
       "\\\"status\\\":p[\\\"status\\\"]} for p in d.get(\\\"projects\\\",[])], "
       "ensure_ascii=False, indent=1))\"")
_, o, e = c.exec_command(cmd, timeout=30)
o.channel.recv_exit_status()
out = o.read().decode("utf-8", "replace")
print(out or e.read().decode("utf-8", "replace"))
c.close()
