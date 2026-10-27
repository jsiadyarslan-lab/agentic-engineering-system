#!/bin/bash
# W1-T02 — القياس الحي لبوابة القبول:
# جلسة خاملة 65ث (مركز التحكم) + 65ث (صفحة مشروع BLOCKED) = صفر طلبات
# runs/active و /runtime بعد التحميل الأولي + SSE حي + صفر أخطاء JS.
set -u
OUT=/home/z/my-project/download/aes-remediation/W1-T02
CREDS_FILE=/tmp/w1t02_creds.txt
BASE="http://127.0.0.1:18086"
PY=/home/z/.venv/bin/python
STAMP=$(date +%s)
mkdir -p "$OUT"

ab() { agent-browser "$@"; }

echo "== [0] مستخدم مؤقت =="
$PY /home/z/my-project/scripts/w1t02_auth_setup.py 2>&1 | tee "$OUT/auth_setup_log.txt"
CREDS=$(cat "$CREDS_FILE"); USERID=${CREDS%%:*}; PW=${CREDS#*:}
AUTHHDR=$(printf '{"Authorization":"Basic %s"}' "$(printf '%s:%s' "$USERID" "$PW" | base64 -w0)")

echo "== [1] النفق =="
$PY /home/z/my-project/scripts/w1t02_tunnel.py > "$OUT/tunnel_log.txt" 2>&1 &
TUN=$!
for i in $(seq 1 40); do curl -s -o /dev/null --max-time 4 "$BASE/health" && break; sleep 0.4; done
echo "auth-wall: $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 $BASE/) (expect 401)"
echo "auth-ok:   $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 -u "$USERID:$PW" $BASE/) (expect 200)"

echo "== [2] تحميل أولي (يسمح بطلباته) + استقرار =="
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?s=$STAMP" --headers "$AUTHHDR" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 4000 > /dev/null 2>&1
ab eval "document.querySelector('script[src*=control-center]').src" 2>&1 | tee "$OUT/asset_version_check.txt"

echo "== [3] نافذة الخمول الأولى: مركز التحكم 65ث =="
ab network requests > "$OUT/net-cc-before.txt" 2>&1
sleep 65
ab network requests > "$OUT/net-cc-after.txt" 2>&1
diff "$OUT/net-cc-before.txt" "$OUT/net-cc-after.txt" | grep '^>' > "$OUT/net-cc-new-requests.txt" || true
CC_TOTAL=$(wc -l < "$OUT/net-cc-new-requests.txt")
CC_POLL=$(grep -cE 'runs/active|/runtime' "$OUT/net-cc-new-requests.txt" || true)
echo "طلبات جديدة خلال 65ث خمول (مركز التحكم): total=$CC_TOTAL poll=$CC_POLL (المطلوب poll=0)"

echo "== [4] حالة SSE وأخطاء JS بعد أول نافذة =="
ab eval "JSON.stringify({sse_connected: window.LiveEvents ? LiveEvents.isConnected() : 'NO_API', ready: document.readyState})" 2>&1 | tee "$OUT/sse_state_cc.txt"
ab errors > "$OUT/errors_cc.txt" 2>&1; cat "$OUT/errors_cc.txt"

echo "== [5] فتح صفحة المشروع 1 (BLOCKED) + استقرار =="
ab eval "(document.querySelector('.proj-item[data-project-id=\"1\"]')||{click:()=>location.hash='#/project/1'}).click()" > /dev/null 2>&1
ab wait 4000 > /dev/null 2>&1
ab eval "JSON.stringify({mode_project: document.body.classList.contains('mode-project'), sse_connected: window.LiveEvents ? LiveEvents.isConnected() : null})" 2>&1 | tee "$OUT/project_open_state.txt"

echo "== [6] نافذة الخمول الثانية: صفحة المشروع 65ث =="
ab network requests > "$OUT/net-proj-before.txt" 2>&1
sleep 65
ab network requests > "$OUT/net-proj-after.txt" 2>&1
diff "$OUT/net-proj-before.txt" "$OUT/net-proj-after.txt" | grep '^>' > "$OUT/net-proj-new-requests.txt" || true
PJ_TOTAL=$(wc -l < "$OUT/net-proj-new-requests.txt")
PJ_POLL=$(grep -cE 'runs/active|/runtime' "$OUT/net-proj-new-requests.txt" || true)
echo "طلبات جديدة خلال 65ث خمول (صفحة المشروع): total=$PJ_TOTAL poll=$PJ_POLL (المطلوب poll=0)"

echo "== [7] الحالة النهائية + لقطة + أخطاء =="
ab eval "JSON.stringify({sse_connected: window.LiveEvents ? LiveEvents.isConnected() : null, last_event_id: window.LiveEvents ? LiveEvents.lastEventId() : null})" 2>&1 | tee "$OUT/sse_state_final.txt"
ab screenshot "$OUT/idle-final-1440.png" > /dev/null 2>&1 && echo "shot: idle-final-1440.png"
ab errors > "$OUT/errors_final.txt" 2>&1; cat "$OUT/errors_final.txt"

echo "== [8] ملخص بوابة القبول =="
{
  echo "asset_version: $(grep -oE 'v=[0-9a-f]+' "$OUT/asset_version_check.txt" | head -1)"
  echo "cc_idle_65s_new_requests_total: $CC_TOTAL"
  echo "cc_idle_65s_poll_requests: $CC_POLL"
  echo "proj_idle_65s_new_requests_total: $PJ_TOTAL"
  echo "proj_idle_65s_poll_requests: $PJ_POLL"
  echo "sse_final: $(cat "$OUT/sse_state_final.txt" | head -1)"
  echo "js_errors_final: $(grep -c . "$OUT/errors_final.txt" || true)"
} | tee "$OUT/gate_summary.txt"

echo "== [9] إغلاق النفق + تنظيف مصادقة بايتي =="
kill $TUN 2>/dev/null || true
$PY /home/z/my-project/scripts/w1t02_auth_cleanup.py 2>&1 | tee "$OUT/auth_cleanup_log.txt"
rm -f "$CREDS_FILE"
echo "DONE"
