#!/bin/bash
# AES-006 Phase 4: LIVE UI validation through SSH tunnel to production (8010).
# Tunnel + browser must live in ONE invocation (sandbox kills processes between calls).
set -u
OUT=/home/z/my-project/download/oracle-deploy/live
mkdir -p "$OUT"

# 1) tunnel up
setsid nohup python3 /home/z/my-project/scripts/tunnel.py >/tmp/tunnel.log 2>&1 &
sleep 4
if ! curl -s --max-time 8 http://127.0.0.1:18010/health | head -c 200; then
  echo "TUNNEL FAILED"; cat /tmp/tunnel.log; exit 1
fi
echo; echo "=== TUNNEL OK, health above ==="

# 2) open the app
agent-browser open http://127.0.0.1:18010/ >/dev/null 2>&1
agent-browser wait --load networkidle >/dev/null 2>&1 || true
sleep 2

# 3) 1440x900 — main conversation view
agent-browser set viewport 1440 900 >/dev/null
sleep 1
agent-browser screenshot "$OUT/live-1440-chat.png"
echo "=== TITLE ==="; agent-browser get title
echo "=== version links in page (must be 4.0.0) ==="
agent-browser eval "Array.from(document.querySelectorAll('link[rel=stylesheet],script[src]')).map(e=>(e.href||e.src).match(/v=([0-9.]+)/)?.[1]).filter(Boolean).reduce((a,v)=>(a[v]=(a[v]||0)+1,a),{})"
echo "=== conversations in sidebar (from real production DB) ==="
agent-browser eval "document.querySelectorAll('#conversations-list .conversation-item, #conversations-list li, [data-conversation-id]').length"
echo "=== fonts loaded? ==="
agent-browser eval "document.fonts.check('16px \"IBM Plex Sans Arabic\"') + ' ' + document.fonts.check('13px \"IBM Plex Mono\"') + ' ' + document.fonts.check('700 16px \"IBM Plex Sans Arabic\"')"

# 4) factory view
echo "=== snapshot interactive (nav) ==="
agent-browser snapshot -i -c 2>/dev/null | head -40
