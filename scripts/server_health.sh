#!/usr/bin/env bash
# AES-FACTORY-RELEASE-READINESS-002 §4 — فحص صحة صادق (مرصد لا مصلِّح)
#
# يطبع: حيوية العملية، استجابة /health الكاملة، وإحصاءات قاعدة
# البيانات (المشاريع/المهام/الأحداث) — لتوثيق استمرارية الحالة.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${AES_PORT:-8010}"
DB="$REPO/runtime/agent_hub_v2.db"

echo "=== server health ==="
if curl -fsS "http://127.0.0.1:${PORT}/health" 2>/dev/null; then
  echo
  echo "server ALIVE on 127.0.0.1:${PORT}"
else
  echo "server NOT responding on 127.0.0.1:${PORT}"
fi

if [ -f "$DB" ]; then
  echo "=== database state ($DB) ==="
  python3 - "$DB" << 'PYEOF'
import sqlite3, sys
conn = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
for table in ("projects", "plans", "phases", "steps", "events", "conversations", "provider_configurations"):
    try:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {n}")
    except Exception:
        print(f"  {table}: (absent)")
try:
    for row in conn.execute("SELECT id, name, status, created_at FROM projects ORDER BY id DESC LIMIT 5"):
        print("  project:", row)
except Exception:
    pass
conn.close()
PYEOF
else
  echo "=== database absent: $DB ==="
fi
