#!/usr/bin/env python3
"""RLR-001 — worker stall investigation (READ-ONLY)."""
import sqlite3
import subprocess

DB = "/opt/aes-vis/runtime/agent_hub_v2.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("== project_events 05:47:30 - 05:54")
for r in db.execute("""select id,kind,substr(payload,1,210) payload,created_at
    from project_events where created_at between '2026-10-26 05:47:30' and '2026-10-26 05:54:00'
    order by id""").fetchall():
    print(f"[{r['id']}] {r['created_at'][11:19]} {r['kind']}: {(r['payload'] or '')[:200]}")

print("\n== engineering_jobs (job 21)")
for r in db.execute("select * from engineering_jobs where id=21").fetchall():
    d = dict(r)
    for k, v in list(d.items()):
        if isinstance(v, str) and len(v) > 90:
            d[k] = v[:90] + "..."
    print(d)

print("\n== last 10 project_events overall")
for r in db.execute("select id,kind,substr(payload,1,150) payload,created_at from project_events order by id desc limit 10").fetchall():
    print(f"[{r['id']}] {r['created_at'][11:19]} {r['kind']}: {(r['payload'] or '')[:145]}")

print("\n== service journal 05:47-05:54 non-GET")
print(subprocess.run(["bash", "-c",
    "sudo -n journalctl -u agentic-vis.service --since '05:47' --until '05:54' --no-pager 2>/dev/null | grep -vE 'GET /' | head -20"],
    capture_output=True, text=True).stdout[:2000])

print("== service threads")
print(subprocess.run(["bash", "-c",
    "svc=$(pgrep -f 'uvicorn api.routes:app --host 127.0.0.1 --port 8011' | head -1); "
    "echo pid=$svc; ps -L -o lwp,etime,pcpu,comm -p $svc 2>/dev/null | head -14"],
    capture_output=True, text=True).stdout[:1200])

print("== executions 151 + planning 89 heartbeat")
for r in db.execute("select id,status,started_at,finished_at from executions where id=151").fetchall():
    print(dict(r))
for r in db.execute("select id,state,started_at,heartbeat_at,lease_expires_at,hard_deadline_at from planning_sessions where id=89").fetchall():
    print(dict(r))
