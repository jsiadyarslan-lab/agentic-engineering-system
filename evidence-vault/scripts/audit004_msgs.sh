#!/bin/bash
# AES-UI-PREMIUM-REDESIGN-004 — final probe: open the conversation WITH messages
set -u
cd /home/z/my-project/ui-work
DB=runtime/ui-redesign.db
PORT=8040

PYTHONPATH=src AGenthubV2_DB_PATH=$DB /home/z/.venv/bin/python3 -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-audit004c.log 2>&1 &
SRV=$!
for i in $(seq 1 60); do curl -s http://127.0.0.1:$PORT/health | grep -q '"ok"' && break; sleep 0.5; done
if ! curl -s http://127.0.0.1:$PORT/health | grep -q '"ok"'; then
  PYTHONPATH=src AGenthubV2_DB_PATH=$DB /home/z/.venv/bin/python3 -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-audit004c.log 2>&1 &
  SRV=$!
  for i in $(seq 1 60); do curl -s http://127.0.0.1:$PORT/health | grep -q '"ok"' && break; sleep 0.5; done
fi
curl -s http://127.0.0.1:$PORT/health | grep -q '"ok"' && echo "== server CONFIRMED" || { echo "== SERVER FAILED"; exit 1; }

ab() { agent-browser "$@"; }
STAMP=$(date +%s)
ab open "http://127.0.0.1:$PORT/?fresh=$STAMP" > /dev/null 2>&1
ab set viewport 1440 900 > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1

echo "== click conversation WITH 4 seeded messages =="
ab eval "var target=[...document.querySelectorAll('.conv-item')].find(n=>n.textContent.includes('مراجعة معمارية')); target? target.click(): 'NOT-FOUND'" > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
echo "bubbles rendered (expect 4): $(ab get count '.bubble' 2>&1)"
echo "bubble classes: $(ab eval "JSON.stringify([...document.querySelectorAll('.bubble')].map(e=>e.className))" 2>&1)"
echo "first bubble text: $(ab eval "var f=[...document.querySelectorAll('.bubble')][0]; f? f.textContent.slice(0,80) : 'NONE'" 2>&1)"
echo "markdown bold rendered (coordinator msg): $(ab get count '.bubble strong, .bubble b' 2>&1)"
ab screenshot "/home/z/my-project/download/ui-redesign/audit004/chat-seeded-messages-1440.png" > /dev/null 2>&1
echo "shot: chat-seeded-messages-1440.png"
echo "page errors: $(ab errors 2>&1 | tail -3)"
echo "console: $(ab console 2>&1 | tail -5)"

kill $SRV 2>/dev/null
echo "== done =="
