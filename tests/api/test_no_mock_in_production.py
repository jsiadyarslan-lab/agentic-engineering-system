"""حارس العودة للديمو (الأمر 006 §16) — لا يمكن الرجوع إلى mock بالخطأ.

طبقتا دفاع دائمتان:
1) فحص المصدر: مسار الإنتاج (api/routes.py) لا يستورد ولا يستدعي
   build_mock_orchestrator إطلاقًا.
2) فحص التشغيل: لو استُدعيت مصنع الـmock لأي سبب أثناء خدمة طلب
   إنتاجي — يفشل الاختبار فورًا (monkeypatch يجعلها تنفجر).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("httpx", reason="TestClient يتطلب httpx")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from api import routes  # noqa: E402
from conftest import sse_events  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
ROUTES_SOURCE = REPO / "src" / "api" / "routes.py"
TASKS_SOURCE = REPO / "src" / "tasks.py"


def test_production_route_source_never_references_mock_factory():
    """فحص المصدر: لا build_mock_orchestrator في مسار الإنتاج أبدًا."""
    for source in (ROUTES_SOURCE, TASKS_SOURCE):
        text = source.read_text(encoding="utf-8")
        assert "build_mock_orchestrator" not in text, (
            f"{source.name} يشير إلى مصنع الـmock — ممنوع في الإنتاج (§12)"
        )
        assert "from core.wiring import" not in text or "mock" not in (
            text.split("from core.wiring import")[1].split("\n")[0]
        )


def test_mock_roles_remain_for_test_wiring_only():
    """الأدوار الحتمية باقية عمدًا — لكن التركيب الحي وحده في الإنتاج."""
    wiring = (REPO / "src" / "core" / "wiring.py").read_text(encoding="utf-8")
    assert "def build_mock_orchestrator" in wiring, (
        "أدوار الاختبار الحتمية يجب أن تبقى (§12 — لا حذف للاختبارات)"
    )
    assert "TEST WIRING ONLY" in wiring


def test_live_task_never_calls_mock_factory(client, api_env, monkeypatch):
    """فحص التشغيل: مصنع الـmock المفخخ لا يُستدعى خلال مهمة إنتاجية."""
    import core.wiring as wiring

    def mock_factory_must_never_run(*_args, **_kwargs):
        raise AssertionError(
            "مصنع الـmock استُدعي من مسار إنتاجي — عودة للديمو ممنوعة (§16)"
        )

    monkeypatch.setattr(
        wiring, "build_mock_orchestrator", mock_factory_must_never_run
    )
    # المهمة تعمل عبر المسار الحي — أي استدعاء mock يفجر الاختبار
    resp = client.post("/api/cycle/stream", json={
        "goal": "مهمة تحت مراقبة حارس الديمو",
    })
    assert resp.status_code == 200
    events = sse_events(resp)
    done = [e for e in events if e["kind"] == "task_done"]
    assert done, [e.get("kind") for e in events]
    assert api_env["router"].calls, "الأدوار الحية استُدعيت فعليًا"


def test_live_chat_never_calls_mock_factory(client, api_env, monkeypatch):
    """فحص التشغيل: المحادثة كذلك — لا مسار إنتاجي يمر من mock."""
    import core.wiring as wiring

    def mock_factory_must_never_run(*_args, **_kwargs):
        raise AssertionError("مصنع الـmock استُدعي من مسار محادثة (§16)")

    monkeypatch.setattr(
        wiring, "build_mock_orchestrator", mock_factory_must_never_run
    )
    resp = client.post("/api/chat/stream", json={"message": "مرحبا"})
    assert resp.status_code == 200
    events = sse_events(resp)
    assert [e["kind"] for e in events].count("message_completed") == 1
    assert api_env["router"].chat_calls


@pytest.fixture()
def client(api_env):
    return TestClient(routes.app)
