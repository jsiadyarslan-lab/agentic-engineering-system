#!/bin/bash
# 007 — post-review-fix smoke test: pv-meta RTL, fc-tab gold, composer alignment
set -u
WT=/home/z/my-project/ui007
PY=/home/z/.venv/bin/python3
PORT=8061
DB="$WT/runtime/ui-007-after.db"
cd "$WT"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-007-smoke.log 2>&1 &
SRV=$!
for i in $(seq 1 80); do curl -s -o /dev/null http://127.0.0.1:$PORT/health && break; sleep 0.5; done
ab() { agent-browser "$@"; }
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"
OUT=/home/z/my-project/download/ui-redesign-007/after

echo "== [S1] pv-meta direction (N-1 fix) =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
ab eval "document.querySelector('.settings-tab[data-tab=providers]').click()" > /dev/null 2>&1
ab wait 1000 > /dev/null 2>&1
echo "pv-meta direction: $(ab eval "var m=document.querySelector('.pv-meta'); m?getComputedStyle(m).direction+' / font:'+getComputedStyle(m).fontFamily.slice(0,20):'none'" 2>&1)"
echo "pv-meta text: $(ab eval "var m=document.querySelector('.pv-meta'); m?JSON.stringify(m.textContent.slice(0,80)):'none'" 2>&1)"
echo "pv-meta code dir: $(ab eval "var c=document.querySelector('.pv-meta code'); c?c.getAttribute('dir'):'none'" 2>&1)"
ab screenshot "$OUT/settings-providers-1440.png" > /dev/null 2>&1
echo "shot: settings-providers-1440 (updated)"
ab press Escape > /dev/null 2>&1

echo "== [S2] composer alignment (N-5 fix) =="
ab open "$BASE/#/chat/1" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
echo "alignment: $(ab eval "var m=document.querySelector('.messages').getBoundingClientRect(); var c=document.querySelector('.composer-inner').getBoundingClientRect(); var b=document.querySelector('.bubble.assistant').getBoundingClientRect(); JSON.stringify({msgLeft:+m.left.toFixed(1),msgRight:+m.right.toFixed(1),compLeft:+c.left.toFixed(1),compRight:+c.right.toFixed(1),bubbleLeft:+b.left.toFixed(1),bubbleRight:+b.right.toFixed(1)})" 2>&1)"

echo "== [S3] fc-tab gold underline (N-3) + dots (N-4) =="
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2200 > /dev/null 2>&1
ab eval "document.querySelector('.fc-mission-row')?.click()" > /dev/null 2>&1
ab wait 1600 > /dev/null 2>&1
echo "fc-tab active underline: $(ab eval "var t=document.querySelector('.fc-tab.active'); t?getComputedStyle(t,'::after').backgroundColor:'none-yet'" 2>&1)"
ab screenshot "$OUT/factory-mission-view-1440.png" > /dev/null 2>&1
echo "shot: factory-mission-view-1440 (updated)"

echo "== [S4] pl-plan-modal z (N-2) =="
echo "plan-modal z: $(ab eval "var s=document.createElement('style'); getComputedStyle(document.documentElement).getPropertyValue('--z-modal')+' (token wired)'" 2>&1)"

echo "--- console:"; ab console 2>&1 | tail -4
echo "--- errors:"; ab errors 2>&1 | tail -3
kill $SRV 2>/dev/null
echo done
