#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3-ENGINE3 — قراءة فقط: اختبار جودة كل محرك للاستعلامات الفاشلة + Search API 8098."""
import sys

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

TESTS = r'''
Q1="react+package.json+peer+dependencies"
Q2="Next.js+14+package.json+dependencies+typescript"
echo "=== engine-by-engine quality for Q1/Q2 ==="
for eng in mojeek oscar mwmbr mwmbl brave qwant startpage wikipedia_en mdn github pypi docker\ hub; do
  for q in "$Q1" "$Q2"; do
    out=$(curl -s "http://127.0.0.1:8888/search?q=$q&format=json&language=en&engines=$eng" 2>/dev/null)
    echo "$out" | python3 -c "
import sys, json
eng = '$eng'
q = '$q'[:20]
try:
    d = json.load(sys.stdin)
    res = d.get('results', [])
    titles = [(r.get('title') or '')[:55] for r in res[:3]]
    print('%-12s %-20s n=%-3d %s' % (eng, q, len(res), ' || '.join(titles)[:150]))
except Exception as e:
    print('%-12s %-20s ERR %s' % (eng, q, str(e)[:60]))
"
  done
done
echo ""
echo "=== what is on 8098 (Search API) ==="
sudo -n ss -tlnp | grep 8098
curl -s -X POST "http://127.0.0.1:8098/search" -H "Content-Type: application/json" -d '{"query":"react package.json peer dependencies","q":"react package.json peer dependencies","max_results":8}' | head -c 1200
echo ""
echo ""
echo "=== full enabled engine list (it/software categories) ==="
curl -s "http://127.0.0.1:8888/config" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for e in d.get('engines', []):
    if e.get('enabled', False) and ('it' in e.get('categories', []) or 'packages' in e.get('categories', [])):
        print('-', e.get('name'), '|', ','.join(e.get('categories', [])))
"
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
