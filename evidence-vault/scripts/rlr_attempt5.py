#!/usr/bin/env python3
"""RLR-001 — attempt 5 full event tail (READ-ONLY)."""
import sqlite3
import subprocess

DB = "/opt/aes-vis/runtime/agent_hub_v2.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("== events after 8726")
for r in db.execute("select id,kind,substr(payload,1,170) payload,created_at from project_events where id > 8726 order by id limit 40").fetchall():
    print(f"[{r['id']}] {r['created_at'][11:19]} {r['kind']}: {(r['payload'] or '')[:165]}")

print("\n== exec 153 now")
for r in db.execute("select id,attempt,status,substr(error,1,60) err,started_at,finished_at from executions where id>=153").fetchall():
    print(dict(r))

print("\n== project now")
for r in db.execute("select status,current_step_id,completion_state,updated_at from projects where id=21").fetchall():
    print(dict(r))

print("\n== screenshots + verdict evidence")
print(subprocess.run(["bash", "-c",
    "ls -la /opt/aes-vis/runtime/projects/21/steps/313/screenshots/ 2>/dev/null | head -20; "
    "echo ---; ls /opt/aes-vis/runtime/projects/21/steps/313/ | head -20"],
    capture_output=True, text=True).stdout[:1500])

print("== chrome alive?")
print(subprocess.run(["bash", "-c",
    "ps -eo pid,etime,comm | grep chrome | head -4"],
    capture_output=True, text=True).stdout[:500])
