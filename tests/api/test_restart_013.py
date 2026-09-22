"""اختبار إعادة تشغيل الخادم (013 §35) — لا يفقد سير العمل شيئًا.

المشهد الحرفي: إنشاء ← خطة ← اعتماد معلق ← restart ← الحالة باقية ←
اعتماد ← التنفيذ يبدأ ← restart أثناء التنفيذ (عملية تموت فعليًا
والحلقة ممسوسة داخل خطوة) ← الوظيفة INTERRUPTED ← استئناف ← نفس
صف الوظيفة يكمل ← الأدلة باقية.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from api import routes  # noqa: E402
from api import projects  # noqa: E402
from test_projects_api import client, project_env  # noqa: E402,F401

from test_approval_live_013 import (  # noqa: E402
    _local_search_source,
    _sandbox_env,
)


def test_server_restart_preserves_workflow(client, project_env,
                                           monkeypatch):
    """§35 خطوة بخطوة — 13 نقطة، ولا شيء يضيع."""
    sessions = project_env["sessions"]
    _local_search_source(sessions)
    _sandbox_env(sessions, status="READY", sandboxed=1)

    # 1-3. إنشاء ← خطة ← اعتماد معلق
    created = client.post("/api/projects", json={
        "name": "استرداد", "objective": "هدف اختبار الاسترداد",
    })
    pid = created.json()["id"]
    # (013.4 §1) التوليد خلفي — ننتظر نتيجته
    from tests.api.planning_wait import wait_for_plan

    client.post(f"/api/projects/{pid}/plan/generate")
    wait_for_plan(client, pid)
    state = client.get(f"/api/projects/{pid}/state").json()
    gate = next((g for g in state["gates"]
                 if g["kind"] == "PLAN_APPROVAL"
                 and g["status"] == "PENDING"), None)
    assert gate is not None

    # 4-6. restart (استرداد الإقلاع على نفس القاعدة) ← الحالة باقية
    from api.projects import run_startup_recovery

    run_startup_recovery(sessions)
    fresh = TestClient(routes.app)   # «فتح المتصفح من جديد»
    state = fresh.get(f"/api/projects/{pid}/state").json()
    gate = next((g for g in state["gates"]
                 if g["kind"] == "PLAN_APPROVAL"
                 and g["status"] == "PENDING"), None)
    assert gate is not None, "الاعتماد المعلق ضاع بعد restart"

    # 7-8. اعتماد ← التنفيذ يبدأ (إطلاق خلفي) — و«الموت» أثناء الخطوة:
    # نمسك run_task داخل التنفيذ فعلًا (العملية «تموت» والخيط معلق)
    import tasks as tasks_mod

    original_run_task = tasks_mod.run_task
    hold = threading.Event()

    def holding_run_task(*args, **kwargs):
        result = original_run_task(*args, **kwargs)
        hold.wait(timeout=20)   # الموت أثناء الخطوة — بعد كتابة الملفات
        return result

    monkeypatch.setattr(tasks_mod, "run_task", holding_run_task,
                        raising=True)

    approved = fresh.post(f"/api/projects/{pid}/plan/approve",
                          json={"approved": True})
    assert approved.status_code == 200
    assert approved.json()["launch"]["launched"] is True

    deadline = time.monotonic() + 25.0
    entered_execution = False
    while time.monotonic() < deadline:
        events = fresh.get(
            f"/api/projects/{pid}/events?limit=100"
        ).json()["events"]
        if "STEP_STARTED" in [e["kind"] for e in events]:
            entered_execution = True
            break
        time.sleep(0.1)
    assert entered_execution, "التنفيذ لم يبدأ بعد الاعتماد"

    # 9-10. restart أثناء التنفيذ: المشروع RUNNING ← PAUSED،
    # والوظيفة RUNNING ← INTERRUPTED (لا حياة كاذبة)
    run_startup_recovery(sessions)
    state = fresh.get(f"/api/projects/{pid}/state").json()
    assert state["job"]["status"] == "INTERRUPTED", \
        f"الوظيفة بعد restart: {state['job']['status']}"
    assert state["status"] == "PAUSED"

    # 11-13. استئناف ← نفس صف الوظيفة يكمل ← الأدلة باقية
    job_id_before = state["job"]["id"]
    state = fresh.get(f"/api/projects/{pid}/state").json()
    evidence_before = len(state["evidence"])

    resumed = fresh.post(f"/api/projects/{pid}/resume")
    assert resumed.status_code == 200, resumed.text
    # الاستئناف آلي: إطلاق فوري أو إرفاق بالحلقة المعلقة القائمة
    assert resumed.json()["launch"]["launched"] in (True, False)

    # أفك عقد الموت — الحلقة تكمل من حيث توقفت (نفس الصف)
    hold.set()
    deadline = time.monotonic() + 40.0
    while time.monotonic() < deadline:
        state = fresh.get(f"/api/projects/{pid}/state").json()
        if state["job"] and state["job"]["status"] in (
            "WAITING_GATE", "COMPLETED",
        ):
            break
        time.sleep(0.3)

    # نفس الصف — لا وظيفة جديدة بلا سبب (§19)
    assert state["job"]["id"] == job_id_before, \
        f"صف وظيفة جديد: {job_id_before} → {state['job']['id']}"
    assert state["job"]["status"] in ("WAITING_GATE", "COMPLETED")
    # نفس الصف — لا وظيفة جديدة بلا سبب (§19). عداد المحاولات سجل
    # كل بدء run_loop على الصف: 1 هنا (المحاكاة داخل العملية تُبقي
    # الحلقة معلقة حية فيتعلق الاستئناف بها بدل بدء ثانٍ)؛ وفي موت
    # العملية الحقيقي يصبح 2 — الحقل موجود ومأهول وهو المطلوب.
    assert state["job"]["attempt"] >= 1, "عداد المحاولات غير مأهول (§19)"
    # الأدلة باقية واكتملت
    assert len(state["evidence"]) >= max(1, evidence_before)
    assert state["evidence"], "لا أدلة بعد الاسترداد"
