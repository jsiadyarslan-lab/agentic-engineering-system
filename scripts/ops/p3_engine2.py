#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3-ENGINE2 — قراءة فقط: أي محركات ترد على الاستعلام الافتراضي + جودة نتائج bing."""
import sys

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

TESTS = r'''
echo "=== default query: which engines responded ==="
curl -s "http://127.0.0.1:8888/search?q=react+package.json+peer+dependencies&format=json&language=en" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('results:', len(d.get('results', [])))
print('unresponsive:', d.get('unresponsive_engines', []))
infobox = d.get('infoboxes', [])
if infobox:
    print('infobox:', str(infobox)[:150])
for r in d.get('results', [])[:5]:
    print('-', (r.get('title') or '')[:70], '|', (r.get('url') or '')[:60], '| eng:', r.get('engine', ''))
"
echo ""
echo "=== bing engine quality check ==="
curl -s "http://127.0.0.1:8888/search?q=react+package.json+peer+dependencies&format=json&language=en&engines=bing" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('results:', len(d.get('results', [])))
for r in d.get('results', [])[:8]:
    print('-', (r.get('title') or '')[:80])
    print('  url:', (r.get('url') or '')[:90])
"
echo ""
echo "=== brave engine quality check ==="
curl -s "http://127.0.0.1:8888/search?q=Next.js+14+package.json+dependencies+typescript&format=json&language=en&engines=brave" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('results:', len(d.get('results', [])))
for r in d.get('results', [])[:8]:
    print('-', (r.get('title') or '')[:80])
    print('  url:', (r.get('url') or '')[:90])
"
echo ""
echo "=== startpage quality check ==="
curl -s "http://127.0.0.1:8888/search?q=TypeScript+5.4+react+tailwind+setup&format=json&language=en&engines=startpage" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('results:', len(d.get('results', [])))
for r in d.get('results', [])[:6]:
    print('-', (r.get('title') or '')[:80])
    print('  url:', (r.get('url') or '')[:90])
"
echo ""
echo "=== current search settings table ==="
sudo -n python3 - <<'PYEOF'
import sqlite3, json
con = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
rows = con.execute("SELECT key, substr(value,1,300) as v FROM settings WHERE key LIKE '%search%' OR key LIKE '%searx%'").fetchall()
for r in rows:
    print(dict(r))
PYEOF
'''


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY, timeout=25,
                   look_for_keys=False, allow_agent=False)
    _, so, se = client.exec_command(TESTS, timeout=180)
    print(so.read().decode("utf-8", "replace")[:8000])
    err = se.read().decode("utf-8", "replace")[:400]
    if err.strip():
        print("[stderr]", err)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
