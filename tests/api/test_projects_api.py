"""اختبارات API المشاريع (الأمر 007 §18) — نقل نحيف حول المحرك الدائم.

المحرك عبر خطاف الاختبار الصريح (نفس فلسفة conftest الأمر 006):
engine حقيقي بكل طبقاته، وحدوده الخارجية منظمة (مخطط/منفذ/موجّه).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("httpx", reason="TestClient يتطلب httpx")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from api import projects, routes  # noqa: E402
from workflow import service  # noqa: E402


class FakeRouter:
    def __init__(self):
        self._providers = {"nvidia"}

    def has_live_provider(self, provider_id):
        return str(provider_id) in self._providers

    def live_providers(self):
        return sorted(self._providers)


SCRIPTED_PLAN = {
    "objective": "هدف الخطة",
    "assumptions": [],
    "acceptance_criteria": ["الملف deliverable.md موجود ضمن الأدلة"],
    "phases": [{
        "title": "مرحلة وحيدة",
        "objective": "عمل",
        "acceptance_criteria": ["الملف deliverable.md موجود ضمن الأدلة"],
        "steps": [{
            "objective": "خطوة وحيدة",
            "input": "",
            "expected_output": "deliverable.md",
            "acceptance_criteria": ["الملف deliverable.md موجود ضمن الأدلة"],
            "dependencies": [],
        }],
    }],
    "risks": [], "dependencies": [], "required_owner_decisions": [],
}


class ScriptedPlanner:
    def generate(self, objective, *, previous_failure=None, feedback=""):
        import json

        return json.loads(json.dumps(SCRIPTED_PLAN))


@pytest.fixture()
def project_env(tmp_path, monkeypatch):
    """قاعدة معزولة + محرك اختباري عبر الخطاف الصريح."""
    import hashlib

    from persistence.database import build_engine, init_db, make_session_factory
    from providers_registry import registry

    monkeypatch.chdir(tmp_path)
    engine = build_engine(tmp_path / "projects-api.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    monkeypatch.setattr(routes, "_sessions", sessions)
    registry.ensure_seeded(sessions)

    runs: list[str] = []

    def fake_run_task(goal, *, router, role_config=None, workspace=None,
                      on_event=None, cycle_id=None, stop_controller=None,
                      resume_from=None, **_kw):
        from tasks import TaskResult

        runs.append(goal)
        root = Path(workspace)
        root.mkdir(parents=True, exist_ok=True)
        output = root / "deliverable.md"
        output.write_text(f"# مخرج\n\n{goal}\n", encoding="utf-8")
        evidence_path = root / "evidence.json"
        evidence_path.write_text("{}", encoding="utf-8")
        return TaskResult(
            verdict="PASS", reason="تم", goal=goal, cycle_id=cycle_id or "",
            final_state="EVIDENCED", workspace=str(root),
            files=["deliverable.md"], tool_calls=[],
            evidence_path=str(evidence_path),
            evidence_sha256=hashlib.sha256(
                evidence_path.read_bytes()).hexdigest(),
            duration_ms=5, state_history=["EVIDENCED"],
        )

    import tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "run_task", fake_run_task)

    def factory(on_event=None, **_kwargs):
        from workflow.engine import ProjectEngine

        return ProjectEngine(
            sessions,
            router_factory=FakeRouter,
            planner_factory=ScriptedPlanner,
            on_event=on_event,
        )

    monkeypatch.setattr(projects, "_test_engine_factory", factory)
    yield {"sessions": sessions, "runs": runs, "tmp_path": tmp_path}
    monkeypatch.setattr(projects, "_test_engine_factory", None)


@pytest.fixture()
def client(project_env):
    return TestClient(routes.app)


def _create_and_approve(client):
    created = client.post("/api/projects", json={
        "name": "مشروع API", "objective": "هدف عبر API للاختبار",
    })
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    plan = client.post(f"/api/projects/{pid}/plan/generate")
    assert plan.status_code == 200, plan.text
    approved = client.post(f"/api/projects/{pid}/plan/approve",
                           json={"approved": True})
    assert approved.status_code == 200, approved.text
    return pid


def test_project_crud_and_plan_flow(client, project_env):
    """إنشاء ← توليد ← اعتماد — كل حالة من القاعدة عبر API نحيف."""
    pid = _create_and_approve(client)
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["status"] == "READY"
    assert detail["plan"]["version"] == 1
    assert detail["plan"]["approved_by_owner"] is True
    assert detail["phases"] and detail["phases"][0]["status"] == "PLANNED"
    # القائمة تعرض المشروع
    listing = client.get("/api/projects").json()
    assert [p["id"] for p in listing["projects"]] == [pid]


def test_run_stream_completes_project(client, project_env):
    """تشغيل الحلقة عبر SSE حتى المرشح — ثم تحقق المالك."""
    pid = _create_and_approve(client)
    with client.stream(
        "POST", f"/api/projects/{pid}/run/stream"
    ) as response:
        assert response.status_code == 200
        kinds = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                import json

                event = json.loads(line[6:])
                kinds.append(event["kind"])
    assert "run.start" in kinds
    assert "PHASE_STARTED" in kinds
    assert "EXECUTION_COMPLETED" in kinds
    assert "AUDIT_COMPLETED" in kinds
    assert "PROJECT_COMPLETION_CANDIDATE" in kinds
    assert "run.done" in kinds
    # المنفذ استُدعي فعليًا (خطوة واحدة)
    assert len(project_env["runs"]) == 1

    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["status"] == "COMPLETED"
    assert detail["completion_state"] == "CANDIDATE"
    # التحقق قبل حل البوابة عبر verify يحلها مباشرة (قناة المالك)
    verified = client.post(f"/api/projects/{pid}/verify").json()
    assert verified["status"] == "VERIFIED"


def test_verify_rejected_before_completion(client, project_env):
    """التحقق قبل الأوان مرفوض — لا VERIFIED بلا مرشح (§16)."""
    pid = _create_and_approve(client)
    early = client.post(f"/api/projects/{pid}/verify")
    assert early.status_code == 409
    assert "يتطلب" in early.json()["detail"]


def test_stop_and_resume_via_api(client, project_env):
    """إيقاف ← استئناف عبر API — الحالة الدائمة في القاعدة."""
    pid = _create_and_approve(client)
    stopped = client.post(f"/api/projects/{pid}/stop",
                          json={"reason": "اختبار"}).json()
    assert stopped["stop_requested"] is True
    # tick يكرم العلم: تشغيل يتوقف فورًا بحالة PAUSED
    with client.stream("POST", f"/api/projects/{pid}/run/stream") as response:
        for _line in response.iter_lines():
            pass
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["status"] == "PAUSED"
    # استئناف + إكمال
    resumed = client.post(f"/api/projects/{pid}/resume").json()
    assert resumed["status"] == "RUNNING"
    with client.stream("POST", f"/api/projects/{pid}/run/stream") as response:
        for _line in response.iter_lines():
            pass
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["status"] == "COMPLETED"


def test_recovery_listing_after_pause(client, project_env):
    """قائمة المشاريع تعرض تقييم الاسترداد للمشاريع غير النهائية (§19)."""
    pid = _create_and_approve(client)
    client.post(f"/api/projects/{pid}/stop", json={"reason": ""})
    with client.stream("POST", f"/api/projects/{pid}/run/stream") as response:
        for _line in response.iter_lines():
            pass
    listing = client.get("/api/projects").json()
    entry = [r for r in listing["recovery"] if r["project_id"] == pid]
    assert entry and entry[0]["resumable"] is True
    assert entry[0]["checkpoint"]


def test_sub_resources_exposed(client, project_env):
    """الموارد الفرعية: مراحل/خطوات/تنفيذات/أدلة/تدقيق/أحداث (§18)."""
    pid = _create_and_approve(client)
    with client.stream("POST", f"/api/projects/{pid}/run/stream") as response:
        for _line in response.iter_lines():
            pass
    assert client.get(f"/api/projects/{pid}/phases").json()["phases"]
    steps = client.get(f"/api/projects/{pid}/steps").json()["steps"]
    assert steps and steps[0]["status"] == "COMPLETED"
    assert client.get(f"/api/projects/{pid}/executions").json()["executions"]
    assert client.get(f"/api/projects/{pid}/evidence").json()["evidence"]
    assert client.get(f"/api/projects/{pid}/audit").json()["audits"]
    events = client.get(f"/api/projects/{pid}/events").json()["events"]
    assert {e["kind"] for e in events} >= {"PROJECT_CREATED", "PLAN_APPROVED"}


def test_unknown_project_404(client, project_env):
    assert client.get("/api/projects/9999").status_code == 404
    assert client.post("/api/projects/9999/stop",
                       json={}).status_code == 404


def test_concurrent_run_rejected(client, project_env):
    """مشروع واحد يعمل في كل لحظة — الثاني يُرفض (§10)."""
    import threading
    import time

    pid1 = _create_and_approve(client)
    pid2 = _create_and_approve(client)

    # شغّل مشروعًا بطيئًا (منفذ ينتظر) في خيط حقيقي
    started = threading.Event()
    release = threading.Event()

    original = projects._test_engine_factory

    def slow_factory(**kwargs):
        engine = original(**kwargs)
        real_run = engine.run

        def slow_run(project_id, *, max_ticks=100):
            started.set()
            release.wait(timeout=10)
            return real_run(project_id, max_ticks=max_ticks)

        engine.run = slow_run  # type: ignore[method-assign]
        return engine

    projects._test_engine_factory = slow_factory
    try:
        thread = threading.Thread(
            target=lambda: TestClient(routes.app).post(
                f"/api/projects/{pid1}/run/stream"
            ), daemon=True,
        )
        thread.start()
        assert started.wait(timeout=5)
        # المشروع الثاني يُرفض والمشروع الأول نشط
        clash = client.post(f"/api/projects/{pid2}/run/stream")
        assert clash.status_code == 409
        listing = client.get("/api/projects").json()
        assert listing["active_run"] == pid1
    finally:
        release.set()
        thread.join(timeout=10)
        projects._test_engine_factory = original
