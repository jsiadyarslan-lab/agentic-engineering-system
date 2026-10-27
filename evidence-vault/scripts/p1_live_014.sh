#!/bin/bash
# AES-014 — LIVE Phase-1 acceptance through the PUBLIC-link path
set -u
OUT=/home/z/my-project/download/redesign-014/phase1-live
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

echo "== [0] جدار =="
echo "no-auth: $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 $BASE/) / auth: $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 -u "$USERID:$PW" $BASE/)"

ab() { agent-browser "$@"; }

echo "== [1] 1440 =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2500 > /dev/null 2>&1
ab screenshot "$OUT/LIVE-p1-welcome-1440.png" > /dev/null 2>&1 && echo "shot: LIVE-p1-welcome-1440"

echo "== [2] قياسات المرحلة الأولى حيًا =="
ab eval "JSON.stringify({
  assetsV: Array.from(document.querySelectorAll('link[rel=stylesheet], script[src]')).map(e => (e.href || e.src).match(/v=([0-9a-f]{8})/)).filter(Boolean).length,
  staleV: Array.from(document.querySelectorAll('link[rel=stylesheet], script[src]')).filter(e => /v=4\\.0\\.0/.test(e.href || e.src)).length,
  composerGap: Math.round(window.innerHeight - document.querySelector('.composer').getBoundingClientRect().bottom),
  inputMinH: getComputedStyle(document.getElementById('input')).minHeight,
  sendRound: getComputedStyle(document.getElementById('send')).borderRadius,
  sendSize: Math.round(document.getElementById('send').getBoundingClientRect().width),
  welcomeCentered: Math.abs((document.querySelector('.welcome').getBoundingClientRect().top + document.querySelector('.welcome').getBoundingClientRect().height/2) - (document.querySelector('.chat-scroll').getBoundingClientRect().top + document.querySelector('.chat-scroll').getBoundingClientRect().height/2)) < 60,
  pillH: Math.round(document.querySelector('.suggestion').getBoundingClientRect().height),
  h1Size: getComputedStyle(document.querySelector('.welcome h1')).fontSize,
  hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  consoleErr: window.__errCount || 0
})" > "$OUT/tokens-live.json" 2>&1
cat "$OUT/tokens-live.json"; echo ""

echo "== [3] تفاعل حي: كتابة + نقر حبة =="
ab eval "const i=document.getElementById('input'); i.value='مرحبا'; i.dispatchEvent(new Event('input',{bubbles:true})); JSON.stringify({sendEnabled: !document.getElementById('send').disabled})" 2>&1 | head -2
ab screenshot "$OUT/LIVE-p1-typing-1440.png" > /dev/null 2>&1 && echo "shot: LIVE-p1-typing-1440"

echo "== [4] mobile 390 =="
ab set viewport 390 844 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP&m=1" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
ab screenshot "$OUT/LIVE-p1-welcome-390.png" > /dev/null 2>&1 && echo "shot: LIVE-p1-welcome-390"
ab eval "JSON.stringify({hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth, gap: Math.round(window.innerHeight - document.querySelector('.composer').getBoundingClientRect().bottom), inputMinH: getComputedStyle(document.getElementById('input')).minHeight})" 2>&1 | head -2

echo "== [5] console =="
ab console > "$OUT/console.txt" 2>&1; wc -l < "$OUT/console.txt"

kill $TUN 2>/dev/null
echo "P1_LIVE_DONE"
