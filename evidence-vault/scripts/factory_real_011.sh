#!/bin/bash
# AES-011 — factory view REAL interaction: proper nav click, health check, tabs
set -u
OUT=/home/z/my-project/download/live-reconciliation-011/live-verify
CREDS=$(cat /home/z/my-project/reproof-011-auth.txt)
AB="agent-browser"

python3 /home/z/my-project/scripts/tunnel_011_public.py > "$OUT/tunnel3.log" 2>&1 &
TUN=$!
sleep 4

$AB set credentials ${CREDS%%:*} ${CREDS#*:}
$AB set viewport 1440 900
$AB open http://127.0.0.1:18080/ > /dev/null
sleep 4

echo "=== click the factory nav button (data-nav=factory) ==="
$AB eval "document.querySelector('.side-nav-item[data-nav=factory]').click(); 'clicked'" 
sleep 3
$AB eval "JSON.stringify({hidden: document.querySelector('#factory-view').hidden, sys: document.querySelector('#factory-system-status').textContent, heading: (document.querySelector('#factory-view h1, #factory-view h2, .cc-title')||{textContent:null}).textContent})" | tee "$OUT/factory-real-state.json"

echo; echo "=== factory screenshot (real view) ==="
$AB screenshot "$OUT/accept-factory-1440-REAL.png"

echo; echo "=== factory quick actions + refresh buttons present? ==="
$AB eval "JSON.stringify({buttons: [...document.querySelectorAll('#factory-view button')].map(b=>b.textContent.trim()).filter(Boolean).slice(0,10)})" | tee "$OUT/factory-buttons.json"

echo; echo "=== back to chat via nav ==="
$AB eval "document.querySelector('.side-nav-item[data-nav=chat]').click(); 'ok'" > /dev/null
sleep 1
$AB errors > "$OUT/errors-final.txt" 2>&1; echo "page errors: $(wc -l < "$OUT/errors-final.txt")"
$AB console > "$OUT/console-final.txt" 2>&1; echo "console lines: $(wc -l < "$OUT/console-final.txt")"

$AB close
kill $TUN 2>/dev/null
echo "FACTORY REAL DONE"
