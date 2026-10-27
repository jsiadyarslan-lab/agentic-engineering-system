#!/usr/bin/env python3
"""RLR-001 — plan 58 steps progress (READ-ONLY)."""
import sqlite3

db = sqlite3.connect("/opt/aes-vis/runtime/agent_hub_v2.db")
db.row_factory = sqlite3.Row

print("== plan 58 steps")
for r in db.execute("""select s.id, s.status, s.attempts, substr(s.objective, 1, 60) obj
    from steps s join phases ph on s.phase_id = ph.id
    where ph.plan_id = 58 order by s.id""").fetchall():
    print(dict(r))

print("\n== project + last execution")
for r in db.execute("select status, current_step_id, completion_state, updated_at from projects where id=21").fetchall():
    print(dict(r))
for r in db.execute("select id, step_id, attempt, status, substr(error, 1, 50) err, started_at, finished_at from executions order by id desc limit 3").fetchall():
    print(dict(r))

print("\n== last evidence")
for r in db.execute("select id, execution_id, step_id, verdict, created_at from evidence_records order by rowid desc limit 3").fetchall():
    print(dict(r))
