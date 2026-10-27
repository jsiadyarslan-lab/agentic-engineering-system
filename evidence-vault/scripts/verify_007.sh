#!/bin/bash
# 007 — verify VLM-flagged potential regressions
set -u
WT=/home/z/my-project/ui007
PY=/home/z/.venv/bin/python3
PORT=8052
DB="$WT/runtime/ui-007-after.db"
cd "$WT"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-007-verify.log 2>&1 &
SRV=$!
for i in $(seq 1 80); do curl -s -o /dev/null http://127.0.0.1:$PORT/health && break; sleep 0.5; done
ab() { agent-browser "$@"; }
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"
OUT=/home/z/my-project/download/ui-redesign-007/after

echo "== [V1] code block content integrity =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/#/chat/1" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
echo "md-pre text: $(ab eval "var p=document.querySelector('.md-pre'); p?JSON.stringify(p.textContent.slice(0,120)):'none'" 2>&1)"
echo "md-pre starts with: $(ab eval "var p=document.querySelector('.md-pre'); p?JSON.stringify(p.textContent.trim().slice(0,25)):'none'" 2>&1)"
echo "source line: $(ab eval "var p=document.querySelector('.md-pre'); p?JSON.stringify(p.textContent.split(String.fromCharCode(10))[0]):'none'" 2>&1)"
echo "API message content start: $(curl -s $BASE/api/conversations/1/messages | head -c 60)"

echo "== [V2] settings provider card buttons =="
ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 1000 > /dev/null 2>&1
ab eval "document.querySelector('.settings-tab[data-tab=providers]').click()" > /dev/null 2>&1
ab wait 1000 > /dev/null 2>&1
echo "pv-cards: $(ab get count '.pv-card' 2>&1)"
echo "pv-btn count: $(ab get count '.pv-btn' 2>&1)"
echo "pv-row count: $(ab get count '.pv-row' 2>&1)"
echo "cfg-cards: $(ab get count '.cfg-card' 2>&1)"
echo "cfg btns (inside cfg): $(ab eval "document.querySelectorAll('.cfg-card button').length" 2>&1)"
echo "pv-btn labels: $(ab eval "JSON.stringify([...document.querySelectorAll('.pv-btn')].map(b=>b.textContent.trim()).slice(0,10))" 2>&1)"
echo "pv-btn visible: $(ab eval "var b=document.querySelector('.pv-btn'); b?JSON.stringify({w:b.getBoundingClientRect().width,h:b.getBoundingClientRect().height,display:getComputedStyle(b).display}):'none'" 2>&1)"
ab screenshot "$OUT/settings-providers-verify-1440.png" > /dev/null 2>&1
echo "shot: settings-providers-verify-1440"
ab press Escape > /dev/null 2>&1

echo "== [V3] suggestion card contrast (computed) =="
ab open "$BASE/?v=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
echo "suggestion-title: $(ab eval "var e=document.querySelector('.suggestion-title'); JSON.stringify({color:getComputedStyle(e).color,size:getComputedStyle(e).fontSize})" 2>&1)"
echo "suggestion-desc: $(ab eval "var e=document.querySelector('.suggestion-desc'); JSON.stringify({color:getComputedStyle(e).color,size:getComputedStyle(e).fontSize})" 2>&1)"
echo "conv-item color: $(ab eval "var e=document.querySelector('.conv-item'); e?getComputedStyle(e).color:'none'" 2>&1)"
echo "body font: $(ab eval "getComputedStyle(document.body).fontFamily.slice(0,40)" 2>&1)"

echo "== [V4] factory tabs + agent accent check =="
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2200 > /dev/null 2>&1
echo "fc-tab active style: $(ab eval "var t=document.querySelector('.fc-tab.active'); t?JSON.stringify({color:getComputedStyle(t).color,border:getComputedStyle(t).borderBottomColor}):'none'" 2>&1)"
echo "factory title size: $(ab eval "getComputedStyle(document.querySelector('#factory-view .cc-title')).fontSize" 2>&1)"
echo "--- console:"; ab console 2>&1 | tail -4
echo "--- errors:"; ab errors 2>&1 | tail -3
kill $SRV 2>/dev/null
echo done
