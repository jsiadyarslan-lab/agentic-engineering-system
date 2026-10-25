"""اختبارات API المشاريع (الأمر 007 §18) — نقل نحيف حول المحرك الدائم.

المحرك عبر خطاف الاختبار الصريح (نفس فلسفة conftest الأمر 006):
engine حقيقي بكل طبقاته، وحدوده الخارجية منظمة (مخطط/منفذ/موجّه).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("httpx", reason="TestClient يتطلب httpx")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from api import projects, routes  # noqa: E402
from tests.api.planning_wait import (  # noqa: E402
    generate_plan_and_wait,
)
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
    # (013.6 §12) نريد مهمة بطيئة بما يكفي للسماح بإيقافها مؤقتًا
    # أثناء التنفيذ - وإلا يكتمل المشروع قبل وصول طلب الإيقاف.
    pause_event = None

    def fake_run_task(goal, *, router, role_config=None, workspace=None,
                      on_event=None, cycle_id=None, stop_controller=None,
                      resume_from=None, stop_cycle_id=None, **_kw):
        from tasks import TaskResult
        import time as _time

        runs.append(goal)
        if on_event is not None:
            try:
                on_event({"kind": "tool.started", "role": "implementer",
                          "tool": "write_file", "query": "deliverable.md",
                          "execution_site": "substrate",
                          "tool_call_id": f"tc-{len(runs)}-1"})
                on_event({"kind": "tool.call", "role": "implementer",
                          "tool": "write_file",
                          "args_summary": "deliverable.md",
                          "execution_site": "substrate",
                          "tool_call_id": f"tc-{len(runs)}-1",
                          "duration_ms": 9})
            except Exception:  # noqa: BLE001
                pass
        root = Path(workspace)
        root.mkdir(parents=True, exist_ok=True)
        output = root / "deliverable.md"
        output.write_text(f"# مخرج\n\n{goal}\n", encoding="utf-8")
        evidence_path = root / "evidence.json"
        evidence_path.write_text("{}", encoding="utf-8")
        # (013.6 §F) احترام طلب الإيقاف المؤقت — واجهة StopController الحقيقية
        # تستخدم stop_cycle_id (مستوى المشروع) للإيقاف، لا cycle_id (مستوى الخطوة)
        check_id = stop_cycle_id or cycle_id
        if stop_controller is not None and check_id is not None:
            checker = (stop_controller.checker_for(check_id)
                       if hasattr(stop_controller, "checker_for")
                       else lambda: stop_controller.is_stopped(check_id))
            # ننتظر الإيقاف مؤقتًا، لكن لا نعلق إلى الأبد — المهلة
            # القصوى 5 ثوانٍ ثم نكمل المهمة (للتأكد من أن الاختبار
            # يمكنه التقاط المشروع في RUNNING قبل أن يكتمل)
            start_wait = _time.monotonic()
            while not checker():
                if _time.monotonic() - start_wait > 5.0:
                    break  # مهلة الأمان: نكمل المهمة حتى لو لم يأتِ الإيقاف
                _time.sleep(0.1)
        else:
            _time.sleep(0.5)
        return TaskResult(
            verdict="PASS", reason="تم", goal=goal, cycle_id=cycle_id or "",
            final_state="EVIDENCED", workspace=str(root),
            files=["deliverable.md"], tool_calls=[],
            evidence_path=str(evidence_path),
            evidence_sha256=hashlib.sha256(
                evidence_path.read_bytes()).hexdigest(),
            duration_ms=500, state_history=["EVIDENCED"],
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
            # (AES-EXP-04 §6) حقن مسبار network_https عبر العقد المعلن
            # (registry.run_probe «الحقن للاختبارات حصرًا») — هدف هذه
            # الاختبارات عقد ناقل الأحداث لا وصول المضيف للإنترنت؛
            # على مضيف بلا خروج شبكي كان المسبار الحقيقي يحجب الفحص
            # المسبق ويحوّل كل هذه الاختبارات إلى اختبارات شبكة.
            probe_injections={"https_fn": _fake_https_getter},
        )

    monkeypatch.setattr(projects, "_test_engine_factory", factory)
    yield {"sessions": sessions, "runs": runs, "tmp_path": tmp_path}
    # (013) الاعتماد يطلق الحلقة خلفيًا الآن — استنزفها قبل فك الترقيع
    # كي لا تستدعي حلقة متأخرة منفذ الاختبار التالي (تسريب عبر الحدود).
    from workflow import runner as _wf_runner

    deadline = time.monotonic() + 60.0
    while _wf_runner.active_run(sessions) is not None:
        if time.monotonic() > deadline:
            break
        time.sleep(0.05)
    monkeypatch.setattr(projects, "_test_engine_factory", None)


@pytest.fixture()
def client(project_env):
    return TestClient(routes.app)


class _FakeHTTPSResponse:
    """استجابة تفي بعقد probe_https كاملًا (status + read + headers)."""

    status = 200
    headers = {"Content-Type": "text/plain"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n=-1):
        return b"aes-test-ok"


def _fake_https_getter(url, timeout=None):
    """مسبار https محقون — عبر آلية الحقن المعلنة للاختبارات حصرًا."""
    return _FakeHTTPSResponse()


def _create_and_approve(client):
    created = client.post("/api/projects", json={
        "name": "مشروع API", "objective": "هدف عبر API للاختبار",
    })
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    # (013.4 §1) التوليد أمر خلفي — ننتظر نتيجته الصادقة
    plan, _detail = generate_plan_and_wait(client, pid)
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
    """قائمة المشاريع تعرض تقييم الاسترداد للمشاريع غير النهائية (§19).

    ننشئ مشروعًا بسياسة COMPATIBLE_LOCAL (تنفذ على Windows)، نعتمد الخطة
    فيطلق التنفيذ تلقائيًا، ثم ننتظر أن يدخل RUNNING ونوقفه مؤقتًا
    فورًا — في هذه اللحظة يجب أن يظهر في recovery مع checkpoint.
    """
    # إنشاء مشروع بسياسة توافق محلي (تنفذ على Windows)
    created = client.post("/api/projects", json={
        "name": "مشروع استرداد", "objective": "هدف للاختبار",
        "execution_policy": "COMPATIBLE_LOCAL",
    })
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    # توليد واعتماد الخطة (الاعتماد يطلق الحلقة تلقائيًا 013.5)
    plan, _detail = generate_plan_and_wait(client, pid)
    assert plan.status_code == 200, plan.text
    approved = client.post(f"/api/projects/{pid}/plan/approve",
                           json={"approved": True})
    assert approved.status_code == 200, approved.text
    print(f"APPROVE: {approved.json()}", flush=True)
    # انتظار أن يدخل المشروع في RUNNING (تنفيذ فعلي)
    import time as _time
    deadline = _time.monotonic() + 30.0
    while True:
        state = client.get(f"/api/projects/{pid}/state").json()
        rt_state = state.get("environment", {}).get("runtime_state", {})
        print(f"POLL: status={state.get('status')}, rt={rt_state.get('state')}, coh={rt_state.get('coherent')}", flush=True)
        if rt_state.get("state") == "RUNNING":
            break
        if _time.monotonic() > deadline:
            raise AssertionError("المشروع لم يدخل RUNNING خلال المهلة")
        _time.sleep(0.1)
    # المشروع يعمل الآن — أوقفه مؤقتًا (pause)
    pause_resp = client.post(f"/api/projects/{pid}/pause", json={"reason": "اختبار الاسترداد"})
    assert pause_resp.status_code == 200, pause_resp.text
    print(f"PAUSE RESPONSE: {pause_resp.json()}", flush=True)
    # انتظار أن يتحول المشروع فعليًا إلى PAUSED (الإيقاف المؤقت غير متزامن)
    deadline = _time.monotonic() + 10.0
    while True:
        proj = client.get(f"/api/projects/{pid}").json()
        if proj.get("status") == "PAUSED":
            break
        if _time.monotonic() > deadline:
            raise AssertionError(f"المشروع لم يتحول إلى PAUSED، الحالة: {proj.get('status')}")
        _time.sleep(0.1)
    # تحقق من قائمة الاسترداد الآن — يجب أن يظهر المشروع
    listing = client.get("/api/projects").json()
    print(f"LISTING PROJECTS: {[p['status'] for p in listing['projects']]}", flush=True)
    print(f"RECOVERY: {listing['recovery']}", flush=True)
    state = client.get(f"/api/projects/{pid}/state").json()
    print(f"STATE: {state.get('status')}", flush=True)
    entry = [r for r in listing["recovery"] if r["project_id"] == pid]
    assert entry and entry[0]["resumable"] is True, f"recovery entry: {entry}"
    assert entry[0]["checkpoint"], "يجب أن يوجد checkpoint عند الإيقاف المؤقت"
    # استئنف وأكمل
    with client.stream("POST", f"/api/projects/{pid}/run/stream") as response:
        for _line in response.iter_lines():
            pass


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
    """مشروع واحد يعمل في كل لحظة — الثاني يُرفض (§10 + 013 §40).

    (013) الاعتماد نفسه يطلق الحلقة الآن: المصنع البطيء يُثبّت قبل
    الاعتماد فيصبح أول tick من إطلاق الاعتماد هو الحاجز — الضمان
    نفسه (واحد باللحظة) عبر المسار الجديد نفسه.
    """
    import threading

    started = threading.Event()
    release = threading.Event()

    original = projects._test_engine_factory

    def slow_factory(**kwargs):
        engine = original(**kwargs)
        # (012) الحلقة تدور عبر engine.tick داخل JobManager.run_loop —
        # الإبطاء عند أول نبضة يثبت المقصد نفسه: مشروع واحد باللحظة
        real_tick = engine.tick

        def slow_tick(project_id):
            started.set()
            release.wait(timeout=10)
            return real_tick(project_id)

        engine.tick = slow_tick  # type: ignore[method-assign]
        return engine

    def _create(pid_name):
        out = client.post("/api/projects", json={
            "name": pid_name, "objective": "هدف اختبار تزامن",
        })
        pid = out.json()["id"]
        assert client.post(
            f"/api/projects/{pid}/plan/generate").status_code == 200
        # (013.4 §1) التوليد خلفي — أكمل الجلسة قبل الاعتماد
        from tests.api.planning_wait import wait_for_plan

        wait_for_plan(client, pid)
        return pid

    # المصنع البطيء أولًا — اعتماد pid1 يطلق حلقة بطيئة فورًا (013 §3)
    projects._test_engine_factory = slow_factory
    try:
        pid1 = _create("الأول")
        pid2 = _create("الثاني")
        thread = threading.Thread(
            target=lambda: TestClient(routes.app).post(
                f"/api/projects/{pid1}/plan/approve",
                json={"approved": True},
            ), daemon=True,
        )
        thread.start()
        assert started.wait(timeout=8), "الحلقة البطيئة لم تبدأ"
        # المشروع الثاني: الاعتماد لا يطلق (تعارض صادق) والبث يُرفض 409
        clash_approve = client.post(
            f"/api/projects/{pid2}/plan/approve", json={"approved": True}
        ).json()
        assert clash_approve["launch"]["launched"] is False
        assert clash_approve["launch"]["reason"] == "conflict"
        clash = client.post(f"/api/projects/{pid2}/run/stream")
        assert clash.status_code == 409
        listing = client.get("/api/projects").json()
        assert listing["active_run"] == pid1
    finally:
        release.set()
        thread.join(timeout=10)
        projects._test_engine_factory = original
