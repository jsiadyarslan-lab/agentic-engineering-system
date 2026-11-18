"""اختبارات API الأمر 011 — إعادة الفحص والسياسة وبوابة التنفيذ وتيار
الأحداث وحقيقة المضيف (§3+§19+§21+§24-§26).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from api import routes  # noqa: E402
from sqlalchemy import select as sa_select  # noqa: E402

from execution.models import ExecutionEnvironment  # noqa: E402
from workflow import service as workflow_service  # noqa: E402


# نفس بيئة اختبارات المشاريع (007) — محرك مخطط + منفذ منظم عبر
# الخطاف الصريح _test_engine_factory؛ الاستيراد يجعل الـfixture مشتركًا.
from test_projects_api import (  # noqa: E402,F401
    FakeRouter, project_env,
)
from tests.api.test_projects_api import ScriptedPlanner  # noqa: E402,F401


@pytest.fixture()
def client(project_env):
    return TestClient(routes.app)


@pytest.fixture()
def sessions(project_env):
    return project_env["sessions"]


def _sandbox_env(sessions, *, status, sandboxed):
    from execution import service as execution_service

    execution_service.ensure_local_registered(sessions)
    with sessions() as s:
        row = s.scalars(sa_select(ExecutionEnvironment).where(
            ExecutionEnvironment.name.in_(("local-linux",
                                           "local-windows")))).first()
        row.status = status
        row.sandboxed = sandboxed
        s.commit()
        return row.id


@pytest.fixture()
def probe_seam(monkeypatch):
    """وصفة مسبار sandbox من المصدر (سجل البيئات) — لا إقلاع ركيزة
    فعلي هنا (له اختباراته الخاصة)؛ حتمية عبر المنصات."""
    from execution import service as execution_service

    def fake_sandbox_probe(sessions_, **_kwargs):
        environments = execution_service.list_environments(sessions_)
        ready = [
            e for e in environments
            if e["status"] == "READY" and e.get("sandboxed")
        ]
        return {
            "status": "READY" if ready else "NOT_READY",
            "reason": "بيئة معزولة جاهزة (وصفة)" if ready
            else "لا بيئة تنفيذ معزولة جاهزة (وصفة)",
            "latency_ms": 1, "ttl_seconds": 300,
            "failure_class": "" if ready else "SANDBOX_FAILURE",
            "failure_stage": "" if ready else "STARTUP",
            "details": {"test_seam": True},
        }

    monkeypatch.setattr(
        execution_service, "sandbox_probe_result", fake_sandbox_probe
    )


def _approved_project(client):
    """إنشاء ← توليد ← اعتماد (عبر مسار الاعتماد الرسمي كما في 007)."""
    out = client.post("/api/projects", json={
        "name": "مشروع 011", "objective": "هدف اختبار بوابة التنفيذ",
    })
    assert out.status_code == 201, out.text
    pid = out.json()["id"]
    assert client.post(f"/api/projects/{pid}/plan/generate").status_code == 200
    from tests.api.planning_wait import wait_for_plan

    wait_for_plan(client, pid)
    approved = client.post(f"/api/projects/{pid}/plan/approve",
                           json={"approved": True})
    assert approved.status_code == 200, approved.text
    return pid


# ------------------------------------------------------------------ #
# §3 — بوابة التنفيذ في تفصيل المشروع: النص الصادق لا الغامض
# ------------------------------------------------------------------ #

def test_project_detail_carries_execution_gate(client, sessions,
                                                probe_seam):
    pid = _approved_project(client)
    _sandbox_env(sessions, status="NOT_READY", sandboxed=0)
    # شغّل → الفحص يحجب (لا بيئة معزولة) → BLOCKED ببوابة توفير
    out = client.post(f"/api/projects/{pid}/preflight")
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["preflight"]["verdict"] == "BLOCKED"
    gate = body["execution_gate"]
    assert gate["state"] == "APPROVED_BUT_BLOCKED"
    assert gate["open_for_execution"] is False
    assert "معزولة" in gate["required"] or "Linux" in gate["required"]
    assert "إعادة الفحص" in gate["owner_action"]
    # لا تسمية غامضة في أي مخرج
    dumped = str(body)
    assert "ليست مفتوحة" not in dumped


@pytest.mark.parametrize("event_format", ["legacy", "matrix", "no_detail"])
def test_snapshot_preserves_recorded_capability_blocker(
        client, sessions, event_format):
    """Read a blocked snapshot without launching or changing the project."""
    svc = workflow_service
    pid = svc.create_project(
        sessions, name="اختبار لقطة الحجب", objective="إنشاء هيكل موقع",
        execution_policy="COMPATIBLE_LOCAL")["id"]
    plan = svc.create_plan(sessions, pid, {"phases": [{
        "title": "إعداد الهيكل", "steps": [{"objective": "إنشاء الهيكل"}],
    }]})
    svc.approve_plan(sessions, plan["id"])
    svc.materialize_plan(sessions, plan)
    phase = svc.list_phases(sessions, pid)[0]
    step = svc.phase_steps(sessions, phase["id"])[0]
    svc.update_phase(sessions, phase["id"], status="RUNNING")
    svc.update_project(sessions, pid, status="BLOCKED",
                       current_step_id=step["id"], current_phase_id=phase["id"])
    _sandbox_env(sessions, status="READY", sandboxed=0)
    execution_id = svc.create_execution(
        sessions, step["id"], attempt=2, provider="test", model="test",
        workspace="test-only")
    svc.update_execution(sessions, execution_id, status="FAILED")
    blocker = {"capability_id": "web_search", "status": "STALE",
               "reason": "انتهت صلاحية فحص مزوّد البحث"}
    if event_format == "legacy":
        gate_id = svc.open_gate(
            sessions, pid, "PREFLIGHT_BLOCKED", "تعطّل البحث",
            {"blocked": [blocker], "execution_id": execution_id},
            status="BLOCKED")
        payload = {"gate_id": gate_id, "step_id": step["id"],
                   "capability_id": "web_search", "status": "STALE"}
    elif event_format == "matrix":
        payload = {"blocked": [blocker], "verdict": "BLOCKED",
                   "step_id": step["id"], "execution_id": execution_id}
    else:
        payload = {}
    svc.add_event(sessions, pid, "PREFLIGHT_PASS", {"verdict": "PASS"})
    svc.add_event(sessions, pid, "PREFLIGHT_BLOCKED", payload)
    # Activity after the blocker must not evict it from the projection.
    for _ in range(55):
        svc.add_event(sessions, pid, "JOB_HEARTBEAT", {})

    response = client.get(f"/api/projects/{pid}/state")
    assert response.status_code == 200, response.text
    snap = response.json()
    gate = snap["execution_gate"]
    assert snap["status"] == "BLOCKED"
    assert snap["active_run"] is None
    assert snap["phases"][0]["status"] == "RUNNING"  # Historical truth.
    assert snap["evidence"] == []
    assert snap["environment"]["selected"]["name"] in (
        "local-linux", "local-windows")
    assert snap["environment"]["satisfies_policy"] is True
    assert gate["state"] == "APPROVED_BUT_BLOCKED"
    assert gate["required"] == ""
    assert "إضافة بيئة" not in gate["owner_action"]
    if event_format == "no_detail":
        assert gate["blockers"] == []
        assert gate["reason"] == "سُجّل حجب دون سبب محدد."
    else:
        assert gate["step_id"] == step["id"]
        assert gate["execution_id"] == execution_id
        assert "web_search: STALE" in gate["reason"]
        assert blocker["reason"] in gate["reason"]
        assert gate["blockers"][0]["capability_id"] == "web_search"
        assert "البحث" in gate["owner_action"]


def test_recheck_after_provisioning_opens_without_reapproval(
        client, sessions, probe_seam):
    """(§19) توفير ← إعادة فحص ← OPEN ← استئناف — بلا إعادة اعتماد."""
    pid = _approved_project(client)
    _sandbox_env(sessions, status="NOT_READY", sandboxed=1)
    blocked = client.post(f"/api/projects/{pid}/preflight").json()
    assert blocked["preflight"]["verdict"] == "BLOCKED"
    # المالك وفر العامل (البيئة المحلية تصبح جاهزة معزولة)
    with sessions() as s:
        row = s.scalars(sa_select(ExecutionEnvironment).where(
            ExecutionEnvironment.name.in_(("local-linux",
                                           "local-windows")))).first()
        row.status = "READY"
        s.commit()
    rechecked = client.post(f"/api/projects/{pid}/preflight")
    assert rechecked.status_code == 200
    body = rechecked.json()
    assert body["preflight"]["verdict"] == "PASS", body
    assert body["execution_gate"]["state"] == "OPEN"
    assert body["execution_gate"]["open_for_execution"] is True
    # الخطة ما زالت معتمدة — لا بوابة اعتماد جديدة
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["plan"]["approved_by_owner"] is True
    assert not [
        g for g in detail["gates"]
        if g["kind"] == "PLAN_APPROVAL" and g["status"] == "PENDING"
    ]
    # (013 §38) الاستئناف آلي الآن: إعادة الفحص الناجحة أطلقت الحلقة
    # نفسها — بلا إعادة اعتماد وبلا زر تشغيل إضافي. نثبت الإطلاق
    # ثم أن التنفيذ تحرك فعليًا (وظيفة بدأت / مشروع انتقل من BLOCKED).
    assert body["launch"]["launched"] is True, body.get("launch")
    import time as _time

    # الجوهر: الوظيفة تركت انتظار العامل وتحركت — أي حالة لاحقة
    # صادقة تثبت الاستئناف (مسابر الشبكة الحقيقية قد تحجب أحيانًا
    # تحت الحمل فتصل WAITING_CAPABILITY — انتقال صادق أيضًا).
    deadline = _time.monotonic() + 25.0
    moved = None
    while _time.monotonic() < deadline:
        job = client.get(f"/api/projects/{pid}/job").json()
        if job.get("status") not in (None, "WAITING_WORKER", "QUEUED"):
            moved = job["status"]
            break
        _time.sleep(0.15)
    assert moved in ("RUNNING", "WAITING_GATE", "COMPLETED", "RETRYING",
                     "WAITING_CAPABILITY", "PAUSED"), moved


# ------------------------------------------------------------------ #
# §26 — سياسة التنفيذ من الـAPI
# ------------------------------------------------------------------ #

def test_execution_policy_set_and_validate(client):
    pid = _approved_project(client)
    bad = client.post(f"/api/projects/{pid}/execution-policy",
                      json={"policy": "WHATEVER"})
    assert bad.status_code == 422
    good = client.post(f"/api/projects/{pid}/execution-policy",
                       json={"policy": "COMPATIBLE_LOCAL"})
    assert good.status_code == 200
    assert good.json()["execution_policy"] == "COMPATIBLE_LOCAL"
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["execution_policy"] == "COMPATIBLE_LOCAL"


def test_create_project_with_policy(client):
    out = client.post("/api/projects", json={
        "name": "متوافق منذ الولادة", "objective": "هدف بلا حساسية",
        "execution_policy": "COMPATIBLE_LOCAL",
    })
    assert out.status_code == 201
    assert out.json()["execution_policy"] == "COMPATIBLE_LOCAL"


# ------------------------------------------------------------------ #
# §21 — تيار الأحداث العام (SSE)
# ------------------------------------------------------------------ #

def test_projects_events_stream_registered(client):
    """التيار مسجل بالمسار والطريقة الصحيحين — التيار اللا نهائي لا
    يُستهلك كاملًا في TestClient (يُثبت حيًا في قبول المتصفح §31)."""
    schema = client.get("/openapi.json").json()
    path = schema["paths"].get("/api/projects/events/stream")
    assert path and "get" in path
    assert "after_id" in path["get"].get("parameters", [{}])[0].get(
        "name", "") or any(
        p.get("name") == "after_id" for p in path["get"]["parameters"]
    )


def test_events_stream_source_is_monotonic_after_id(client, sessions):
    """مصدر التيار (السجل الدائم) يعيد الأحدث من المعرف حصرًا بترتيب
    رتيب — لا إعادة إرسال القديم (روح 008 §19)."""
    pid = _approved_project(client)
    events = client.get(f"/api/projects/{pid}/events").json()["events"]
    assert events
    last_id = events[-1]["id"]
    from workflow import service as workflow_service

    newer = workflow_service.list_recent_events(sessions, last_id, 100)
    assert all(e["id"] > last_id for e in newer)
    # والأحداث عبر المشاريع كلها بترتيب معرف صاعد
    all_events = workflow_service.list_recent_events(sessions, 0, 500)
    ids = [e["id"] for e in all_events]
    assert ids == sorted(ids)
    assert len({e["project_id"] for e in all_events}) >= 1


# ------------------------------------------------------------------ #
# §24-§25 — حقيقة المضيف من الـruntime
# ------------------------------------------------------------------ #

def test_host_truth_endpoint(client):
    out = client.get("/api/execution/host-truth")
    assert out.status_code == 200
    body = out.json()
    assert body["host_platform"]  # Linux/x86_64 في هذه الحاوية
    assert body["runtime_truth"]["os"]
    assert body["runtime_truth"]["git"]
    assert body["isolation"] in ("SANDBOXED", "UNAVAILABLE")
    assert "policies" in body and len(body["policies"]) == 2
    assert "worker_command" in body


def test_environments_list_carries_isolation_and_host(client, sessions):
    _sandbox_env(sessions, status="READY", sandboxed=1)
    out = client.get("/api/execution/environments")
    assert out.status_code == 200
    env = out.json()["environments"][0]
    assert env["isolation"] in ("SANDBOXED", "NONE", "WORKER_DECLARED")
    assert env["host_platform"]


# ------------------------------------------------------------------ #
# §12 — مزودو البحث بحالتهم الموحدة من الـAPI
# ------------------------------------------------------------------ #

def test_research_providers_effective_status(client, sessions):
    out = client.get("/api/research/providers")
    assert out.status_code == 200
    providers = out.json()["providers"]
    assert providers
    for provider in providers:
        assert "effective_status" in provider
        assert provider["effective_status"] in (
            "READY", "STALE", "NOT_READY", "NOT_CONFIGURED",
            "UNKNOWN", "DISABLED",
        )
        assert "configured" in provider
