#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3-ENGINE5 — قراءة فقط: قائمة محركات general المفعلة + اختبار عزل لكل محرك + إصدار SearXNG."""
import sys

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

TESTS = r'''
echo "=== enabled engines in general category ==="
curl -s "http://127.0.0.1:8888/config" | python3 -c "
import sys, json
d = json.load(sys.stdin)
gens = [e for e in d.get('engines', []) if e.get('enabled', False) and 'general' in e.get('categories', [])]
for e in gens:
    print('- %-22s categories=%s' % (e.get('name'), ','.join(e.get('categories', []))))
print('TOTAL general engines:', len(gens))
"
echo ""
echo "=== searxng version ==="
curl -s "http://127.0.0.1:8888/config" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('version:', d.get('version', '?'))
"
echo ""
echo "=== isolation test per general engine (Q2: next.js) ==="
for eng in wikipedia wikidata "bing\ news" lingva currency mojeek oscar mwmbl startpage; do
  curl -s "http://127.0.0.1:8888/search?q=Next.js+14+package.json+dependencies+typescript&format=json&language=en&engines=$eng" | python3 -c "
import sys, json
eng = '$eng'
try:
    d = json.load(sys.stdin)
    res = d.get('results', [])
    unresp = [u[0] if isinstance(u, list) else str(u) for u in d.get('unresponsive_engines', [])]
    titles = [(r.get('title') or '')[:40] for r in res[:3]]
    print('%-12s n=%-3d unresp=%s | %s' % (eng, len(res), unresp, ' || '.join(titles)[:130]))
except Exception as e:
    print('%-12s ERR' % eng)
"
done
echo ""
echo "=== full settings.yml ==="
sudo -n cat /etc/searxng/settings.yml
'''


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY, timeout=25,
                   look_for_keys=False, allow_agent=False)
    _, so, se = client.exec_command(TESTS, timeout=240)
    print(so.read().decode("utf-8", "replace")[:10000])
    err = se.read().decode("utf-8", "replace")[:400]
    if err.strip():
        print("[stderr]", err)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
