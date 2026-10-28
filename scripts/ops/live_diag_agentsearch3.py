#!/usr/bin/env python3
# LIVE-DIAG-003 (read-only reproduction): run the app's own provider+gate code
# against SearXNG for the exact failing/succeeding queries of step-86.
# No DB writes, no probe writes — pure HTTP reads + in-memory computation.
import json, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=120):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    return so.read().decode(errors="replace").strip(), se.read().decode(errors="replace").strip()

PY = r'''
import sys, json, urllib.parse, urllib.request
sys.path.insert(0, "/opt/agentic-engineering-system/src")
from research import providers as rp

QUERIES = [
    ("OK-217",  "Astro TypeScript template strict tsconfig specification"),
    ("OK-218",  "Astro config output static defineConfig documentation"),
    ("FAIL-219","Astro create typescript template devDependencies @astrojs/typescript"),
    ("FAIL-226","Astro npm create typescript template configuration guide"),
    ("FAIL-227","astro.config.mjs defineConfig output static example"),
    ("FAIL-228","astro tsconfig.json extends astro/tsconfigs/strict"),
    ("FAIL-235","Astro TypeScript setup guide official documentation"),
]

SEARX = "http://127.0.0.1:8888"

for tag, q in QUERIES:
    print("=" * 70)
    print("[%s] QUERY: %s" % (tag, q))
    lang = "ar" if rp._ARABIC_SCRIPT_RE.search(q) else "en"
    url = "%s/search?q=%s&format=json&language=%s" % (SEARX, urllib.parse.quote(q), lang)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": rp._USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        results = data.get("results", [])
        print("  searxng raw: %d results (language=%s)" % (len(results), lang))
        for item in results[:5]:
            print("    - title: %r" % (str(item.get("title",""))[:90]))
            print("      url:   %s" % str(item.get("url",""))[:90])
            print("      snip:  %r" % (str(item.get("content",""))[:110]))
        # now the app gate on these raw results
        mapped = [{"title": str(i.get("title","")), "url": str(i.get("url","")),
                   "snippet": str(i.get("content",""))[:300]} for i in results[:rp.MAX_SEARCH_RESULTS]]
        rep = rp.relevance_report(q, mapped)
        print("  GATE: tokens=%s" % rep["tokens"])
        print("        covered=%s -> %d/%d (required %d) strong_results=%d relevant=%s"
              % (rep["covered"], len(rep["covered"]), len(rep["tokens"]),
                 rep["required"], rep["strong_results"], rep["relevant"]))
        if mapped:
            r0 = rp.result_relevance(q, mapped[0])
            print("        first-result: hit=%s ratio=%s specific=%s strong=%s"
                  % (r0["hit"], r0["ratio"], r0["specific"], r0["strong"]))
    except Exception as e:
        print("  searxng raw ERR: %s: %s" % (type(e).__name__, e))
    # and the provider object end-to-end (as the app calls it)
    try:
        p = rp.SearxJsonSearchProvider(base_url="http://127.0.0.1:8888")
        res = p.search(q)
        print("  PROVIDER.search -> OK %d strong results: %s"
              % (len(res), [r["title"][:60] for r in res[:3]]))
    except Exception as e:
        print("  PROVIDER.search -> RAISE %s: %s" % (type(e).__name__, str(e)[:300]))
    print()
'''

o, e = run("cd /opt/agentic-engineering-system && python3 - <<'PYEOF'\n" + PY + "\nPYEOF")
print(o[:16000])
print("STDERR:", e[:800])

print("\n=== searxng engines enabled (settings.yml) ===")
o2, e2 = run("sudo -n grep -A3 'name:.*bing\\|name:.*brave\\|name:.*wikipedia' /etc/searxng/settings.yml | head -30; "
             "sudo -n journalctl -u searxng --since '2026-10-28 01:15' --no-pager 2>/dev/null | grep -iE 'error|timeout|exception' | tail -10")
print(o2[:3000] if o2 else "(none)")
ssh.close()
print("\nDIAG3 DONE")
