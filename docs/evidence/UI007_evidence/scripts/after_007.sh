#!/bin/bash
# AES-UI-PREMIUM-REDESIGN-007 — AFTER CAPTURE + INTERACTION TESTS
# Same paths/viewports as baseline. Runs on aes-ui-premium-redesign-007 worktree.
set -u
WT=/home/z/my-project/ui007
PY=/home/z/.venv/bin/python3
PORT=8051
OUT=/home/z/my-project/download/ui-redesign-007/after
mkdir -p "$OUT"
DB="$WT/runtime/ui-007-after.db"
rm -f "$DB"
AGenthubV2_DB_PATH="$DB" PYTHONPATH="$WT/src" "$PY" /home/z/my-project/scripts/seed_ui_007.py 2>&1 | tail -1

cd "$WT"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-007-after.log 2>&1 &
SRV=$!
for i in $(seq 1 80); do curl -s -o /dev/null http://127.0.0.1:$PORT/health && break; sleep 0.5; done
echo "== server up (port $PORT)"
curl -s -X POST http://127.0.0.1:$PORT/api/projects -H 'Content-Type: application/json' \
  -d '{"name":"بناء وحدة تحليل الأداء الأسبوعية","objective":"توليد تقرير أداء API أسبوعي مع p50/p95 وتنبيهات الانحدار، من المصدر حتى PDF عربي موثق بالأدلة."}' > /dev/null
curl -s -X POST http://127.0.0.1:$PORT/api/projects -H 'Content-Type: application/json' \
  -d '{"name":"ترحيل الركيزة إلى bwrap v2","objective":"ترقية عامل العزل مع الحفاظ على عقود الجاهزية العشرة وأدلة الاختبار 15/15."}' > /dev/null
echo "== projects seeded (2)"

ab() { agent-browser "$@"; }
M() { ab eval "$1" 2>&1; }
shot() { ab screenshot "$OUT/$2.png" > /dev/null 2>&1; echo "shot: $2"; }
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"

MEASURE='JSON.stringify({vp:[innerWidth,innerHeight],docW:document.documentElement.scrollWidth,hOverflow:document.documentElement.scrollWidth>innerWidth,sidebarW:document.getElementById("sidebar").getBoundingClientRect().width,chatHeadH:document.querySelector(".chat-head")?document.querySelector(".chat-head").getBoundingClientRect().height:null,composerH:document.querySelector(".composer")?document.querySelector(".composer").getBoundingClientRect().height:null,welcomeH1:document.querySelector(".welcome h1")?getComputedStyle(document.querySelector(".welcome h1")).fontSize:null,placeholderColor:getComputedStyle(document.getElementById("input"),"::placeholder").color,textDim:getComputedStyle(document.documentElement).getPropertyValue("--text-dim").trim(),textFaint:getComputedStyle(document.documentElement).getPropertyValue("--text-faint").trim()})'

echo "== [A1] welcome (empty) 1440 =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?a=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
echo "MEASURE-1440: $(M "$MEASURE")"
shot after welcome-1440
echo "suggestion cards: $(ab get count '.suggestion' 2>&1), titles: $(ab get count '.suggestion-title' 2>&1)"
echo "conv empty: $(M "document.getElementById('conv-empty')?.textContent")"

echo "== [A2] settings tabs 1440 =="
ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
shot after settings-general-1440
for T in providers models tools execution advanced; do
  ab eval "document.querySelector('.settings-tab[data-tab=$T]').click()" > /dev/null 2>&1
  ab wait 800 > /dev/null 2>&1
  shot after settings-$T-1440
done
ab press Escape > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1

echo "== [A3] runs/archive/factory empty =="
ab eval "document.querySelector('.side-nav-item[data-nav=runs]').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
shot after runs-1440
ab eval "document.querySelector('.side-nav-item[data-nav=archive]').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
shot after archive-1440
ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
ab wait 500 > /dev/null 2>&1
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2500 > /dev/null 2>&1
shot after factory-1440
echo "factory stats: $(M "JSON.stringify([...document.querySelectorAll('.fc-stat-value')].map(e=>e.textContent.trim()))")"
echo "factory bg computed: $(M "getComputedStyle(document.getElementById('factory-view')).backgroundColor")"

echo "== [A4] chat with content (hash route) =="
ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
ab wait 500 > /dev/null 2>&1
ab open "$BASE/#/chat/1" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
echo "bubbles: $(ab get count '.bubble' 2>&1), md-table: $(ab get count '.md-table-wrap' 2>&1), md-code: $(ab get count '.md-code' 2>&1)"
shot after chat-long-ar-1440
ab screenshot --full "$OUT/after chat-long-ar-1440-full.png" > /dev/null 2>&1
echo "shot: chat-long-ar-1440-full"
ab eval "location.hash='#/chat/2'" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
shot after chat-en-1440

echo "== [A5] BUG-04 verify: empty conversation shows hint =="
ab eval "location.hash='#/chat/5'" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
echo "empty-note: $(M "document.querySelector('.history-loading')?.textContent.slice(0,60)")"
shot after chat-empty-conv-1440
ab eval "location.hash='#/chat/1'" > /dev/null 2>&1
ab wait 1200 > /dev/null 2>&1

