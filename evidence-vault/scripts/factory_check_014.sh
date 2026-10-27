#!/bin/bash
# AES-014 — تحقق مركز: حالة المصنع عبر المسار العام
set -u
OUT=/home/z/my-project/download/redesign-014/live-verify
mkdir -p "$OUT"
CREDS=$(cat /home/z/my-project/reproof-014-auth.txt)
USERID=${CREDS%%:*}
PW=${CREDS#*:}
BASE="http://127.0.0.1:18082"
STAMP=$(date +%s)
AUTHHDR=$(printf '{"Authorization":"Basic %s"}' "$(printf '%s:%s' "$USERID" "$PW" | base64 -w0)")

/home/z/.venv/bin/python3 /home/z/my-project/scripts/tunnel_014.py > "$OUT/tunnel2.log" 2>&1 &
TUN=$!
for i in $(seq 1 40); do curl -s -o /dev/null "$BASE/health" && break; sleep 0.4; done

agent-browser set viewport 1440 900 > /dev/null 2>&1
agent-browser open "$BASE/?s=$STAMP&f=1" --headers "$AUTHHDR" > /dev/null 2>&1
agent-browser wait --load networkidle > /dev/null 2>&1
agent-browser wait 1800 > /dev/null 2>&1
agent-browser click data-nav=factory > /dev/null 2>&1
agent-browser wait 2200 > /dev/null 2>&1

agent-browser eval "JSON.stringify({
  bodyHasConnected: /CONNECTED|متصل/i.test(document.body.textContent),
  bodyHasDisconnected: /DISCONNECTED|غير متصل/i.test(document.body.textContent),
  factoryVisible: (() => { const f = document.querySelector('[data-nav=factory-view], #factory-view, .factory-view, #view-factory'); return f ? !f.hidden : null; })(),
  statusText: (() => { const m = document.body.textContent.match(/SYSTEM[^\\n]{0,40}|النظام[^\\n]{0,40}/i); return m ? m[0].trim() : null; })(),
  sysDot: (() => { const d = document.querySelector('.status-dot, .fc-dot, [class*=dot]'); return d ? getComputedStyle(d).backgroundColor : null; })()
})" > "$OUT/factory-status.json" 2>&1
cat "$OUT/factory-status.json"; echo ""

kill $TUN 2>/dev/null
echo "FACTORY_CHECK_DONE"
