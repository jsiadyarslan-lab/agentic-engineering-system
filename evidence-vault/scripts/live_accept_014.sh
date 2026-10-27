#!/bin/bash
# AES-014 — LIVE Phase-0 acceptance through the PUBLIC-link path
# (SSH tunnel -> same nginx vhost + Basic Auth the owner's browser hits)
set -u
OUT=/home/z/my-project/download/redesign-014/live-verify
mkdir -p "$OUT"
CREDS=$(cat /home/z/my-project/reproof-014-auth.txt)   # aes014:PW
USERID=${CREDS%%:*}
PW=${CREDS#*:}
BASE="http://127.0.0.1:18082"
STAMP=$(date +%s)
AUTHHDR=$(printf '{"Authorization":"Basic %s"}' "$(printf '%s:%s' "$USERID" "$PW" | base64 -w0)")

/home/z/.venv/bin/python3 /home/z/my-project/scripts/tunnel_014.py > "$OUT/tunnel.log" 2>&1 &
TUN=$!
for i in $(seq 1 40); do curl -s -o /dev/null "$BASE/health" && break; sleep 0.4; done

echo "== [0] جدار المصادقة =="
echo "no-auth: $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 $BASE/)"
echo "auth:    $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 -u "$USERID:$PW" $BASE/)"

ab() { agent-browser "$@"; }

echo "== [1] desktop 1440 — cold load =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2500 > /dev/null 2>&1
ab screenshot "$OUT/LIVE-welcome-1440.png" > /dev/null 2>&1 && echo "shot: LIVE-welcome-1440"

echo "== [2] توكنات المرحلة صفر من DOM الحي عبر المسار العام =="
ab eval "JSON.stringify({
  assetsV: Array.from(document.querySelectorAll('link[rel=stylesheet], script[src]')).map(e => (e.href || e.src).match(/v=([0-9a-f]{8})/)).filter(Boolean).length,
  staleV: Array.from(document.querySelectorAll('link[rel=stylesheet], script[src]')).filter(e => /v=4\\.0\\.0/.test(e.href || e.src)).length,
  bodyFont: getComputedStyle(document.body).fontSize,
  bodyLH: getComputedStyle(document.body).lineHeight,
  bodyLS: getComputedStyle(document.body).letterSpacing,
  bodyBg: getComputedStyle(document.body).backgroundColor,
  sbW: Math.round(document.querySelector('.sidebar').getBoundingClientRect().width),
  sbBg: getComputedStyle(document.querySelector('.sidebar')).backgroundColor,
  h1Size: getComputedStyle(document.querySelector('.welcome h1')).fontSize,
  h1Weight: getComputedStyle(document.querySelector('.welcome h1')).fontWeight,
  h1LH: getComputedStyle(document.querySelector('.welcome h1')).lineHeight,
  h1LS: getComputedStyle(document.querySelector('.welcome h1')).letterSpacing,
  navLS: getComputedStyle(document.querySelector('.side-nav-item')).letterSpacing,
  fontsLoaded: document.fonts.check('15px \"IBM Plex Sans Arabic\"'),
  dir: document.documentElement.dir,
  consoleErr: window.__errCount || 0
})" > "$OUT/tokens-live-1440.json" 2>&1
cat "$OUT/tokens-live-1440.json"
echo ""

echo "== [3] تمرير أفقي/أخطاء 1440 =="
ab eval "JSON.stringify({hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth})" > "$OUT/overflow-1440.json" 2>&1
cat "$OUT/overflow-1440.json"; echo ""

echo "== [4] mobile 390 =="
ab set viewport 390 844 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP&m=1" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
ab screenshot "$OUT/LIVE-welcome-390.png" > /dev/null 2>&1 && echo "shot: LIVE-welcome-390"
ab eval "JSON.stringify({hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth, h1Size: getComputedStyle(document.querySelector('.welcome h1')).fontSize})" > "$OUT/overflow-390.json" 2>&1
cat "$OUT/overflow-390.json"; echo ""

echo "== [5] المصنع 1440 (تفاعل حي) =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP&f=1" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
ab click data-nav=factory > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
ab screenshot "$OUT/LIVE-factory-1440.png" > /dev/null 2>&1 && echo "shot: LIVE-factory-1440"
ab eval "JSON.stringify({sysConnected: !!Array.from(document.querySelectorAll('.chip, .badge, .fc-status, [class*=status]')).find(e => /CONNECTED|متصل/.test(e.textContent))})" > "$OUT/factory-live.json" 2>&1
cat "$OUT/factory-live.json"; echo ""

echo "== [6] أخطاء console =="
ab console > "$OUT/console.txt" 2>&1
wc -l < "$OUT/console.txt"; head -5 "$OUT/console.txt"

kill $TUN 2>/dev/null
echo "LIVE_ACCEPT_DONE"
