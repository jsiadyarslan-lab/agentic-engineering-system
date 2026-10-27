#!/usr/bin/env python3
"""RLR-001 — why do steps fail? events around failed executions (READ-ONLY)."""
import sqlite3

DB = "/opt/aes-vis/runtime/agent_hub_v2.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("== events in window 05:19:00 - 05:24:00 (last cycle: fail->replan->new step)")
for r in db.execute("""
    select id, cycle_id, seq, role, kind, state, substr(payload,1,260) payload, created_at
    from events
    where created_at between '2026-10-26 05:19:00' and '2026-10-26 05:24:30'
    order by id
""").fetchall():
    print(f"[{r['id']}] {r['created_at'][11:19]} {r['cycle_id']}/{r['seq']} {r['role']}.{r['kind']} {r['state'] or ''}")
    p = r['payload'] or ''
    if any(k in p for k in ('error', 'failed', 'FAILED', 'retry', 'timeout', 'timeout', 'refused', 'BLOCKED')):
        print('   >>', p[:250])
    else:
        print('   ', p[:150])

print("\n== retry_records schema + rows")
cols = [c[1] for c in db.execute("pragma table_info(retry_records)").fetchall()]
print("cols:", cols)
for r in db.execute("select * from retry_records order by rowid desc limit 6").fetchall():
    d = dict(r)
    for k, v in list(d.items()):
        if isinstance(v, str) and len(v) > 130:
            d[k] = v[:130] + "..."
    print(d)

print("\n== evidence_records schema + latest")
cols = [c[1] for c in db.execute("pragma table_info(evidence_records)").fetchall()]
print("cols:", cols)
q = ", ".join(cols[:10])
for r in db.execute(f"select {q} from evidence_records order by rowid desc limit 5").fetchall():
    d = dict(r)
    for k, v in list(d.items()):
        if isinstance(v, str) and len(v) > 130:
            d[k] = v[:130] + "..."
    print(d)

print("\n== completed vs failed steps (which plans)")
for r in db.execute("""
    select p.id plan, s.status, count(*) n
    from steps s join phases ph on s.phase_id=ph.id join plans p on ph.plan_id=p.id
    where ph.project_id=21 group by p.id, s.status order by p.id desc limit 24
""").fetchall():
    print(dict(r))
