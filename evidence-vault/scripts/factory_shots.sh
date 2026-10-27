#!/bin/bash
# AES-UI-PREMIUM-REDESIGN-003 — جلسة تحقق تطبيق التصميم المرجعي حرفياً على المصنع
# خادم + متصفح + لقطات + فحوص محسوبة في استدعاء واحد (البيئة تقتل العمليات بين الاستدعاءات)
set -u
cd /home/z/my-project/ui-work
DB=runtime/ui-redesign.db
PORT=8020
OUT=/home/z/my-project/download/ui-redesign/factory
REF=/home/z/my-project/upload/Qwen_html_20261025_dkx5qgv14.html
mkdir -p "$OUT"

PYTHONPATH=src AGenthubV2_DB_PATH=$DB python3 -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-factory.log 2>&1 &
SRV=$!
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:$PORT/health && break; sleep 0.5; done

echo "== serving checks =="
curl -s -o /dev/null -w "app: %{http_code}\n" "http://127.0.0.1:$PORT/"
curl -s -o /dev/null -w "mono-400 font: %{http_code}\n" "http://127.0.0.1:$PORT/static/fonts/plex-mono-400-latin.woff2"
curl -s -o /dev/null -w "mono-500 font: %{http_code}\n" "http://127.0.0.1:$PORT/static/fonts/plex-mono-500-latin.woff2"
curl -s -o /dev/null -w "arabic-700 font: %{http_code}\n" "http://127.0.0.1:$PORT/static/fonts/plex-arabic-700-arabic.woff2"
curl -s -o /dev/null -w "factory css: %{http_code}\n" "http://127.0.0.1:$PORT/static/factory-control.css?v=4.0.0"

ab() { agent-browser "$@"; }

echo "== reference design shot (the uploaded file itself) =="
ab open "file://$REF" > /dev/null 2>&1
ab set viewport 1440 900 > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1; ab wait 800 > /dev/null 2>&1
ab screenshot "$OUT/reference-1440.png" > /dev/null 2>&1
echo "shot: reference-1440"

echo "== app factory view =="
STAMP=$(date +%s)
ab open "http://127.0.0.1:$PORT/?fresh=$STAMP#/factory" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab set viewport 1440 900 > /dev/null 2>&1
ab reload > /dev/null 2>&1; ab wait --load networkidle > /dev/null 2>&1; ab wait 2500 > /dev/null 2>&1
ab screenshot "$OUT/factory-overview-1440.png" > /dev/null 2>&1
echo "shot: factory-overview-1440"

echo "== literal token assertions =="
ab eval "JSON.stringify({
  monoLoaded: document.fonts.check('12px \"IBM Plex Mono\"'),
  mono500Loaded: document.fonts.check('500 12px \"IBM Plex Mono\"'),
  boldLoaded: document.fonts.check('700 14px \"IBM Plex Sans Arabic\"'),
  surfaceBg: getComputedStyle(document.getElementById('factory-view')).backgroundColor,
  accent: getComputedStyle(document.getElementById('factory-view')).getPropertyValue('--acc').trim(),
  cardBg: document.querySelector('.fc-card') ? getComputedStyle(document.querySelector('.fc-card')).backgroundColor : 'NO-CARD',
  cardHeadBg: document.querySelector('.fc-card h3') ? getComputedStyle(document.querySelector('.fc-card h3')).backgroundColor : 'NO-H3',
  headBlur: getComputedStyle(document.querySelector('#factory-view .cc-head')).backdropFilter,
  statusPill: getComputedStyle(document.getElementById('factory-system-status')).backgroundColor,
  bodyFont: getComputedStyle(document.getElementById('factory-view')).fontFamily.split(',')[0]
})" 2>&1

echo "== create-mission form =="
ab eval "document.getElementById('fc-new-mission').click()" > /dev/null 2>&1
ab wait 1200 > /dev/null 2>&1
ab screenshot "$OUT/factory-create-1440.png" > /dev/null 2>&1
echo "shot: factory-create-1440"

echo "== mission view (overview tab) =="
ab eval "document.getElementById('fc-cancel-create').click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab eval "var r=document.querySelector('.fc-mission-row'); if(r){r.click(); 'mission-opened'} else 'NO-MISSION-ROW'" 2>&1
ab wait 2000 > /dev/null 2>&1
ab screenshot "$OUT/factory-mission-1440.png" > /dev/null 2>&1
echo "shot: factory-mission-1440"

echo "== mission view (agents tab — pcard tiles) =="
ab eval "var t=document.querySelector('.fc-tab[data-tab=agents]'); if(t){t.click(); 'agents-tab'} else 'NO-AGENTS-TAB'" 2>&1
ab wait 2000 > /dev/null 2>&1
ab screenshot "$OUT/factory-mission-agents-1440.png" > /dev/null 2>&1
echo "shot: factory-mission-agents-1440"

echo "== run view (if a run row exists) =="
ab eval "var b=document.getElementById('factory-back'); if(b){b.click(); 'back'}" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab eval "var r=document.querySelector('.fc-run-row'); if(r){r.click(); 'run-opened'} else 'NO-RUN-ROW'" 2>&1
ab wait 2000 > /dev/null 2>&1
if ab eval "document.querySelector('.factory-run-view') ? 'RUNVIEW' : 'NO'" 2>&1 | grep -q RUNVIEW; then
  ab screenshot "$OUT/factory-run-1440.png" > /dev/null 2>&1
  echo "shot: factory-run-1440"
else
  echo "run view: no run rows in test DB — skipped"
fi

echo "== mobile 390 =="
ab set viewport 390 844 > /dev/null 2>&1
ab open "http://127.0.0.1:$PORT/#/factory" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1; ab wait 2500 > /dev/null 2>&1
ab screenshot "$OUT/factory-overview-390.png" > /dev/null 2>&1
echo "shot: factory-overview-390"
ab eval "document.documentElement.scrollWidth + 'x' + document.documentElement.clientWidth" 2>&1

echo "== tablet 768 =="
ab set viewport 768 1024 > /dev/null 2>&1
ab reload > /dev/null 2>&1; ab wait --load networkidle > /dev/null 2>&1; ab wait 2500 > /dev/null 2>&1
ab screenshot "$OUT/factory-overview-768.png" > /dev/null 2>&1
echo "shot: factory-overview-768"

echo "== console + page errors =="
ab console 2>&1 | tail -15
ab errors 2>&1 | tail -10

kill $SRV 2>/dev/null
echo "== session done =="
ls -la "$OUT"
