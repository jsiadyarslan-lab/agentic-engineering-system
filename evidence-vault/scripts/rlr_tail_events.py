#!/usr/bin/env python3
"""RLR-001 — tail events + job state (READ-ONLY)."""
import sqlite3
import subprocess

DB = "/opt/aes-vis/runtime/agent_hub_v2.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("== events 8601-8645")
for r in db.execute("select id,kind,substr(payload,1,190) payload,created_at from project_events where id between 8601 and 8645 order by id").fetchall():
    print(f"[{r['id']}] {r['created_at'][11:19]} {r['kind']}: {(r['payload'] or '')[:180]}")

print("\n== job 21")
for r in db.execute("select id,status,waiting_kind,substr(waiting_detail,1,80) wd,tick_count,retries,checkpoints,heartbeat_at from engineering_jobs where id=21").fetchall():
    print(dict(r))

print("\n== exec 151 state")
for r in db.execute("select id,status,started_at,finished_at from executions where id=151").fetchall():
    print(dict(r))

print("\n== journal 05:48-05:54 non-GET")
print(subprocess.run(["bash", "-c",
    "sudo -n journalctl -u agentic-vis.service --since '05:48' --until '05:55' --no-pager 2>/dev/null | grep -vE 'GET /' | head -18"],
    capture_output=True, text=True).stdout[:1800])

print("== recent chrome procs with etime")
print(subprocess.run(["bash", "-c",
    "ps -eo pid,etime,comm | grep chrome | head -8"],
    capture_output=True, text=True).stdout[:800])
