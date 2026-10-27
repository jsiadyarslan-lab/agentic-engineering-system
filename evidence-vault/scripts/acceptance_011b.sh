#!/bin/bash
# AES-011 — follow-up: in-browser sha256 (fixed eval) + warm HAR statuses + factory state
set -u
OUT=/home/z/my-project/download/live-reconciliation-011/live-verify
CREDS=$(cat /home/z/my-project/reproof-011-auth.txt)
AB="agent-browser"

python3 /home/z/my-project/scripts/tunnel_011_public.py > "$OUT/tunnel2.log" 2>&1 &
TUN=$!
sleep 4

$AB set credentials ${CREDS%%:*} ${CREDS#*:}
$AB set viewport 1440 900
$AB open http://127.0.0.1:18080/ > /dev/null
sleep 4

echo "=== in-browser SHA-256 vs git 947e6e55 (fixed) ==="
$AB eval "(async () => {
  const expect = {
    'theme.css':'91e070f7a67c5b6ac252393baf3587e6bfb7b1750a4f3f2d5ab3ca50490b9a28',
    'styles.css':'707efdcce5ad55eb1283251c35e1350428ec49f55aca77c689c24afc799ca6be',
    'app.js':'477313bc312380445ea339cdc93d89fbdd38077ee7ba58ba71abeef988bc424b',
    'app-shell.css':'9cdc1b9dc9a45bd59d107512b774ecc42ae530c12965dcf1d321e95a2c894d7f',
    'factory-control.css':'430246ed0ff22c4bca2307d058861890188d92df810023b2d307478992ee61fa',
    'factory-control.js':'34de0270cb38ad7ec5e8579f5f6a186cafed43970fb787121cdf81346e07c700'
  };
  const hex = b => [...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,'0')).join('');
  const out = {};
  for (const [name, want] of Object.entries(expect)) {
    const resp = await fetch('/static/' + name + '?v=947e6e55', {cache:'force-cache'});
    const buf = await resp.arrayBuffer();
    const got = hex(await crypto.subtle.digest('SHA-256', buf));
    out[name] = {status: resp.status, got: got.slice(0,16), want: want.slice(0,16), match: got === want};
  }
  return JSON.stringify(out);
})()" | tee "$OUT/browser-sha256-vs-git.json"

echo; echo "=== server-side fingerprints via the same public path (curl) ==="
for f in theme.css styles.css app.js app-shell.css factory-control.css factory-control.js index.html; do
  if [ "$f" = "index.html" ]; then url="http://127.0.0.1:18080/"; else url="http://127.0.0.1:18080/static/$f?v=947e6e55"; fi
  h=$(curl -s --max-time 8 -u "$CREDS" "$url" | sha256sum | cut -c1-64)
  echo "$f $h" | tee -a "$OUT/server-served-sha256.txt"
done

echo; echo "=== API: is a mission active? (factory state context) ==="
curl -s --max-time 8 -u "$CREDS" http://127.0.0.1:18080/api/projects/runs/active | head -c 300 | tee "$OUT/runs-active.json"; echo
curl -s --max-time 8 -u "$CREDS" http://127.0.0.1:18080/api/projects | head -c 300 | tee "$OUT/projects.json"; echo

echo; echo "=== factory view recheck (wait longer for live-events socket) ==="
$AB find text "المصنع" click 2>/dev/null || true
sleep 6
$AB eval "JSON.stringify({text: ((document.querySelector('#factory-view')||document.body).innerText||'').replace(/\s+/g,' ').slice(0,300)})" | tee "$OUT/factory-live2.json"

echo; echo "=== warm HAR analysis (statuses) ==="
HAR=$(ls -t /home/z/.agent-browser/tmp/har/har-*.har 2>/dev/null | head -2)
echo "har files: $HAR"
cp $HAR "$OUT/" 2>/dev/null
python3 - <<'PY'
import json, glob, os
files = sorted(glob.glob("/home/z/my-project/download/live-reconciliation-011/live-verify/har-*.har"), key=os.path.getmtime)
for fp in files[-1:]:
    data = json.load(open(fp))
    entries = data["log"]["entries"]
    print(f"--- {os.path.basename(fp)}: {len(entries)} entries ---")
    from collections import Counter
    c = Counter()
    for e in entries:
        u = e["request"]["url"]
        st = e["response"]["status"]
        if "/static/" in u or u.rstrip("/").endswith(":18080") or u.endswith("18080/"):
            name = u.split("/static/")[-1] if "/static/" in u else "(index /)"
            c[(name.split("?")[0], st)] += 1
    for (name, st), n in sorted(c.items()):
        print(f"  {name:40s} {st}  x{n}")
PY

$AB close
kill $TUN 2>/dev/null
echo "FOLLOW-UP DONE"
