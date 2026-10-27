#!/bin/bash
# AES-UI-PREMIUM-REDESIGN-004 — FINAL INTEGRATION AUDIT (live browser phase)
# Runs on aes-ui-premium-redesign @ f83f164 (ui-work worktree).
# Tests: chat view + composer, navigation (settings/runs/archive), factory
# request-storm guard, real-data DOM-vs-API match, JS console/page errors.
set -u
cd /home/z/my-project/ui-work
DB=runtime/ui-redesign.db
PORT=8040
OUT=/home/z/my-project/download/ui-redesign/audit004
mkdir -p "$OUT"

echo "== [0] seed demo conversations (real SQLAlchemy layer, idempotent) =="
AGenthubV2_DB_PATH=$DB PYTHONPATH=src /home/z/.venv/bin/python3 /home/z/my-project/scripts/seed_ui_demo.py 2>&1 | tail -1

PYTHONPATH=src AGenthubV2_DB_PATH=$DB /home/z/.venv/bin/python3 -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-audit004.log 2>&1 &
SRV=$!
for i in $(seq 1 60); do curl -s -o /dev/null http://127.0.0.1:$PORT/health && break; sleep 0.5; done
echo "== server up on port $PORT (pid $SRV, log /tmp/aes-audit004.log)"

ab() { agent-browser "$@"; }

# ================= 1. CHAT VIEW =================
STAMP=$(date +%s)
ab open "http://127.0.0.1:$PORT/?fresh=$STAMP" > /dev/null 2>&1
ab set viewport 1440 900 > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
echo "== [1] CHAT VIEW =="
echo "title: $(ab get title 2>&1)"
echo "conv-items in sidebar (from real API): $(ab get count '.conv-item' 2>&1)"
echo "composer present: $(ab eval "document.getElementById('input') ? 'YES' : 'NO'" 2>&1)"
ab screenshot "$OUT/chat-1440.png" > /dev/null 2>&1
echo "shot: chat-1440.png"
echo "--- console after chat load:"
ab console 2>&1 | tail -6
ab console --clear > /dev/null 2>&1

# ================= 2. CHAT COMPOSER + SEND =================
echo "== [2] CHAT COMPOSER / SEND =="
ab eval "var i=document.getElementById('input'); i.value='رسالة تدقيق 004 — اختبار زر الإرسال'; i.dispatchEvent(new Event('input',{bubbles:true})); 'typed'" > /dev/null 2>&1
echo "send enabled after typing (expect false): $(ab eval "document.getElementById('send').disabled" 2>&1)"
ab eval "var i=document.getElementById('input'); i.value=''; i.dispatchEvent(new Event('input',{bubbles:true})); 'cleared'" > /dev/null 2>&1
echo "send disabled after clear (expect true): $(ab eval "document.getElementById('send').disabled" 2>&1)"
ab eval "var i=document.getElementById('input'); i.value='مرحبا — رسالة تدقيق حية'; i.dispatchEvent(new Event('input',{bubbles:true})); 'typed2'" > /dev/null 2>&1
echo "msg nodes before send: $(ab get count '.msg' 2>&1)"
ab eval "document.getElementById('send').click()" > /dev/null 2>&1
ab wait 5000 > /dev/null 2>&1
echo "msg nodes after send (chat + honest outcome): $(ab get count '.msg' 2>&1)"
echo "error-card nodes after send: $(ab get count '[class*=error]' 2>&1)"
echo "composer cleared after send (expect cleared): $(ab eval "document.getElementById('input').value === '' ? 'cleared' : 'NOT-cleared'" 2>&1)"
echo "send re-enabled after settle: $(ab eval "!document.getElementById('send').disabled ? 'YES' : 'still-disabled'" 2>&1)"
echo "--- console after chat send:"
ab console 2>&1 | tail -8
ab console --clear > /dev/null 2>&1

# ================= 3. NAVIGATION =================
echo "== [3] NAVIGATION (settings / runs / archive / back) =="
ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 700 > /dev/null 2>&1
echo "settings drawer open: $(ab eval "!document.getElementById('settings-drawer').hidden ? 'YES' : 'NO'" 2>&1)"
ab screenshot "$OUT/settings-open-1440.png" > /dev/null 2>&1
echo "shot: settings-open-1440.png"
ab press Escape > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1
echo "settings drawer after Esc (expect hidden): $(ab eval "document.getElementById('settings-drawer').hidden ? 'hidden' : 'STILL-OPEN'" 2>&1)"

