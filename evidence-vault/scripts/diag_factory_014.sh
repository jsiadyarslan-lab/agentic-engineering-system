#!/bin/bash
# AES-014 — تشخيص حالة المصنع: هل fetch('/health') يحمل المصادقة؟
set -u
OUT=/home/z/my-project/download/redesign-014/live-verify
CREDS=$(cat /home/z/my-project/reproof-014-auth.txt)
USERID=${CREDS%%:*}
PW=${CREDS#*:}
BASE="http://127.0.0.1:18082"
STAMP=$(date +%s)
AUTHHDR=$(printf '{"Authorization":"Basic %s"}' "$(printf '%s:%s' "$USERID" "$PW" | base64 -w0)")

/home/z/.venv/bin/python3 /home/z/my-project/scripts/tunnel_014.py > "$OUT/tunnel3.log" 2>&1 &
TUN=$!
for i in $(seq 1 40); do curl -s -o /dev/null "$BASE/health" && break; sleep 0.4; done

agent-browser set viewport 1440 900 > /dev/null 2>&1
agent-browser open "$BASE/?s=$STAMP" --headers "$AUTHHDR" > /dev/null 2>&1
agent-browser wait --load networkidle > /dev/null 2>&1
agent-browser wait 1500 > /dev/null 2>&1

echo "== fetch /health من داخل الصفحة =="
agent-browser eval "fetch('/health').then(r => r.text().then(t => JSON.stringify({status: r.status, bodyHead: t.slice(0, 60)}))).catch(e => JSON.stringify({err: String(e)}))" 2>&1 | head -3

echo "== click factory ثم الحالة بعد 4 ثوان =="
agent-browser click data-nav=factory > /dev/null 2>&1
agent-browser wait 4000 > /dev/null 2>&1
agent-browser eval "JSON.stringify({
  statusText: (document.getElementById('factory-system-status') || {}).textContent,
  statusClass: (document.getElementById('factory-system-status') || {}).className
})" 2>&1 | head -3

kill $TUN 2>/dev/null
echo "DIAG_DONE"
