#!/bin/bash
# AES-DESIGN-IMPL-012 — diagnose black conversation view
set -u
REPO=/home/z/my-project/repo
PY=/home/z/.venv/bin/python3
PORT=8023
DB="$REPO/runtime/ui-012.db"
OUT=/home/z/my-project/download/design-impl-012/local-verify
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"
mkdir -p "$OUT"

cd "$REPO"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app \
  --host 127.0.0.1 --port $PORT > "$OUT/server3.log" 2>&1 &
SRV=$!
for i in $(seq 1 100); do curl -s -o /dev/null "http://127.0.0.1:$PORT/health" && break; sleep 0.4; done

ab() { agent-browser "$@"; }
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?d=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1

ab eval "window.__errs=[];window.addEventListener('error',e=>window.__errs.push('ERR: '+e.message+':'+e.lineno));window.addEventListener('unhandledrejection',e=>window.__errs.push('REJ: '+(e.reason&&e.reason.message||e.reason)));'on'" > /dev/null 2>&1

echo "== click chat-mode conversation (c2 مراجعة معمارية) =="
ab eval "
(() => {
  const items=[...document.querySelectorAll('#conversations .conv-item')];
  const target=items.find(i=>i.textContent.includes('مراجعة'))||items[1];
  if(target) target.click();
  return JSON.stringify({found:!!target, label:target&&target.textContent.trim().slice(0,40)});
})()" 2>&1
ab wait 1500 > /dev/null 2>&1

ab eval "
(() => {
  const q=s=>document.querySelector(s);
  const vis=el=>{if(!el)return 'MISSING';const r=el.getBoundingClientRect();const cs=getComputedStyle(el);return JSON.stringify({hidden:el.hidden,display:cs.display,w:+r.width.toFixed(0),h:+r.height.toFixed(0)})};
  return JSON.stringify({
    bodyClass: document.body.className,
    chatTitle: (q('#chat-title')||{}).textContent,
    head: vis(q('.chat-head')),
    composer: vis(q('.composer')),
    messages: vis(q('.messages')),
    msgCount: document.querySelectorAll('.messages .bubble').length,
    msgHTML: (q('.messages')||{}).childElementCount,
    scroll: vis(q('.chat-scroll')),
    welcome: vis(q('#welcome')),
    errs: window.__errs
  });
})()" 2>&1 | tee "$OUT/diag-conversation.json"

ab screenshot "$OUT/diag-conversation.png" > /dev/null 2>&1

echo "== direct hash route #/chat/2 =="
ab open "$BASE/#/chat/2" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
ab eval "
(() => {
  const q=s=>document.querySelector(s);
  return JSON.stringify({
    chatTitle:(q('#chat-title')||{}).textContent,
    msgCount: document.querySelectorAll('.messages .bubble').length,
    firstMsg: (q('.messages .bubble-body')||{}).textContent?.slice(0,60),
    headShown: !(q('.chat-head')||{}).hidden,
    composerShown: !(q('.composer')||{}).hidden,
    composerH: +(q('.composer')||{getBoundingClientRect:()=>({height:0})}).getBoundingClientRect().height
  });
})()" 2>&1 | tee "$OUT/diag-route.json"
ab screenshot "$OUT/diag-route-chat2.png" > /dev/null 2>&1

kill $SRV 2>/dev/null; wait $SRV 2>/dev/null
echo "== done =="
