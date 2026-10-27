#!/bin/bash
# AES-DESIGN-IMPL-012 — FINAL visual acceptance through the PUBLIC-link path
# (SSH tunnel -> same nginx vhost + Basic Auth the owner's browser hits)
set -u
OUT=/home/z/my-project/download/design-impl-012/live-verify
mkdir -p "$OUT"
CREDS=$(cat /home/z/my-project/reproof-012-auth.txt)   # aes012:PW
USERID=${CREDS%%:*}
PW=${CREDS#*:}
BASE="http://127.0.0.1:18081"
STAMP=$(date +%s)

python3 /home/z/my-project/scripts/tunnel_012.py > "$OUT/tunnel.log" 2>&1 &
TUN=$!
for i in $(seq 1 30); do curl -s -o /dev/null "$BASE/health" && break; sleep 0.4; done

echo "== [0] unauthenticated vs authenticated =="
echo "no-auth: $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 $BASE/)"
echo "auth:    $(curl -s -o /dev/null -w '%{http_code}' -u "$USERID:$PW" --max-time 8 $BASE/)"
echo "health:  $(curl -s --max-time 8 $BASE/health | head -c 90)"

ab() { agent-browser "$@"; }
AUTHHDR='{"Authorization":"Basic YWVzMDEyOkEwMTJ2LTY1NGQ2ZDhjNGI0Ng=="}'

echo "== [1] desktop 1440 — cold authenticated load =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP" --headers "$AUTHHDR" > /dev/null 2>&1
sleep 1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1

echo "== [2] DOM asset versioning =="
ab eval "
(() => {
  const links=[...document.querySelectorAll('link[href*=\"/static/\"] , script[src*=\"/static/\"]')];
  const vNew=links.filter(l=>/v=002cf4a/.test(l.href||l.src)).length;
  const vOld=links.filter(l=>/v=4\.0\.0/.test(l.href||l.src)).length;
  return JSON.stringify({total:links.length, v002cf4a:vNew, v400:vOld, title:document.title, lang:document.documentElement.lang, dir:document.documentElement.dir});
})()" 2>&1 | tee "$OUT/dom-versioning-1440.json"

echo "== [3] computed design tokens (live DOM) =="
ab eval "
(() => {
  const cs=el=>el?getComputedStyle(el):null;
  const root=getComputedStyle(document.documentElement);
  return JSON.stringify({
    bodyBg: cs(document.body).backgroundColor,
    accent: root.getPropertyValue('--accent').trim(),
    ok: root.getPropertyValue('--ok').trim(),
    sidebarW: cs(document.querySelector('.sidebar')).width,
    brand: (document.querySelector('.brand-name')||{}).textContent,
    search: !!document.getElementById('side-search'),
    kbd: !!document.querySelector('.new-chat-key')
  });
})()" 2>&1 | tee "$OUT/theme-applied-1440.json"

echo "== [4] console + page errors (CLI) =="
ab console > "$OUT/console-1440.txt" 2>&1; echo "console lines: $(wc -l < "$OUT/console-1440.txt")"
ab errors > "$OUT/errors-1440.txt" 2>&1; echo "errors file:"; cat "$OUT/errors-1440.txt"

echo "== [5] overflow checks =="
ab eval "JSON.stringify({sw:document.documentElement.scrollWidth,cw:document.documentElement.clientWidth})" 2>&1 | tee "$OUT/overflow-1440.json"

echo "== [6] SHA-256 of browser-loaded bytes vs git 002cf4a =="
ab eval "
(async () => {
  const files=['theme.css','styles.css','app.js','app-shell.css','factory-control.css','factory-control.js'];
  const out={};
  for (const f of files){
    try{
      const r=await fetch('/static/'+f+'?v=002cf4a0',{cache:'no-store'});
      const buf=await r.arrayBuffer();
      const h=await crypto.subtle.digest('SHA-256',buf);
      out[f]=Array.from(new Uint8Array(h)).map(b=>b.toString(16).padStart(2,'0')).join('');
    }catch(e){out[f]='FETCH_FAIL:'+e.message}
  }
  return JSON.stringify(out);
})()" 2>&1 | tee "$OUT/browser-sha256.json"

echo "== [7] live interactions: factory / settings / conversation =="
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$OUT/live-factory-1440.png" > /dev/null 2>&1 && echo "shot: live-factory-1440"
ab eval "JSON.stringify({factoryStatus:(document.getElementById('factory-system-status')||{}).textContent})" 2>&1
ab eval "document.getElementById('factory-back').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
ab screenshot "$OUT/live-settings-1440.png" > /dev/null 2>&1 && echo "shot: live-settings-1440"
ab press Escape > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1
ab eval "(document.querySelectorAll('#conversations .conv-item')[1]||{}).click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$OUT/live-conversation-1440.png" > /dev/null 2>&1 && echo "shot: live-conversation-1440"

echo "== [8] desktop main shot =="
ab eval "document.getElementById('new-chat').click()" > /dev/null 2>&1
ab wait 800 > /dev/null 2>&1
ab screenshot "$OUT/live-chat-1440.png" > /dev/null 2>&1 && echo "shot: live-chat-1440"

echo "== [9] mobile 390 — fresh reload =="
ab set viewport 390 844 > /dev/null 2>&1
ab open "$BASE/?m=$STAMP" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
ab screenshot "$OUT/live-chat-390.png" > /dev/null 2>&1 && echo "shot: live-chat-390"
ab eval "JSON.stringify({sw:document.documentElement.scrollWidth,cw:document.documentElement.clientWidth,collapsed:document.body.classList.contains('sidebar-collapsed')})" 2>&1 | tee "$OUT/mobile-390.json"
ab errors > "$OUT/errors-mobile.txt" 2>&1; cat "$OUT/errors-mobile.txt"

kill $TUN 2>/dev/null; wait $TUN 2>/dev/null
echo "== acceptance session done =="
