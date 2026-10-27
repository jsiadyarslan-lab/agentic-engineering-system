#!/bin/bash
# AES-006 Phase 4 part 2: factory view, navigation, viewports, error checks.
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

# --- factory view ---
agent-browser snapshot -i -c >/dev/null 2>&1
FACTORY_REF=$(agent-browser snapshot -i --json 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
def walk(nodes):
    for n in nodes:
        if 'مصنع' in (n.get('name') or ''):
            print(n.get('ref')); return True
        if walk(n.get('children', [])): return True
    return False
walk(d.get('snapshot', d) if isinstance(d, dict) else d)" 2>/dev/null | head -1)
echo "factory ref: $FACTORY_REF"
agent-browser click "${FACTORY_REF:-@e8}" >/dev/null 2>&1
sleep 3
agent-browser screenshot "$OUT/live-1440-factory.png"
echo "=== factory: view visible + real data ==="
agent-browser eval "(() => { const v=document.querySelector('#factory-view'); const rows=document.querySelectorAll('#factory-view [data-mission-id], #factory-view .mission-row').length; const stats=document.querySelector('#factory-view .stats, #factory-view [class*=stat]'); return {visible: !!v && v.offsetParent!==null, missionRows: rows, statText: stats? stats.textContent.slice(0,120):null}; })()"

# --- request-storm check: count API calls in 10s while sitting on factory ---
agent-browser network requests >/dev/null 2>&1 || true
echo "=== API requests during 10s on factory (storm check) ==="
sleep 10
agent-browser network requests --filter "api/" 2>/dev/null | tail -12

# --- back to conversations ---
agent-browser snapshot -i -c >/dev/null 2>&1
CHAT_REF=$(agent-browser snapshot -i --json 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
def walk(nodes):
    for n in nodes:
        if 'المحادثات' in (n.get('name') or ''):
            print(n.get('ref')); return True
        if walk(n.get('children', [])): return True
    return False
walk(d.get('snapshot', d) if isinstance(d, dict) else d)" 2>/dev/null | head -1)
echo "chat ref: $CHAT_REF"
agent-browser click "${CHAT_REF:-@e6}" >/dev/null 2>&1
sleep 2
echo "=== back on chat: heading + composer present ==="
agent-browser eval "(() => { const h=document.querySelector('h1'); const c=document.querySelector('#composer, [class*=composer]'); return {heading: h? h.textContent.slice(0,40):null, composer: !!c}; })()"

# --- 768x1024 ---
agent-browser set viewport 768 1024 >/dev/null
sleep 1
agent-browser screenshot "$OUT/live-768-chat.png"
echo "=== 768: no horizontal scroll ==="
agent-browser eval "document.documentElement.scrollWidth + ' vs ' + document.documentElement.clientWidth"

# --- 390x844 ---
agent-browser set viewport 390 844 >/dev/null
sleep 1
agent-browser screenshot "$OUT/live-390-chat.png"
echo "=== 390: no horizontal scroll ==="
agent-browser eval "document.documentElement.scrollWidth + ' vs ' + document.documentElement.clientWidth"
agent-browser screenshot --full "$OUT/live-390-chat-full.png" >/dev/null 2>&1

# --- errors: console + page errors + failed network ---
echo "=== console messages (errors only) ==="
agent-browser console 2>/dev/null | grep -iE "error|warn|fail" | head -10 || echo "(no error/warn lines)"
echo "=== page errors ==="
agent-browser errors 2>/dev/null | head -10 || echo "(no page errors)"
echo "=== failed network requests (non-2xx) ==="
agent-browser network requests 2>/dev/null | grep -vE " (200|204|30[12]) " | head -10 || echo "(all 2xx)"

agent-browser close >/dev/null 2>&1
kill $(cat /tmp/aes-tunnel.pid) 2>/dev/null
echo "=== VALIDATION PART 2 DONE ==="
