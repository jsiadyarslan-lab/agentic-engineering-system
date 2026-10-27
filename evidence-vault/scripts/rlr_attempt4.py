#!/usr/bin/env python3
"""RLR-001 — attempt 4 live progress (READ-ONLY)."""
import sqlite3
import subprocess

DB = "/opt/aes-vis/runtime/agent_hub_v2.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("== project + executions now")
for r in db.execute("select status,current_step_id,updated_at from projects where id=21").fetchall():
    print(dict(r))
for r in db.execute("select id,attempt,status,substr(error,1,50) err,started_at,finished_at from executions where id>=152").fetchall():
    print(dict(r))

print("\n== events after 06:08:30 (tool/browser)")
for r in db.execute("""select id,kind,substr(payload,1,150) payload,created_at
    from project_events where created_at > '2026-10-26 06:08:30'
    order by id limit 25""").fetchall():
    print(f"[{r['id']}] {r['created_at'][11:19]} {r['kind']}: {(r['payload'] or '')[:145]}")

print("\n== screenshots now")
print(subprocess.run(["bash", "-c",
    "ls -la /opt/aes-vis/runtime/projects/21/steps/313/screenshots/ 2>/dev/null | head -20"],
    capture_output=True, text=True).stdout[:1200])

print("== newest workspace files")
print(subprocess.run(["bash", "-c",
    "ls -lt /opt/aes-vis/runtime/projects/21/steps/313/ | head -10"],
    capture_output=True, text=True).stdout[:900])

print("== chrome procs etime")
print(subprocess.run(["bash", "-c",
    "ps -eo pid,etime,comm | grep chrome | head -6"],
    capture_output=True, text=True).stdout[:600])
