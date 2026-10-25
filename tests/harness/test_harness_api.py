"""اختبارات API الـHarness (012) — وظائف وخط زمن وسلسلة وأدوار
وقدرات عبر HTTP حقيقي (TestClient) مع محرك مخطط كاختبارات 007.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests" / "api"))

from api import routes  # noqa: E402

from test_projects_api import (  # noqa: E402
    FakeRouter, ScriptedPlanner, _fake_https_getter,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """قاعدة معزولة + محرك مخطط عبر الخطاف الصريح (نمط 007)."""
    from persistence.database import (
        build_engine, init_db, make_session_factory,
    )
    from providers_registry import registry

    monkeypatch.chdir(tmp_path)
    db = build_engine(tmp_path / "harness-api.db")
    init_db(db)
    sessions = make_session_factory(db)
    monkeypatch.setattr(routes, "_sessions", sessions)
    registry.ensure_seeded(sessions)

    # منفذ خطوة ناجح منظّم — نفس عقد run_task (كما في 007)
    import hashlib
    import tasks as tasks_mod

    def fake_run_task(goal, *, router, role_config=None, workspace=None,
                      on_event=None, cycle_id=None, stop_controller=None,
                      resume_from=None, **_kw):
        from tasks import TaskResult

        root = Path(workspace)
        root.mkdir(parents=True, exist_ok=True)
        output = root / "deliverable.md"
        output.write_text(f"# مخرج\n\n{goal}\n", encoding="utf-8")
        evidence_path = root / "evidence.json"
        evidence_path.write_text("{}", encoding="utf-8")
        return TaskResult(
            verdict="PASS", reason="تم", goal=goal,
            cycle_id=cycle_id or "", final_state="EVIDENCED",
            workspace=str(root), files=["deliverable.md"],
            tool_calls=[], evidence_path=str(evidence_path),
            evidence_sha256=hashlib.sha256(
                evidence_path.read_bytes()).hexdigest(),
            duration_ms=5, state_history=["EVIDENCED"],
        )

    monkeypatch.setattr(tasks_mod, "run_task", fake_run_task)

    from api import projects

    def factory(on_event=None, **_kwargs):
        from workflow.engine import ProjectEngine

        return ProjectEngine(
            sessions, router_factory=FakeRouter,
            planner_factory=ScriptedPlanner, on_event=on_event,
            # (AES-EXP-04 §6) مسبار network_https محقون عبر العقد
            # المعلن — نفس نمط tests/api: هدف هذه الاختبارات عقد API
            # الوظائف لا وصول المضيف للإنترنت (على مضيف بلا خروج كانت
            # الدورات تحجب عند الفحص المسبق فتنفجر مهلات 150ث).
            probe_injections={"https_fn": _fake_https_getter},
        )

    monkeypatch.setattr(projects, "_test_engine_factory", factory)
    yield TestClient(routes.app)
    monkeypatch.setattr(projects, "_test_engine_factory", None)


def _approved(client):
    out = client.post("/api/projects", json={
        "name": "API الوظائف", "objective": "هدف اختبار API الوظيفة",
    })
    pid = out.json()["id"]
    from planning_wait import wait_for_plan

    client.post(f"/api/projects/{pid}/plan/generate")
    wait_for_plan(client, pid)
    client.post(f"/api/projects/{pid}/plan/approve",
                json={"approved": True})
    return pid


def _run(client, pid):
    with client.stream(
        "POST", f"/api/projects/{pid}/run/stream"
    ) as response:
        assert response.status_code == 200
        for _line in response.iter_lines():
            pass


# ---------- الوظيفة عبر API ----------

def test_project_detail_carries_job(client):
    pid = _approved(client)
    detail = client.get(f"/api/projects/{pid}").json()
    # (013 §3) الاعتماد أمر يطلق الحلقة — الوظيفة وُلدت فعلًا
    # (JOB_CREATED) وحالتها من الدورة الحقيقية لا وظيفة وهمية.
    assert detail["job"] is not None
    assert detail["job"]["status"] in ("QUEUED", "RUNNING",
                                           "WAITING_GATE", "COMPLETED")
    _run(client, pid)
    detail = client.get(f"/api/projects/{pid}").json()
    job = detail["job"]
    assert job and job["status"] == "WAITING_GATE"
    assert job["waiting_kind"] == "GATE"
    assert job["heartbeat_at"]
    assert job["tick_count"] >= 1


def test_job_endpoints(client):
    pid = _approved(client)
    # (013) الاعتماد أطلق الوظيفة فعلًا — 404 فقط لوظيفة غير موجودة
    assert client.get("/api/jobs/9999").status_code == 404

    _run(client, pid)
    job = client.get(f"/api/projects/{pid}/job").json()
    assert job["status"] == "WAITING_GATE"

    by_id = client.get(f"/api/harness/jobs/{job['id']}").json()
    assert by_id["id"] == job["id"]
    assert by_id["waiting_detail"]["gate_kinds"]

    listing = client.get("/api/harness/jobs").json()
    assert any(j["id"] == job["id"] for j in listing["jobs"])

    # التحقق عبر API يكمل الوظيفة (ربط mark_verified)
    verified = client.post(f"/api/projects/{pid}/verify").json()
    assert verified["status"] == "VERIFIED"
    final = client.get(f"/api/projects/{pid}/job").json()
    assert final["status"] == "COMPLETED"


def test_job_events_reach_stream_and_events(client):
    pid = _approved(client)
    _run(client, pid)
    events = client.get(f"/api/projects/{pid}/events").json()["events"]
    kinds = {e["kind"] for e in events}
    assert {"JOB_QUEUED", "JOB_STARTED", "JOB_WAITING"} <= kinds


# ---------- الإسقاطات عبر API ----------

def test_timeline_endpoint(client):
    pid = _approved(client)
    _run(client, pid)
    timeline = client.get(f"/api/projects/{pid}/timeline").json()
    assert timeline["stages"][0] == "OBJECTIVE"
    canons = [i["canonical"] for i in timeline["items"]]
    assert "project/created" in canons
    assert "plan/approved" in canons
    assert "job/waiting" in canons
    # كل بند يحمل مرحلة وفاعلًا وعنوانًا
    item = timeline["items"][0]
    assert item["stage"] and item["actor"] and item["title"]


def test_chain_endpoint_full_view(client):
    pid = _approved(client)
    _run(client, pid)
    chain = client.get(f"/api/projects/{pid}/chain").json()
    by_stage = {s["stage"]: s["status"] for s in chain["stages"]}
    assert by_stage["OBJECTIVE"] == "DONE"
    assert by_stage["APPROVAL"] == "DONE"
    assert by_stage["VERIFICATION"] == "WAITING"
    assert chain["complete"] is False

    client.post(f"/api/projects/{pid}/verify")
    chain = client.get(f"/api/projects/{pid}/chain").json()
    by_stage = {s["stage"]: s["status"] for s in chain["stages"]}
    assert by_stage["VERIFICATION"] == "DONE"
    assert chain["complete"] is True


# ---------- الأدوار والقدرات عبر API ----------

def test_roles_endpoint(client):
    roles = client.get("/api/harness/roles").json()["roles"]
    assert [r["role"] for r in roles] == [
        "thinker", "reviewer", "implementer", "verifier", "arbiter",
    ]
    for role in roles:
        assert role["prompt_exists"] is True
        assert "live_selection" in role
        assert "transport_key" in role["live_selection"]


def test_capabilities_endpoint(client):
    caps = client.get("/api/harness/capabilities").json()["capabilities"]
    by_id = {c["capability_id"]: c for c in caps}
    assert by_id["sandbox"]["blocked_kind"] == "WORKER"
    assert by_id["llm"]["blocked_kind"] == "CAPABILITY"
    assert by_id["web_search"]["resolution"] == "FAILOVER"
    # (013.5 §L) خمسة مزودين: ويكيبيديا أُضيفت مزودًا حقيقيًا
    # ومفعّلة افتراضيًا (بلا مفتاح) بعد DDG/Bing/SearXNG/Search API.
    assert len(by_id["web_search"]["providers"]) == 5


def test_event_vocabulary_endpoint(client):
    out = client.get("/api/harness/events/vocabulary").json()
    assert "JOB_WAITING" in out["job_event_kinds"]
    assert out["canonical_map"]["PLAN_APPROVED"] == "plan/approved"
    assert out["chain_stages"][0] == "OBJECTIVE"
