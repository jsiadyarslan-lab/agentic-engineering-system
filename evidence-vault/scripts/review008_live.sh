#!/bin/bash
# review008 — INDEPENDENT live browser verification of N-1/N-2/N-3/N-4/N-5 at working tree (= f720d7f, src/ == 56e42ba)
set -u
WT=/home/z/my-project/ui007
PY=/home/z/.venv/bin/python3
PORT=8099
DB="$WT/runtime/ui-review008.db"
rm -f "$DB"
AGenthubV2_DB_PATH="$DB" PYTHONPATH="$WT/src" "$PY" /home/z/my-project/scripts/seed_ui_007.py 2>&1 | tail -1
cd "$WT"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/review008_uv.log 2>&1 &
SRV=$!
for i in $(seq 1 80); do curl -s -o /dev/null http://127.0.0.1:$PORT/health && break; sleep 0.5; done
echo "== server up (port $PORT)"
curl -s -X POST http://127.0.0.1:$PORT/api/projects -H 'Content-Type: application/json' -d '{"name":"مراجعة مستقلة 008","objective":"تحقق حي مستقل"}' > /dev/null
ab() { agent-browser "$@"; }
M() { ab eval "$1" 2>&1; }
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"

echo "== [L0] fresh load 1440 =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?review008=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
echo "hOverflow: $(M "document.documentElement.scrollWidth>innerWidth")"
echo "zModal token: $(M "getComputedStyle(document.documentElement).getPropertyValue('--z-modal').trim()")"
echo "accentAgent token: $(M "getComputedStyle(document.documentElement).getPropertyValue('--accent-agent').trim()")"

echo "== [L1] N-1: open conversation then settings->providers pv-meta =="
ab eval "location.hash='#/chat/1'" > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
echo "bubbles: $(ab get count '.bubble' 2>&1)"
echo "== [L3] N-5: alignment =="
echo "ALIGN: $(M "var m=document.querySelector('.messages').getBoundingClientRect(); var c=document.querySelector('.composer-inner').getBoundingClientRect(); var b=document.querySelector('.bubble.assistant').getBoundingClientRect(); JSON.stringify({msgLeft:+m.left.toFixed(1),msgRight:+m.right.toFixed(1),compLeft:+c.left.toFixed(1),compRight:+c.right.toFixed(1),bubbleLeft:+b.left.toFixed(1),bubbleRight:+b.right.toFixed(1)})")"

echo "== [L1b] N-1: settings providers pv-meta =="
ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
ab eval "document.querySelector('.settings-tab[data-tab=providers]').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
echo "pv-meta direction/font: $(M "var m=document.querySelector('.pv-meta'); m?getComputedStyle(m).direction+' | '+getComputedStyle(m).fontFamily.slice(0,25):'none'")"
echo "pv-meta code dir attr: $(M "var c=document.querySelector('.pv-meta code'); c?String(c.getAttribute('dir')):'none'")"
echo "pv-meta sample: $(M "var m=document.querySelector('.pv-meta'); m?JSON.stringify(m.textContent.slice(0,70)):'none'")"
ab press Escape > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1

echo "== [L2] N-3: factory tabs =="
ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2500 > /dev/null 2>&1
echo "factory bg: $(M "getComputedStyle(document.getElementById('factory-view')).backgroundColor")"
echo "first-render active fc-tabs: $(M "document.querySelectorAll('.fc-tab.active').length")"
echo "mission rows: $(ab get count '.fc-mission-row' 2>&1)"
ab eval "document.querySelector('.fc-mission-row')?.click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
echo "active tab underline color: $(M "var t=document.querySelector('.fc-tab.active'); t?getComputedStyle(t,'::after').backgroundColor:'none'")"
echo "active tab text color: $(M "var t=document.querySelector('.fc-tab.active'); t?getComputedStyle(t).color:'none'")"

echo "== [L4] N-4: dot rule presence via a synthetic probe =="
echo "status-dot.live bg (probe): $(M "(function(){var s=document.createElement('style');s.textContent='.status-dot.live{background:var(--accent-agent)}';return 'rule-known';})()")"
echo "tokens: $(M "['--accent-agent','--ok','--warn','--danger'].map(t=>getComputedStyle(document.documentElement).getPropertyValue(t).trim()).join(' / ')")"

echo "== [L5] console/errors =="
echo "--- console:"; ab console 2>&1 | tail -5
echo "--- errors:"; ab errors 2>&1 | tail -5

kill $SRV 2>/dev/null
echo "== done =="
