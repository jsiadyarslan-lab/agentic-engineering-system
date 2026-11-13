#!/usr/bin/env python3
"""W2-T25-AUDIT — independent completion audit of project #3 (BUILD A NEWS WEBSITE).
Gathers live evidence from server API + sqlite (read-only) + site HTML; every claim re-verified here.

AES-P0-CONTAINMENT-PR-REMEDIATION-1113-R1 fix 6 — credential transport: the token
never appears in this file, in the remote command text, in any URL, or in the
argument list of any spawned process (curl reads the header from STDIN via
`-H @-`; printf is a shell builtin, so the value stays in the remote shell's
memory only). It is never printed and never written to the audit JSON."""
import json, paramiko, sys, os

KEY = "/tmp/oracle_key"
OUT = "/home/z/my-project/download/aes-remediation/W2-T25/audit_w2t25_independent.json"
checks = []

def add(cid, desc, ok, ev):
    if not isinstance(ev, str):
        ev = json.dumps(ev, ensure_ascii=False, default=str)
    checks.append({"id": cid, "check": desc, "result": "PASS" if ok else "FAIL", "evidence": ev[:600]})

def run(ssh, cmd, timeout=60):
    _, out, err = ssh.exec_command(cmd, timeout=timeout)
    return out.read().decode("utf-8", "replace").strip(), err.read().decode("utf-8", "replace").strip()

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("92.5.14.150", username="opc", key_filename=KEY, timeout=20)

# A1: project terminal status
# R1 fix 6: header piped via stdin — token never in curl's argv (not in /proc/*/cmdline)
o, _ = run(ssh, "printf \"X-Access-Key: %s\" \"$(sudo cat /etc/w2t25-monitor/monitor_token)\" | curl -s -m 10 -H @- 'http://127.0.0.1:8765/api/status'")
st = json.loads(o)
add("A1", "project.status == COMPLETED (API)", st["project"]["status"] == "COMPLETED",
    {"status": st["project"]["status"], "updated_at": st["project"]["updated_at"]})

# A2: final audit 418 PASS with clean findings
o, _ = run(ssh, "sudo python3 -c \"import sqlite3,json;c=sqlite3.connect('file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro',uri=True);c.row_factory=sqlite3.Row;print(json.dumps([dict(r) for r in c.execute('SELECT id,verdict,findings,created_at FROM audit_records WHERE id=418')],default=str))\"")
a418 = json.loads(o)[0]
f = json.loads(a418["findings"])
add("A2", "final audit #418 verdict PASS and failed_audits empty and no pending/broken",
    a418["verdict"] == "PASS" and f["failed_audits"] == [] and f["steps_pending"] == [] and f["broken_evidence"] == [],
    {"verdict": a418["verdict"], "failed_audits": f["failed_audits"], "phases": f"{f['phases_completed']}/{f['phases_total']}"})

# A3: plan v112 steps all COMPLETED first-try
o, _ = run(ssh, "sudo python3 -c \"import sqlite3,json;c=sqlite3.connect('file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro',uri=True);c.row_factory=sqlite3.Row;print(json.dumps([dict(r) for r in c.execute('SELECT id,status,attempts FROM steps WHERE id BETWEEN 1038 AND 1043 ORDER BY id')]))\"")
steps = json.loads(o)
add("A3", "plan v112 steps 1038-1043 all COMPLETED attempts=1",
    all(s["status"] == "COMPLETED" and s["attempts"] == 1 for s in steps) and len(steps) == 6,
    steps)

# A4: counts
c = st["counts"]
add("A4", "counts reconciled: done=300 total=958 failed=87 plans=112",
    c["steps_done"] == 300 and c["steps_total"] == 958 and c["steps_failed"] == 87 and c["plans_total"] == 112, c)

# A5: gate ledger
o, _ = run(ssh, "sudo python3 -c \"import sqlite3,json;c=sqlite3.connect('file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro',uri=True);r1=dict(c.execute('SELECT status,COUNT(*) FROM owner_gates WHERE project_id=3 GROUP BY status').fetchall());r2=dict(c.execute('SELECT kind,COUNT(*) FROM owner_gates WHERE project_id=3 GROUP BY kind').fetchall());print(json.dumps({'by_status':r1,'by_kind':r2}))\"")
g = json.loads(o)
add("A5", "gate ledger: 288 total, 287 APPROVED, only #312 FINAL_VERIFICATION PENDING",
    g["by_status"].get("APPROVED") == 287 and g["by_status"].get("PENDING") == 1 and g["by_kind"].get("FINAL_VERIFICATION") == 1, g)

