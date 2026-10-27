#!/usr/bin/env python3
"""RLR-001 — why did step 314 fail? (READ-ONLY)."""
import json
import sqlite3
import subprocess

DB = "/opt/aes-vis/runtime/agent_hub_v2.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("== step 314 full")
for r in db.execute("select * from steps where id=314").fetchall():
    d = dict(r)
    for k, v in list(d.items()):
        if isinstance(v, str) and len(v) > 200:
            d[k] = v[:200] + "..."
    print(d)

print("\n== execution 156 evidence.json tool_calls")
try:
    ev = json.load(open("/opt/aes-vis/runtime/projects/21/steps/314/evidence.json"))
    for t in (ev.get("tool_calls") or []):
        print("-", t.get("tool") or t.get("kind"), "|", str(t.get("args_summary"))[:120])
    print("verdict:", ev.get("verdict"), "| reasons:", ev.get("verdict_reasons"))
    print("verification:", json.dumps(ev.get("verification"), ensure_ascii=False)[:500])
except FileNotFoundError:
    print("no evidence.json in steps/314")

print("\n== step 314 workspace")
print(subprocess.run(["bash", "-c",
    "ls -la /opt/aes-vis/runtime/projects/21/steps/314/ 2>/dev/null | head -14"],
    capture_output=True, text=True).stdout[:900])

print("== styles.css exists? head")
print(subprocess.run(["bash", "-c",
    "head -c 300 /opt/aes-vis/runtime/projects/21/steps/314/styles.css 2>/dev/null || echo NO_FILE"],
    capture_output=True, text=True).stdout[:500])

print("\n== retry records 314")
for r in db.execute("select * from retry_records where step_id=314 order by id desc limit 2").fetchall():
    print(dict(r))
