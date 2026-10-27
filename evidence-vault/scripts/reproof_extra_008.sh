#!/bin/bash
# AES-UI-PREMIUM-REDESIGN-008 — targeted follow-up checks
# X1: BUG-04 empty-note exact text (all .history-loading elements, longer wait)
# X2: no-provider error card full text + .eb-btn presence scan
set -u
WT=/home/z/my-project/ui007
PY=/home/z/.venv/bin/python3
PORT=8072
OUT="$WT/docs/evidence/UI007_evidence/reproof-008"
LOG="$OUT/browser-session-extra.txt"
DB="$WT/runtime/ui-008-reproof.db"
cd "$WT"
{
echo "# AES-UI-PREMIUM-REDESIGN-008 — follow-up checks (BUG-04 empty note text; error card text)"
echo "# date(UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "# commit: $(git rev-parse HEAD)"
echo "# runtime: uvicorn 127.0.0.1:$PORT, DB reused from re-proof session (conv 5 = empty)"
echo
} > "$LOG"

AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-008-extra.log 2>&1 &
SRV=$!
for i in $(seq 1 80); do curl -s -o /dev/null "http://127.0.0.1:$PORT/health" && break; sleep 0.5; done
ab() { agent-browser "$@"; }
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"

echo "== [X1] BUG-04: every .history-loading text on existing-but-empty conversation #/chat/5 ==" >> "$LOG"
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/#/chat/5" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 3000 > /dev/null 2>&1
echo "history-loading texts: $(ab eval "JSON.stringify([...document.querySelectorAll('.history-loading')].map(function(e){return e.textContent.trim().slice(0,90)}))" 2>&1)" >> "$LOG"
echo "messages children: $(ab eval "document.getElementById('messages').children.length" 2>&1)" >> "$LOG"
ab screenshot "$OUT/shots/chat-empty-conv-1440.png" > /dev/null 2>&1
echo "shot: chat-empty-conv-1440 (refreshed)" >> "$LOG"

echo >> "$LOG"
echo "== [X2] no-provider send: full error card text + .eb-btn scan ==" >> "$LOG"
ab open "$BASE/?x=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab eval "var i=document.getElementById('input'); i.value='اختبر'; i.dispatchEvent(new Event('input',{bubbles:true})); 'ok'" > /dev/null 2>&1
ab eval "document.getElementById('send').click()" > /dev/null 2>&1
ab wait 7000 > /dev/null 2>&1
echo "sys-card.error text: $(ab eval "var e=document.querySelector('.sys-card.error'); e?JSON.stringify(e.textContent.replace(/\s+/g,' ').slice(0,150)):'none'" 2>&1)" >> "$LOG"
echo "eb-btn in DOM: $(ab eval "document.querySelectorAll('.eb-btn').length" 2>&1)" >> "$LOG"
ab screenshot "$OUT/shots/chat-error-no-provider-1440.png" > /dev/null 2>&1
echo "shot: chat-error-no-provider-1440 (refreshed)" >> "$LOG"

echo >> "$LOG"
echo "--- console (expect empty):" >> "$LOG"
ab console 2>&1 | tail -3 >> "$LOG"
echo "--- errors (expect empty):" >> "$LOG"
ab errors 2>&1 | tail -3 >> "$LOG"

kill $SRV 2>/dev/null
ab close > /dev/null 2>&1
echo "== done ==" >> "$LOG"
cat "$LOG"
