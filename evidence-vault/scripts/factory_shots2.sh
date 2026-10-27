#!/bin/bash
set -u
cd /home/z/my-project/ui-work
DB=runtime/ui-redesign.db
PORT=8020
OUT=/home/z/my-project/download/ui-redesign/factory
mkdir -p "$OUT"

PYTHONPATH=src AGenthubV2_DB_PATH=$DB python3 -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-factory2.log 2>&1 &
SRV=$!
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:$PORT/health && break; sleep 0.5; done

ab() { agent-browser "$@"; }
STAMP=$(date +%s)
ab open "http://127.0.0.1:$PORT/?fresh=$STAMP#/factory" > /dev/null 2>&1
ab set viewport 1440 900 > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1; ab wait 3000 > /dev/null 2>&1
ab screenshot "$OUT/factory-overview-1440.png" > /dev/null 2>&1
echo "shot: factory-overview-1440"

echo "== mission row now shows real data? =="
ab eval "var r=document.querySelector('.fc-mission-row'); r ? r.textContent.replace(/\\s+/g,' ').slice(0,120) : 'NO-ROW'" 2>&1

ab eval "document.querySelector('.fc-mission-row').click()" > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
ab screenshot "$OUT/factory-mission-1440.png" > /dev/null 2>&1
echo "shot: factory-mission-1440"

ab eval "document.querySelector('.fc-tab[data-tab=agents]').click()" > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
ab screenshot "$OUT/factory-mission-agents-1440.png" > /dev/null 2>&1
echo "shot: factory-mission-agents-1440"
echo "== agents cards content =="
ab eval "document.querySelector('.fc-agent-card') ? document.querySelector('.fc-agent-card').textContent.replace(/\\s+/g,' ').slice(0,150) : 'NO-CARD'" 2>&1

echo "== network failures =="
ab network requests 2>&1 | grep -iE "fail|error|✗|404|500" | head -12
echo "== network all (summary) =="
ab network requests 2>&1 | tail -5

echo "== console =="
ab console 2>&1 | head -10
echo "== page errors =="
ab errors 2>&1 | head -8

kill $SRV 2>/dev/null
echo "== done =="
