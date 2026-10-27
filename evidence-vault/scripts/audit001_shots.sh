#!/bin/bash
# AES-AUDIT-001 — LIVE visual audit capture through the PUBLIC-link path
# (SSH tunnel -> same nginx vhost + Basic Auth the owner's browser hits).
# Captures ALL surfaces @1440 + mobile @390 + tokens + console + polling evidence.
set -u
OUT=/home/z/my-project/download/aes-audit-001
SHOTS=$OUT/shots
mkdir -p "$SHOTS"
CREDS=$(cat "$OUT/auth.txt")
USERID=${CREDS%%:*}
PW=${CREDS#*:}
BASE="http://127.0.0.1:18085"
STAMP=$(date +%s)
AUTHHDR=$(printf '{"Authorization":"Basic %s"}' "$(printf '%s:%s' "$USERID" "$PW" | base64 -w0)")

python3 /home/z/my-project/scripts/audit001_tunnel.py > "$OUT/tunnel.log" 2>&1 &
TUN=$!
for i in $(seq 1 40); do curl -s -o /dev/null --max-time 4 "$BASE/health" && break; sleep 0.4; done

echo "== [0] auth wall =="
echo "no-auth: $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 $BASE/)"
echo "auth:    $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 -u "$USERID:$PW" $BASE/)"

ab() { agent-browser "$@"; }

echo "== [1] desktop 1440 cold load =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2500 > /dev/null 2>&1
ab screenshot "$SHOTS/01-welcome-1440.png" > /dev/null 2>&1 && echo "shot: 01-welcome-1440"
ab screenshot "$SHOTS/01-welcome-1440-full.png" --full > /dev/null 2>&1 && echo "shot: 01-welcome-1440-full"

echo "== [2] design tokens (live computed) =="
ab eval "
(() => {
  const cs=(el)=>el?getComputedStyle(el):null;
  const root=getComputedStyle(document.documentElement);
  const pick=(el,props)=>{const s=cs(el);if(!s)return null;const o={};props.forEach(p=>o[p]=s.getPropertyValue(p));return o;};
  const sidebar=document.querySelector('.sidebar');
  const composer=document.querySelector('.composer')||document.querySelector('#composer');
  const brand=document.querySelector('.brand-name');
  const h1=document.querySelector('h1,h2,.chat-title,.welcome-title');
  const btn=document.querySelector('button');
  return JSON.stringify({
    root: {accent: root.getPropertyValue('--accent').trim(), bg: root.getPropertyValue('--bg').trim()||root.getPropertyValue('--surface-0').trim(), text1: root.getPropertyValue('--text-1').trim()||root.getPropertyValue('--text-primary').trim()},
    body: pick(document.body,['font-family','font-size','line-height','background-color','color','direction']),
    sidebar: sidebar? pick(sidebar,['width','background-color','border-right']) : null,
    composer: composer? pick(composer,['height','background-color','border-radius','border','padding']) : null,
    brand: brand? pick(brand,['font-size','font-weight','letter-spacing','color']) : null,
    firstButton: btn? pick(btn,['background-color','color','border-radius','font-size','padding','border']) : null,
    heading: h1? pick(h1,['font-size','font-weight','line-height','letter-spacing','color']) : null,
    navItems: [...document.querySelectorAll('.side-nav-item')].map(n=>n.textContent.trim()).slice(0,8),
    title: document.title, viewport: {w:innerWidth,h:innerHeight}
  });
})()" 2>&1 | tee "$SHOTS/tokens-1440.json"

echo "== [3] fonts truth =="
ab eval "
(async () => {
  const loaded=[...document.fonts].filter(f=>f.status==='loaded').map(f=>f.family+' '+f.weight);
  return JSON.stringify({fontsLoaded:loaded.slice(0,14), plexArabic:document.fonts.check('16px \"IBM Plex Sans Arabic\"')});
})()" 2>&1 | tee "$SHOTS/fonts-1440.json"

echo "== [4] console + errors (welcome) =="
ab console > "$SHOTS/console-01-welcome.txt" 2>&1
ab errors > "$SHOTS/errors-01-welcome.txt" 2>&1; cat "$SHOTS/errors-01-welcome.txt"

echo "== [5] polling evidence: 65s in chat view, count requests =="
ab network requests > "$SHOTS/net-before-poll.txt" 2>&1
sleep 65
ab network requests > "$SHOTS/net-after-poll.txt" 2>&1
echo "requests during 65s idle chat view:"
diff "$SHOTS/net-before-poll.txt" "$SHOTS/net-after-poll.txt" | grep -c '^>' || echo 0
grep -oE 'runs/active|projects/[0-9]+/runtime|/api/[a-z/]+' "$SHOTS/net-after-poll.txt" 2>/dev/null | sort | uniq -c | sort -rn | head -10

echo "== [6] conversation view =="
ab eval "(document.querySelectorAll('#conversations .conv-item')[0]||{}).click()" > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
ab screenshot "$SHOTS/02-conversation-1440.png" > /dev/null 2>&1 && echo "shot: 02-conversation-1440"
ab screenshot "$SHOTS/02-conversation-1440-full.png" --full > /dev/null 2>&1 && echo "shot: 02-conversation-1440-full"
ab errors > "$SHOTS/errors-02-conversation.txt" 2>&1; cat "$SHOTS/errors-02-conversation.txt"

echo "== [7] factory view =="
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2200 > /dev/null 2>&1
ab screenshot "$SHOTS/03-factory-1440.png" > /dev/null 2>&1 && echo "shot: 03-factory-1440"
ab screenshot "$SHOTS/03-factory-1440-full.png" --full > /dev/null 2>&1 && echo "shot: 03-factory-1440-full"
ab errors > "$SHOTS/errors-03-factory.txt" 2>&1; cat "$SHOTS/errors-03-factory.txt"
ab eval "document.getElementById('factory-back').click()" > /dev/null 2>&1
ab wait 800 > /dev/null 2>&1

echo "== [8] runs + archive views =="
ab eval "document.querySelector('.side-nav-item[data-nav=runs]').click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$SHOTS/04-runs-1440.png" > /dev/null 2>&1 && echo "shot: 04-runs-1440"
ab eval "document.querySelector('.side-nav-item[data-nav=archive]').click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$SHOTS/05-archive-1440.png" > /dev/null 2>&1 && echo "shot: 05-archive-1440"
ab errors > "$SHOTS/errors-04-05-runs-archive.txt" 2>&1; cat "$SHOTS/errors-04-05-runs-archive.txt"
ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
ab wait 800 > /dev/null 2>&1

echo "== [9] settings drawer: 4 tabs =="
ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 1200 > /dev/null 2>&1
ab screenshot "$SHOTS/06-settings-general-1440.png" > /dev/null 2>&1 && echo "shot: 06-settings-general"
ab eval "[...document.querySelectorAll('.settings-tab')].find(t=>t.dataset.tab==='providers').click()" > /dev/null 2>&1
ab wait 1200 > /dev/null 2>&1
ab screenshot "$SHOTS/07-settings-providers-1440.png" > /dev/null 2>&1 && echo "shot: 07-settings-providers"
ab eval "[...document.querySelectorAll('.settings-tab')].find(t=>t.dataset.tab==='tools').click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$SHOTS/08-settings-tools-1440.png" > /dev/null 2>&1 && echo "shot: 08-settings-tools"
ab eval "[...document.querySelectorAll('.settings-tab')].find(t=>t.dataset.tab==='execution').click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$SHOTS/09-settings-execution-1440.png" > /dev/null 2>&1 && echo "shot: 09-settings-execution"
ab errors > "$SHOTS/errors-06-09-settings.txt" 2>&1; cat "$SHOTS/errors-06-09-settings.txt"
ab press Escape > /dev/null 2>&1
ab wait 500 > /dev/null 2>&1

echo "== [10] project live view #/project/1 (OSINT) =="
ab open "$BASE/#/project/1" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 3000 > /dev/null 2>&1
ab screenshot "$SHOTS/10-project1-1440.png" > /dev/null 2>&1 && echo "shot: 10-project1-1440"
ab screenshot "$SHOTS/10-project1-1440-full.png" --full > /dev/null 2>&1 && echo "shot: 10-project1-1440-full"
ab errors > "$SHOTS/errors-10-project1.txt" 2>&1; cat "$SHOTS/errors-10-project1.txt"

echo "== [11] project tabs: overview + workflow + evidence =="
ab eval "[...document.querySelectorAll('.pl-tab')].find(t=>t.dataset.tab==='overview').click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$SHOTS/11-project1-overview-1440.png" > /dev/null 2>&1 && echo "shot: 11-project1-overview"
ab eval "[...document.querySelectorAll('.pl-tab')].find(t=>t.dataset.tab==='workflow').click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$SHOTS/12-project1-workflow-1440.png" > /dev/null 2>&1 && echo "shot: 12-project1-workflow"
ab eval "[...document.querySelectorAll('.pl-tab')].find(t=>t.dataset.tab==='evidence').click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$SHOTS/13-project1-evidence-1440.png" > /dev/null 2>&1 && echo "shot: 13-project1-evidence"
ab errors > "$SHOTS/errors-11-13-project-tabs.txt" 2>&1; cat "$SHOTS/errors-11-13-project-tabs.txt"

echo "== [12] mobile 390: welcome + conversation + project =="
ab set viewport 390 844 > /dev/null 2>&1
ab open "$BASE/?m=$STAMP" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2200 > /dev/null 2>&1
ab screenshot "$SHOTS/14-welcome-390.png" > /dev/null 2>&1 && echo "shot: 14-welcome-390"
ab eval "JSON.stringify({sw:document.documentElement.scrollWidth,cw:document.documentElement.clientWidth,collapsed:document.body.classList.contains('sidebar-collapsed')})" 2>&1 | tee "$SHOTS/mobile-390.json"
ab eval "(document.querySelectorAll('#conversations .conv-item')[0]||{}).click()" > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
ab screenshot "$SHOTS/15-conversation-390.png" > /dev/null 2>&1 && echo "shot: 15-conversation-390"
ab open "$BASE/#/project/1" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 2500 > /dev/null 2>&1
ab screenshot "$SHOTS/16-project1-390.png" > /dev/null 2>&1 && echo "shot: 16-project1-390"
ab eval "JSON.stringify({sw:document.documentElement.scrollWidth,cw:document.documentElement.clientWidth})" 2>&1 | tee "$SHOTS/mobile-project-390.json"
ab errors > "$SHOTS/errors-14-16-mobile.txt" 2>&1; cat "$SHOTS/errors-14-16-mobile.txt"

echo "== [13] final: total network requests this session =="
ab network requests > "$SHOTS/net-final.txt" 2>&1
grep -cE '^(GET|POST)' "$SHOTS/net-final.txt" 2>/dev/null || echo 0

kill $TUN 2>/dev/null; wait $TUN 2>/dev/null
echo "== AUDIT-001 capture session done =="
