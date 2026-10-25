#!/bin/bash
# AES-UI-PREMIUM-REDESIGN-007 — BASELINE EVIDENCE CAPTURE
# Usage: baseline_007.sh empty|populated
# Runs on aes-ui-premium-redesign-007 @ b38dbaf (ui007 worktree).
# Captures screenshots + DOM measurements + console errors for the BEFORE state.
set -u
PHASE="${1:-empty}"
WT=/home/z/my-project/ui007
PY=/home/z/.venv/bin/python3
PORT=8050
OUT=/home/z/my-project/download/ui-redesign-007/baseline
mkdir -p "$OUT"

if [ "$PHASE" = "empty" ]; then
  DB="$WT/runtime/ui-007-empty.db"
else
  DB="$WT/runtime/ui-007.db"
fi
rm -f "$DB"

if [ "$PHASE" = "populated" ]; then
  echo "== [0] seed conversations+messages (real SQLAlchemy layer) =="
  AGenthubV2_DB_PATH="$DB" PYTHONPATH="$WT/src" "$PY" /home/z/my-project/scripts/seed_ui_007.py 2>&1 | tail -1
fi

cd "$WT"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-007-base.log 2>&1 &
SRV=$!
for i in $(seq 1 80); do curl -s -o /dev/null http://127.0.0.1:$PORT/health && break; sleep 0.5; done
echo "== server up on port $PORT (db: $(basename $DB))"

if [ "$PHASE" = "populated" ]; then
  echo "== [0b] create 2 projects via real API =="
  curl -s -X POST http://127.0.0.1:$PORT/api/projects -H 'Content-Type: application/json' \
    -d '{"name":"بناء وحدة تحليل الأداء الأسبوعية","objective":"توليد تقرير أداء API أسبوعي مع p50/p95 وتنبيهات الانحدار، من المصدر حتى PDF عربي موثق بالأدلة."}' | head -c 220; echo
  curl -s -X POST http://127.0.0.1:$PORT/api/projects -H 'Content-Type: application/json' \
    -d '{"name":"ترحيل الركيزة إلى bwrap v2","objective":"ترقية عامل العزل مع الحفاظ على عقود الجاهزية العشرة وأدلة الاختبار 15/15."}' | head -c 220; echo
fi

ab() { agent-browser "$@"; }
M() { ab eval "$1" 2>&1; }
shot() { ab screenshot "$OUT/$2.png" > /dev/null 2>&1; echo "shot: $2"; }
BASE="http://127.0.0.1:$PORT"
STAMP=$(date +%s)

MEASURE='JSON.stringify({vp:[innerWidth,innerHeight],docW:document.documentElement.scrollWidth,hOverflow:document.documentElement.scrollWidth>innerWidth,bodyFont:getComputedStyle(document.body).fontFamily.slice(0,60),bodySize:getComputedStyle(document.body).fontSize,sidebarW:(document.getElementById("sidebar")||{}).getBoundingClientRect?document.getElementById("sidebar").getBoundingClientRect().width:null,chatHeadH:document.querySelector(".chat-head")?document.querySelector(".chat-head").getBoundingClientRect().height:null,composerH:document.querySelector(".composer")?document.querySelector(".composer").getBoundingClientRect().height:null,welcomeH1:document.querySelector(".welcome h1")?getComputedStyle(document.querySelector(".welcome h1")).fontSize:null,convItem:(document.querySelector(".conv-item"))?JSON.stringify({fs:getComputedStyle(document.querySelector(".conv-item")).fontSize,pad:getComputedStyle(document.querySelector(".conv-item")).padding,h:document.querySelector(".conv-item").getBoundingClientRect().height}):null,navItem:(document.querySelector(".side-nav-item"))?JSON.stringify({fs:getComputedStyle(document.querySelector(".side-nav-item")).fontSize,h:document.querySelector(".side-nav-item").getBoundingClientRect().height}):null,bubble:(document.querySelector(".bubble .bubble-body"))?JSON.stringify({fs:getComputedStyle(document.querySelector(".bubble .bubble-body")).fontSize,lh:getComputedStyle(document.querySelector(".bubble .bubble-body")).lineHeight,color:getComputedStyle(document.querySelector(".bubble .bubble-body")).color}):null,input:(document.getElementById("input"))?JSON.stringify({fs:getComputedStyle(document.getElementById("input")).fontSize,h:document.getElementById("input").getBoundingClientRect().height}):null})'

