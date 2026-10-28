#!/usr/bin/env python3
# LIVE-DIAG-004 (read-only): SearXNG engine battery — which engines actually
# answer from this host right now? Uses SearXNG's per-engine query parameter,
# no settings changes. Also checks whether results VARY per query (cache check).
import json, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=180):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    return so.read().decode(errors="replace").strip(), se.read().decode(errors="replace").strip()

PY = r'''
import json, urllib.parse, urllib.request

SEARX = "http://127.0.0.1:8888"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

def q1(engine, query):
    url = "%s/search?q=%s&format=json&language=en&engines=%s" % (
        SEARX, urllib.parse.quote(query), urllib.parse.quote(engine))
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        results = data.get("results", [])
        unres = data.get("unresponsive_engines", [])
        titles = [str(i.get("title",""))[:55] for i in results[:3]]
        return {"engine": engine, "n": len(results), "unresponsive": unres, "titles": titles}
    except Exception as e:
        return {"engine": engine, "n": -1, "err": "%s: %s" % (type(e).__name__, str(e)[:120])}

# A: variance check on bing (same engine, two very different queries)
print("### A. bing variance check (canned page?)")
a1 = q1("bing", "solar panel efficiency 2026")
a2 = q1("bing", "chocolate cake recipe")
print(json.dumps(a1, ensure_ascii=False)[:400])
print(json.dumps(a2, ensure_ascii=False)[:400])
print("SAME_TITLES:", a1.get("titles") == a2.get("titles"))

# B: engine battery on a neutral query
print()
print("### B. engine battery (query: climate conference)")
ENGINES = ["bing", "brave", "startpage", "mojeek", "mullvad", "presearch",
           "wikipedia", "duckduckgo", "google", "qwant", "ecosia",
           "bing news", "google news", "duckduckgo news", "yahoo news",
           "wikidata", "microsoft"]
for eng in ENGINES:
    r = q1(eng, "climate conference")
    line = "%-20s n=%-3d" % (r["engine"], r["n"])
    if r["n"] >= 0:
        if r.get("unresponsive"):
            line += " unresponsive=%s" % (r["unresponsive"])[:120]
        line += " | " + " ; ".join(r.get("titles", [])[:2])
    else:
        line += " ERR " + r.get("err", "")
    print(line[:220])

# C: news engines with a news query (the owner's real need)
print()
print("### C. news engines (query: knesset election results)")
for eng in ["bing news", "google news", "duckduckgo news", "yahoo news",
            "startpage", "brave", "mojeek", "mullvad"]:
    r = q1(eng, "knesset election results")
    line = "%-20s n=%-3d" % (r["engine"], r["n"])
    if r["n"] >= 0:
        if r.get("unresponsive"):
            line += " unresp=%s" % (r["unresponsive"])[:100]
        line += " | " + " ; ".join(r.get("titles", [])[:2])
    else:
        line += " ERR " + r.get("err", "")
    print(line[:220])
'''

o, e = run("python3 - <<'PYEOF'\n" + PY + "\nPYEOF")
print(o[:9000])
print("STDERR:", e[:500])
ssh.close()
print("\nDIAG4 DONE")