ab eval "document.querySelector('.side-nav-item[data-nav=runs]').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
echo "nav=runs → unhidden cc-views: $(ab eval "[...document.querySelectorAll('.cc-view')].filter(v=>!v.hidden).map(v=>v.id).join(',')||'none'" 2>&1)"
ab screenshot "$OUT/runs-1440.png" > /dev/null 2>&1
echo "shot: runs-1440.png"
ab eval "document.querySelector('.side-nav-item[data-nav=archive]').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
echo "nav=archive → unhidden cc-views: $(ab eval "[...document.querySelectorAll('.cc-view')].filter(v=>!v.hidden).map(v=>v.id).join(',')||'none'" 2>&1)"
ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
ab wait 700 > /dev/null 2>&1
echo "nav=chat → unhidden cc-views (expect none): $(ab eval "[...document.querySelectorAll('.cc-view')].filter(v=>!v.hidden).map(v=>v.id).join(',')||'none'" 2>&1)"
echo "--- console after navigation:"
ab console 2>&1 | tail -6
ab console --clear > /dev/null 2>&1

# ================= 4. FACTORY — REQUEST STORM GUARD =================
echo "== [4] FACTORY REQUEST-STORM CHECK =="
ab eval "(function(){window.__req={n:0,urls:{}};if(!window.__fetchPatched){window.__fetchPatched=true;var of=window.fetch;window.fetch=function(){var u=String(arguments[0]).split('?')[0];window.__req.n++;window.__req.urls[u]=(window.__req.urls[u]||0)+1;return of.apply(this,arguments)};var oo=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(m,u){var k=String(u).split('?')[0];window.__req.n++;window.__req.urls[k]=(window.__req.urls[k]||0)+1;return oo.apply(this,arguments)}}return 'patched'})()" > /dev/null 2>&1
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
echo "requests @+2s:  $(ab eval "window.__req.n" 2>&1)"
ab wait 10000 > /dev/null 2>&1
echo "requests @+12s: $(ab eval "window.__req.n" 2>&1)"
ab wait 5000 > /dev/null 2>&1
echo "requests @+17s: $(ab eval "window.__req.n" 2>&1)  (stable if == @+12s)"
echo "per-url tally: $(ab eval "JSON.stringify(window.__req.urls)" 2>&1)"

# ================= 5. REAL DATA: DOM vs API =================
echo "== [5] REAL DATA — factory DOM vs API ground truth =="
echo "DOM stats: $(ab eval "JSON.stringify({missionRows: document.querySelectorAll('.fc-mission-row').length, statValues: [...document.querySelectorAll('.fc-stat-value')].map(e=>e.textContent.trim()), sysStatus: document.getElementById('factory-system-status').textContent})" 2>&1)"
echo "DOM mission ids: $(ab eval "JSON.stringify([...document.querySelectorAll('.fc-mission-row')].map(r=>r.getAttribute('data-mission-id')))" 2>&1)"
echo "API /api/projects: $(curl -s http://127.0.0.1:$PORT/api/projects)"
echo "API /api/harness/roles (first 400): $(curl -s http://127.0.0.1:$PORT/api/harness/roles | head -c 400)"
echo "API /api/mission/status: $(curl -s http://127.0.0.1:$PORT/api/mission/status)"
echo "API /health: $(curl -s http://127.0.0.1:$PORT/health)"
ab screenshot "$OUT/factory-overview-1440.png" > /dev/null 2>&1
echo "shot: factory-overview-1440.png"

# ================= 6. RE-ENTRY BOUNDED REFETCH =================
echo "== [6] FACTORY RE-ENTRY (bounded refetch, no storm) =="
ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
ab wait 800 > /dev/null 2>&1
ab eval "window.__req.n=0; window.__req.urls={}; 'reset'" > /dev/null 2>&1
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 8000 > /dev/null 2>&1
echo "re-entry requests @+8s (expect ~4 then stable): $(ab eval "window.__req.n + ' :: ' + JSON.stringify(window.__req.urls)" 2>&1)"

# ================= 7. FINAL CONSOLE / ERRORS =================
echo "== [7] CONSOLE (factory phase) =="
ab console 2>&1 | tail -10
echo "== [7] PAGE ERRORS (whole session) =="
ab errors 2>&1 | tail -8
echo "== [7] agent-browser tracked network (filter api) =="
ab network requests --filter api 2>&1 | tail -12

kill $SRV 2>/dev/null
echo "== done, server stopped =="