if [ "$PHASE" = "empty" ]; then
  # ============ EMPTY STATES ============
  ab open "$BASE/?fresh=$STAMP" > /dev/null 2>&1
  ab set viewport 1440 900 > /dev/null 2>&1
  ab wait --load networkidle > /dev/null 2>&1
  ab wait 1200 > /dev/null 2>&1
  echo "== [E1] welcome/empty 1440 =="
  echo "MEASURE-1440-welcome: $(M "$MEASURE")"
  shot empty welcome-1440
  echo "conv-empty text: $(M "document.getElementById('conv-empty')?.textContent")"
  echo "projects empty: $(M "document.getElementById('projects-list')?.textContent.trim().slice(0,80)")"

  echo "== [E2] settings tabs 1440 =="
  ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
  ab wait 900 > /dev/null 2>&1
  shot empty settings-general-1440
  for T in providers models tools execution advanced; do
    ab eval "document.querySelector('.settings-tab[data-tab=$T]').click()" > /dev/null 2>&1
    ab wait 800 > /dev/null 2>&1
    shot empty settings-$T-1440
  done
  ab press Escape > /dev/null 2>&1
  ab wait 400 > /dev/null 2>&1

  echo "== [E3] runs/archive empty =="
  ab eval "document.querySelector('.side-nav-item[data-nav=runs]').click()" > /dev/null 2>&1
  ab wait 900 > /dev/null 2>&1
  echo "runs body: $(M "document.getElementById('runs-body')?.textContent.trim().slice(0,120)")"
  shot empty runs-1440
  ab eval "document.querySelector('.side-nav-item[data-nav=archive]').click()" > /dev/null 2>&1
  ab wait 900 > /dev/null 2>&1
  shot empty archive-1440
  ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
  ab wait 500 > /dev/null 2>&1

  echo "== [E4] factory empty 1440 =="
  ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
  ab wait 2200 > /dev/null 2>&1
  shot empty factory-1440
  echo "factory stats: $(M "JSON.stringify([...document.querySelectorAll('.fc-stat-value')].map(e=>e.textContent.trim()))")"

  echo "== [E5] mobile fresh-load 390 =="
  ab set viewport 390 844 > /dev/null 2>&1
  ab open "$BASE/?m=$STAMP" > /dev/null 2>&1
  ab wait --load networkidle > /dev/null 2>&1
  ab wait 1200 > /dev/null 2>&1
  echo "MEASURE-390-mobile: $(M "$MEASURE")"
  shot empty mobile-welcome-390
  ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
  ab wait 2000 > /dev/null 2>&1
  shot empty mobile-factory-390
  echo "mobile hOverflow: $(M "document.documentElement.scrollWidth > innerWidth")"
  ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
  ab wait 900 > /dev/null 2>&1
  shot empty mobile-settings-390

  echo "== [E6] console/errors (empty phase) =="
  echo "--- console:"; ab console 2>&1 | tail -12
  echo "--- page errors:"; ab errors 2>&1 | tail -8
