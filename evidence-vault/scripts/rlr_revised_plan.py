#!/usr/bin/env python3
"""RLR-001 — revised plan + gate inspection (READ-ONLY)."""
import sqlite3

db = sqlite3.connect("/opt/aes-vis/runtime/agent_hub_v2.db")
db.row_factory = sqlite3.Row

print("== plans (latest 3) for project 21")
pcols = [c[1] for c in db.execute("pragma table_info(plans)").fetchall()]
print("plan cols:", pcols[:12])
sel = ", ".join(f'"{c}"' for c in pcols[:10])
for r in db.execute(f'select {sel} from plans where project_id=21 order by id desc limit 2').fetchall():
    d = dict(r)
    for k, v in list(d.items()):
        if isinstance(v, str) and len(v) > 100:
            d[k] = v[:100] + "..."
    print(d)

pid_row = db.execute("select id from plans where project_id=21 order by id desc limit 1").fetchone()
if pid_row:
    pid = pid_row["id"]
    print(f"\n== steps of plan {pid}")
    for s in db.execute("""select s.id, s.ordinal, s.status, substr(s.objective,1,120) obj,
                              substr(s.acceptance_criteria,1,150) crit
                           from steps s join phases ph on s.phase_id=ph.id
                           where ph.plan_id=? order by ph.ordinal, s.ordinal""", (pid,)).fetchall():
        print(dict(s))

print("\n== owner_gates latest 3")
cols = [c[1] for c in db.execute("pragma table_info(owner_gates)").fetchall()]
print("cols:", cols)
q = ", ".join(f'"{c}"' for c in cols[:10])
for r in db.execute(f"select {q} from owner_gates order by rowid desc limit 3").fetchall():
    d = dict(r)
    for k, v in list(d.items()):
        if isinstance(v, str) and len(v) > 150:
            d[k] = v[:150] + "..."
    print(d)

print("\n== project + job now")
for r in db.execute("select status,current_plan_id,current_step_id,updated_at from projects where id=21").fetchall():
    print(dict(r))
for r in db.execute("select status,waiting_kind,waiting_detail from engineering_jobs where id=21").fetchall():
    print(r["status"], r["waiting_kind"], (r["waiting_detail"] or "")[:200])
