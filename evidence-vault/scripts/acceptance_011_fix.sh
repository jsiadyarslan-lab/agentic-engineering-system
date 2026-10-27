#!/bin/bash
# AES-011 — VISUAL ACCEPTANCE after the 500 fix, through the EXACT public path:
#   local:18080 --SSH tunnel--> server 127.0.0.1:80 (nginx vhost + Basic Auth) -> 8010
# Authorized session: temp user aesdiag (Basic Auth). Commit under test: 947e6e55.
set -u
OUT=/home/z/my-project/download/live-reconciliation-011/fix-500/live-verify
mkdir -p "$OUT"
CREDS=$(cat /home/z/my-project/reproof-011b-auth.txt)
AB="agent-browser"

python3 /home/z/my-project/scripts/tunnel_011_public.py > "$OUT/tunnel.log" 2>&1 &
TUN=$!
sleep 4

# sanity: the DOCUMENT through the public path with auth must be 200 (this was the 500)
DOC_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -u "$CREDS" http://127.0.0.1:18080/)
echo "document via public path WITH auth: $DOC_CODE (must be 200)" | tee "$OUT/document-status.txt"

$AB set credentials ${CREDS%%:*} ${CREDS#*:}

echo; echo "===== DESKTOP 1440 ====="
$AB set viewport 1440 900
$AB open http://127.0.0.1:18080/ > /dev/null
sleep 5

$AB eval "JSON.stringify({title: document.title, lang: document.documentElement.lang, dir: document.documentElement.dir, h1: (document.querySelector('h1, .brand-name')||{textContent:null}).textContent})" | tee "$OUT/title-1440.json"

echo; echo "--- DOM asset versioning (live browser DOM) ---"
$AB eval "JSON.stringify({total_linked: document.querySelectorAll('link[href],script[src]').length, v_947e6e55: [...document.querySelectorAll('link[href],script[src]')].filter(e=>(e.href||e.src||'').includes('v=947e6e55')).length, v_4_0_0: [...document.querySelectorAll('link[href],script[src]')].filter(e=>(e.href||e.src||'').includes('v=4.0.0')).length, sample: [...document.querySelectorAll('link[href]')].slice(0,4).map(e=>e.href.split('/').pop())})" | tee "$OUT/dom-versioning-1440.json"

echo; echo "--- in-browser SHA-256 of bytes the browser actually holds vs git 947e6e55 ---"
$AB eval "(async () => {
  const expect = {
    'theme.css':'91e070f7a67c5b6ac252393baf3587e6bfb7b1750a4f3f2d5ab3ca50490b9a28',
    'styles.css':'707efdcce5ad55eb1283251c35e1350428ec49f55aca77c689c24afc799ca6be',
    'app.js':'477313bc312380445ea339cdc93d89fbdd38077ee7ba58ba71abeef988bc424b',
    'app-shell.css':'9cdc1b9dc9a45bd59d107512b774ecc42ae530c12965dcf1d321e95a2c894d7f',
    'factory-control.css':'430246ed0ff22c4bca2307d058861890188d92df810023b2d307478992ee61fa',
    'factory-control.js':'34de0270cb38ad7ec5e8579f5f6a186cafed43970fb787121cdf81346e07c700'
  };
  const hex = b => [...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,'0')).join('');
  const out = {};
  for (const [name, want] of Object.entries(expect)) {
    const resp = await fetch('/static/' + name + '?v=947e6e55', {cache:'force-cache'});
    const buf = await resp.arrayBuffer();
    const got = hex(await crypto.subtle.digest('SHA-256', buf));
    out[name] = {status: resp.status, got16: got.slice(0,16), want16: want.slice(0,16), match: got === want};
  }
  return JSON.stringify(out);
})()" | tee "$OUT/browser-sha256-vs-git.json"

