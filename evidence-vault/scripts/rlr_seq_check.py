#!/usr/bin/env python3
"""RLR-001 — post-restart sequence check (READ-ONLY)."""
import sqlite3
import subprocess

DB = "/opt/aes-vis/runtime/agent_hub_v2.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("== events 06:05:20 - 06:08:30")
for r in db.execute("""select id,kind,substr(payload,1,160) payload,created_at
    from project_events where created_at between '2026-10-26 06:05:20' and '2026-10-26 06:08:30'
    order by id""").fetchall():
    print(f"[{r['id']}] {r['created_at'][11:19]} {r['kind']}: {(r['payload'] or '')[:155]}")

print("\n== project + exec 152 now")
for r in db.execute("select status,current_step_id,updated_at from projects where id=21").fetchall():
    print(dict(r))
for r in db.execute("select id,status,started_at,finished_at from executions where id>=152").fetchall():
    print(dict(r))

print("\n== job 21")
for r in db.execute("select id,status,waiting_kind,tick_count,heartbeat_at from engineering_jobs where id=21").fetchall():
    print(dict(r))

print("\n== newest 313 workspace files")
print(subprocess.run(["bash", "-c",
    "ls -lt /opt/aes-vis/runtime/projects/21/steps/313/ 2>/dev/null | head -8"],
    capture_output=True, text=True).stdout[:800])