echo "== [A6] task mode + settings + error state =="
ab eval "document.getElementById('plus').click()" > /dev/null 2>&1
ab wait 250 > /dev/null 2>&1
shot after plus-menu-1440
ab eval "document.querySelector('.plus-option[data-mode=task]').click()" > /dev/null 2>&1
ab wait 600 > /dev/null 2>&1
ab eval "document.getElementById('task-settings-toggle').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
shot after task-settings-1440
ab eval "document.getElementById('plus').click()" > /dev/null 2>&1
ab wait 250 > /dev/null 2>&1
ab eval "document.querySelector('.plus-option[data-mode=chat]').click()" > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1
ab eval "var i=document.getElementById('input'); i.value='اختبر الاتصال'; i.dispatchEvent(new Event('input',{bubbles:true})); 'typed'" > /dev/null 2>&1
ab eval "document.getElementById('send').click()" > /dev/null 2>&1
ab wait 7000 > /dev/null 2>&1
echo "error card: $(ab get count '.sys-card.error' 2>&1)"
shot after chat-error-no-provider-1440

echo "== [A7] project view + tabs =="
ab eval "document.querySelectorAll('.pj-item')[0].click()" > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
shot after project-conversation-1440
for T in overview workflow evidence artifacts history; do
  ab eval "document.querySelector('.pl-tab[data-tab=$T]').click()" > /dev/null 2>&1
  ab wait 1100 > /dev/null 2>&1
  shot after project-$T-1440
done
ab eval "document.getElementById('pl-back').click()" > /dev/null 2>&1
ab wait 700 > /dev/null 2>&1

echo "== [A8] runs populated + factory mission =="
ab eval "document.querySelector('.side-nav-item[data-nav=runs]').click()" > /dev/null 2>&1
ab wait 1200 > /dev/null 2>&1
shot after runs-1440
ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2500 > /dev/null 2>&1
shot after factory-1440
echo "mission rows: $(ab get count '.fc-mission-row' 2>&1)"
ab eval "document.querySelector('.fc-mission-row')?.click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
shot after factory-mission-view-1440

echo "== [A9] 1920 + 1280 =="
ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
ab set viewport 1920 1080 > /dev/null 2>&1
ab wait 600 > /dev/null 2>&1
shot after chat-1920
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2200 > /dev/null 2>&1
shot after factory-1920
ab set viewport 1280 800 > /dev/null 2>&1
ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
ab wait 600 > /dev/null 2>&1
shot after chat-1280
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
shot after factory-1280

echo "== [A10] tablet 768 =="
ab set viewport 768 1024 > /dev/null 2>&1
ab open "$BASE/?t=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1600 > /dev/null 2>&1
echo "MEASURE-768: $(M "$MEASURE")"
shot after tablet-chat-768
ab eval "location.hash='#/chat/1'" > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
echo "bubbles 768: $(ab get count '.bubble' 2>&1)"
shot after tablet-chat-content-768
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2200 > /dev/null 2>&1
shot after tablet-factory-768
echo "768 hOverflow: $(M "document.documentElement.scrollWidth > innerWidth" 2>&1)"

echo "== [A11] mobile 390 + 360 (fresh loads) =="
ab set viewport 390 844 > /dev/null 2>&1
ab open "$BASE/?m=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1600 > /dev/null 2>&1
echo "MEASURE-390: $(M "$MEASURE")"
shot after mobile-chat-390
ab eval "location.hash='#/chat/1'" > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
echo "390 hOverflow: $(M "document.documentElement.scrollWidth > innerWidth" 2>&1)"
shot after mobile-chat-content-390
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2200 > /dev/null 2>&1
shot after mobile-factory-390
echo "390 factory hOverflow: $(M "document.documentElement.scrollWidth > innerWidth" 2>&1)"
ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
shot after mobile-settings-390
ab set viewport 360 800 > /dev/null 2>&1
ab open "$BASE/?n=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1600 > /dev/null 2>&1
echo "MEASURE-360: $(M "$MEASURE")"
shot after mobile-chat-360

echo "== [A12] BUG-03 verify: resize sync =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?r=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1400 > /dev/null 2>&1
echo "fresh 1440 sidebar: $(M "document.body.classList.contains('sidebar-collapsed') ? 'collapsed(BAD)' : 'open(GOOD)'")"
ab set viewport 390 844 > /dev/null 2>&1
ab wait 500 > /dev/null 2>&1
echo "after shrink→390 (no reload): $(M "document.body.classList.contains('sidebar-collapsed') ? 'collapsed(GOOD)' : 'open(BAD)'")"
ab set viewport 1440 900 > /dev/null 2>&1
ab wait 500 > /dev/null 2>&1
echo "after grow→1440 (no reload): $(M "document.body.classList.contains('sidebar-collapsed') ? 'collapsed(BAD)' : 're-opened(GOOD)'")"

echo "== [A13] console/errors (whole session) =="
echo "--- console:"; ab console 2>&1 | tail -10
echo "--- page errors:"; ab errors 2>&1 | tail -6

kill $SRV 2>/dev/null
echo "== done after-capture =="