echo; echo "--- theme APPLIED? computed styles + fonts ---"
$AB eval "JSON.stringify({bodyBg: getComputedStyle(document.body).backgroundColor, bodyColor: getComputedStyle(document.body).color, bodyFont: getComputedStyle(document.body).fontFamily.slice(0,60), fontsLoaded: [...new Set([...document.fonts].filter(f=>f.status==='loaded').map(f=>f.family))].slice(0,6), accentVar: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()})" | tee "$OUT/theme-applied-1440.json"

echo; echo "--- network resource statuses (cold) ---"
$AB eval "JSON.stringify(performance.getEntriesByType('resource').map(r=>({n: r.name.split('/').pop().split('?')[0].slice(0,40), s: r.responseStatus, t: r.transferSize})).filter(r=>r.s!==undefined && r.s!==200))" | tee "$OUT/network-non200-1440.json"

echo; echo "--- console + page errors ---"
$AB console > "$OUT/console-1440.txt" 2>&1; echo "console lines: $(wc -l < "$OUT/console-1440.txt")"
$AB errors > "$OUT/errors-1440.txt" 2>&1; echo "page error lines: $(wc -l < "$OUT/errors-1440.txt")"
head -3 "$OUT/errors-1440.txt"

echo; echo "--- horizontal overflow 1440 ---"
$AB eval "JSON.stringify({scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth, hOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth})" | tee "$OUT/overflow-1440.json"

echo; echo "--- screenshot: chat 1440 ---"
$AB screenshot "$OUT/accept-chat-1440-FIX.png"

echo; echo "===== INTERACTION 1: factory (real click on data-nav) ====="
$AB eval "document.querySelector('.side-nav-item[data-nav=factory]').click(); 'clicked'"
sleep 4
$AB eval "JSON.stringify({factoryHidden: document.querySelector('#factory-view').hidden, sysStatus: (document.querySelector('#factory-system-status')||{textContent:null}).textContent, buttons: [...document.querySelectorAll('#factory-view button')].map(b=>b.textContent.trim()).filter(Boolean).slice(0,8)})" | tee "$OUT/factory-state.json"
$AB screenshot "$OUT/accept-factory-1440-FIX.png"

echo; echo "===== INTERACTION 2: settings open + Esc close ====="
$AB eval "document.querySelector('.side-nav-item[data-nav=settings], .side-nav-item[data-nav=env]').click(); 'clicked'"
sleep 2
$AB screenshot "$OUT/accept-settings-1440-FIX.png"
$AB press Escape
sleep 1
$AB eval "JSON.stringify({settingsStillOpen: !!document.querySelector('.settings-panel.open, #settings-view.open, [data-settings-open=true]'), activeView: (document.querySelector('.view.active, .app-view:not([hidden])')||{id:null}).id || null})" | tee "$OUT/settings-esc.json"

echo; echo "===== MOBILE 390 (fresh reload) ====="
$AB set viewport 390 844
$AB reload
sleep 5
$AB eval "JSON.stringify({clientW: document.documentElement.clientWidth, scrollW: document.documentElement.scrollWidth, hOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth, sidebarCollapsed: !!document.querySelector('body.sidebar-collapsed, .app-shell.collapsed, aside.collapsed, .side-nav.collapsed'), title: document.title})" | tee "$OUT/mobile-390.json"
$AB screenshot "$OUT/accept-chat-390-FIX.png"
$AB errors > "$OUT/errors-final.txt" 2>&1; echo "final page error lines: $(wc -l < "$OUT/errors-final.txt")"
$AB console > "$OUT/console-final.txt" 2>&1; echo "final console lines: $(wc -l < "$OUT/console-final.txt")"

echo; echo "===== HAR snapshot ====="
HAR=$(ls -t /home/z/.agent-browser/tmp/har/har-*.har 2>/dev/null | head -1)
echo "har: $HAR"
cp "$HAR" "$OUT/" 2>/dev/null || echo "(no har file found)"

$AB close
kill $TUN 2>/dev/null
echo; echo "ACCEPTANCE DONE — artifacts:"; ls -la "$OUT"
