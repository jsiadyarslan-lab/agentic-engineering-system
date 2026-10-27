#!/bin/bash
# AES-014 — قبول المرحلة الثانية محليًا: بنية الرسائل الجديدة
set -u
REPO=/home/z/my-project/wt-014
PY=/home/z/.venv/bin/python3
PORT=8025
DB="$REPO/runtime/ui-014p2.db"
OUT=/home/z/my-project/download/redesign-014/phase2-local
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"
mkdir -p "$OUT"

rm -f "$DB"
"$PY" /home/z/my-project/scripts/seed_p2_014.py

cd "$REPO"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app \
  --host 127.0.0.1 --port $PORT > "$OUT/server.log" 2>&1 &
SRV=$!
for i in $(seq 1 100); do curl -s -o /dev/null "http://127.0.0.1:$PORT/health" && break; sleep 0.4; done

ab() { agent-browser "$@"; }

ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1

echo "== فتح المحادثة المزروعة =="
ab eval "location.hash = '#/chat/1'; 'ROUTED'" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$OUT/p2-conversation-1440.png" > /dev/null 2>&1 && echo "shot: p2-conversation-1440"

echo "== قياسات بنية المرحلة الثانية =="
ab eval "JSON.stringify({
  msgHeads: document.querySelectorAll('.msg-head').length,
  firstWho: (document.querySelector('.msg-who')||{}).textContent,
  firstWhen: (document.querySelector('.msg-when')||{}).textContent,
  whenFF: getComputedStyle(document.querySelector('.msg-when')).fontFamily.slice(0,14),
  orphanMinW: getComputedStyle(document.querySelector('.bubble.user')).minWidth,
  userAlign: getComputedStyle(document.querySelector('.bubble.user')).alignSelf,
  codeblockHeads: document.querySelectorAll('.md-code-head').length,
  codeLang: (document.querySelector('.md-code-lang')||{}).textContent,
  copyBtn: !!document.querySelector('.md-copy'),
  preBg: getComputedStyle(document.querySelector('.md-pre')).backgroundColor,
  verdict: (document.querySelector('.verdict')||{}).textContent,
  verdictFail: !!document.querySelector('.verdict.fail'),
  verdictColor: document.querySelector('.verdict.fail') ? getComputedStyle(document.querySelector('.verdict.fail')).color : null,
  verdictWeight: document.querySelector('.verdict.fail') ? getComputedStyle(document.querySelector('.verdict.fail')).fontWeight : null,
  errBorder: (() => { const r = document.createElement('div'); return 'css-check'; })(),
  hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth
})" 2>&1 | head -4

echo "== تفاعل النسخ =="
ab eval "document.querySelector('.md-copy').click(); JSON.stringify({copied: document.querySelector('.md-copy').classList.contains('copied')})" 2>&1 | head -2

echo "== console =="
ab console > "$OUT/console.txt" 2>&1; wc -l < "$OUT/console.txt"

kill $SRV 2>/dev/null
echo "P2_LOCAL_DONE"
