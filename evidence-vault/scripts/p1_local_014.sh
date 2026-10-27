#!/bin/bash
# AES-014 — قبول المرحلة الأولى محليًا: الهندسة الجديدة + تفاعل حي
set -u
REPO=/home/z/my-project/wt-014
PY=/home/z/.venv/bin/python3
PORT=8024
DB="$REPO/runtime/ui-014c.db"
OUT=/home/z/my-project/download/redesign-014/phase1-local
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"
mkdir -p "$OUT"
rm -f "$DB"

cd "$REPO"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app \
  --host 127.0.0.1 --port $PORT > "$OUT/server.log" 2>&1 &
SRV=$!
for i in $(seq 1 100); do curl -s -o /dev/null "http://127.0.0.1:$PORT/health" && break; sleep 0.4; done

ab() { agent-browser "$@"; }

echo "== [1] 1440 cold =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
ab screenshot "$OUT/p1-welcome-1440.png" > /dev/null 2>&1 && echo "shot: p1-welcome-1440"

echo "== [2] هندسة المرحلة الأولى (قياس DOM) =="
ab eval "JSON.stringify({
  composerBottomGap: Math.round(window.innerHeight - document.querySelector('.composer').getBoundingClientRect().bottom),
  trayW: Math.round(document.querySelector('.composer-inner').getBoundingClientRect().width),
  trayH: Math.round(document.querySelector('.composer-inner').getBoundingClientRect().height),
  inputMinH: getComputedStyle(document.getElementById('input')).minHeight,
  sendRound: getComputedStyle(document.getElementById('send')).borderRadius,
  sendSize: Math.round(document.getElementById('send').getBoundingClientRect().width),
  sendX: Math.round(document.getElementById('send').getBoundingClientRect().x),
  welcomeW: Math.round(document.querySelector('.welcome').getBoundingClientRect().width),
  welcomeCentered: Math.abs((document.querySelector('.welcome').getBoundingClientRect().top + document.querySelector('.welcome').getBoundingClientRect().height/2) - (document.querySelector('.chat-scroll').getBoundingClientRect().top + document.querySelector('.chat-scroll').getBoundingClientRect().height/2)) < 60,
  pillH: Math.round(document.querySelector('.suggestion').getBoundingClientRect().height),
  pillFont: getComputedStyle(document.querySelector('.suggestion-title')).fontSize,
  pillLS: getComputedStyle(document.querySelector('.suggestion')).letterSpacing,
  hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth
})" 2>&1 | head -3

echo "== [3] تفاعل: كتابة تفعّل الإرسال =="
ab eval "const i=document.getElementById('input'); i.value='اختبر'; i.dispatchEvent(new Event('input',{bubbles:true})); JSON.stringify({sendEnabled: !document.getElementById('send').disabled})" 2>&1 | head -2

echo "== [4] mobile 390 =="
ab set viewport 390 844 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP&m=1" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1600 > /dev/null 2>&1
ab screenshot "$OUT/p1-welcome-390.png" > /dev/null 2>&1 && echo "shot: p1-welcome-390"
ab eval "JSON.stringify({hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth, composerBottomGap: Math.round(window.innerHeight - document.querySelector('.composer').getBoundingClientRect().bottom)})" 2>&1 | head -2

echo "== [5] console =="
ab console > "$OUT/console.txt" 2>&1; wc -l < "$OUT/console.txt"

kill $SRV 2>/dev/null
echo "P1_LOCAL_DONE"