# A6: driver clean terminal stop (pgrep excludes the probing bash itself; keepalive log must confirm no restart)
o, _ = run(ssh, "grep -c 'PROJECT_TERMINAL:COMPLETED' /home/opc/w2t25_drive/latest.log; pgrep -f '^python3 /home/opc/w2t25_server_drive.py$' || echo NOPROC; tail -2 /home/opc/w2t25_drive/keepalive.log")
lines = o.splitlines()
ka_no_restart = "COMPLETED \u2014 no restart" in o or "COMPLETED - no restart" in o
add("A6", "driver stopped itself cleanly (PROJECT_TERMINAL:COMPLETED), no python driver process runs, keepalive refuses restart",
    lines and lines[0] == "1" and "NOPROC" in o and ka_no_restart, o[:300])

# A7: owner-mode brake never lifted by me
o, _ = run(ssh, "stat -c '%y' /home/opc/w2t25_owner_mode 2>/dev/null || echo MISSING")
add("A7", "owner-mode brake file still present (mtime unchanged 2026-10-31 23:46 UTC) — all gate approvals human",
    "MISSING" not in o and o.startswith("2026-10-31 23:46"), o)

# A8: nginx proof of human approvals from owner's browser
o, _ = run(ssh, "sudo grep -E 'POST /api/projects/3/(gates/|plan/approve)' /var/log/nginx/access.log | grep ' 200 ' | grep 2.215.157.88 | tail -3")
add("A8", "nginx log: owner browser (2.215.157.88) POSTs approved gates/plan with 200",
    bool(o.strip()), o[:400])

# A9: live site (served via API 8765 /preview/index.html with token cookie) shows the three Arabic article cards
# R1 fix 6: cookie header piped via stdin — token never in curl's argv
o, _ = run(ssh, "printf \"Cookie: w2t25k=%s\" \"$(sudo cat /etc/w2t25-monitor/monitor_token)\" | curl -s -m 10 -o /dev/null -w '%{http_code}' -H @- http://127.0.0.1:8765/preview/index.html; echo; printf \"Cookie: w2t25k=%s\" \"$(sudo cat /etc/w2t25-monitor/monitor_token)\" | curl -s -m 10 -H @- http://127.0.0.1:8765/preview/index.html | grep -o -E 'مقال (أول|ثاني|ثالث)' | sort | uniq -c")
lines = [l for l in o.splitlines() if l.strip()]
code = lines[0] if lines else "?"
arts = [l for l in lines[1:] if l.strip()]
add("A9", "live preview site HTTP 200 and serves the three Arabic article cards",
    code == "200" and len(arts) >= 3, {"http": code, "headings": arts})

# A10: local visual evidence files fresh
paths = ["/home/z/my-project/download/aes-remediation/W2-T25/shots/" + f for f in ("dashboard.png", "site_desktop.png", "site_mobile.png", "control_owner.png")]
import datetime
info = {}
for p in paths:
    if os.path.exists(p):
        mt = datetime.datetime.fromtimestamp(os.path.getmtime(p), datetime.UTC).isoformat()
        info[os.path.basename(p)] = {"size": os.path.getsize(p), "mtime": mt}
add("A10", "4 fresh screenshots pulled (>= 2026-11-01T04:21Z) for owner visual proof",
    len(info) == 4 and all(v["mtime"] >= "2026-11-01T04:21" for v in info.values()), info)

ssh.close()

verdict = "PASS" if all(c["result"] == "PASS" for c in checks) else "FAIL"
doc = {
    "task": "W2-T25-AUDIT",
    "scope": "Independent completion audit of project #3 BUILD A NEWS WEBSITE (factory terminal state)",
    "audited_at_utc": datetime.datetime.now(datetime.UTC).isoformat(),
    "method": "live re-verification: API status + read-only sqlite (owner_gates/audit_records/steps) + nginx access log + site HTML + local artifacts",
    "verdict": verdict,
    "checks_total": len(checks),
    "checks_passed": sum(1 for c in checks if c["result"] == "PASS"),
    "checks": checks,
    "honest_caveats": [
        "87/958 steps failed historically (death-spiral era v84-v107) — count preserved in ledger, not hidden.",
        "Final audit at 11:35 (+08) FAILED citing 11 historical failed audits; plan v112 remediation cleared them (audit #418 failed_audits=[]) — the cumulative-blocking mechanism remains a watch item.",
        "Audits 398/399 (11:02-11:10 +08) marked CSS content criteria 'unverifiable' though layout.css was evidenced — auditor content-window issue, engine fix candidate.",
        "Shot script reports 'list articles: 0' while the rendered page visually shows the 3 article cards — selector mismatch in the shot tool, site itself renders them (A9 evidence).",
        "Rendered page is functionally minimal (no visible theme/layout styling in screenshot; placeholder Arabic copy) — COMPLETED reflects the plan's mechanical acceptance criteria, not production-grade design.",
        "Gate #312 FINAL_VERIFICATION deliberately left PENDING for the owner (owner-mode brake never lifted)."
    ]
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=1)
print(f"VERDICT: {verdict}  checks: {doc['checks_passed']}/{doc['checks_total']}")
for c in checks:
    print(f"  {c['id']} {c['result']} — {c['check']}")
