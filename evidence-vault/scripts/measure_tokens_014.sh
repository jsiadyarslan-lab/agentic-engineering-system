#!/bin/bash
# AES-014 — قياس توكنات المرحلة صفر من DOM الحي (جلسة مركزة)
set -u
REPO=/home/z/my-project/wt-014
PY=/home/z/.venv/bin/python3
PORT=8023
DB="$REPO/runtime/ui-014b.db"
OUT=/home/z/my-project/download/redesign-014/local-verify
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"
mkdir -p "$OUT"

cd "$REPO"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app \
  --host 127.0.0.1 --port $PORT > "$OUT/server2.log" 2>&1 &
SRV=$!
for i in $(seq 1 100); do curl -s -o /dev/null "http://127.0.0.1:$PORT/health" && break; sleep 0.4; done

agent-browser set viewport 1440 900 > /dev/null 2>&1
agent-browser open "$BASE/?s=$STAMP" > /dev/null 2>&1
agent-browser wait --load networkidle > /dev/null 2>&1
agent-browser wait 1500 > /dev/null 2>&1

agent-browser eval "JSON.stringify({
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
  composerBg: getComputedStyle(document.querySelector('.composer')).backgroundColor,
  navLS: getComputedStyle(document.querySelector('.side-nav-item')).letterSpacing,
  techFF: (document.querySelector('.tech, code') ? getComputedStyle(document.querySelector('.tech, code')).fontFamily.slice(0,14) : 'none'),
  dir: document.documentElement.dir
})" > "$OUT/tokens-1440.json" 2>&1
cat "$OUT/tokens-1440.json"
echo ""
kill $SRV 2>/dev/null
echo "TOKENS_DONE"
