#!/bin/bash
# AES-DESIGN-IMPL-012 — local pre-deploy visual acceptance (server+browser one session)
set -u
REPO=/home/z/my-project/repo
PY=/home/z/.venv/bin/python3
PORT=8021
DB="$REPO/runtime/ui-012.db"
OUT=/home/z/my-project/download/design-impl-012/local-verify
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"
mkdir -p "$OUT"

cd "$REPO"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app \
  --host 127.0.0.1 --port $PORT > "$OUT/server.log" 2>&1 &
SRV=$!

for i in $(seq 1 100); do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/health" && break
  sleep 0.4
done
echo "== health: $(curl -s http://127.0.0.1:$PORT/health | head -c 120)"

# project for the sidebar (durable projects API)
curl -s -X POST "$BASE/api/projects" -H 'Content-Type: application/json' \
  -d '{"name":"أرد بناء منصة osint","objective":"منصة OSINT معيارية بلغة Python مع واجهتي API وCLI ووحدات جمع من مصادر عامة"}' > "$OUT/project-create.json" 2>&1
echo "== project: $(head -c 200 "$OUT/project-create.json")"

ab() { agent-browser "$@"; }

echo "== [1] desktop 1440 — cold load =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
ab screenshot "$OUT/local-chat-1440.png" > /dev/null 2>&1 && echo "shot: local-chat-1440"

echo "== [2] computed design tokens =="
ab eval "
(() => {
  const cs = el => el ? getComputedStyle(el) : null;
  const body = cs(document.body);
  const sb = cs(document.querySelector('.sidebar'));
  const nc = cs(document.querySelector('.new-chat'));
  const send = cs(document.querySelector('#send'));
  const nav = document.querySelector('.side-nav-item.active');
  const ss = document.getElementById('side-search');
  const kbd = document.querySelector('.new-chat-key');
  return JSON.stringify({
    bodyBg: body.backgroundColor, bodyFont: body.fontFamily.slice(0,30),
    sidebarW: sb.width, sidebarBg: sb.backgroundColor,
    newChatBg: nc.backgroundImage.slice(0,60), newChatRadius: nc.borderRadius,
    sendBg: send.backgroundColor, sendInk: send.color,
    accentVar: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
    searchPresent: !!ss, kbdPresent: !!kbd,
    brandName: (document.querySelector('.brand-name')||{}).textContent,
    brandSub: (document.querySelector('.brand-sub')||{}).textContent,
    overflowX: document.documentElement.scrollWidth + '/' + document.documentElement.clientWidth
  });
})()" 2>&1 | tee "$OUT/tokens-1440.json"

echo "== [3] console + page errors =="
ab console > "$OUT/console-1440.txt" 2>&1; grep -ciE "error" "$OUT/console-1440.txt" || true
ab errors > "$OUT/errors-1440.txt" 2>&1; wc -l < "$OUT/errors-1440.txt"

echo "== [4] project seeded into sidebar? =="
ab eval "JSON.stringify({pj: document.querySelectorAll('#projects-list .pj-item').length, conv: document.querySelectorAll('#conversations .conv-item').length})" 2>&1

echo "== [5] factory view (live click) =="
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 1200 > /dev/null 2>&1
ab screenshot "$OUT/local-factory-1440.png" > /dev/null 2>&1 && echo "shot: local-factory-1440"
ab eval "JSON.stringify({status: (document.getElementById('factory-system-status')||{}).textContent})" 2>&1
ab eval "document.getElementById('factory-back') ? document.getElementById('factory-back').click() : document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
ab wait 800 > /dev/null 2>&1

echo "== [6] settings drawer (live) =="
ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 1000 > /dev/null 2>&1
ab screenshot "$OUT/local-settings-1440.png" > /dev/null 2>&1 && echo "shot: local-settings-1440"
ab press Escape > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1

echo "== [7] conversation with seeded content =="
ab eval "
(() => {
  const items = document.querySelectorAll('#conversations .conv-item');
  if (items[0]) items[0].click();
  return 'clicked:' + items.length;
})()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$OUT/local-conversation-1440.png" > /dev/null 2>&1 && echo "shot: local-conversation-1440"

echo "== [8] mobile 390 — fresh reload =="
ab set viewport 390 844 > /dev/null 2>&1
ab open "$BASE/?m=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$OUT/local-chat-390.png" > /dev/null 2>&1 && echo "shot: local-chat-390"
ab eval "JSON.stringify({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, sidebarCollapsed: document.body.classList.contains('sidebar-collapsed')})" 2>&1 | tee "$OUT/mobile-390.json"

echo "== [9] Ctrl+K shortcut probe =="
ab set viewport 1440 900 > /dev/null 2>&1
ab eval "document.activeElement && document.activeElement.blur()" > /dev/null 2>&1
ab press "Control+k" > /dev/null 2>&1
ab wait 600 > /dev/null 2>&1
ab eval "JSON.stringify({title: (document.getElementById('chat-title')||{}).textContent})" 2>&1

kill $SRV 2>/dev/null
wait $SRV 2>/dev/null
echo "== done =="
