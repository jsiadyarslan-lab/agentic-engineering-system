#!/usr/bin/env python3
"""RLR-001 — compact live status (READ-ONLY)."""
import sqlite3
import subprocess

DB = "/opt/aes-vis/runtime/agent_hub_v2.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("== LAST 14 events")
for r in db.execute("select id,kind,substr(payload,1,110) payload,created_at from project_events order by id desc limit 14").fetchall():
    print(f"[{r['id']}] {r['created_at'][11:19]} {r['kind']}: {(r['payload'] or '')[:105]}")

print("\n== exec 153 + project")
for r in db.execute("select id,attempt,status,substr(error,1,60) err,started_at,finished_at from executions where id>=153").fetchall():
    print(dict(r))
for r in db.execute("select status,current_step_id,completion_state,updated_at from projects where id=21").fetchall():
    print(dict(r))

print("\n== screenshots")
print(subprocess.run(["bash", "-c",
    "ls -la /opt/aes-vis/runtime/projects/21/steps/313/screenshots/ 2>/dev/null | tail -18"],
    capture_output=True, text=True).stdout[:1400])

print("== last evidence verdict")
for r in db.execute("select id,execution_id,step_id,verdict,created_at from evidence_records order by rowid desc limit 2").fetchall():
    print(dict(r))
