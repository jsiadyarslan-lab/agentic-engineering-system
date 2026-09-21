"""اختبارات المحادثة الحية (الأمر 006 §2 + الأمر 008 §2-§6).

العقد الموحد (008 §17): message_started ← chat.status(generating) ←
message_delta* (قطع فعلية) ← message_completed — حفظ الرسائل، ولا
mock fallback أبدًا؛ تعذر المزود = chat.error بـ CONFIGURATION_REQUIRED.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("httpx", reason="TestClient يتطلب httpx")

from api import routes  # noqa: E402
from conftest import sse_events  # noqa: E402


@pytest.fixture()
def client(api_env):
    return TestClient(routes.app)


def test_chat_creates_conversation_and_streams_reply(client, api_env):
    """رسالة واحدة ← محادثة جديدة + رد حي بالنموذج المحدد + حفظ الرسالتين."""
    resp = client.post("/api/chat/stream", json={
        "message": "ما أسرع طريقة لتعلم البرمجة؟",
        "provider": "zai-test",
        "model": "glm-test-4.6",
    })
    assert resp.status_code == 200, resp.text[:300]
    events = sse_events(resp)

    started = [e for e in events if e["kind"] == "message_started"]
    deltas = [e for e in events if e["kind"] == "message_delta"]
    done = [e for e in events if e["kind"] == "message_completed"]
    statuses = [e for e in events if e["kind"] == "chat.status"]
    errors = [e for e in events if e["kind"] == "chat.error"]
    assert started and len(done) == 1 and not errors, [
        e.get("kind") for e in events
    ]

    # الحالة الحية صادقة (008 §31): connecting ثم generating قبل القطع
    assert started[0]["status"] == "connecting"
    assert [s["status"] for s in statuses][:1] == ["generating"]

    # الاستدعاء وصل فعليًا بالنموذج المحدد — إثبات التمرير الصريح
    assert api_env["router"].chat_calls, "لم يصل أي استدعاء محادثة للموجّه"
    assert api_env["router"].chat_calls[-1] == {
        "provider": "zai-test", "model": "glm-test-4.6"
    }

    conversation_id = started[0]["details"]["conversation_id"]
    assert done[0]["details"]["provider"] == "zai-test"
    assert done[0]["details"]["model"] == "glm-test-4.6"
    assert done[0]["details"]["conversation_id"] == conversation_id
    assert done[0]["details"]["streamed"] is True
    assert started[0]["message_id"] == done[0]["message_id"]

    # بث حقيقي (008 §3): قطع متعددة يتجمع نصها في الرد الكامل
    streamed = "".join(d["delta"] for d in deltas)
    assert streamed.strip() and len(deltas) >= 2

    # المحادثة حقيقية: الرسالتان (المستخدم والمساعد) محفوظتان
    history = client.get(f"/api/conversations/{conversation_id}/messages")
    assert history.status_code == 200
    roles_saved = [m["role"] for m in history.json()["messages"]]
    assert roles_saved == ["user", "assistant"]


def test_chat_continues_existing_conversation_with_history(client, api_env):
    """رسالة ثانية في المحادثة نفسها — التاريخ يُبنى من الرسائل المحفوظة."""
    first = sse_events(client.post("/api/chat/stream", json={
        "message": "سؤال أول",
    }))
    started = [e for e in first if e["kind"] == "message_started"]
    conversation_id = started[0]["details"]["conversation_id"]

    second = sse_events(client.post("/api/chat/stream", json={
        "message": "سؤال ثانٍ",
        "conversation_id": conversation_id,
    }))
    assert [e["kind"] for e in second].count("message_completed") == 1

    history = client.get(
        f"/api/conversations/{conversation_id}/messages"
    ).json()["messages"]
    assert [m["role"] for m in history] == [
        "user", "assistant", "user", "assistant"
    ]
    assert history[0]["content"] == "سؤال أول"
    assert history[2]["content"] == "سؤال ثانٍ"


def test_chat_unknown_conversation_404(client, api_env):
    resp = client.post("/api/chat/stream", json={
        "message": "رسالة", "conversation_id": 9999,
    })
    assert resp.status_code == 404
    assert "غير معروفة" in resp.json()["detail"]


def test_chat_no_mock_fallback_when_provider_unavailable(
    client, api_env, monkeypatch
):
    """لا سقوط إلى mock أبدًا (§15 Chat): مزود غير متاح = خطأ صريح."""
    api_env["router"]._providers = {"nvidia"}  # zai-test غير متاح الآن

    events = sse_events(client.post("/api/chat/stream", json={
        "message": "رسالة بمزود غائب",
        "provider": "zai-test",
        "model": "glm-test-4.6",
    }))
    errors = [e for e in events if e["kind"] == "chat.error"]
    assert errors, [e.get("kind") for e in events]
    assert errors[0]["code"] == "CONFIGURATION_REQUIRED"
    assert "zai-test" in errors[0]["text"]
    # لا استدعاء حي حدث — ولا نجاح وهمي
    assert not api_env["router"].chat_calls


def test_chat_router_failure_is_error_not_silence(client, api_env):
    """فشل الاستدعاء الحي = chat.error صريح بالسبب — لا صمت ولا وهم."""
    def broken_chat_live(messages, **_kwargs):
        raise RuntimeError("انقطاع شبكة مفاجئ")

    api_env["router"].chat_live = broken_chat_live
    events = sse_events(client.post("/api/chat/stream", json={
        "message": "رسالة ستفشل",
    }))
    errors = [e for e in events if e["kind"] == "chat.error"]
    assert errors
    assert "انقطاع شبكة" in errors[0]["text"]
