#!/usr/bin/env python3
"""RLR-001 — detailed E2E run state on VIS instance (READ-ONLY)."""
import sqlite3

DB = "/opt/aes-vis/runtime/agent_hub_v2.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("== project 21")
for r in db.execute("select * from projects where id=21").fetchall():
    print(dict(r))

print("\n== phases (latest 8)")
cols = [c[1] for c in db.execute("pragma table_info(phases)").fetchall()]
print("cols:", cols)
for r in db.execute("select * from phases where project_id=21 order by id desc limit 8").fetchall():
    d = dict(r)
    for k, v in list(d.items()):
        if isinstance(v, str) and len(v) > 90:
            d[k] = v[:90] + "..."
    print(d)

print("\n== steps status summary")
for r in db.execute("select status, count(*) n from steps where phase_id in (select id from phases where project_id=21) group by status").fetchall():
    print(dict(r))

print("\n== executions count + latest")
print("total executions:", db.execute("select count(*) from executions").fetchone()[0])
cols = [c[1] for c in db.execute("pragma table_info(executions)").fetchall()]
print("cols:", cols)
for r in db.execute("select * from executions order by rowid desc limit 5").fetchall():
    d = dict(r)
    for k, v in list(d.items()):
        if isinstance(v, str) and len(v) > 80:
            d[k] = v[:80] + "..."
    print(d)

print("\n== engineering_jobs")
cols = [c[1] for c in db.execute("pragma table_info(engineering_jobs)").fetchall()]
print("cols:", cols)
for r in db.execute("select * from engineering_jobs order by rowid desc limit 3").fetchall():
    d = dict(r)
    for k, v in list(d.items()):
        if isinstance(v, str) and len(v) > 80:
            d[k] = v[:80] + "..."
    print(d)

print("\n== evidence_records latest")
for r in db.execute("select id, kind, substr(detail_json,1,100) detail, created_at from evidence_records order by rowid desc limit 6").fetchall():
    print(dict(r))

print("\n== planning sessions 21 latest 6")
for r in db.execute("select id,attempt,state,provider,model,started_at,heartbeat_at,hard_deadline_at from planning_sessions where project_id=21 order by id desc limit 6").fetchall():
    print(dict(r))

print("\n== messages (factory conversation) latest 8")
for r in db.execute("select id,conversation_id,role,substr(content,1,80) content,state_badge,created_at from messages order by id desc limit 8").fetchall():
    print(dict(r))

print("\n== retry_records latest")
for r in db.execute("select * from retry_records order by rowid desc limit 5").fetchall():
    d = dict(r)
    for k, v in list(d.items()):
        if isinstance(v, str) and len(v) > 100:
            d[k] = v[:100] + "..."
    print(d)
