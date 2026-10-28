#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3-ENGINES — قراءة فقط: فحص محركات SearXNG المتاحة والعاملة."""
import sys

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

TESTS = r'''
echo "=== engines from /config ==="
curl -s "http://127.0.0.1:8888/config" | python3 -c "
import sys, json
d = json.load(sys.stdin)
engines = d.get('engines', [])
print('total engines:', len(engines))
for e in engines:
    if e.get('enabled', False):
        print('- %-20s %-30s timeout=%s langs=%s' % (e.get('name'), ','.join(e.get('categories', []))[:30], e.get('timeout'), e.get('supported_languages', [''])[0] if e.get('supported_languages') else ''))
" 2>&1 | head -50
echo ""
echo "=== engine tests: specific engines ==="
for eng in google bing duckduckgo wikipedia wikipedia_en mojeek brave qwant startpage mwmbl oscar; do
  cnt=$(curl -s "http://127.0.0.1:8888/search?q=react+package.json+peer+dependencies&format=json&language=en&engines=$eng" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(len(d.get('results', [])))
except Exception:
    print('ERR')
" 2>/dev/null)
  echo "engine $eng -> $cnt results"
done
'''


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY, timeout=25,
                   look_for_keys=False, allow_agent=False)
    _, so, se = client.exec_command(TESTS, timeout=180)
    print(so.read().decode("utf-8", "replace")[:7000])
    err = se.read().decode("utf-8", "replace")[:400]
    if err.strip():
        print("[stderr]", err)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
