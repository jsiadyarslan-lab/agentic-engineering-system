#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3-SEARXTEST — قراءة فقط: اختبار مباشر لمثيل SearXNG باستعلام تقني."""
import json
import sys

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

DBPY = '''
import sqlite3, json
con = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
rows = con.execute("SELECT kind,name,config_json,enabled FROM research_providers").fetchall()
print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=1))
'''

TESTS = r'''
echo "=== searxng direct: technical query ==="
curl -s "http://127.0.0.1:8888/search?q=React+18+package.json+peer+dependencies&format=json&language=en" | python3 -c "
import sys, json
d = json.load(sys.stdin)
res = d.get('results', [])[:6]
print('total results:', len(d.get('results', [])))
for r in res:
    print('-', (r.get('title') or '')[:90])
    print('  url:', (r.get('url') or '')[:100])
    print('  content:', (r.get('content') or '')[:120].replace(chr(10),' '))
"
echo ""
echo "=== searxng direct: next.js query ==="
curl -s "http://127.0.0.1:8888/search?q=Next.js+14+package.json+dependencies+typescript&format=json&language=en" | python3 -c "
import sys, json
d = json.load(sys.stdin)
res = d.get('results', [])[:6]
print('total results:', len(d.get('results', [])))
for r in res:
    print('-', (r.get('title') or '')[:90])
    print('  url:', (r.get('url') or '')[:100])
"
echo ""
echo "=== searxng config ==="
sudo -n cat /etc/searxng/settings.yml 2>/dev/null | head -60 || sudo -n find /opt -name "settings.yml" -path "*searx*" 2>/dev/null | head -3
'''


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY, timeout=25,
                   look_for_keys=False, allow_agent=False)
    _, so, se = client.exec_command("sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % DBPY, timeout=30)
    print("=== provider configs ===")
    print(so.read().decode("utf-8", "replace")[:2000])
    _, so, se = client.exec_command(TESTS, timeout=90)
    print(so.read().decode("utf-8", "replace")[:5000])
    err = se.read().decode("utf-8", "replace")[:400]
    if err.strip():
        print("[stderr]", err)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
