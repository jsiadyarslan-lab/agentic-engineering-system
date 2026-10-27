#!/usr/bin/env python3
"""RLR-001 — stderr-tool files + evidence verdicts + code condition (READ-ONLY)."""
import sqlite3
import subprocess

DB = "/opt/aes-vis/runtime/agent_hub_v2.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("== evidence verdicts")
for r in db.execute('select id, execution_id, step_id, verdict, verification, review_result, audit_result, "commit" as commit_sha, evidence_path from evidence_records order by rowid desc limit 8').fetchall():
    d = dict(r)
    for k in ("verification", "review_result", "audit_result"):
        if d.get(k) and isinstance(d[k], str) and len(d[k]) > 60:
            d[k] = d[k][:60] + "..."
    print(d)

print("\n== last FAILED executions 141-146 detail")
for r in db.execute("select id, step_id, attempt, status, substr(error,1,60) err, started_at, finished_at from executions where id between 140 and 147 order by id").fetchall():
    print(dict(r))

print("\n== workspace of running step 311 + recent failed 299")
print(subprocess.run(["bash", "-c",
    "ls -la /opt/aes-vis/runtime/projects/21/steps/311/ 2>/dev/null | head -12; echo ---299---; "
    "ls -la /opt/aes-vis/runtime/projects/21/steps/299/ 2>/dev/null | head -12; echo ---stderr files---; "
    "ls /opt/aes-vis/runtime/projects/21/steps/299/stderr-tool-*.txt 2>/dev/null | head -6"],
    capture_output=True, text=True).stdout[:1500])

print("== stderr-tool content (299)")
print(subprocess.run(["bash", "-c",
    "for f in $(ls /opt/aes-vis/runtime/projects/21/steps/299/stderr-tool-*.txt 2>/dev/null | head -3); do echo \"--- $f\"; head -c 400 \"$f\"; echo; done"],
    capture_output=True, text=True).stdout[:1600])

print("== grep the fail condition in code")
print(subprocess.run(["bash", "-c",
    "grep -rn 'لم تكتمل أدلة' /opt/aes-vis/src --include='*.py' | head -6"],
    capture_output=True, text=True).stdout[:800])

print("== journal tail of agentic-vis (factory lines)")
print(subprocess.run(["bash", "-c",
    "sudo -n journalctl -u agentic-vis.service --since '05:15' --no-pager 2>/dev/null | grep -vE 'GET /|POST /api/(conversations|projects|messages)' | tail -30"],
    capture_output=True, text=True).stdout[:3500])
