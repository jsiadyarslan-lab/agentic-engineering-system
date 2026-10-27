#!/bin/bash
set -u
cd /home/z/my-project/ui-work
DB=runtime/ui-redesign.db
PORT=8020
OUT=/home/z/my-project/download/ui-redesign/factory
REF=/home/z/my-project/upload/Qwen_html_20261025_dkx5qgv14.html
mkdir -p "$OUT"

PYTHONPATH=src AGenthubV2_DB_PATH=$DB python3 -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-factory3.log 2>&1 &
SRV=$!
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:$PORT/health && break; sleep 0.5; done

ab() { agent-browser "$@"; }

# المرجع نفسه للمقارنة البصرية
ab open "file://$REF" > /dev/null 2>&1
ab set viewport 1440 900 > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1; ab wait 800 > /dev/null 2>&1
ab screenshot "$OUT/reference-1440.png" > /dev/null 2>&1
echo "shot: reference-1440"

STAMP=$(date +%s)
ab open "http://127.0.0.1:$PORT/?fresh=$STAMP#/factory" > /dev/null 2>&1
ab set viewport 1440 900 > /dev/null 2>&1
ab reload > /dev/null 2>&1; ab wait --load networkidle > /dev/null 2>&1; ab wait 3000 > /dev/null 2>&1
ab screenshot "$OUT/factory-overview-1440.png" > /dev/null 2>&1
echo "shot: factory-overview-1440"

echo "== literal assertions =="
ab eval "JSON.stringify({
  mono: document.fonts.check('12px \"IBM Plex Mono\"'),
  bold: document.fonts.check('700 14px \"IBM Plex Sans Arabic\"'),
  bg: getComputedStyle(document.getElementById('factory-view')).backgroundColor,
  acc: getComputedStyle(document.getElementById('factory-view')).getPropertyValue('--acc').trim(),
  card: document.querySelector('.fc-card') ? getComputedStyle(document.querySelector('.fc-card')).backgroundColor : 'NO',
  head: document.querySelector('.fc-card h3') ? getComputedStyle(document.querySelector('.fc-card h3')).backgroundColor : 'NO',
  missionRow: document.querySelector('.fc-mission-row') ? 'REAL-DATA' : 'NO-ROW'
})" 2>&1

ab eval "document.getElementById('fc-new-mission').click()" > /dev/null 2>&1
ab wait 1200 > /dev/null 2>&1
ab screenshot "$OUT/factory-create-1440.png" > /dev/null 2>&1
echo "shot: factory-create-1440"

ab eval "document.getElementById('fc-cancel-create').click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab eval "document.querySelector('.fc-mission-row').click()" > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
ab screenshot "$OUT/factory-mission-1440.png" > /dev/null 2>&1
echo "shot: factory-mission-1440"

ab eval "document.querySelector('.fc-tab[data-tab=agents]').click()" > /dev/null 2>&1
ab wait 2200 > /dev/null 2>&1
ab screenshot "$OUT/factory-mission-agents-1440.png" > /dev/null 2>&1
echo "shot: factory-mission-agents-1440"

ab set viewport 390 844 > /dev/null 2>&1
ab reload > /dev/null 2>&1; ab wait --load networkidle > /dev/null 2>&1; ab wait 3000 > /dev/null 2>&1
ab screenshot "$OUT/factory-overview-390.png" > /dev/null 2>&1
echo "shot: factory-overview-390"
echo "mobile overflow: $(ab eval "document.documentElement.scrollWidth + 'x' + document.documentElement.clientWidth" 2>&1)"

ab set viewport 768 1024 > /dev/null 2>&1
ab reload > /dev/null 2>&1; ab wait --load networkidle > /dev/null 2>&1; ab wait 3000 > /dev/null 2>&1
ab screenshot "$OUT/factory-overview-768.png" > /dev/null 2>&1
echo "shot: factory-overview-768"

echo "== console (factory) =="
ab console 2>&1 | head -8

kill $SRV 2>/dev/null
echo "== done =="
