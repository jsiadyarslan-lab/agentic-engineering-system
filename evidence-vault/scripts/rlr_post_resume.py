#!/usr/bin/env python3
"""RLR-001 — post-resume monitor (READ-ONLY)."""
import sqlite3
import subprocess

DB = "/opt/aes-vis/runtime/agent_hub_v2.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("== project")
for r in db.execute("select status,current_step_id,completion_state,updated_at from projects where id=21").fetchall():
    print(dict(r))

print("\n== executions >= 151")
for r in db.execute("select id,step_id,attempt,status,substr(error,1,60) err,started_at,finished_at from executions where id>=151").fetchall():
    print(dict(r))

print("\n== last 8 project_events")
for r in db.execute("select id,kind,substr(payload,1,130) payload,created_at from project_events order by id desc limit 8").fetchall():
    print(f"[{r['id']}] {r['created_at'][11:19]} {r['kind']}: {(r['payload'] or '')[:125]}")

print("\n== planning sessions > 89")
for r in db.execute("select id,attempt,state,started_at,heartbeat_at from planning_sessions where id>89 order by id").fetchall():
    print(dict(r))

print("\n== screenshots dir")
print(subprocess.run(["bash", "-c",
    "ls -la /opt/aes-vis/runtime/projects/21/steps/313/screenshots/ 2>/dev/null | head -18"],
    capture_output=True, text=True).stdout[:1200])
