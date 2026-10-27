#!/bin/bash
# AES-DESIGN-IMPL-012 — decisive in-page error probe across all interactions
set -u
REPO=/home/z/my-project/repo
PY=/home/z/.venv/bin/python3
PORT=8022
DB="$REPO/runtime/ui-012.db"
OUT=/home/z/my-project/download/design-impl-012/local-verify
STAMP=$(date +%s)
BASE="http://127.0.0.1:$PORT"
mkdir -p "$OUT"

cd "$REPO"
AGenthubV2_DB_PATH="$DB" PYTHONPATH=src "$PY" -m uvicorn src.api.routes:app \
  --host 127.0.0.1 --port $PORT > "$OUT/server2.log" 2>&1 &
SRV=$!
for i in $(seq 1 100); do curl -s -o /dev/null "http://127.0.0.1:$PORT/health" && break; sleep 0.4; done

ab() { agent-browser "$@"; }
ab set viewport 1440 900 > /dev/null 2>&1
ab open "$BASE/?p=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1

# inject in-page collectors BEFORE interactions
ab eval "
window.__errs = [];
window.addEventListener('error', e => window.__errs.push('ERR: ' + e.message + ' @ ' + e.filename + ':' + e.lineno));
window.addEventListener('unhandledrejection', e => window.__errs.push('REJ: ' + (e.reason && e.reason.message || e.reason)));
'collectors-on'" > /dev/null 2>&1

echo "== A: factory open+back (the Hub.setMode path) =="
ab eval "document.querySelector('.side-nav-item[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 900 > /dev/null 2>&1
ab eval "document.getElementById('factory-back') && document.getElementById('factory-back').click()" > /dev/null 2>&1
ab wait 700 > /dev/null 2>&1

echo "== B: open conversation with content =="
ab eval "(document.querySelectorAll('#conversations .conv-item')[0]||{}).click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot "$OUT/probe-conversation-1440.png" > /dev/null 2>&1

echo "== C: settings open/esc =="
ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 700 > /dev/null 2>&1
ab press Escape > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1

echo "== D: composer typing + mode menu =="
ab eval "document.getElementById('input').value='اختبار كتابة'; document.getElementById('input').dispatchEvent(new Event('input'))" > /dev/null 2>&1
ab eval "document.getElementById('plus').click()" > /dev/null 2>&1
ab wait 400 > /dev/null 2>&1
ab eval "document.getElementById('plus').click()" > /dev/null 2>&1

echo "== E: archive + runs nav =="
ab eval "document.querySelector('.side-nav-item[data-nav=archive]').click()" > /dev/null 2>&1
ab wait 700 > /dev/null 2>&1
ab eval "document.querySelector('.side-nav-item[data-nav=runs]').click()" > /dev/null 2>&1
ab wait 700 > /dev/null 2>&1
ab eval "document.querySelector('.side-nav-item[data-nav=chat]').click()" > /dev/null 2>&1
ab wait 500 > /dev/null 2>&1

echo "== F: in-page error collector dump =="
ab eval "JSON.stringify({count: window.__errs.length, errs: window.__errs.slice(0,10)})" 2>&1 | tee "$OUT/inpage-errors.json"

echo "== G: pageerrors CLI + console final =="
ab errors > "$OUT/probe-cli-errors.txt" 2>&1; cat "$OUT/probe-cli-errors.txt"
ab console > "$OUT/probe-console.txt" 2>&1; echo "console lines: $(wc -l < "$OUT/probe-console.txt")"

echo "== H: composer alignment vs messages column =="
ab eval "
(() => {
  const m = document.querySelector('.messages').getBoundingClientRect();
  const c = document.querySelector('.composer-inner').getBoundingClientRect();
  return JSON.stringify({msgL:+m.left.toFixed(1), msgR:+m.right.toFixed(1), cL:+c.left.toFixed(1), cR:+c.right.toFixed(1)});
})()" 2>&1 | tee "$OUT/alignment.json"

kill $SRV 2>/dev/null; wait $SRV 2>/dev/null
echo "== done =="
