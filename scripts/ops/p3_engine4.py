#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3-ENGINE4 — قراءة فقط: stackoverflow/اختبارات إضافية + Search API 8098 بمفتاحه."""
import sys

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

TESTS = r'''
echo "=== stackoverflow engine ==="
curl -s "http://127.0.0.1:8888/search?q=react+package.json+peer+dependencies&format=json&language=en&engines=stackoverflow" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('n=', len(d.get('results', [])))
for r in d.get('results', [])[:6]:
    print('-', (r.get('title') or '')[:75])
    print('  ', (r.get('url') or '')[:85])
"
echo ""
echo "=== combined: mdn+stackoverflow+startpage+mojeek ==="
curl -s "http://127.0.0.1:8888/search?q=Next.js+14+package.json+dependencies+typescript&format=json&language=en&engines=mdn,stackoverflow,startpage,mojeek" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('n=', len(d.get('results', [])))
for r in d.get('results', [])[:10]:
    print('-', (r.get('title') or '')[:75])
    print('  ', (r.get('url') or '')[:85])
"
echo ""
echo "=== search-api env (read-only) ==="
sudo -n cat /etc/search-api/env 2>/dev/null | sed 's/=.*KEY.*/=<redacted>/' | head -5
API_KEY=$(sudo -n sh -c 'grep -oP "(?<=API_KEY=).*" /etc/search-api/env 2>/dev/null | head -1' 2>/dev/null)
echo "key found: $([ -n "$API_KEY" ] && echo yes || echo no)"
echo ""
echo "=== search-api with key: technical query ==="
curl -s -X POST "http://127.0.0.1:8098/search" -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" -H "X-API-Key: $API_KEY" -d '{"query":"react package.json peer dependencies","q":"react package.json peer dependencies","max_results":8}' | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    items = d.get('results', d if isinstance(d, list) else [])
    print('n=', len(items))
    for r in items[:6]:
        if isinstance(r, dict):
            print('-', (r.get('title') or '')[:75])
            print('  ', (r.get('url') or r.get('href') or '')[:85])
except Exception as e:
    print('ERR', e)
    print(sys.stdin.read()[:400])
"
echo ""
echo "=== search-api with key: next.js query ==="
curl -s -X POST "http://127.0.0.1:8098/search" -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" -H "X-API-Key: $API_KEY" -d '{"query":"Next.js 14 package.json dependencies typescript tailwind","q":"Next.js 14 package.json dependencies typescript tailwind","max_results":8}' | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    items = d.get('results', d if isinstance(d, list) else [])
    print('n=', len(items))
    for r in items[:6]:
        if isinstance(r, dict):
            print('-', (r.get('title') or '')[:75])
            print('  ', (r.get('url') or r.get('href') or '')[:85])
except Exception as e:
    print('ERR', e)
"
echo ""
echo "=== what is the 8098 service ==="
sudo -n systemctl cat search-api 2>/dev/null | head -15 || ps aux | grep -E "pid.*620917" | head -3
sudo -n ls -la /opt/search-api/ 2>/dev/null | head -8
'''


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY, timeout=25,
                   look_for_keys=False, allow_agent=False)
    _, so, se = client.exec_command(TESTS, timeout=240)
    print(so.read().decode("utf-8", "replace")[:9000])
    err = se.read().decode("utf-8", "replace")[:400]
    if err.strip():
        print("[stderr]", err)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
