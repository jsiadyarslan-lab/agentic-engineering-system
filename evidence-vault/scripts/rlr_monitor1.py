#!/usr/bin/env python3
"""RLR-001 — monitor E2E progress + inspect aes-rlr-001 history (READ-ONLY)."""
import sqlite3
import subprocess

DB = "/opt/aes-vis/runtime/agent_hub_v2.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("== project 21 status")
for r in db.execute("select id,status,current_plan_id,current_phase_id,current_step_id,completion_state,updated_at from projects where id=21").fetchall():
    print(dict(r))

print("\n== executions > 146")
for r in db.execute("select id,step_id,attempt,status,substr(error,1,70) err,started_at,finished_at from executions where id>146 order by id").fetchall():
    print(dict(r))

print("\n== plan 57 steps")
for r in db.execute("select id,ordinal,status,attempts,substr(objective,1,55) obj from steps where phase_id in (138,139) order by phase_id, ordinal").fetchall():
    print(dict(r))

print("\n== phases 138/139 status")
for r in db.execute("select id,plan_id,ordinal,title,status,completed_at from phases where id in (138,139)").fetchall():
    print(dict(r))

print("\n== last evidence verdicts")
for r in db.execute('select id, execution_id, step_id, verdict, created_at from evidence_records order by rowid desc limit 3').fetchall():
    print(dict(r))

print("\n== planning sessions after 89")
for r in db.execute("select id,attempt,state,started_at,heartbeat_at from planning_sessions where id>89 order by id").fetchall():
    print(dict(r))

print("\n== aes-rlr-001 git log (last 25)")
print(subprocess.run(["bash", "-c",
    "cd /opt/aes-vis && git log --oneline -25 2>&1 | head -30"],
    capture_output=True, text=True).stdout)

print("\n== branch topology")
print(subprocess.run(["bash", "-c",
    "cd /opt/aes-vis && git branch -a 2>/dev/null | head -10; echo ---; "
    "git log --oneline -3 origin/aes-rlr-001 2>/dev/null; echo ---merge-base---; "
    "git merge-base HEAD 947e6e5 2>&1 | head -2; echo ---count---; "
    "git rev-list --count 947e6e5..HEAD 2>&1 | head -1"],
    capture_output=True, text=True).stdout)
