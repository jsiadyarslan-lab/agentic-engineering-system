#!/bin/bash
# AES-014 — المرحلة صفر: قبول بصري محلي قبل الالتزام (خادم+متصفح بجلسة واحدة)
set -u
REPO=/home/z/my-project/wt-014
PY=/home/z/.venv/bin/python3
PORT=8022
DB="$REPO/runtime/ui-014.db"
OUT=/home/z/my-project/download/redesign-014/local-verify
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"
mkdir -p "$OUT"
rm -f "$DB"

cd "$REPO"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app \
  --host 127.0.0.1 --port $PORT > "$OUT/server.log" 2>&1 &
SRV=$!

for i in $(seq 1 100); do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/health" && break
  sleep 0.4
done
echo "== health: $(curl -s http://127.0.0.1:$PORT/health | head -c 100)"

curl -s -X POST "$BASE/api/projects" -H 'Content-Type: application/json' \
  -d '{"name":"أرد بناء منصة osint","objective":"منصة OSINT معيارية بلغة Python مع واجهتي API وCLI ووحدات جمع من مصادر عامة"}' > "$OUT/project-create.json" 2>&1
echo "== project: $(head -c 120 "$OUT/project-create.json")"

ab() { agent-browser "$@"; }

echo "== [1] desktop 1440 — cold load =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
ab screenshot "$OUT/local-welcome-1440.png" > /dev/null 2>&1 && echo "shot: local-welcome-1440"

echo "== [2] G1/G2/G7 tokens من DOM الحي =="
ab eval "
(() => {
  const cs = el => el ? getComputedStyle(el) : null;
  const body = cs(document.body);
  const sb = cs(document.querySelector('.sidebar'));
  const sbEl = document.querySelector('.sidebar');
  const h1 = cs(document.querySelector('.welcome h1'));
  const composer = cs(document.querySelector('.composer')) || cs(document.getElementById('composer'));
  const nav = cs(document.querySelector('.side-nav-item'));
  const chip = cs(document.querySelector('.chip'));
  const tech = cs(document.querySelector('.tech, code'));
  return JSON.stringify({
    bodyFont: body.fontSize, bodyLH: body.lineHeight, bodyLS: body.letterSpacing,
    bodyBg: body.backgroundColor, bodyFF: body.fontFamily.slice(0, 28),
    h1Size: h1 && h1.fontSize, h1Weight: h1 && h1.fontWeight, h1LH: h1 && h1.lineHeight, h1LS: h1 && h1.letterSpacing,
    sidebarW: sbEl && Math.round(sbEl.getBoundingClientRect().width), sidebarBg: sb && sb.backgroundColor,
    composerBg: composer && composer.backgroundColor,
    navLS: nav && nav.letterSpacing, chipLS: chip && chip.letterSpacing,
    techFF: tech && tech.fontFamily.slice(0, 14), techSize: tech && tech.fontSize,
    dir: document.documentElement.dir, lang: document.documentElement.lang
  });
}" 2>/dev/null | tee "$OUT/tokens-1440.json"
echo ""

echo "== [3] أخطاء الصفحة والتمرير الأفقي 1440 =="
ab eval "
(() => {
  const d = document.documentElement;
  return JSON.stringify({ hScroll: d.scrollWidth > d.clientWidth, sw: d.scrollWidth, cw: d.clientWidth });
})()" 2>/dev/null | tee "$OUT/overflow-1440.json"
echo ""

echo "== [4] mobile 390 =="
ab set viewport 390 844 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP&m=1" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$OUT/local-welcome-390.png" > /dev/null 2>&1 && echo "shot: local-welcome-390"
ab eval "
(() => {
  const d = document.documentElement;
  const h1 = getComputedStyle(document.querySelector('.welcome h1'));
  return JSON.stringify({ hScroll: d.scrollWidth > d.clientWidth, h1Size: h1.fontSize });
})()" 2>/dev/null | tee "$OUT/overflow-390.json"
echo ""

echo "== [5] المصنع والإعدادات (1440) =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP&f=1" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab click data-nav=factory > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$OUT/local-factory-1440.png" > /dev/null 2>&1 && echo "shot: local-factory-1440"

echo "== console errors =="
ab console > "$OUT/console.txt" 2>&1
wc -l "$OUT/console.txt"; head -5 "$OUT/console.txt"

kill $SRV 2>/dev/null
echo "LOCAL_ACCEPT_DONE"
