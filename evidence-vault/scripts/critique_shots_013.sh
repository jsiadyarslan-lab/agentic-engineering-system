#!/bin/bash
# AES-013 — LIVE visual critique capture session through the PUBLIC-link path
# (SSH tunnel -> same nginx vhost + Basic Auth the owner's browser hits)
# Captures: fresh screenshots of every view @1440 + @390 + measured design tokens.
set -u
OUT=/home/z/my-project/download/design-critique-013
mkdir -p "$OUT"
CREDS=$(cat /home/z/my-project/reproof-013-auth.txt)   # aes013:PW
USERID=${CREDS%%:*}
PW=${CREDS#*:}
BASE="http://127.0.0.1:18081"
STAMP=$(date +%s)
AUTHHDR=$(printf '{"Authorization":"Basic %s"}' "$(printf '%s:%s' "$USERID" "$PW" | base64 -w0)")

python3 /home/z/my-project/scripts/tunnel_013.py > "$OUT/tunnel.log" 2>&1 &
TUN=$!
for i in $(seq 1 30); do curl -s -o /dev/null "$BASE/health" && break; sleep 0.4; done

echo "== [0] auth wall =="
echo "no-auth: $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 $BASE/)"
echo "auth:    $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 -u "$USERID:$PW" $BASE/)"

ab() { agent-browser "$@"; }

echo "== [1] desktop 1440 cold load =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2500 > /dev/null 2>&1
ab screenshot "$OUT/LIVE-welcome-1440.png" > /dev/null 2>&1 && echo "shot: LIVE-welcome-1440"
ab screenshot "$OUT/LIVE-welcome-1440-full.png" --full > /dev/null 2>&1 && echo "shot: LIVE-welcome-1440-full"

echo "== [2] measured design tokens (live computed styles) =="
ab eval "
(() => {
  const cs=(el)=>el?getComputedStyle(el):null;
  const root=getComputedStyle(document.documentElement);
  const pick=(el,props)=>{const s=cs(el);if(!s)return null;const o={};props.forEach(p=>o[p]=s.getPropertyValue(p));return o;};
  const sidebar=document.querySelector('.sidebar');
  const composer=document.querySelector('.composer')||document.querySelector('#composer');
  const brand=document.querySelector('.brand-name');
  const btn=document.querySelector('button');
  const h1=document.querySelector('h1,h2,.chat-title,.welcome-title');
  const msgUser=document.querySelector('.msg.user,.message-user,.bubble-user');
  const msgAI=document.querySelector('.msg.assistant,.message-ai,.bubble-ai');
  return JSON.stringify({
    root: {
      font: root.getPropertyValue('--font-sans').trim(),
      fontMono: root.getPropertyValue('--font-mono').trim(),
      accent: root.getPropertyValue('--accent').trim(),
      bg: root.getPropertyValue('--bg').trim() || root.getPropertyValue('--surface-0').trim(),
      textPrimary: root.getPropertyValue('--text-primary').trim() || root.getPropertyValue('--text-1').trim()
    },
    body: pick(document.body,['font-family','font-size','line-height','background-color','color','direction']),
    sidebar: sidebar? pick(sidebar,['width','background-color','border-right','padding-top']) : null,
    composer: composer? pick(composer,['height','background-color','border-radius','border','padding']) : null,
    brand: brand? pick(brand,['font-size','font-weight','letter-spacing','color']) : null,
    firstButton: btn? pick(btn,['background-color','color','border-radius','font-size','padding','border']) : null,
    heading: h1? pick(h1,['font-size','font-weight','line-height','letter-spacing','color']) : null,
    msgUser: msgUser? pick(msgUser,['background-color','color','border-radius','padding','font-size','max-width']) : null,
    msgAI: msgAI? pick(msgAI,['background-color','color','padding','font-size','line-height']) : null,
    title: document.title,
    viewport: {w:innerWidth,h:innerHeight}
  });
})()" 2>&1 | tee "$OUT/tokens-1440.json"

echo "== [3] font loading truth =="
ab eval "
(async () => {
  const loaded=[...document.fonts].filter(f=>f.status==='loaded').map(f=>f.family+' '+f.weight);
  return JSON.stringify({fontsLoaded:loaded.slice(0,12), fontCheck:{plexArabic:document.fonts.check('16px \"IBM Plex Sans Arabic\"'), inter:document.fonts.check('16px Inter')}});
})()" 2>&1 | tee "$OUT/fonts-1440.json"

echo "== [4] console + errors =="
ab console > "$OUT/console-1440.txt" 2>&1; echo "console lines: $(wc -l < "$OUT/console-1440.txt")"
ab errors > "$OUT/errors-1440.txt" 2>&1; cat "$OUT/errors-1440.txt"

echo "== [5] conversation view =="
ab eval "(document.querySelectorAll('#conversations .conv-item')[0]||{}).click()" > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
ab screenshot "$OUT/LIVE-conversation-1440.png" > /dev/null 2>&1 && echo "shot: LIVE-conversation-1440"
ab screenshot "$OUT/LIVE-conversation-1440-full.png" --full > /dev/null 2>&1 && echo "shot: LIVE-conversation-1440-full"

echo "== [6] factory view =="
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
ab screenshot "$OUT/LIVE-factory-1440.png" > /dev/null 2>&1 && echo "shot: LIVE-factory-1440"
ab screenshot "$OUT/LIVE-factory-1440-full.png" --full > /dev/null 2>&1 && echo "shot: LIVE-factory-1440-full"
ab eval "document.getElementById('factory-back').click()" > /dev/null 2>&1
ab wait 800 > /dev/null 2>&1

echo "== [7] settings modal =="
ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 1000 > /dev/null 2>&1
ab screenshot "$OUT/LIVE-settings-1440.png" > /dev/null 2>&1 && echo "shot: LIVE-settings-1440"
ab press Escape > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1

echo "== [8] mobile 390 fresh =="
ab set viewport 390 844 > /dev/null 2>&1
ab open "$BASE/?m=$STAMP" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
ab screenshot "$OUT/LIVE-welcome-390.png" > /dev/null 2>&1 && echo "shot: LIVE-welcome-390"
ab eval "(document.querySelectorAll('#conversations .conv-item')[0]||{}).click()" > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
ab screenshot "$OUT/LIVE-conversation-390.png" > /dev/null 2>&1 && echo "shot: LIVE-conversation-390"
ab eval "JSON.stringify({sw:document.documentElement.scrollWidth,cw:document.documentElement.clientWidth,collapsed:document.body.classList.contains('sidebar-collapsed')})" 2>&1 | tee "$OUT/mobile-390.json"
ab errors > "$OUT/errors-mobile.txt" 2>&1; cat "$OUT/errors-mobile.txt"

kill $TUN 2>/dev/null; wait $TUN 2>/dev/null
echo "== critique capture session done =="