else
  # ============ POPULATED STATES ============
  ab open "$BASE/?fresh=$STAMP" > /dev/null 2>&1
  ab set viewport 1440 900 > /dev/null 2>&1
  ab wait --load networkidle > /dev/null 2>&1
  ab wait 1500 > /dev/null 2>&1
  echo "== [P1] chat 1440 populated =="
  echo "MEASURE-1440-chat: $(M "$MEASURE")"
  echo "conv items: $(ab get count '.conv-item' 2>&1)"
  echo "pj items: $(ab get count '.pj-item' 2>&1)"
  shot pop chat-1440
  # open first conversation (long AR title + markdown)
  ab eval "document.querySelectorAll('.conv-item')[0].click()" > /dev/null 2>&1
  ab wait 1600 > /dev/null 2>&1
  echo "msgs rendered: $(ab get count '.msg' 2>&1)"
  echo "md table: $(ab get count '.md-table-wrap' 2>&1), md code: $(ab get count '.md-code' 2>&1)"
  shot pop chat-long-ar-1440
  ab screenshot --full "$OUT/pop chat-long-ar-1440-full.png" > /dev/null 2>&1
  echo "shot: chat-long-ar-1440-full"
  # second conversation English
  ab eval "document.querySelectorAll('.conv-item')[1].click()" > /dev/null 2>&1
  ab wait 1200 > /dev/null 2>&1
  shot pop chat-en-1440

  echo "== [P2] task mode + task settings =="
  ab eval "document.getElementById('plus').click()" > /dev/null 2>&1
  ab wait 300 > /dev/null 2>&1
  shot pop plus-menu-1440
  ab eval "document.querySelector('.plus-option[data-mode=task]').click()" > /dev/null 2>&1
  ab wait 600 > /dev/null 2>&1
  ab eval "document.getElementById('task-settings-toggle').click()" > /dev/null 2>&1
  ab wait 800 > /dev/null 2>&1
  shot pop task-settings-1440

  echo "== [P3] honest error: send w/o provider =="
  ab eval "var i=document.getElementById('input'); i.value='اختبر الاتصال من فضلك'; i.dispatchEvent(new Event('input',{bubbles:true})); 'typed'" > /dev/null 2>&1
  ab eval "document.getElementById('send').click()" > /dev/null 2>&1
  ab wait 6000 > /dev/null 2>&1
  echo "error cards: $(ab get count '.sys-card.error' 2>&1)"
  shot pop chat-error-no-provider-1440

  echo "== [P4] project view + tabs =="
  ab eval "document.querySelectorAll('.pj-item')[0].click()" > /dev/null 2>&1
  ab wait 2000 > /dev/null 2>&1
  shot pop project-conversation-1440
  for T in overview workflow evidence artifacts history; do
    ab eval "document.querySelector('.pl-tab[data-tab=$T]').click()" > /dev/null 2>&1
    ab wait 1100 > /dev/null 2>&1
    shot pop project-$T-1440
  done

  echo "== [P5] runs/archive populated =="
  ab eval "document.querySelector('.pl-tab[data-tab=conversation]').click()" > /dev/null 2>&1
  ab eval "document.getElementById('pl-back').click()" > /dev/null 2>&1
  ab wait 700 > /dev/null 2>&1
  ab eval "document.querySelector('.side-nav-item[data-nav=runs]').click()" > /dev/null 2>&1
  ab wait 1200 > /dev/null 2>&1
  shot pop runs-1440
  ab eval "document.querySelector('.side-nav-item[data-nav=archive]').click()" > /dev/null 2>&1
  ab wait 1000 > /dev/null 2>&1
  shot pop archive-1440
  ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
  ab wait 500 > /dev/null 2>&1

  echo "== [P6] factory populated 1440 + mission view =="
  ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
  ab wait 2500 > /dev/null 2>&1
  shot pop factory-1440
  echo "mission rows: $(ab get count '.fc-mission-row' 2>&1)"
  ab eval "document.querySelector('.fc-mission-row')?.click()" > /dev/null 2>&1
  ab wait 1500 > /dev/null 2>&1
  shot pop factory-mission-view-1440

  echo "== [P7] 1920 + 1280 chat/factory =="
  ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
  ab set viewport 1920 1080 > /dev/null 2>&1
  ab wait 600 > /dev/null 2>&1
  shot pop chat-1920
  ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
  ab wait 2000 > /dev/null 2>&1
  shot pop factory-1920
  ab set viewport 1280 800 > /dev/null 2>&1
  ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
  ab wait 600 > /dev/null 2>&1
  shot pop chat-1280
  ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
  ab wait 1800 > /dev/null 2>&1
  shot pop factory-1280

  echo "== [P8] tablet 768x1024 =="
  ab set viewport 768 1024 > /dev/null 2>&1
  ab open "$BASE/?t=$STAMP" > /dev/null 2>&1
  ab wait --load networkidle > /dev/null 2>&1
  ab wait 1400 > /dev/null 2>&1
  echo "MEASURE-768: $(M "$MEASURE")"
  shot pop tablet-chat-768
  ab eval "document.querySelectorAll('.conv-item')[0].click()" > /dev/null 2>&1
  ab wait 1400 > /dev/null 2>&1
  shot pop tablet-chat-content-768
  ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
  ab wait 2000 > /dev/null 2>&1
  shot pop tablet-factory-768
  echo "768 hOverflow: $(M "document.documentElement.scrollWidth > innerWidth")"

  echo "== [P9] mobile fresh 390 + 360 =="
  ab set viewport 390 844 > /dev/null 2>&1
  ab open "$BASE/?m1=$STAMP" > /dev/null 2>&1
  ab wait --load networkidle > /dev/null 2>&1
  ab wait 1400 > /dev/null 2>&1
  echo "MEASURE-390: $(M "$MEASURE")"
  shot pop mobile-chat-390
  ab eval "document.querySelectorAll('.conv-item')[0].click()" > /dev/null 2>&1
  ab wait 1500 > /dev/null 2>&1
  shot pop mobile-chat-content-390
  echo "390 hOverflow: $(M "document.documentElement.scrollWidth > innerWidth")"
  ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
  ab wait 2000 > /dev/null 2>&1
  shot pop mobile-factory-390
  ab set viewport 360 800 > /dev/null 2>&1
  ab open "$BASE/?m2=$STAMP" > /dev/null 2>&1
  ab wait --load networkidle > /dev/null 2>&1
  ab wait 1400 > /dev/null 2>&1
  echo "MEASURE-360: $(M "$MEASURE")"
  shot pop mobile-chat-360
  echo "360 hOverflow: $(M "document.documentElement.scrollWidth > innerWidth")"

  echo "== [P10] console/errors (populated phase) =="
  echo "--- console:"; ab console 2>&1 | tail -15
  echo "--- page errors:"; ab errors 2>&1 | tail -8
fi

kill $SRV 2>/dev/null
echo "== done ($PHASE), server stopped =="
