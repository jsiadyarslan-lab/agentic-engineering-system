#!/usr/bin/env python3
# LIVE-DIAG-006 (read-only): current SearXNG engine enablement + bing news
# capability tests (English/Arabic/repeat) + single vs multi token on bing.
import json, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=120):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    return so.read().decode(errors="replace").strip(), se.read().decode(errors="replace").strip()

print("=== 1. engines state in /etc/searxng/settings.yml ===")
o, e = run("sudo -n python3 -c \""
           "import yaml; d = yaml.safe_load(open('/etc/searxng/settings.yml')); "
           "[print('%-22s disabled=%-5s cats=%s' % (e2.get('name','?'), e2.get('disabled', False), e2.get('categories',''))) "
           "for e2 in d.get('engines', [])]\" 2>&1 | head -50")
print(o[:3000])

print("\n=== 2. bing news tests (repeat + Arabic + relevance) ===")
PY = r'''
import json, urllib.parse, urllib.request
SEARX = "http://127.0.0.1:8888"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

def q1(engine, query, lang="en"):
    url = "%s/search?q=%s&format=json&language=%s&engines=%s" % (
        SEARX, urllib.parse.quote(query), lang, urllib.parse.quote(engine))
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        res = d.get("results", [])
        return {"n": len(res), "unres": d.get("unresponsive_engines", []),
                "titles": [str(i.get("title",""))[:70] for i in res[:4]],
                "urls": [str(i.get("url",""))[:60] for i in res[:2]]}
    except Exception as ex:
        return {"n": -1, "err": str(ex)[:150]}

tests = [
    ("bing news", "knesset election results", "en"),
    ("bing news", "knesset election results", "en"),      # repeat (rate check)
    ("bing news", "نتائج انتخابات الكنيست", "ar"),         # Arabic
    ("bing news", "solar energy breakthrough", "en"),
    ("bing news", "news website design", "en"),
    ("bing", "conference", "en"),                          # single token again
    ("bing", "energy policy", "en"),                       # 2-token
    ("bing", "energy", "en"),                              # 1-token
]
for eng, q, lang in tests:
    r = q1(eng, q, lang)
    line = "%-11s q=%-28r lang=%s n=%-3d" % (eng, q[:26], lang, r["n"])
    if r["n"] >= 0:
        if r.get("unres"): line += " unres=%s" % str(r["unres"])[:80]
        line += "\n              titles: %s" % " ; ".join(r.get("titles", [])[:3])[:200]
    else:
        line += " ERR " + r.get("err", "")
    print(line)
'''
o, e = run("python3 - <<'PYEOF'\n" + PY + "\nPYEOF")
print(o[:4000])
print("STDERR:", e[:300])
ssh.close()
print("\nDIAG6 DONE")
