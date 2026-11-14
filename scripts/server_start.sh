#!/usr/bin/env bash
# AES-FACTORY-RELEASE-READINESS-002 §4 — أمر بدء واحد قابل للتكرار
#
# الاستخدام:
#   bash scripts/server_start.sh [--fresh-db]     # بدء/إعادة بدء الخادم
#   bash scripts/server_stop.sh                   # إيقاف صادق (انظر أدناه)
#   bash scripts/server_health.sh                 # فحص صحة صادق
#
# العقد:
# - أمر واحد يبدأ الخادم بلا أي تهيئة يدوية داخلية: venv إن لزم،
#   تبعيات مثبتة إن لزم (pip install -e '.[test]')، ثم uvicorn.
# - قاعدة البيانات في runtime/agent_hub_v2.db (نسبة لمجلد التشغيل)
#   — الإيقاف/البدء لا يمسّها إطلاقًا: الاستمرارية ملف SQLite واحد.
# - PID المكتوب في runtime/server.pid هو هوية الخادم الحية الوحيدة
#   — الإيقاف يقتل ذلك الـ PID فقط ثم يتحقق أن المنفذ حرّ فعلًا.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${AES_PORT:-8010}"
RUNTIME="$REPO/runtime"
LOG="$RUNTIME/server_${PORT}.log"
PIDFILE="$RUNTIME/server.pid"

mkdir -p "$RUNTIME"
cd "$REPO"

# 1) بيثون المشروع (venv محلي إن وُجد وإلا المفسّر الحالي)
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

# 2) التبعيات إن لم تُثبَّت في هذا المفسّر (اختبار قابل للاستيراد)
if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "[start] installing project deps..."
  "$PY" -m pip install -e ".[test]" -q || exit 2
fi

# 3) خادم حي سابق؟ لا بدء مزدوج (idempotent)
if [ -f "$PIDFILE" ]; then
  OLD="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
    echo "[start] server already running (pid=$OLD) — nothing to do"
    exit 0
  fi
  rm -f "$PIDFILE"
fi

# 4) بدء منفصل كليًا عن الجلسة (setsid) — لا يُقتل مع نهاية الجلسة
echo "[start] launching uvicorn api.routes:app on 127.0.0.1:${PORT}"
setsid env PYTHONPATH="$REPO/src" "$PY" -m uvicorn api.routes:app \
  --host 127.0.0.1 --port "$PORT" >>"$LOG" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PIDFILE"

# 5) انتظار صحة حقيقية (لا «بدأ فقط») — حتى 30 ثانية
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "[start] healthy: http://127.0.0.1:${PORT}/ (pid=$NEW_PID)"
    curl -fsS "http://127.0.0.1:${PORT}/health" | head -c 300; echo
    exit 0
  fi
  sleep 1
done

echo "[start] FAILED to become healthy in 30s — last log lines:"
tail -n 20 "$LOG" || true
exit 3
