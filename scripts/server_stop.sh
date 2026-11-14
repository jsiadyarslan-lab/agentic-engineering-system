#!/usr/bin/env bash
# AES-FACTORY-RELEASE-READINESS-002 §4 — إيقاف صادق قابل للتكرار
#
# العقد: يقتل PID المكتوب في runtime/server.pid فقط، ثم يتحقق فعليًا
# أن المنفذ حرّ وأن العملية انتهت — لا صمت على فشل الإيقاف.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${AES_PORT:-8010}"
PIDFILE="$REPO/runtime/server.pid"

if [ ! -f "$PIDFILE" ]; then
  echo "[stop] no pidfile — server not started by server_start.sh"
  exit 0
fi

PID="$(cat "$PIDFILE" 2>/dev/null || true)"
if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
  echo "[stop] pid $PID not alive — cleaning stale pidfile"
  rm -f "$PIDFILE"
  exit 0
fi

kill "$PID" 2>/dev/null || true
for _ in $(seq 1 20); do
  kill -0 "$PID" 2>/dev/null || break
  sleep 0.5
done
if kill -0 "$PID" 2>/dev/null; then
  echo "[stop] graceful kill failed — escalating (TERM group then KILL)"
  kill -TERM -- -"$PID" 2>/dev/null || true
  sleep 2
  kill -KILL "$PID" 2>/dev/null || true
fi

rm -f "$PIDFILE"
# تحقق صادق: المنفذ حرّ فعلًا
if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "[stop] ERROR: something still answers on ${PORT}"
  exit 1
fi
echo "[stop] server stopped cleanly; port ${PORT} free; DB untouched"
