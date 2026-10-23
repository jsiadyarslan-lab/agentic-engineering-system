"""اختبارات انعدام تجويع المنفّذات المشتركة (AES-EXP-04 §6).

العقد المطلوب: فشل طلب منفرد أو انتهاء مهلته لا يحتجز المنفّذ المشترك
ولا يمنع طلبًا لاحقًا صالحًا. يثبت على المنفّذين اثنين:

1. منفّذ المحادثة (v2-chat): فشل محادثة واحدة (بمزود يفشل مرة) لا يمنع
   محادثة لاحقة ناجحة — الخيط يتحرر عند الفشل لا بعد مهلة كلية.
2. خيط حلقات سير العمل (aes-workflow-run — خيط وحيد): مهمة محجوبة
   بالفحص المسبق (مسبارات حقيقية سريعة الفشل على مضيف بلا خروج) تنهي
   نفسها بحد إعادة الفحص المعلن فلا تحجز خيط الحلقات للأبد — والمهمة
   التالية تكتمل.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from api import routes  # noqa: E402
from conftest import sse_events  # noqa: E402
from test_projects_api import client, project_env  # noqa: E402,F401


@pytest.fixture()
def chat_client(api_env):
    return TestClient(routes.app)


def test_chat_single_failure_does_not_starve_executor(
    chat_client, api_env, monkeypatch
):
    """(§6) فشل محادثة منفرد لا يحتجز منفّذ المحادثة المشترك."""
    router = api_env["router"]
    original_stream = router.chat_live_stream
    state = {"failed": False}

    def failing_stream(messages, *, provider_id=None, model=None,
                       on_delta=None, **kw):
        if not state["failed"]:
            state["failed"] = True
            raise RuntimeError("فشل مزود محاكى للاختبار (مرة واحدة)")
        return original_stream(
            messages, provider_id=provider_id, model=model,
            on_delta=on_delta, **kw
        )

    monkeypatch.setattr(router, "chat_live_stream", failing_stream)

    started = time.monotonic()
    first = chat_client.post("/api/chat/stream", json={
        "message": "رسالة تفشل مرة واحدة", "provider": "zai-test",
        "model": "glm-test",
    })
    assert first.status_code == 200, first.text[:200]
    events = sse_events(first)
    assert any(e.get("kind") == "chat.error" for e in events), (
        [e.get("kind") for e in events]
    )

    # المحادثة التالية على نفس المنفّذ تنجح — لا تجويع بعد الفشل
    second = chat_client.post("/api/chat/stream", json={
        "message": "رسالة تلي الفشل مباشرة", "provider": "zai-test",
        "model": "glm-test",
    })
    assert second.status_code == 200, second.text[:200]
    events2 = sse_events(second)
    assert any(e.get("kind") == "message_completed" for e in events2), (
        [e.get("kind") for e in events2]
    )
    assert state["failed"] is True and router.chat_calls, (
        "النداء الثاني لم يصل للموجّه — المنفّذ محتجز"
    )
    assert time.monotonic() - started < 40, (
        "دورة فشل ثم نجاح استغرقت زمنًا يدل على احتجاز المنفّذ"
    )


def test_preflight_blocked_run_terminates_and_releases_runner(
    client, project_env, monkeypatch
):
    """(§6) مهمة محجوبة بالفحص المسبق تنتهي بحد معلن ويُحرَّر الخيط.

    محرك بلا حقن مسبارات + AES_PROBE_TIMEOUT_S قصيرة = حجب صادق سريع؛
    حد إعادة الفحص ينهي الوظيفة بفشل مسمّى بدل حلقة مفتوحة. المهمة
    التالية (بحقن الـfixture القياسي) تكتمل — دليل تحرر الخيط.
    """
    from api import projects as projects_mod
    from tests.api.planning_wait import wait_for_plan
    from workflow import runner as wf_runner

    sessions = project_env["sessions"]
    real_factory = projects_mod._test_engine_factory

    def no_injection_factory(on_event=None, **_kw):
        engine = real_factory(on_event=on_event)
        engine._probe_injections = None  # المسبارات الحقيقية حصرًا
        return engine

    monkeypatch.setattr(
        projects_mod, "_test_engine_factory", no_injection_factory
    )
    created = client.post("/api/projects", json={
        "name": "محجوبة شبكيًا", "objective": "هدف اختبار الحجب المحدود",
    })
    pid = created.json()["id"]
    client.post(f"/api/projects/{pid}/plan/generate")
    wait_for_plan(client, pid)
    approved = client.post(f"/api/projects/{pid}/plan/approve",
                           json={"approved": True})
    assert approved.status_code == 200

    # الحجب الصادق يصل ثم الوظيفة تنتهي بالسقف الزمني الحائط (120ث
    # افتراضيًا) — لا انتظار مفتوح ولا احتجاز دائم للخيط الوحيد
    deadline = time.monotonic() + 220.0
    released = False
    while time.monotonic() < deadline:
        if wf_runner.active_run(sessions) is None:
            released = True
            break
        time.sleep(0.2)
    assert released, (
        "خيط الحلقات ما زال محتجزًا بالمهمة المحجوبة — حد إعادة الفحص "
        "لم يعمل"
    )
    blocked_seen = client.get(f"/api/projects/{pid}").json()
    assert blocked_seen.get("status") in ("BLOCKED", "FAILED"), (
        f"حالة المشروع المحجوب غير صادقة: {blocked_seen.get('status')}"
    )

    # الخيط المحرر: مهمة تالية بالحقن القياسي تكتمل
    monkeypatch.setattr(projects_mod, "_test_engine_factory", real_factory)
    created2 = client.post("/api/projects", json={
        "name": "تلي المحجوبة", "objective": "هدف ينجح بعد تحرر الخيط",
    })
    pid2 = created2.json()["id"]
    client.post(f"/api/projects/{pid2}/plan/generate")
    wait_for_plan(client, pid2)
    approved2 = client.post(f"/api/projects/{pid2}/plan/approve",
                            json={"approved": True})
    assert approved2.status_code == 200
    deadline = time.monotonic() + 120.0
    final_status = ""
    while time.monotonic() < deadline:
        detail = client.get(f"/api/projects/{pid2}").json()
        final_status = str(detail.get("status", ""))
        if final_status in ("COMPLETED", "VERIFIED"):
            break
        if wf_runner.active_run(sessions) is None and final_status in (
            "FAILED", "BLOCKED"
        ):
            break
        time.sleep(0.3)
    assert final_status in ("COMPLETED", "VERIFIED"), (
        f"المهمة التالية لم تكتمل — خيط الحلقات ما زال محتجزًا "
        f"(الحالة: {final_status})"
    )
