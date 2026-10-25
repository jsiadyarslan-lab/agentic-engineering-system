#!/bin/bash
# AES-UI-PREMIUM-REDESIGN-008 — LIVE BROWSER RE-PROOF at candidate head 56e42ba
# Fresh isolated DB, fresh server, one continuous browser session.
# Writes ONLY to docs/evidence/UI007_evidence/reproof-008/ (never touches 007 originals).
set -u
WT=/home/z/my-project/ui007
PY=/home/z/.venv/bin/python3
PORT=8071
OUT="$WT/docs/evidence/UI007_evidence/reproof-008"
SHOTS="$OUT/shots"
LOG="$OUT/browser-session.txt"
DB="$WT/runtime/ui-008-reproof.db"
mkdir -p "$SHOTS"
rm -f "$DB"

L() { echo "$1" >> "$LOG"; }
{
echo "# AES-UI-PREMIUM-REDESIGN-008 — Live browser re-proof session"
echo "# date(UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "# commit: $(git -C "$WT" rev-parse HEAD)"
echo "# runtime: uvicorn 127.0.0.1:$PORT, isolated DB runtime/ui-008-reproof.db"
echo "# seed: scripts/seed_ui_007.py (real SQLAlchemy models) + 2 projects via POST /api/projects"
echo "# browser: agent-browser (Chromium) — single continuous session"
echo
} > "$LOG"

cd "$WT"
AGenthubV2_DB_PATH="$DB" PYTHONPATH="$WT/src" "$PY" /home/z/my-project/scripts/seed_ui_007.py >> "$LOG" 2>&1
L "seed: done"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-008-reproof-server.log 2>&1 &
SRV=$!
for i in $(seq 1 80); do curl -s -o /dev/null "http://127.0.0.1:$PORT/health" && break; sleep 0.5; done
L "health: $(curl -s "http://127.0.0.1:$PORT/health" | head -c 240)"
curl -s -X POST "http://127.0.0.1:$PORT/api/projects" -H 'Content-Type: application/json' -d '{"name":"بناء وحدة تحليل الأداء الأسبوعية","objective":"توليد تقرير أداء API أسبوعي مع p50/p95 وتنبيهات الانحدار، من المصدر حتى PDF عربي موثق بالأدلة."}' > /dev/null
curl -s -X POST "http://127.0.0.1:$PORT/api/projects" -H 'Content-Type: application/json' -d '{"name":"ترحيل الركيزة إلى bwrap v2","objective":"ترقية عامل العزل مع الحفاظ على عقود الجاهزية العشرة وأدلة الاختبار 15/15."}' > /dev/null
L "projects seeded: 2"

ab() { agent-browser "$@"; }
M() { ab eval "$1" 2>&1; }
shot() { ab screenshot "$SHOTS/$1.png" > /dev/null 2>&1; L "shot: $1"; }
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"

MEASURE='JSON.stringify({vp:[innerWidth,innerHeight],docW:document.documentElement.scrollWidth,hOverflow:document.documentElement.scrollWidth>innerWidth,sidebarW:document.getElementById("sidebar").getBoundingClientRect().width,chatHeadH:document.querySelector(".chat-head")?document.querySelector(".chat-head").getBoundingClientRect().height:null,composerH:document.querySelector(".composer")?document.querySelector(".composer").getBoundingClientRect().height:null,welcomeH1:document.querySelector(".welcome h1")?getComputedStyle(document.querySelector(".welcome h1")).fontSize:null,placeholderColor:getComputedStyle(document.getElementById("input"),"::placeholder").color,navItemFont:getComputedStyle(document.querySelector(".side-nav-item")).fontSize,textDim:getComputedStyle(document.documentElement).getPropertyValue("--text-dim").trim(),textFaint:getComputedStyle(document.documentElement).getPropertyValue("--text-faint").trim(),accentAgent:getComputedStyle(document.documentElement).getPropertyValue("--accent-agent").trim(),zModal:getComputedStyle(document.documentElement).getPropertyValue("--z-modal").trim(),fontMono:getComputedStyle(document.documentElement).getPropertyValue("--font-mono").trim().slice(0,34),docDir:document.documentElement.dir,fontArabic700:document.fonts.check("700 20px \"IBM Plex Sans Arabic\""),fontMonoLoaded:document.fonts.check("400 14px \"IBM Plex Mono\"")})'

L ""
L "== [R1] welcome (empty state) @1440 =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?r1=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
L "MEASURE|welcome-1440|$(M "$MEASURE")"
L "suggestion cards/titles/descs: $(ab get count '.suggestion' 2>&1)/$(ab get count '.suggestion-title' 2>&1)/$(ab get count '.suggestion-desc' 2>&1)"
shot welcome-1440

