"""Exercise the single workspace against the isolated AES API, not Oracle."""
from pathlib import Path
import json
import subprocess
from fastapi.testclient import TestClient
from api import routes
from workflow import service as svc
from tests.api.conftest import sse_events

def test_v4_workspace_uses_same_project_across_tabs_and_never_launches_on_read(api_env, tmp_path):
    db = api_env["sessions"]
    p = svc.create_project(db, name="واجهة AES معزولة", objective="بناء نتيجة قابلة للفحص")
    q = svc.create_project(db, name="مشروع منفصل", objective="العزل بين المشاريع")
    pid, qid = p["id"], q["id"]
    pl = svc.create_plan(db, pid, {
        "objective": p["objective"], "acceptance_criteria": ["حفظ ملف موثق"],
        "phases": [{"title": "البناء الأولي", "steps": [{"objective": "إنشاء الهيكل", "expected_output": "هيكل المشروع"}]}],
    })
    svc.approve_plan(db, pl["id"])
    svc.materialize_plan(db, pl)
    phase = svc.list_phases(db, pid)[0]["id"]
    step = svc.phase_steps(db, phase)[0]["id"]
    svc.update_project(db, pid, status="BLOCKED", current_plan_id=pl["id"], current_phase_id=phase, current_step_id=step)
    svc.update_phase(db, phase, status="RUNNING", current_step_id=step)
    run = svc.create_execution(db, step, attempt=2, provider="test", model="test", workspace="")
    svc.update_execution(db, run, status="FAILED", error="خطأ معزول")
    g = svc.open_gate(db, pid, "PREFLIGHT_BLOCKED", "سبب الحجب الصحيح", {}, status="BLOCKED")
    svc.add_event(db, pid, "PREFLIGHT_BLOCKED", {"gate_id":g, "step_id":step, "capability_id":"web_search", "status":"STALE", "verdict":"BLOCKED"})
    svc.create_evidence(db, execution_id=run, step_id=step, project_id=pid, files={}, tool_calls=[],
                        verification={"final_state":"EXECUTION_BLOCKED"}, review_result={}, commit="",
                        evidence_path="", evidence_sha256="", verdict="EXECUTION_BLOCKED")
    c = TestClient(routes.app)
    # This one explicitly initiated test chat uses the isolated provider.
    send = c.post("/api/chat/stream", json={"project_id":pid, "message":"ما حالة المشروع؟"})
    assert send.status_code == 200
    ev = sse_events(send)
    bind = next(x for x in ev if x["kind"] == "conversation.bind")["scope"]
    assert bind["project_id"] == pid
    assert any(e["kind"] == "message_completed" for e in ev)
    cid = bind["conversation_id"]
    site = c.get("/static/factory_v3_live.html")
    assert site.status_code == 200
    owner_path = "/static/aes-engineering-control-v4-live.html"
    live_page = c.get(owner_path)
    assert live_page.status_code == 200 and live_page.content == site.content
    assert c.head(owner_path).status_code == 200
    assert 'aes-control-v4-skin' in site.text
    assert c.get("/api/openapi.json").status_code == 404
    spec = c.get("/openapi.json").json()
    assert "project_id" in spec["components"]["schemas"]["ChatStartIn"]["properties"]
    paths = ["/api/projects",f"/api/chat/active?conversation_id={cid}",f"/api/conversations/{cid}/messages"]
    paths.extend(f"/api/projects/{i}/{v}" for i in (pid, qid) for v in ("state","conversations","steps","runtime","evidence","artifacts"))
    store = {}
    for path in paths:
        row = c.get(path)
        assert row.status_code == 200, (path,row.status_code)
        store[path] = row.json()
    assert store[f"/api/projects/{pid}/state"]["active_run"] is None
    assert not store[f"/api/projects/{qid}/conversations"]["conversations"]
    assert not store[f"/api/projects/{qid}/evidence"]["evidence"]
    d = tmp_path/"contract.json"
    d.write_text(json.dumps({"rows":store,"pid":pid,"qid":qid,"cid":cid},ensure_ascii=False))
    root = Path(__file__).resolve().parents[2]
    job = subprocess.run(["node",str(Path(__file__).with_name("aes_v4_workspace.cjs")),str(d),str(root/"src/ui/factory_v3_live.html")],
                         capture_output=True,text=True,timeout=20)
    assert job.returncode == 0, job.stdout + job.stderr
