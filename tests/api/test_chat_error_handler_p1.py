"""اختبارات تراجع P1 (AES-EXP-03) — معالج أخطاء المحادثة لا ينهد.

الجذر الموثق في AES-EXP-01: ``streamed``/``partial`` كانا يُهيَّآن
بعد مسار البحث في الويب داخل ``run_chat_in_thread``، فأي فشل قبل
التهيئة (بناء الموجّه، البحث، قراءة السجل…) كان يُسقط معالج الفشل
نفسه بـ ``UnboundLocalError: partial`` — الخيط يموت صامتة بلا
chat.error والواجهة تعلق على «يكتب الآن…». هذه الاختبارات تثبت:

1. فشل ما قبل التهيئة ← chat.error مصنّف + رسالة فاشلة محفوظة.
2. فشل البث فقط ← تراجع معلن (stream_fallback) ثم إكمال صحيح.
3. فشل بعد بث جزئي ← المحفوظ يحمل الجزئي والخطأ معًا (لا تختفي إجابة).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from api import routes  # noqa: E402
from conftest import sse_events  # noqa: E402


@pytest.fixture()
def client(api_env):
    return TestClient(routes.app)


def _kinds(events):
    return [e.get("kind") for e in events]


def _last_assistant(client, conversation_id):
    rows = client.get(
        f"/api/conversations/{conversation_id}/messages").json()
    messages = rows if isinstance(rows, list) else rows.get("messages", [])
    assistants = [m for m in messages if m.get("role") == "assistant"]
    return assistants[-1] if assistants else None


def test_failure_before_partial_init_yields_chat_error(
        client, api_env, monkeypatch):
    """فشل المزود قبل تهيئة partial ← chat.error سليم لا انهيار ثانوي.

    قبل الإصلاح: هذا السيناريو كان يقتل خيط المحادثة بـ
    UnboundLocalError: partial — بلا أي chat.error في البث.
    """
    from router.model_router import ProviderCallError

    def broken_factory(**_kwargs):
        raise ProviderCallError(
            "المزود غير متاح — محاكاة فشل ما قبل تهيئة partial")

    monkeypatch.setattr(routes, "_build_live_router", broken_factory)
    resp = client.post("/api/chat/stream", json={
        "message": "سؤال تجريبي لفشل مبكر",
        "provider": "zai-test", "model": "glm-test-4.6",
    })
    assert resp.status_code == 200
    events = sse_events(resp)
    errors = [e for e in events if e.get("kind") == "chat.error"]
    assert errors, f"لا chat.error في البث: {_kinds(events)}"
    error = errors[0]
    assert error["details"].get("conversation_id"), error
    # رسالة فاشلة محفوظة — السجل متسق لا صامت (لا نجاح وهمي أيضًا)
    saved = _last_assistant(client, error["details"]["conversation_id"])
    assert saved is not None
    assert "فشل" in (saved.get("content") or "") or saved.get("state_badge") in (
        "FAILED", "PARTIAL")
    assert saved.get("state_badge") != "COMPLETED"


def test_stream_only_failure_falls_back_declared(client, api_env):
    """فشل البث المتدفق فقط ← تراجع معلن ثم message_completed صحيح."""
    from router.model_router import ProviderCallError

    router = api_env["router"]

    def broken_stream(messages, *, on_delta=None, **_kw):
        raise ProviderCallError("النقل المتدفق غير مدعوم — محاكاة")

    monkey_patch = router.chat_live_stream
    router.chat_live_stream = broken_stream
    try:
        resp = client.post("/api/chat/stream", json={
            "message": "ما هي فوائد الاختبار الآلي؟",
            "provider": "zai-test", "model": "glm-test-4.6",
        })
    finally:
        router.chat_live_stream = monkey_patch
    assert resp.status_code == 200
    events = sse_events(resp)
    kinds = _kinds(events)
    assert "chat.status" in kinds
    fallback = [e for e in events
                if e.get("kind") == "chat.status"
                and e.get("status") == "stream_fallback"]
    assert fallback, f"لا تراجع معلن: {kinds}"
    completed = [e for e in events if e.get("kind") == "message_completed"]
    assert completed, f"لا إكمال بعد التراجع: {kinds}"
    # لا فشل معلن في مسار النجاح بعد التراجع
    assert "chat.error" not in kinds


def test_midstream_failure_persists_partial_with_error(
        client, api_env, monkeypatch):
    """فشل بعد بث جزئي ← chat.error يحسب partial_chars والنص محفوظ.

    الفشل هنا يطال البث **والتراجع** معًا — فلا ينجح التراجع المعلن
    ويبقى المسار الأعلى (معالج الأخطاء) هو من يجب أن يتعامل مع
    الجزئي المُبثّ: يُحفظ مع chat.error ولا تختفي الإجابة.
    """
    from router.model_router import ProviderCallError

    router = api_env["router"]

    def broken_stream(messages, *, on_delta=None, **_kw):
        if on_delta is not None:
            on_delta("جزء أول وصل قبل الانقطاع. ")
        raise ProviderCallError("انقطاع بعد بث جزئي — محاكاة")

    def broken_live(messages, *, provider_id=None, model=None, **_kw):
        raise ProviderCallError("التراجع نفسه فشل — محاكاة")

    monkeypatch.setattr(router, "chat_live_stream", broken_stream)
    monkeypatch.setattr(router, "chat_live", broken_live)
    resp = client.post("/api/chat/stream", json={
        "message": "رسالة يقطعها المزود في منتصف البث",
        "provider": "zai-test", "model": "glm-test-4.6",
    })
    assert resp.status_code == 200
    events = sse_events(resp)
    errors = [e for e in events if e.get("kind") == "chat.error"]
    assert errors, f"لا chat.error: {_kinds(events)}"
    details = errors[0]["details"]
    assert details.get("partial_chars", 0) >= len("جزء أول وصل قبل الانقطاع. ")
    saved = _last_assistant(client, details["conversation_id"])
    assert saved is not None
    assert "جزء أول وصل" in (saved.get("content") or "")
    assert saved.get("state_badge") == "PARTIAL"