L ""
L "== [R2] chat-1440 — the single before-shot lacking an after counterpart in 007 (re-captured here) =="
ab open "$BASE/#/chat/1" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
L "bubbles/md-table/md-code: $(ab get count '.bubble' 2>&1)/$(ab get count '.md-table-wrap' 2>&1)/$(ab get count '.md-code' 2>&1)"
L "MEASURE|chat-1440|$(M "$MEASURE")"
shot chat-1440

L ""
L "== [R3] N-1 re-verification: pv-meta direction + code isolation (settings → providers) =="
ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
ab eval "document.querySelector('.settings-tab[data-tab=providers]').click()" > /dev/null 2>&1
ab wait 1000 > /dev/null 2>&1
L "pv-meta direction/font: $(M "var m=document.querySelector('.pv-meta'); m?getComputedStyle(m).direction+' | '+getComputedStyle(m).fontFamily.slice(0,25):'none'")"
L "pv-meta code dir attr: $(M "var c=document.querySelector('.pv-meta code'); c?String(c.getAttribute('dir')):'none'")"
L "pv-meta sample: $(M "var m=document.querySelector('.pv-meta'); m?JSON.stringify(m.textContent.slice(0,70)):'none'")"
L "settings buttons count: $(M "document.querySelectorAll('#settings-drawer button').length")"
shot settings-providers-1440
ab press Escape > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1

L ""
L "== [R4] N-5 re-verification: composer/messages/bubble edge alignment =="
ab open "$BASE/#/chat/1" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
L "MEASURE|alignment|$(M "var m=document.querySelector('.messages').getBoundingClientRect(); var c=document.querySelector('.composer-inner').getBoundingClientRect(); var b=document.querySelector('.bubble.assistant').getBoundingClientRect(); JSON.stringify({msgLeft:+m.left.toFixed(1),msgRight:+m.right.toFixed(1),compLeft:+c.left.toFixed(1),compRight:+c.right.toFixed(1),bubbleLeft:+b.left.toFixed(1),bubbleRight:+b.right.toFixed(1)})")"

L ""
L "== [R5] N-3 re-verification: factory tabs — first render without active; active underline gold =="
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2500 > /dev/null 2>&1
L "factory bg computed: $(M "getComputedStyle(document.getElementById('factory-view')).backgroundColor")"
L "first-render active fc-tabs: $(M "document.querySelectorAll('.fc-tab.active').length")"
L "fc-tab base: $(M "var t=document.querySelector('.fc-tab'); t?JSON.stringify({color:getComputedStyle(t).color,size:getComputedStyle(t).fontSize,weight:getComputedStyle(t).fontWeight}):'none'")"
L "factory stats: $(M "JSON.stringify([...document.querySelectorAll('.fc-stat-value')].map(function(e){return e.textContent.trim()}))")"
ab eval "document.querySelector('.fc-mission-row')?.click()" > /dev/null 2>&1
ab wait 1600 > /dev/null 2>&1
L "active tab underline color: $(M "var t=document.querySelector('.fc-tab.active'); t?getComputedStyle(t,'::after').backgroundColor:'none'")"
L "active tab text color: $(M "var t=document.querySelector('.fc-tab.active'); t?getComputedStyle(t).color:'none'")"
shot factory-mission-view-1440

L ""
L "== [R6] N-4 re-verification: unified dot semantics =="
L "mission dots (rendered): $(M "JSON.stringify([...document.querySelectorAll('.fc-mission-row')].slice(0,3).map(function(r){var d=r.querySelector('[class*=dot]'); return d?{cls:String(d.className),color:getComputedStyle(d).backgroundColor,anim:getComputedStyle(d).animationName}:null}))")"
L "tokens: accent-agent / ok / warn / danger = $(M "var cs=getComputedStyle(document.documentElement); [cs.getPropertyValue('--accent-agent'),cs.getPropertyValue('--ok'),cs.getPropertyValue('--warn'),cs.getPropertyValue('--danger')].join(' / ').trim()")"

L ""
L "== [R7] N-6 re-verification: honest no-provider error + eb-btn computed colors =="
ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
ab wait 500 > /dev/null 2>&1
ab eval "document.getElementById('plus').click()" > /dev/null 2>&1
ab wait 250 > /dev/null 2>&1
ab eval "document.querySelector('.plus-option[data-mode=chat]').click()" > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1
ab eval "var i=document.getElementById('input'); i.value='اختبر الاتصال'; i.dispatchEvent(new Event('input',{bubbles:true})); 'typed'" > /dev/null 2>&1
ab eval "document.getElementById('send').click()" > /dev/null 2>&1
ab wait 7000 > /dev/null 2>&1
L "sys-card.error count: $(ab get count '.sys-card.error' 2>&1)"
L "error human text: $(M "var e=document.querySelector('.sys-card.error .human-error'); e?JSON.stringify(e.textContent.slice(0,90)):'none'")"
L "eb-btn count: $(ab get count '.eb-btn' 2>&1)"
L "eb-btn computed: $(M "var b=document.querySelector('.eb-btn'); b?JSON.stringify({bg:getComputedStyle(b).backgroundColor,color:getComputedStyle(b).color}):'not-rendered-in-this-state'")"
shot chat-error-no-provider-1440

