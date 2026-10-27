#!/usr/bin/env python3
"""RLR-001 — FINAL E2E evidence collection (READ-ONLY)."""
import sqlite3
import subprocess

DB = "/opt/aes-vis/runtime/agent_hub_v2.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("== FINAL project state")
for r in db.execute("select status, current_plan_id, current_step_id, completion_state, updated_at from projects where id=21").fetchall():
    print(dict(r))

print("\n== planning sessions summary")
for r in db.execute("""select state, count(*) n from planning_sessions
    where project_id=21 group by state""").fetchall():
    print(dict(r))

print("\n== executions summary (whole E2E)")
for r in db.execute("""select status, count(*) n from executions
    where step_id in (select s.id from steps s join phases ph on s.phase_id=ph.id
    join plans p on ph.plan_id=p.id where p.project_id=21) group by status""").fetchall():
    print(dict(r))

print("\n== steps summary")
for r in db.execute("""select s.status, count(*) n from steps s join phases ph on s.phase_id=ph.id
    join plans p on ph.plan_id=p.id where p.project_id=21 group by s.status""").fetchall():
    print(dict(r))

print("\n== evidence verdicts summary")
for r in db.execute("""select verdict, count(*) n from evidence_records
    where project_id=21 group by verdict""").fetchall():
    print(dict(r))

print("\n== browser events summary")
for r in db.execute("""select kind, count(*) n from project_events
    where kind like 'BROWSER%' group by kind""").fetchall():
    print(dict(r))

print("\n== model reasoning events (bridge proof)")
for r in db.execute("""select count(*) n from project_events
    where kind = 'MODEL_REASONING'""").fetchall():
    print("MODEL_REASONING events:", r["n"])
for r in db.execute("""select count(*) n from project_events
    where kind = 'BROWSER_PAGE_LOADED'""").fetchall():
    print("BROWSER_PAGE_LOADED events:", r["n"])

print("\n== best site files (step 312 workspace)")
print(subprocess.run(["bash", "-c",
    "ls -la /opt/aes-vis/runtime/projects/21/steps/312/*.html "
    "/opt/aes-vis/runtime/projects/21/steps/312/script.js 2>/dev/null | awk '{print $5, $9}'"],
    capture_output=True, text=True).stdout[:800])

print("\n== git log (server branch)")
print(subprocess.run(["bash", "-c",
    "git -C /opt/aes-vis log --oneline -4"],
    capture_output=True, text=True).stdout[:600])

print("\n== current time")
print(subprocess.run(["date"], capture_output=True, text=True).stdout.strip())
