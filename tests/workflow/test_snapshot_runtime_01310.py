"""اختبارات endpoint حالة المشروع (013.10 §4) — إغلاق PD-3.

العقد الحرفي من الأمر: GET /api/projects/{id}/runtime يعيد HTTP 200
صحيحة في الحالتين الطبيعيتين — قبل وجود تنفيذ وبعد تسجيل تنفيذ
فعلي — والبيانات المعروضة من المخزن لا mock. وأخطاء القراءة
الحقيقية تُصنّف بصدق (لا لقطة ناجحة مصطنعة).

الجذر (PD-3): current_execution_id عمود في Step لا Project،
وsession.get يعيد كائن ORM لا قاموسًا — الكود القديم كان يقرأ
project.get("current_execution_id") فيرفع AttributeError ويعطل
المسار كله بـHTTP 500 (دليل: 6 اختبارات snapshot كانت حمراء
على رأس 013.9).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from api import routes  # noqa: E402
from persistence.database import (  # noqa: E402
    build_engine, init_db, make_session_factory,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """عميل API حقيقي على قاعدة معزولة — لا mock في المسار."""
    engine = build_engine(tmp_path / "runtime-01310.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    monkeypatch.setattr(routes, "_sessions", sessions)
    monkeypatch.chdir(tmp_path)
    yield TestClient(routes.app), sessions


def _make_project(client) -> dict:
    response = client[0].post("/api/projects", json={
        "name": "مشروع حالة التشغيل 013.10",
        "objective": "إثبات endpoint حالة المشروع بلا انهيار",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _seed_running_execution(sessions, project_id: int) -> dict:
    """بذر خطوة جارية وتنفيذ أمر حقيقي — نفس سلسلة الكتابة في
    engine (update_step current_execution_id + current_step_id)."""
    import datetime as _dt

    from workflow.models import Execution, Project, Step

    with sessions() as session:
        step = Step(
            phase_id=0, ordinal=1, objective="خطوة تنفيذ أمر حقيقي",
            status="RUNNING", attempts=1,
        )
        session.add(step)
        session.flush()
        execution = Execution(
            step_id=step.id, attempt=1, status="RUNNING",
            agent_role="implementer",
            command="python -c \"print('real')\"",
            command_type="step_execution",
            cwd="C:/work/ws", pid=4321, parent_pid=4000,
        )
        session.add(execution)
        session.flush()
        step.current_execution_id = execution.id
        project = session.get(Project, int(project_id))
        project.current_step_id = step.id
        project.status = "RUNNING"
        project.updated_at = _dt.datetime.now(_dt.timezone.utc)
        session.commit()
        return {"step_id": step.id, "execution_id": execution.id}


# ------------------------------------------------------------------ #
# الحالة 1: مشروع موجود بلا تنفيذ جارٍ ← 200 وexecution فارغة
# ------------------------------------------------------------------ #

def test_runtime_endpoint_200_before_any_execution(client):
    http, sessions = client
    project = _make_project(client)
    response = http.get(f"/api/projects/{project['id']}/runtime")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project_id"] == project["id"]
    assert body["status"] == project["status"]
    assert body["execution"] is None
    # عقد اللقطة كامل — لا حقل غائب يضطر الواجهة للاشتقاق
    for field in ("stage", "progress", "waiting_for", "environment",
                  "available_actions", "recent_events"):
        assert field in body, f"حقل العقد مفقود: {field}"


# ------------------------------------------------------------------ #
# الحالة 2: current_execution_id صالح وسجل تنفيذ موجود ← 200 والبيانات
#           من المخزن (نفس القيم المدخلة حرفيًا)
# ------------------------------------------------------------------ #

def test_runtime_endpoint_200_with_live_execution(client):
    http, sessions = client
    project = _make_project(client)
    seeded = _seed_running_execution(sessions, project["id"])

    response = http.get(f"/api/projects/{project['id']}/runtime")
    assert response.status_code == 200, response.text
    body = response.json()
    execution = body["execution"]
    assert execution is not None, "تنفيذ جارٍ مخزَّن لم يظهر في اللقطة"
    assert execution["id"] == seeded["execution_id"]
    assert execution["step_id"] == seeded["step_id"]
    assert execution["status"] == "RUNNING"
    assert execution["command"] == "python -c \"print('real')\""
    assert execution["command_type"] == "step_execution"
    assert execution["cwd"] == "C:/work/ws"
    assert execution["pid"] == 4321
    assert execution["parent_pid"] == 4000
    assert execution["agent_role"] == "implementer"


# ------------------------------------------------------------------ #
# الحالة 3: معرّف غير موجود ← فشل مصنّف بصدق (404 عبر KeyError)
# ------------------------------------------------------------------ #

def test_runtime_endpoint_unknown_project_is_honest_404(client):
    http, _sessions = client
    response = http.get("/api/projects/999999/runtime")
    assert response.status_code == 404, (
        "مشروع غير موجود أعيد 200 وهميًا — كذب لقطة"
    )
    assert "مشروع غير معروف" in response.text


def test_runtime_endpoint_invalid_project_id_rejected(client):
    http, _sessions = client
    response = http.get("/api/projects/not-an-int/runtime")
    assert response.status_code in (404, 422), response.text


# ------------------------------------------------------------------ #
# الحالة 4: فشل قراءة حقيقي يُرفع كما هو — لا لقطة ناجحة مصطنعة
# ------------------------------------------------------------------ #

def test_real_read_failure_propagates_not_fake_snapshot(
        client, monkeypatch):
    http, sessions = client
    project = _make_project(client)

    from workflow import service as workflow_service
    from workflow.snapshot import runtime_snapshot

    def broken_read(_sessions, _project_id):
        raise RuntimeError("فشل قراءة حقيقي مضبوط للاختبار")

    monkeypatch.setattr(workflow_service, "get_project", broken_read)
    with pytest.raises(RuntimeError):
        runtime_snapshot(sessions, project["id"])


# ------------------------------------------------------------------ #
# سلسلة القراءة القانونية نفسها (Project ← Step ← Execution) —
# مشروع بلا current_step_id لا يخترع تنفيذًا
# ------------------------------------------------------------------ #

def test_no_current_step_means_no_execution(client):
    http, sessions = client
    project = _make_project(client)
    from workflow.snapshot import runtime_snapshot

    snap = runtime_snapshot(sessions, project["id"])
    assert snap["execution"] is None
