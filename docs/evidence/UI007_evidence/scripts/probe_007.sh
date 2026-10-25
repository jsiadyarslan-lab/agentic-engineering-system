#!/bin/bash
# 007 — focused probe: error-state classes + message render + resize behavior
set -u
WT=/home/z/my-project/ui007
PY=/home/z/.venv/bin/python3
PORT=8050
OUT=/home/z/my-project/download/ui-redesign-007/baseline
DB="$WT/runtime/ui-007.db"
cd "$WT"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-007-probe.log 2>&1 &
SRV=$!
for i in $(seq 1 80); do curl -s -o /dev/null http://127.0.0.1:$PORT/health && break; sleep 0.5; done
ab() { agent-browser "$@"; }
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"

# CRITICAL: set viewport BEFORE open (avoid stale 390 collapse)
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?probe=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
echo "sidebarW at 1440 fresh: $(ab eval "document.getElementById('sidebar').getBoundingClientRect().width" 2>&1)"

echo "== messages render check =="
ab eval "document.querySelectorAll('.conv-item')[0].click()" > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
echo "bubbles: $(ab get count '.bubble' 2>&1)"
echo "assistant bubbles: $(ab get count '.bubble.assistant' 2>&1)"
echo "md-table-wrap: $(ab get count '.md-table-wrap' 2>&1)"
echo "md-code: $(ab get count '.md-code' 2>&1)"
echo "md-list: $(ab get count '.md-list' 2>&1)"
echo "bubble-measure: $(ab eval "var b=document.querySelector('.bubble.assistant .bubble-body'); b?JSON.stringify({fs:getComputedStyle(b).fontSize,lh:getComputedStyle(b).lineHeight,color:getComputedStyle(b).color}):'none'" 2>&1)"
ab screenshot "$OUT/pop chat-long-ar-1440.png" > /dev/null 2>&1
echo "shot: chat-long-ar-1440 (re-taken with sidebar open)"

echo "== user bubble measure =="
echo "user-bubble: $(ab eval "var u=document.querySelector('.bubble.user'); u?JSON.stringify({bg:getComputedStyle(u).backgroundColor,fs:getComputedStyle(u.querySelector('.bubble-body')).fontSize}):'none'" 2>&1)"

echo "== error state: chat mode send without provider =="
ab eval "var p=document.querySelector('.plus-option[data-mode=chat]'); 'skip'" > /dev/null 2>&1
ab eval "document.getElementById('plus').click()" > /dev/null 2>&1
ab wait 200 > /dev/null 2>&1
ab eval "document.querySelector('.plus-option[data-mode=chat]').click()" > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1
ab eval "var i=document.getElementById('input'); i.value='اختبر الاتصال'; i.dispatchEvent(new Event('input',{bubbles:true})); 'typed'" > /dev/null 2>&1
echo "send disabled: $(ab eval "document.getElementById('send').disabled" 2>&1)"
ab eval "document.getElementById('send').click()" > /dev/null 2>&1
ab wait 7000 > /dev/null 2>&1
echo "after-send classes in #messages: $(ab eval "JSON.stringify([...document.querySelectorAll('#messages > *')].map(e=>e.className||e.tagName).slice(-8))" 2>&1)"
echo "sys-card: $(ab get count '.sys-card' 2>&1), human-error: $(ab get count '.human-error' 2>&1), config-card: $(ab get count '.config-card' 2>&1), error-ish: $(ab get count '[class*=error]' 2>&1)"
ab screenshot "$OUT/pop chat-error-no-provider-1440.png" > /dev/null 2>&1
echo "shot: chat-error-no-provider-1440 (re-taken)"
echo "last-msg-text: $(ab eval "var m=[...document.querySelectorAll('#messages > *')]; m.length? (m[m.length-1].textContent||'').slice(0,200):'none'" 2>&1)"

echo "== resize behavior probe: 1440 -> 390 -> 1440 without reload =="
ab eval "document.body.classList.contains('sidebar-collapsed') ? 'collapsed-before-resize' : 'open-before-resize'" 2>&1
ab set viewport 390 844 > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1
echo "after shrink to 390 (no reload): $(ab eval "document.body.classList.contains('sidebar-collapsed') ? 'collapsed' : 'STILL-OPEN-AT-390'" 2>&1)"
ab eval "document.documentElement.scrollWidth > innerWidth ? 'HOVERFLOW' : 'no-hoverflow'" 2>&1
ab set viewport 1440 900 > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1
echo "after grow back to 1440 (no reload): $(ab eval "document.body.classList.contains('sidebar-collapsed') ? 'STILL-COLLAPSED-AT-1440 (resize bug)' : 're-opened'" 2>&1)"

echo "== task-settings + model picker probe =="
ab set viewport 1440 900 > /dev/null 2>&1
ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1
ab eval "document.getElementById('plus').click()" > /dev/null 2>&1
ab wait 200 > /dev/null 2>&1
ab eval "document.querySelector('.plus-option[data-mode=task]').click()" > /dev/null 2>&1
ab wait 600 > /dev/null 2>&1
ab eval "document.getElementById('task-settings-toggle').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
ab screenshot "$OUT/pop task-settings-1440.png" > /dev/null 2>&1
echo "ts-body rows: $(ab get count '.ts-row' 2>&1)"
echo "ts-measure: $(ab eval "var t=document.querySelector('.task-settings'); t?JSON.stringify({fs:getComputedStyle(t).fontSize,w:t.getBoundingClientRect().width}):'none'" 2>&1)"

echo "== settings models tab + model picker =="
ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
ab eval "document.querySelector('.settings-tab[data-tab=models]').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
echo "role rows: $(ab get count '#role-models > *' 2>&1)"
ab screenshot "$OUT/pop settings-models-1440.png" > /dev/null 2>&1
echo "shot: settings-models-1440 (populated)"
ab press Escape > /dev/null 2>&1

echo "--- console:"; ab console 2>&1 | tail -8
echo "--- errors:"; ab errors 2>&1 | tail -5
kill $SRV 2>/dev/null
echo "== done probe =="
