#!/bin/bash
# 007 — re-capture chat content shots with correct assistant-role seed
set -u
WT=/home/z/my-project/ui007
PY=/home/z/.venv/bin/python3
PORT=8050
OUT=/home/z/my-project/download/ui-redesign-007/baseline
DB="$WT/runtime/ui-007.db"
rm -f "$DB"
AGenthubV2_DB_PATH="$DB" PYTHONPATH="$WT/src" "$PY" /home/z/my-project/scripts/seed_ui_007.py 2>&1 | tail -1
cd "$WT"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-007-recap.log 2>&1 &
SRV=$!
for i in $(seq 1 80); do curl -s -o /dev/null http://127.0.0.1:$PORT/health && break; sleep 0.5; done
ab() { agent-browser "$@"; }
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"

ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?recap=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
echo "sidebarW: $(ab eval "document.getElementById('sidebar').getBoundingClientRect().width" 2>&1)"
ab open "$BASE/#/chat/1" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
echo "chat-title: $(ab eval "document.getElementById('chat-title').textContent.slice(0,40)" 2>&1)"
echo "bubbles: $(ab get count '.bubble' 2>&1), assistant: $(ab get count '.bubble.assistant' 2>&1)"
echo "md-table: $(ab get count '.md-table-wrap' 2>&1), md-code: $(ab get count '.md-code' 2>&1), md-list: $(ab get count '.md-list' 2>&1)"
ab screenshot "$OUT/pop chat-long-ar-1440.png" > /dev/null 2>&1
ab screenshot --full "$OUT/pop chat-long-ar-1440-full.png" > /dev/null 2>&1
echo "shot: chat-long-ar-1440 + full"
ab eval "location.hash='#/chat/2'" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
echo "en-title: $(ab eval "document.getElementById('chat-title').textContent.slice(0,40)" 2>&1)"
ab screenshot "$OUT/pop chat-en-1440.png" > /dev/null 2>&1
echo "shot: chat-en-1440"

# tablet + mobile with content (fresh loads, viewport set BEFORE open)
ab set viewport 768 1024 > /dev/null 2>&1
ab open "$BASE/?t=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1600 > /dev/null 2>&1
echo "auto-restored conv bubbles (768): $(ab get count '.bubble' 2>&1)"
ab screenshot "$OUT/pop tablet-chat-content-768.png" > /dev/null 2>&1
echo "shot: tablet-chat-content-768"

ab set viewport 390 844 > /dev/null 2>&1
ab open "$BASE/?m=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1600 > /dev/null 2>&1
echo "auto-restored conv bubbles (390): $(ab get count '.bubble' 2>&1)"
echo "390 hOverflow: $(ab eval "document.documentElement.scrollWidth > innerWidth" 2>&1)"
ab screenshot "$OUT/pop mobile-chat-content-390.png" > /dev/null 2>&1
echo "shot: mobile-chat-content-390"
echo "md table visible on 390: $(ab eval "var t=document.querySelector('.md-table-wrap'); t?JSON.stringify({w:t.getBoundingClientRect().width,scrollable:t.scrollWidth>t.clientWidth}):'none'" 2>&1)"

echo "--- console:"; ab console 2>&1 | tail -6
echo "--- errors:"; ab errors 2>&1 | tail -4
kill $SRV 2>/dev/null
echo "== done recap =="
