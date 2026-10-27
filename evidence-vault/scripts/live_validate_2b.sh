#!/bin/bash
# AES-006 Phase 4 part 2b: factory via semantic locator + request-rate measurement.
set -u
OUT=/home/z/my-project/download/oracle-deploy/live
mkdir -p "$OUT"

setsid nohup python3 /home/z/my-project/scripts/tunnel.py >/tmp/tunnel.log 2>&1 &
sleep 4
curl -s --max-time 8 http://127.0.0.1:18010/health >/dev/null || { echo "TUNNEL FAILED"; exit 1; }
echo "tunnel OK"

agent-browser open http://127.0.0.1:18010/ >/dev/null 2>&1
agent-browser wait --load networkidle >/dev/null 2>&1 || true
agent-browser set viewport 1440 900 >/dev/null
sleep 2

# --- factory via SEMANTIC locator ---
agent-browser find text "مصنع الوكلاء" click >/dev/null 2>&1
sleep 4
agent-browser screenshot "$OUT/live-1440-factory.png"
echo "=== factory view state ==="
agent-browser eval "(() => { const v=document.querySelector('#factory-view'); return {exists: !!v, visible: !!v && v.offsetParent!==null, display: v? getComputedStyle(v).display : null}; })()"
echo "=== factory real data: missions + stats + agents ==="
agent-browser eval "(() => { const v=document.querySelector('#factory-view'); if(!v) return 'no view'; const missions=Array.from(v.querySelectorAll('[data-mission-id]')).map(r=>r.getAttribute('data-mission-id')); const conn=v.querySelector('[class*=stat], .overview-stats'); const agents=v.querySelectorAll('[class*=agent], .agent-row, [data-agent-role]').length; return {missionIds: missions.slice(0,5), statsText: conn? conn.textContent.replace(/\\s+/g,' ').slice(0,150):null, agentRows: agents}; })()"

# --- request rate on factory: count, wait 12s, count again ---
C1=$(agent-browser network requests 2>/dev/null | wc -l)
sleep 12
C2=$(agent-browser network requests 2>/dev/null | wc -l)
echo "=== request rate on factory over 12s: $C1 -> $C2 (delta $((C2-C1))) ==="
agent-browser network requests 2>/dev/null | tail -4

# --- factory at 390 too ---
agent-browser set viewport 390 844 >/dev/null; sleep 1
agent-browser screenshot "$OUT/live-390-factory.png"
agent-browser eval "document.documentElement.scrollWidth + ' vs ' + document.documentElement.clientWidth"

# --- back to chat via semantic locator ---
agent-browser set viewport 1440 900 >/dev/null
agent-browser find text "المحادثات" click >/dev/null 2>&1
sleep 2
agent-browser screenshot "$OUT/live-1440-back-to-chat.png"
agent-browser eval "(() => { const v=document.querySelector('#factory-view'); const h=document.querySelector('h1'); return {factoryHidden: v? getComputedStyle(v).display==='none':null, chatHeading: h? h.textContent.slice(0,30):null}; })()"

# --- settings panel open + Esc close ---
agent-browser find text "الإعدادات" click >/dev/null 2>&1 || agent-browser find text "المزودون" click >/dev/null 2>&1
sleep 1
agent-browser screenshot "$OUT/live-1440-settings.png"
agent-browser eval "!!document.querySelector('[class*=settings][class*=open], #settings-panel.open, .settings-panel[style*=block]')"
agent-browser press Escape >/dev/null 2>&1
sleep 1
echo "=== settings closed after Esc ==="
agent-browser eval "!document.querySelector('[class*=settings][class*=open], #settings-panel.open, .settings-panel[style*=block]')"

# --- final error audit ---
echo "=== console errors ==="; agent-browser console 2>/dev/null | grep -icE "error" || echo 0
agent-browser console 2>/dev/null | grep -iE "error" | head -5
echo "=== page errors count ==="; agent-browser errors 2>/dev/null | wc -l
echo "=== total network vs 200s ==="
TOTAL=$(agent-browser network requests 2>/dev/null | wc -l)
OK200=$(agent-browser network requests 2>/dev/null | grep -c "200" )
echo "total=$TOTAL  with-200=$OK200"

agent-browser close >/dev/null 2>&1
kill $(cat /tmp/aes-tunnel.pid) 2>/dev/null
echo "=== PART 2B DONE ==="
