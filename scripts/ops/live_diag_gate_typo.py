#!/usr/bin/env python3
# LIVE-DIAG-0328-D (read-only): reproduce the gate behavior for the owner's
# exact typo'd query "اخبار انتخابات الكنسيت اليوم" (الكنسيت vs الكنيست)
# through SearXNG live results + the app's own relevance gate.
# No DB writes, no probe writes — pure reads.
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
    ("owner-typo",  "اخبار انتخابات الكنسيت اليوم"),
    ("owner-correct","اخبار انتخابات الكنيست اليوم"),
    ("thin-followup","انت و ملخص"),
]

SEARX = "http://127.0.0.1:8888"

for tag, q in QUERIES:
    print("=" * 70)
    print("[%s] QUERY: %s" % (tag, q))
    toks = rp.query_tokens(q)
    print("  tokens: %s" % toks)
    print("  generic among them: %s" % [t for t in toks if t in rp._GENERIC_TOKENS])
    lang = "ar" if rp._ARABIC_SCRIPT_RE.search(q) else "en"
    url = "%s/search?q=%s&format=json&language=%s" % (SEARX, urllib.parse.quote(q), lang)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": rp._USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        results = data.get("results", [])
        print("  searxng raw: %d results (language=%s)" % (len(results), lang))
        mapped = [{"title": str(i.get("title","")), "url": str(i.get("url","")),
                   "snippet": str(i.get("content",""))[:300]} for i in results[:rp.MAX_SEARCH_RESULTS]]
        for i, item in enumerate(mapped[:6]):
            r0 = rp.result_relevance(q, item)
            print("    %d. title: %r" % (i+1, item["title"][:80]))
            print("       hit=%s ratio=%s specific=%s strong=%s"
                  % (r0["hit"], r0["ratio"], r0["specific"], r0["strong"]))
        rep = rp.relevance_report(q, mapped)
        print("  GATE: covered=%s -> %d/%d (required %d) strong_results=%d relevant=%s"
              % (rep["covered"], len(rep["covered"]), len(rep["tokens"]),
                 rep["required"], rep["strong_results"], rep["relevant"]))
    except Exception as e:
        print("  ERROR: %r" % e)
'''

cmd = "cd /opt/agentic-engineering-system && python3 - <<'PYEOF'\n" + PY + "\nPYEOF"
out, err = run(cmd)
print(out)
if err:
    print("STDERR:", err[:1500])
ssh.close()