L ""
L "== [R8] horizontal overflow at all 6 target viewports (fresh loads) =="
for V in "1920 1080" "1440 900" "1280 800" "768 1024" "390 844" "360 800"; do
  set -- $V
  ab set viewport "$1" "$2" > /dev/null 2>&1
  ab open "$BASE/?vp=$1-$STAMP" > /dev/null 2>&1
  ab wait --load networkidle > /dev/null 2>&1
  ab wait 1400 > /dev/null 2>&1
  L "MEASURE|viewport-$1|$(M "$MEASURE")"
done
ab set viewport 768 1024 > /dev/null 2>&1
ab open "$BASE/?t=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1400 > /dev/null 2>&1
shot tablet-chat-768
ab set viewport 390 844 > /dev/null 2>&1
ab open "$BASE/?m=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1400 > /dev/null 2>&1
shot mobile-chat-390
ab set viewport 360 800 > /dev/null 2>&1
ab open "$BASE/?n=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1400 > /dev/null 2>&1
shot mobile-chat-360

L ""
L "== [R9] BUG-04 re-verification: existing-but-empty conversation shows honest guidance =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/#/chat/5" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1600 > /dev/null 2>&1
L "empty-note text: $(M "var e=document.querySelector('.history-loading'); e?JSON.stringify(e.textContent.trim().slice(0,80)):'none'")"
shot chat-empty-conv-1440

L ""
L "== [R10] BUG-03 re-verification: sidebar sync across 900px breakpoint without reload =="
ab open "$BASE/?bug3=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1400 > /dev/null 2>&1
L "fresh@1440: $(M "document.body.classList.contains('sidebar-collapsed')?'collapsed(BAD)':'open(GOOD)'")"
ab set viewport 390 844 > /dev/null 2>&1
ab wait 600 > /dev/null 2>&1
L "shrunk→390 no-reload: $(M "document.body.classList.contains('sidebar-collapsed')?'collapsed(GOOD)':'open(BAD)'")"
ab set viewport 1440 900 > /dev/null 2>&1
ab wait 600 > /dev/null 2>&1
L "grown→1440 no-reload: $(M "document.body.classList.contains('sidebar-collapsed')?'collapsed(BAD)':'re-opened(GOOD)'")"

L ""
L "== [R11] runs & archive surfaces render =="
ab eval "document.querySelector('.side-nav-item[data-nav=runs]').click()" > /dev/null 2>&1
ab wait 1000 > /dev/null 2>&1
L "runs-view display: $(M "var v=document.getElementById('runs-view'); v?getComputedStyle(v).display:'none'")"
ab eval "document.querySelector('.side-nav-item[data-nav=archive]').click()" > /dev/null 2>&1
ab wait 1000 > /dev/null 2>&1
L "archive-view display: $(M "var v=document.getElementById('archive-view'); v?getComputedStyle(v).display:'none'")"

L ""
L "== [R12] project view tabs render with real data =="
ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
ab wait 500 > /dev/null 2>&1
ab eval "document.querySelectorAll('.pj-item')[0].click()" > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
L "project tabs: $(M "JSON.stringify([...document.querySelectorAll('.pl-tab')].map(function(t){return t.textContent.trim()}))")"
ab eval "document.querySelector('.pl-tab[data-tab=evidence]').click()" > /dev/null 2>&1
ab wait 1100 > /dev/null 2>&1
shot project-evidence-1440

L ""
L "== [R13] whole-session console output and page errors (expect empty) =="
L "--- console:"
ab console 2>&1 | tail -8 >> "$LOG"
L "--- errors:"
ab errors 2>&1 | tail -5 >> "$LOG"

L ""
L "== [R14] static wiring appendix (tokens) =="
rg -n -- "--accent-agent" src/ui/theme.css src/ui/factory-control.css src/ui/live.css >> "$LOG" 2>&1
rg -n -- "--z-modal" src/ui/theme.css src/ui/project-live.css >> "$LOG" 2>&1

kill $SRV 2>/dev/null
ab close > /dev/null 2>&1
L ""
L "== session end =="
echo "DONE — log: $LOG (exit ok)"
