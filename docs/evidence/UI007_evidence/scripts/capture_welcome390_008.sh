#!/bin/bash
# AES-UI-PREMIUM-REDESIGN-008 — reviewer-finding fix: capture mobile-welcome-390
# (name-matched counterpart of baseline/mobile-welcome-390.png, which was captured
#  as a fresh load at 390. The visual state equals after/mobile-chat-390.png —
#  fresh load at 390 with sidebar collapsed — this adds the explicit name pairing.)
set -u
WT=/home/z/my-project/ui007
PY=/home/z/.venv/bin/python3
PORT=8073
OUT="$WT/docs/evidence/UI007_evidence/reproof-008"
LOG="$OUT/browser-session-extra.txt"
DB="$WT/runtime/ui-008-reproof.db"
cd "$WT"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-008-w390.log 2>&1 &
SRV=$!
for i in $(seq 1 80); do curl -s -o /dev/null "http://127.0.0.1:$PORT/health" && break; sleep 0.5; done
ab() { agent-browser "$@"; }
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"

{
echo ""
echo "== [X3] reviewer-finding fix: name-matched after counterpart for baseline mobile-welcome-390 =="
echo "# date(UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "# state: fresh load at 390x844 (sidebar auto-collapsed) — same visual state as baseline/mobile-welcome-390 (empty DB, fresh load @390) and as after/mobile-chat-390 (populated DB, fresh load @390)"
} >> "$LOG"

ab set viewport 390 844 > /dev/null 2>&1
ab open "$BASE/?w390=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
echo "MEASURE|mobile-welcome-390|$(ab eval 'JSON.stringify({vp:[innerWidth,innerHeight],docW:document.documentElement.scrollWidth,hOverflow:document.documentElement.scrollWidth>innerWidth,sidebarW:document.getElementById("sidebar").getBoundingClientRect().width,welcomeH1:document.querySelector(".welcome h1")?getComputedStyle(document.querySelector(".welcome h1")).fontSize:null,suggestions:document.querySelectorAll(".suggestion").length,sidebarCollapsed:document.body.classList.contains("sidebar-collapsed")})' 2>&1)" >> "$LOG"
ab screenshot "$OUT/shots/mobile-welcome-390.png" > /dev/null 2>&1
echo "shot: mobile-welcome-390 (name-matched counterpart added)" >> "$LOG"
echo "--- console:" >> "$LOG"; ab console 2>&1 | tail -3 >> "$LOG"
echo "--- errors:" >> "$LOG"; ab errors 2>&1 | tail -3 >> "$LOG"
kill $SRV 2>/dev/null
ab close > /dev/null 2>&1
echo "== done ==" >> "$LOG"
tail -12 "$LOG"
