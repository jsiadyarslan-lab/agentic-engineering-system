#!/usr/bin/env python3
# W2-T22 pre-deploy offline gate validation (v2):
# On the server (read-only network reads, OLD code untouched):
#   - fetch raw Wikipedia results via the app's own provider class
#   - fetch raw SearXNG JSON, compact-mapped remotely
# Then locally apply the NEW repo gate code to decide chain stop.
import json, sys
import paramiko

REPO = "/home/z/my-project/repo"
sys.path.insert(0, REPO + "/src")
from research import providers as rp  # noqa: E402

QUERY = "اخبار انتخابات الكنسيت اليوم"

_client = paramiko.SSHClient()
_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
_client.connect("92.5.14.150", username="opc", key_filename="/tmp/oracle_key",
                timeout=20, look_for_keys=False, allow_agent=False)

def ssh(cmd, t=90):
    _, so, se = _client.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    return out, err

REMOTE = r'''
import sys, json
sys.path.insert(0, "/opt/agentic-engineering-system/src")
from research.providers import WikipediaSearchProvider, _USER_AGENT

QUERY = "اخبار انتخابات الكنسيت اليوم"
out = {}

# Wikipedia via the app's own provider class (network read only)
try:
    wiki = WikipediaSearchProvider()
    raw = wiki._search_one("ar", "https://ar.wikipedia.org/w/api.php", QUERY, 12)
    out["wiki_ar"] = [{"title": r["title"], "snippet": r["snippet"][:300]} for r in raw]
except Exception as e:
    out["wiki_ar"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}

# SearXNG raw
import urllib.parse, urllib.request
url = "http://127.0.0.1:8888/search?q=%s&format=json&language=ar" % urllib.parse.quote(QUERY)
try:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    out["searx"] = [{"title": str(i.get("title", "")),
                     "url": str(i.get("url", "")),
                     "snippet": str(i.get("content") or "")[:300]}
                    for i in data.get("results", [])[:10]]
except Exception as e:
    out["searx"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}

print("@@JSON@@")
print(json.dumps(out, ensure_ascii=False))
'''

out, err = ssh("python3 - <<'PYEOF'\n" + REMOTE + "\nPYEOF")
if err:
    print("STDERR:", err[:800])
payload = json.loads(out.split("@@JSON@@", 1)[1])

print("== Wikipedia(ar) raw via app provider ==")
wiki_ar = payload.get("wiki_ar")
if isinstance(wiki_ar, dict):
    print("  ERROR:", wiki_ar.get("error"))
elif isinstance(wiki_ar, list):
    print(f"  {len(wiki_ar)} results")
    for h in wiki_ar:
        print(f"    - {h['title'][:70]}")

print("\n== SearXNG raw ==")
searx = payload.get("searx")
if isinstance(searx, dict):
    print("  ERROR:", searx.get("error"))
elif isinstance(searx, list):
    print(f"  {len(searx)} results")

def gate_check(name, items):
    if not isinstance(items, list) or not items:
        print(f"\n== NEW gate on {name}: (none) ==")
        return None
    mapped = [{"title": str(i["title"]),
               "url": str(i.get("url") or "https://ar.wikipedia.org/wiki/x"),
               "snippet": str(i.get("snippet") or "")}
              for i in items]
    rep = rp.relevance_report(QUERY, mapped)
    print(f"\n== NEW gate on {name} ==")
    print(f"  count={len(mapped)} covered={rep['covered']} "
          f"strong={rep['strong_results']}/{len(mapped)} "
          f"required={rep['required']} relevant={rep['relevant']}")
    for i, item in enumerate(mapped[:10]):
        r0 = rp.result_relevance(QUERY, item)
        print(f"    {i+1}. {item['title'][:65]!r}")
        print(f"       hit={r0['hit']} strong={r0['strong']}")
    return rep

rep_w = gate_check("Wikipedia(ar)", wiki_ar)
rep_s = gate_check("SearXNG", searx)

print("\n== CHAIN VERDICT (id order: 3=Wikipedia -> 4=SearXNG -> 5=API) ==")
if rep_w and rep_w["relevant"]:
    print("  Wikipedia passes -> chain STOPS at Wikipedia (encyclopedic sources)")
elif rep_w is not None:
    print("  Wikipedia rejected -> falls through to SearXNG")
if rep_s and rep_s["relevant"]:
    print("  SearXNG passes with live news" + (" (serves)" if not (rep_w and rep_w["relevant"]) else " (would serve if wikipedia failed)"))
elif rep_s is not None:
    print("  SearXNG rejected -> falls to Search API")

_client.close()
