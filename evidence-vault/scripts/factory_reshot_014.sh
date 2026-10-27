#!/bin/bash
# AES-014 — إعادة لقطة المصنع بنقر JS مباشر (تثبيت عدم الانحدار)
set -u
OUT=/home/z/my-project/download/redesign-014/live-verify
CREDS=$(cat /home/z/my-project/reproof-014-auth.txt)
USERID=${CREDS%%:*}
PW=${CREDS#*:}
BASE="http://127.0.0.1:18082"
STAMP=$(date +%s)
AUTHHDR=$(printf '{"Authorization":"Basic %s"}' "$(printf '%s:%s' "$USERID" "$PW" | base64 -w0)")

/home/z/.venv/bin/python3 /home/z/my-project/scripts/tunnel_014.py > "$OUT/tunnel4.log" 2>&1 &
TUN=$!
for i in $(seq 1 40); do curl -s -o /dev/null "$BASE/health" && break; sleep 0.4; done

agent-browser set viewport 1440 900 > /dev/null 2>&1
agent-browser open "$BASE/?s=$STAMP" --headers "$AUTHHDR" > /dev/null 2>&1
agent-browser wait --load networkidle > /dev/null 2>&1
agent-browser wait 2000 > /dev/null 2>&1

agent-browser eval "document.querySelector('[data-nav=factory]').click(); 'CLICKED'" > /dev/null 2>&1
agent-browser wait 3000 > /dev/null 2>&1

agent-browser eval "JSON.stringify({
  viewHidden: document.getElementById('factory-view').hidden,
  statusText: document.getElementById('factory-system-status').textContent,
  statVals: Array.from(document.querySelectorAll('.fc-stat-value')).slice(0,4).map(e => e.textContent.trim())
})" 2>&1 | head -3

agent-browser screenshot "$OUT/LIVE-factory-1440.png" > /dev/null 2>&1 && echo "shot retaken: LIVE-factory-1440"

kill $TUN 2>/dev/null
echo "FACTORY_RESHOT_DONE"
