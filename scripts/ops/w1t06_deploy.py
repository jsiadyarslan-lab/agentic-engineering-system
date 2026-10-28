#!/usr/bin/env python3
# W1-T06 deploy: ff pull fb48857 -> py_compile -> R6-gated restart -> verify
# engine code live + the env-blocker classification works with the app's own
# code on production (safe simulation with a fake NOT_READY capability view
# in an ISOLATED python process — no production data touched).
import json, time, paramiko, os

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EVDIR = "/home/z/my-project/download/aes-remediation/W1-T06"
os.makedirs(EVDIR, exist_ok=True)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W1-T06 deploy (fb48857)", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=180, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:140], "rc": rc, "out": out.strip()[:3000],
            "err": err.strip()[:400]}

ev["health_before"] = run("curl -s -o /dev/null -w '%{http_code}' -m 8 http://127.0.0.1:8010/health", 20, "health before")
ev["head_before"] = run("sudo -n git -C /opt/agentic-engineering-system rev-parse HEAD", 20, "HEAD before")

ev["git_pull"] = run("sudo -n git -C /opt/agentic-engineering-system pull --ff-only origin main 2>&1 | tail -4", 120, "git ff pull")
ev["head_after_pull"] = run("sudo -n git -C /opt/agentic-engineering-system rev-parse HEAD", 20, "HEAD after pull")

ev["py_compile"] = run(
    "cd /opt/agentic-engineering-system && .venv/bin/python -m py_compile "
    "src/workflow/engine.py && echo COMPILE_OK", 120, "py_compile")

ev["restart"] = run("sudo -n systemctl restart agentic && echo RESTART_ISSUED", 120, "restart")
health_after = ""
for i in range(36):
    time.sleep(5)
    code = run("curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:8010/health", 20, "health poll")
    if code.get("out") == "200":
        health_after = f"200 (after {(i+1)*5}s)"
        break
ev["health_after_restart"] = health_after or "NOT_200_WITHIN_180S"

ev["services_after"] = run("systemctl is-active agentic nginx searxng search-api", 20, "services after")
ev["journal_err"] = run("sudo -n journalctl -u agentic -p err --since '-5 minutes' --no-pager | tail -8", 30, "journal errors")

# --- live verification of the new classification code (isolated process,
# temporary DB, monkeypatched capability view — production data untouched) ---
SMOKE = r'''
import sys, json, tempfile, pathlib
sys.path.insert(0, "/opt/agentic-engineering-system/src")

# isolated temp DB — never touches production runtime
from persistence.database import build_engine, init_db, make_session_factory
tmp = pathlib.Path(tempfile.mkdtemp(prefix="w1t06-smoke-"))
engine_db = build_engine(tmp / "smoke.db")
init_db(engine_db)
sessions = make_session_factory(engine_db)

from workflow import service
from workflow.engine import ProjectEngine

eng = ProjectEngine(sessions, router_factory=lambda: type("R", (), {"has_live_provider": staticmethod(lambda p: True), "live_providers": staticmethod(lambda: ["nvidia"])})())
project = eng.create_project("w1t06-smoke", "هدف تحقق دخاني")
plan_data = {"objective": "هدف دخاني", "phases": [{"title": "مرحلة دخانية", "objective": "هدف", "steps": [{"objective": "خطوة دخانية", "input": "", "expected_output": "out.md", "acceptance_criteria": ["out.md"]}]}]}
plan = service.create_plan(sessions, project["id"], plan_data, status="APPROVED")
service.materialize_plan(sessions, plan)
phase = service.list_phases(sessions, project["id"])[0]
step = service.phase_steps(sessions, phase["id"])[0]

exec_ids = []
for attempt in (1, 2):
    eid = service.create_execution(sessions, step["id"], attempt=attempt,
                                   provider="nvidia", model="smoke",
                                   workspace=str(tmp))
    service.update_execution(sessions, eid, status="FAILED", error="سبب عام")
    exec_ids.append(eid)

from readiness.models import ToolInvocation
with sessions() as s:
    s.add(ToolInvocation(
        cycle_id=f"project-{project['id']}-step-{step['id']}",
        tool_call_id="tc-smoke", tool="web_search", status="FAILED",
        failure_class="DEPENDENCY_FAILURE", failure_stage="PROVIDER_RESOLUTION",
        failure_reason="SEARCH_PROVIDER_NOT_READY", query="q", error=""))
    s.commit()

from readiness import service as readiness_service
readiness_service.capability_view = lambda sessions_, cid: {
    "capability_id": cid, "readiness_status": "NOT_READY",
    "reason": "منظم للاختبار", "failure_reason": "جهّز المزود"}

reason = "الحالة النهائية FAILED — الدورة لم تكتمل أدلةً"
out = eng._on_step_failure(project, plan, phase, step, exec_ids[-1], reason)
gates = service.open_gates(sessions, project["id"])
fresh = service.get_step(sessions, step["id"])
print("@@J@@")
print(json.dumps({
    "outcome": out,
    "gate_kind": gates[-1]["kind"] if gates else None,
    "gate_status": gates[-1]["status"] if gates else None,
    "step_status_after": fresh["status"],
}, ensure_ascii=False, default=str))
'''
ev["smoke_env_blocker"] = run(
    "cd /opt/agentic-engineering-system && .venv/bin/python - <<'PYEOF'\n" + SMOKE + "\nPYEOF",
    120, "smoke env-blocker classification")

# --- verify production capability view currently (real, read-only) ---
ev["web_search_now"] = run(
    "curl -s -m 10 http://127.0.0.1:8010/api/environment/readiness | "
    "python3 -c \"import json,sys; d=json.load(sys.stdin); caps=d.get('capabilities') or d.get('items') or []; "
    "w=[c for c in caps if 'web_search' in str(c.get('capability_id',c.get('id',c.get('name'))))]; "
    "print(json.dumps({'web_search': (w[0].get('readiness_status') or w[0].get('status')) if w else None, "
    "'not_ready_count': len([c for c in caps if (c.get('readiness_status') or c.get('status'))=='NOT_READY']), "
    "'total': len(caps)}, ensure_ascii=False))\"", 30, "web_search readiness now")

ssh.close()

path = f"{EVDIR}/deploy.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps({k: v for k, v in ev.items() if k != "_meta"}, ensure_ascii=False, indent=1)[:3000])
print("\nsaved:", path)
