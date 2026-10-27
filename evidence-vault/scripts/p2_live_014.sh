#!/bin/bash
# AES-014 — LIVE Phase-2 acceptance through the PUBLIC-link path (real data)
set -u
OUT=/home/z/my-project/download/redesign-014/phase2-live
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

echo "auth: $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 -u "$USERID:$PW" $BASE/) / no-auth: $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 $BASE/)"

ab() { agent-browser "$@"; }

ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2500 > /dev/null 2>&1

echo "== فتح أول محادثة حقيقية =="
ab eval "const b = document.querySelectorAll('.conv-item')[0]; if (b) { b.click(); 'OPENED'; } else 'NO_CONVERSATIONS'" 2>&1 | head -2
ab wait 2000 > /dev/null 2>&1
ab screenshot "$OUT/LIVE-p2-conversation-1440.png" > /dev/null 2>&1 && echo "shot: LIVE-p2-conversation-1440"

echo "== قياسات المرحلة الثانية حية =="
ab eval "JSON.stringify({
  assetsV: Array.from(document.querySelectorAll('link[rel=stylesheet], script[src]')).map(e => (e.href || e.src).match(/v=([0-9a-f]{8})/)).filter(Boolean).length,
  staleV: Array.from(document.querySelectorAll('link[rel=stylesheet], script[src]')).filter(e => /v=4\\.0\\.0/.test(e.href || e.src)).length,
  bubbles: document.querySelectorAll('.bubble').length,
  msgHeads: document.querySelectorAll('.msg-head').length,
  whoSample: Array.from(document.querySelectorAll('.msg-who')).slice(0,4).map(e => e.textContent),
  whenMono: document.querySelector('.msg-when') ? getComputedStyle(document.querySelector('.msg-when')).fontFamily.slice(0,14) : null,
  userAlign: document.querySelector('.bubble.user') ? getComputedStyle(document.querySelector('.bubble.user')).alignSelf : null,
  userMinW: document.querySelector('.bubble.user') ? getComputedStyle(document.querySelector('.bubble.user')).minWidth : null,
  codeblockHeads: document.querySelectorAll('.md-code-head').length,
  hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  consoleErr: window.__errCount || 0
})" 2>&1 | head -4

echo "== mobile 390 =="
ab set viewport 390 844 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP&m=2" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
ab eval "const b = document.querySelectorAll('.conv-item')[0]; if (b) b.click(); 'OK'" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$OUT/LIVE-p2-conversation-390.png" > /dev/null 2>&1 && echo "shot: LIVE-p2-conversation-390"
ab eval "JSON.stringify({hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth})" 2>&1 | head -2

echo "== console =="
ab console > "$OUT/console.txt" 2>&1; wc -l < "$OUT/console.txt"

kill $TUN 2>/dev/null
echo "P2_LIVE_DONE"
