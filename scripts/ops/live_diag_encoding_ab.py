#!/usr/bin/env python3
# LIVE-DIAG-005 (read-only): controlled A/B — plus vs %20 encoding, language param,
# single vs multi token, and raw bing.com from host. Pinpoint where the query breaks.
import json, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=180):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    return so.read().decode(errors="replace").strip(), se.read().decode(errors="replace").strip()

print("=== 0. searxng version + journal errors ===")
o, e = run("sudo -n journalctl -u searxng --since '2026-10-28 01:10' --no-pager 2>/dev/null | grep -viE 'GET /search|access' | tail -15; "
           "cd /opt/searxng 2>/dev/null && sudo -n cat searx/version.py 2>/dev/null | grep -i version | head -2; "
           "curl -s http://127.0.0.1:8888/config | python3 -c 'import json,sys; d=json.load(sys.stdin); print(\"searxng_version:\", d.get(\"version\"))' 2>/dev/null")
print(o[:2000])

print("\n=== A/B: bing engine, encodings & params ===")
PY = r'''
import json, urllib.parse, urllib.request
SEARX = "http://127.0.0.1:8888"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

def raw(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        titles = [str(i.get("title",""))[:60] for i in d.get("results", [])[:4]]
        return len(d.get("results", [])), titles
    except Exception as ex:
        return -1, ["ERR %s: %s" % (type(ex).__name__, str(ex)[:100])]

Q = "climate conference"
tests = [
    ("plus,   lang=en", "/search?q=climate+conference&format=json&language=en&engines=bing"),
    ("pct20,  lang=en", "/search?q=climate%20conference&format=json&language=en&engines=bing"),
    ("plus,   no lang ", "/search?q=climate+conference&format=json&engines=bing"),
    ("plus,   lang=all", "/search?q=climate+conference&format=json&language=all&engines=bing"),
    ("single token conf", "/search?q=conference&format=json&language=en&engines=bing"),
    ("plus,   lang=en, startpage", "/search?q=climate+conference&format=json&language=en&engines=startpage"),
    ("pct20,  lang=en, startpage", "/search?q=climate%20conference&format=json&language=en&engines=startpage"),
    ("plus,   lang=en, mojeek", "/search?q=climate+conference&format=json&language=en&engines=mojeek"),
    ("plus,   lang=all, mojeek", "/search?q=climate+conference&format=json&language=all&engines=mojeek"),
    ("plus,   lang=en, mullvad", "/search?q=climate+conference&format=json&language=en&engines=mullvad"),
    ("plus,   lang=all, mullvad", "/search?q=climate+conference&format=json&language=all&engines=mullvad"),
    ("plus,   lang=en, ecosia", "/search?q=climate+conference&format=json&language=en&engines=ecosia"),
    ("plus,   lang=all, ecosia", "/search?q=climate+conference&format=json&language=all&engines=ecosia"),
    ("plus,   lang=en, mullvad, astro q", "/search?q=astro+typescript+template&format=json&language=en&engines=mullvad"),
]
for label, path in tests:
    n, titles = raw(SEARX + path)
    print("%-38s n=%-3d %s" % (label, n, " ; ".join(titles)[:170]))
'''
o, e = run("python3 - <<'PYEOF'\n" + PY + "\nPYEOF")
print(o[:5000])
print("STDERR:", e[:300])

print("\n=== raw bing.com from host (multi-token, plus) ===")
o, e = run("curl -s -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36' "
           "'https://www.bing.com/search?q=climate+conference&setlang=en' | python3 -c \""
           "import sys,re; h=sys.stdin.read(); "
           "ts=re.findall(r'<h2><a[^>]*>(.*?)</a></h2>', h)[:6]; "
           "print('titles:', ts if ts else 'NONE len=%d' % len(h))\"")
print(o[:1500])
ssh.close()
print("\nDIAG5 DONE")
