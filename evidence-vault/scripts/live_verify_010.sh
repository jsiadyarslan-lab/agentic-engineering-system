#!/bin/bash
# AES-010 — live UI verification through SSH tunnel + real browser
# Tunnel + browser must live within THIS single call (env kills processes between calls).
set -u
OUT=/home/z/my-project/reproof-010/live-verify
mkdir -p "$OUT"

# 1) start tunnel in background
python3 /home/z/my-project/scripts/tunnel_010.py > "$OUT/tunnel.log" 2>&1 &
TUNNEL_PID=$!
sleep 4
if ! curl -s --max-time 6 http://127.0.0.1:18010/health > "$OUT/health.json" 2>&1; then
  echo "TUNNEL/HEALTH FAILED"; cat "$OUT/tunnel.log"; kill $TUNNEL_PID 2>/dev/null; exit 1
fi
echo "=== health via tunnel ==="; head -c 300 "$OUT/health.json"; echo

AB="agent-browser"
echo; echo "=== open app at 1440 ==="
$AB set viewport 1440 900
$AB open http://127.0.0.1:18010/
sleep 3
$AB get title | tee "$OUT/title.txt"
echo; echo "=== DOM checks ==="
$AB eval "JSON.stringify({dir: document.documentElement.getAttribute('dir'), lang: document.documentElement.getAttribute('lang'), assets_v400: [...document.querySelectorAll('link[href*=\\\"?v=4.0.0\\\"],script[src*=\\\"?v=4.0.0\\\"]')].length, title: document.title, h1: (document.querySelector('h1')||{}).textContent})" | tee "$OUT/dom-1440.json"
echo; echo "=== conversations in sidebar ==="
$AB eval "JSON.stringify({convs: [...document.querySelectorAll('#conversation-list .conversation-item, .conv-item, [data-conversation-id]')].length, sidebarText: (document.querySelector('aside, #sidebar')||{innerText:''}).innerText.slice(0,300)})" | tee "$OUT/sidebar.json"
echo; echo "=== screenshot chat-1440 ==="
$AB screenshot "$OUT/chat-1440.png"
echo; echo "=== console/errors ==="
$AB console > "$OUT/console.txt" 2>&1; echo "console lines: $(wc -l < "$OUT/console.txt")"
$AB errors > "$OUT/errors.txt" 2>&1; echo "page errors: $(wc -l < "$OUT/errors.txt")"
head -5 "$OUT/errors.txt"

echo; echo "=== factory view ==="
$AB find text "المصنع" click 2>/dev/null || $AB find role button click --name "المصنع" 2>/dev/null || echo "(factory tab find attempts logged)"
sleep 3
$AB eval "JSON.stringify({factoryVisible: !!document.querySelector('#factory-view'), factoryDisplay: (document.querySelector('#factory-view')||{}).style ? getComputedStyle(document.querySelector('#factory-view')).display : null, healthText: (document.querySelector('.system-status, .factory-status, #factory-view')||{innerText:''}).innerText.slice(0,200)})" | tee "$OUT/factory.json"
$AB screenshot "$OUT/factory-1440.png"
$AB errors >> "$OUT/errors.txt" 2>&1

echo; echo "=== back to chat + settings (Esc) ==="
$AB find text "المحادثات" click 2>/dev/null || $AB find role button click --name "المحادثات" 2>/dev/null || true
sleep 2
$AB find role button click --name "الإعدادات" 2>/dev/null || $AB find text "الإعدادات" click 2>/dev/null || true
sleep 2
$AB screenshot "$OUT/settings-1440.png"
$AB press Escape
sleep 1
$AB eval "JSON.stringify({settingsOpen: !!document.querySelector('.settings-panel.open, #settings-view.open, [data-settings-open=true]')})" | tee "$OUT/settings-after-esc.json"

echo; echo "=== viewport 768 ==="
$AB set viewport 768 900
sleep 2
$AB eval "JSON.stringify({hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth, scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth})" | tee "$OUT/overflow-768.json"
$AB screenshot "$OUT/chat-768.png"

echo; echo "=== viewport 390 with fresh reload (auto-collapse) ==="
$AB set viewport 390 844
$AB reload
sleep 4
$AB eval "JSON.stringify({hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth, scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth, sidebarCollapsed: !!document.querySelector('body.sidebar-collapsed, .app-shell.collapsed, aside.collapsed'), h1Clipped: (function(){const h=document.querySelector('h1'); if(!h) return null; const r=h.getBoundingClientRect(); return r.width<30 || r.right<0 || r.left>window.innerWidth;})()})" | tee "$OUT/mobile-390.json"
$AB screenshot "$OUT/chat-390.png"
$AB errors >> "$OUT/errors.txt" 2>&1

echo; echo "=== final error/console tally ==="
echo "page errors total lines: $(wc -l < "$OUT/errors.txt")"
cat "$OUT/errors.txt" | head -5

$AB close
kill $TUNNEL_PID 2>/dev/null
echo; echo "LIVE VERIFY DONE — artifacts in $OUT"
ls -la "$OUT"
