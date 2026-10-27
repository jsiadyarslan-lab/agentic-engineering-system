#!/bin/bash
# AES-014 — LIVE Phase-3 acceptance through the PUBLIC-link path
set -u
OUT=/home/z/my-project/download/redesign-014/phase3-live
mkdir -p "$OUT"
CREDS=$(cat /home/z/my-project/reproof-014-auth.txt)
USERID=${CREDS%%:*}
PW=${CREDS#*:}
BASE="http://127.0.0.1:18082"
STAMP=$(date +%s)
AUTHHDR=$(printf '{"Authorization":"Basic %s"}' "$(printf '%s:%s' "$USERID" "$PW" | base64 -w0)")

/home/z/.venv/bin/python3 /home/z/my-project/scripts/tunnel_014.py > "$OUT/tunnel.log" 2>&1 &
TUN=$!
for i in $(seq 1 40); do curl -s -o /dev/null "$BASE/health" && break; sleep 0.4; done

ab() { agent-browser "$@"; }
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2500 > /dev/null 2>&1
ab screenshot "$OUT/LIVE-p3-welcome-1440.png" > /dev/null 2>&1 && echo "shot: LIVE-p3-welcome-1440"

ab eval "JSON.stringify({
  assetsV: Array.from(document.querySelectorAll('link[rel=stylesheet], script[src]')).map(e => (e.href || e.src).match(/v=([0-9a-f]{8})/)).filter(Boolean).length,
  staleV: Array.from(document.querySelectorAll('link[rel=stylesheet], script[src]')).filter(e => /v=4\\.0\\.0/.test(e.href || e.src)).length,
  sectionHead: (document.querySelector('.conv-section-head span') || {}).textContent,
  convItems: document.querySelectorAll('.conv-item').length,
  twoLineItems: document.querySelectorAll('.conv-item .conv-title').length,
  metaLines: document.querySelectorAll('.conv-item .conv-meta').length,
  dots: document.querySelectorAll('.conv-item .status-dot.sm').length,
  dotSize: document.querySelector('.conv-item .status-dot.sm') ? getComputedStyle(document.querySelector('.conv-item .status-dot.sm')).width : null,
  newChatH: Math.round(document.getElementById('new-chat').getBoundingClientRect().height),
  searchH: Math.round(document.getElementById('side-search').getBoundingClientRect().height),
  searchBg: getComputedStyle(document.getElementById('side-search')).backgroundColor,
  sidebarW: Math.round(document.querySelector('.sidebar').getBoundingClientRect().width),
  hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  consoleErr: window.__errCount || 0
})" 2>&1 | head -3
ab console > "$OUT/console.txt" 2>&1; echo "console lines: $(wc -l < "$OUT/console.txt")"
kill $TUN 2>/dev/null
echo "P3_LIVE_DONE"
