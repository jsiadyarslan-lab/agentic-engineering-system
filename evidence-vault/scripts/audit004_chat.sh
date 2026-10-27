#!/bin/bash
# AES-UI-PREMIUM-REDESIGN-004 — chat real-data re-verification (after explicit seeding)
set -u
cd /home/z/my-project/ui-work
DB=runtime/ui-redesign.db
PORT=8040
OUT=/home/z/my-project/download/ui-redesign/audit004

echo "== [0] explicit seed of isolated DB =="
/home/z/.venv/bin/python3 /home/z/my-project/scripts/seed_audit004.py 2>&1

PYTHONPATH=src AGenthubV2_DB_PATH=$DB /home/z/.venv/bin/python3 -m uvicorn src.api/routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-audit004b.log 2>&1 &
SRV=$!
for i in $(seq 1 60); do curl -s http://127.0.0.1:$PORT/health | grep -q '"ok"' && break; sleep 0.5; done
if ! curl -s http://127.0.0.1:$PORT/health | grep -q '"ok"'; then
  echo "!! first start failed (log tail):"; tail -3 /tmp/aes-audit004b.log
  PYTHONPATH=src AGenthubV2_DB_PATH=$DB /home/z/.venv/bin/python3 -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-audit004b.log 2>&1 &
  SRV=$!
  for i in $(seq 1 60); do curl -s http://127.0.0.1:$PORT/health | grep -q '"ok"' && break; sleep 0.5; done
fi
curl -s http://127.0.0.1:$PORT/health | grep -q '"ok"' && echo "== server CONFIRMED up on port $PORT" || { echo "== SERVER FAILED"; exit 1; }

ab() { agent-browser "$@"; }

echo "== API ground truth =="
echo "/api/conversations: $(curl -s http://127.0.0.1:$PORT/api/conversations | head -c 500)"

STAMP=$(date +%s)
ab open "http://127.0.0.1:$PORT/?fresh=$STAMP" > /dev/null 2>&1
ab set viewport 1440 900 > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1

echo "== [1] sidebar conversations (real API data) =="
echo "conv-items: $(ab get count '.conv-item' 2>&1)"
echo "conv titles: $(ab eval "JSON.stringify([...document.querySelectorAll('.conv-text')].map(e=>e.textContent.trim()))" 2>&1)"

echo "== [2] open first conversation → messages render =="
ab eval "document.querySelector('.conv-item').click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
echo "bubbles rendered: $(ab get count '.bubble' 2>&1)"
echo "bubble roles: $(ab eval "JSON.stringify([...document.querySelectorAll('.bubble')].map(e=>e.className))" 2>&1)"
ab screenshot "$OUT/chat-with-messages-1440.png" > /dev/null 2>&1
echo "shot: chat-with-messages-1440.png"

echo "== [3] live send → honest outcome with real bubbles =="
echo "bubbles before send: $(ab get count '.bubble' 2>&1)"
ab eval "var i=document.getElementById('input'); i.value='رسالة تدقيق 004 من متصفح حقيقي'; i.dispatchEvent(new Event('input',{bubbles:true})); 'typed'" > /dev/null 2>&1
ab eval "document.getElementById('send').click()" > /dev/null 2>&1
ab wait 6000 > /dev/null 2>&1
echo "bubbles after send: $(ab get count '.bubble' 2>&1)"
echo "last bubble text: $(ab eval "var zz=[...document.querySelectorAll('.bubble')].pop(); zz? zz.textContent.slice(0,160) : 'NONE'" 2>&1)"
echo "error elements: $(ab get count '[class*=error]' 2>&1)"
echo "page errors: $(ab errors 2>&1 | tail -4)"
echo "console tail: $(ab console 2>&1 | tail -6)"

echo "== [4] factory quick re-check (overview real data intact) =="
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2500 > /dev/null 2>&1
echo "DOM stats: $(ab eval "JSON.stringify({missionRows: document.querySelectorAll('.fc-mission-row').length, stats: [...document.querySelectorAll('.fc-stat-value')].map(e=>e.textContent.trim())})" 2>&1)"
echo "console after factory: $(ab console 2>&1 | tail -4)"
echo "page errors (whole session): $(ab errors 2>&1 | tail -4)"

kill $SRV 2>/dev/null
echo "== done =="
