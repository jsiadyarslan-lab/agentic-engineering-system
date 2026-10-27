#!/bin/bash
# 007 — debug history rendering
set -u
WT=/home/z/my-project/ui007
PY=/home/z/.venv/bin/python3
PORT=8050
DB="$WT/runtime/ui-007.db"
cd "$WT"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-007-dbg.log 2>&1 &
SRV=$!
for i in $(seq 1 80); do curl -s -o /dev/null http://127.0.0.1:$PORT/health && break; sleep 0.5; done
ab() { agent-browser "$@"; }
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"

echo "== API ground truth =="
echo "conversations: $(curl -s $BASE/api/conversations | head -c 500)"
echo "messages c1: $(curl -s $BASE/api/conversations/1/messages | head -c 600)"

ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?dbg=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
echo "conv-items: $(ab get count '.conv-item' 2>&1)"
echo "conv-empty: $(ab eval "document.getElementById('conv-empty')?.textContent" 2>&1)"
echo "hash before: $(ab eval "location.hash" 2>&1)"
ab eval "document.querySelectorAll('.conv-item')[0].click()" > /dev/null 2>&1
ab wait 2500 > /dev/null 2>&1
echo "hash after: $(ab eval "location.hash" 2>&1)"
echo "chat-title: $(ab eval "document.getElementById('chat-title').textContent" 2>&1)"
echo "messages children: $(ab eval "JSON.stringify([...document.querySelectorAll('#messages > *')].map(e=>e.className))" 2>&1)"
echo "welcome display: $(ab eval "getComputedStyle(document.getElementById('welcome')).display" 2>&1)"
echo "history-loading present: $(ab get count '.history-loading' 2>&1)"
echo "network calls to conversations: $(ab network requests --filter conversations 2>&1 | tail -5)"
echo "--- console:"; ab console 2>&1 | tail -10
kill $SRV 2>/dev/null
echo done
