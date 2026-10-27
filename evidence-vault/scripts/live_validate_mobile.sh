#!/bin/bash
# AES-006: proper mobile test — fresh load at 390 (mimics real phone).
set -u
OUT=/home/z/my-project/download/oracle-deploy/live
setsid nohup python3 /home/z/my-project/scripts/tunnel.py >/tmp/tunnel.log 2>&1 &
sleep 4
curl -s --max-time 8 http://127.0.0.1:18010/health >/dev/null || { echo "TUNNEL FAILED"; exit 1; }

agent-browser open about:blank >/dev/null 2>&1
agent-browser set viewport 390 844 >/dev/null
agent-browser open http://127.0.0.1:18010/ >/dev/null 2>&1
agent-browser wait --load networkidle >/dev/null 2>&1 || true
sleep 2
agent-browser screenshot "$OUT/live-390-chat-fresh.png"
echo "=== fresh-load 390 measurements ==="
agent-browser eval "(() => { const sb=document.querySelector('#sidebar, aside, [class*=sidebar]'); const h1=document.querySelector('h1'); const main=document.querySelector('main, [class*=main]'); return {docScrollW: document.documentElement.scrollWidth, docClientW: document.documentElement.clientWidth, sidebarVisible: sb? sb.offsetParent!==null : 'none', sidebarW: sb? sb.offsetWidth : null, h1Text: h1? h1.textContent.slice(0,25) : null, h1Clipped: h1? h1.scrollWidth>h1.clientWidth : null, mainW: main? main.offsetWidth : null}; })()"
echo; echo "=== 768 fresh too ==="
agent-browser open about:blank >/dev/null 2>&1
agent-browser set viewport 768 1024 >/dev/null
agent-browser open http://127.0.0.1:18010/ >/dev/null 2>&1
agent-browser wait --load networkidle >/dev/null 2>&1 || true
sleep 2
agent-browser screenshot "$OUT/live-768-chat-fresh.png"
agent-browser eval "(() => ({docScrollW: document.documentElement.scrollWidth, docClientW: document.documentElement.clientWidth})())"
agent-browser close >/dev/null 2>&1
kill $(cat /tmp/aes-tunnel.pid) 2>/dev/null
echo done
