"""التقاط دليل الاسترداد الحي (013.5 §C.4 / §R) — قراءة فقط."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "runtime" / "agent_hub_v2.db"

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

report: dict = {
    "captured_at": datetime.now(timezone.utc).isoformat(),
    "db": str(DB),
    "db_bytes": DB.stat().st_size,
}

report["projects"] = [
    dict(row) for row in conn.execute(
        "select id, name, status, created_at, updated_at, last_error "
        "from projects order by id"
    )
]

report["planning_sessions"] = [
    dict(row) for row in conn.execute(
        "select id, project_id, state, provider, model, request_id, "
        "attempt, started_at, finished_at, last_activity_at, heartbeat_at, "
        "last_meaningful_activity_at, lease_expires_at, hard_deadline_at, "
        "error_class, substr(coalesce(error_detail,''),1,200) as error_detail "
        "from planning_sessions order by id"
    )
]

report["stuck_planning"] = [
    dict(row) for row in conn.execute(
        "select id, name, status, created_at, last_error from projects "
        "where status = 'PLANNING'"
    )
]

report["generating_sessions"] = [
    dict(row) for row in conn.execute(
        "select id, project_id, state, lease_expires_at, heartbeat_at "
        "from planning_sessions where state = 'GENERATING'"
    )
]

report["healed_events"] = [
    dict(row) for row in conn.execute(
        "select id, project_id, kind, "
        "substr(coalesce(payload,''),1,500) as payload, created_at "
        "from project_events where kind in ('PLANNING_INVARIANT_HEALED',"
        "'PLANNING_INTERRUPTED','WORKFLOW_DIAGNOSED',"
        "'PLANNING_RESULT_DISCARDED') order by id desc limit 12"
    )
]

report["role_provider_mappings"] = [
    dict(row) for row in conn.execute(
        "select role, provider, configuration, model from "
        "role_provider_mappings order by role"
    )
]

out = ROOT / "runtime" / "evidence"
out.mkdir(parents=True, exist_ok=True)
target = out / "order0135-recovery-after-boot.json"
target.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                  encoding="utf-8")
print(json.dumps({
    "stuck_planning": report["stuck_planning"],
    "generating_sessions": report["generating_sessions"],
    "healed_events": [e["kind"] for e in report["healed_events"]],
    "roles": [(m["role"], m["provider"], m["model"])
              for m in report["role_provider_mappings"]],
    "evidence": str(target),
}, ensure_ascii=False, indent=2))
print("sys", sys.version.split()[0])
