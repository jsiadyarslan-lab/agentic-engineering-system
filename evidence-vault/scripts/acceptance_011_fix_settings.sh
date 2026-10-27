#!/bin/bash
# AES-011 — REDO settings interaction with the CORRECT selector (#settings-open / #settings-drawer)
set -u
OUT=/home/z/my-project/download/live-reconciliation-011/fix-500/live-verify
CREDS=$(cat /home/z/my-project/reproof-011b-auth.txt)
AB="agent-browser"

python3 /home/z/my-project/scripts/tunnel_011_public.py > "$OUT/tunnel-redo.log" 2>&1 &
TUN=$!
sleep 4

$AB set credentials ${CREDS%%:*} ${CREDS#*:}
$AB set viewport 1440 900
$AB open http://127.0.0.1:18080/ > /dev/null
sleep 5

echo "===== INTERACTION 2 (redo): settings drawer open + Esc close ====="
echo "--- closed state before ---"
$AB eval "JSON.stringify({drawerHiddenBefore: document.querySelector('#settings-drawer').hidden})"
echo "--- click the gear (#settings-open) ---"
$AB eval "document.querySelector('#settings-open').click(); 'clicked'"
sleep 2
$AB eval "JSON.stringify({drawerHiddenAfterOpen: document.querySelector('#settings-drawer').hidden, drawerVisible: !!document.querySelector('#settings-drawer:not([hidden])'), tabs: [...document.querySelectorAll('#settings-tabs button, .settings-tabs button')].map(b=>b.textContent.trim()).slice(0,8)})" | tee "$OUT/settings-open.json"
$AB screenshot "$OUT/accept-settings-1440-FIX.png"

echo "--- press Escape ---"
$AB press Escape
sleep 1
$AB eval "JSON.stringify({drawerHiddenAfterEsc: document.querySelector('#settings-drawer').hidden})" | tee "$OUT/settings-esc.json"

echo "--- console/errors after interactions ---"
$AB console > "$OUT/console-redo.txt" 2>&1; echo "console lines: $(wc -l < "$OUT/console-redo.txt")"
$AB errors > "$OUT/errors-redo.txt" 2>&1; echo "page error lines: $(wc -l < "$OUT/errors-redo.txt")"

$AB close
kill $TUN 2>/dev/null
echo "SETTINGS REDO DONE"
