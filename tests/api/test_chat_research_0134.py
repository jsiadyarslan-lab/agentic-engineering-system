"""اختبارات الويب في المحادثة العادية (013.4 §25-§30) — R/S/T/U.

- R. البحث يعمل في محادثة عادية: research.started ← research.results ←
     سياق المصادر يصل النموذج ← research.used + web_used
- S. جلب صفحة معروفة (WEB_FETCH) عند رابط في الرسالة
- T. المتصفح قدرة معلنة منفصلة (لا يُستدعى ضمنًا في المحادثة)
- U. المزود غير الجاهز: WEB_UNAVAILABLE صادقة — لا نتائج ملفقة
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


@pytest.fixture()
def client(api_env):
    return TestClient(routes.app)


def _chat(client, message, **extra):
    body = {"message": message, "provider": "zai-test",
            "model": "glm-test-4.6", **extra}
    resp = client.post("/api/chat/stream", json=body)
    assert resp.status_code == 200, resp.text[:300]
    return sse_events(resp)


FAKE_RESULTS = [
    {"title": f"نتيجة {i}", "url": f"https://example.com/r{i}",
     "snippet": "مقتطف حقيقي من مزود منظّم"}
    for i in range(5)
]


@pytest.fixture()
def stub_search(monkeypatch):
    """حدود المزود منظمة (نقل الشبكة وحده) — الخدمة والمصفوفة حقيقيان."""
    from research import service as research_service

    def fake_search(sessions, query):
        return {"provider": "منظّم", "provider_kind": "search_test",
                "results": [dict(r) for r in FAKE_RESULTS], "attempts": []}

    monkeypatch.setattr(research_service, "search", fake_search)
    return fake_search


# ---------------------------- R. البحث ----------------------------- #

def test_web_search_in_normal_chat(client, api_env, stub_search):
    """(§26) «ابحث عن أحدث…» ← بحث فعلي ← مصادر ← مؤشر 🌐 معلن."""
    events = _chat(client, "ابحث عن أحدث تقنيات OSINT")

    kinds = [e["kind"] for e in events]
    assert "research.started" in kinds, kinds
    assert "research.results" in kinds, kinds
    assert "research.used" in kinds, kinds
    assert "message_completed" in kinds

    results = next(e for e in events if e["kind"] == "research.results")
    assert results["details"]["count"] == len(FAKE_RESULTS)

    used = next(e for e in events if e["kind"] == "research.used")
    assert used["details"]["search"] is True
    assert len(used["details"]["sources"]) == len(FAKE_RESULTS)

    done = next(e for e in events if e["kind"] == "message_completed")
    assert done["details"]["web_used"] is True

    # سياق المصادر وصل النموذج فعليًا (استشهاد مرقم)
    last_call = api_env["router"].calls[-1]
    messages_dump = getattr(last_call, "messages_dump", None)


def test_sources_context_reaches_model(client, api_env, stub_search,
                                       monkeypatch):
    """سياق المصادر المرقم يُمرر للنموذج — الاستشهاد ممكن فعليًا."""
    captured = {}

    original = api_env["router"].chat_live_stream

    def capture_stream(messages, *, provider_id=None, model=None,
                       on_delta=None, **_kw):
        captured["messages"] = [
            {"role": m.role, "content": m.content} for m in messages
        ]
        return original(messages, provider_id=provider_id, model=model,
                        on_delta=on_delta)

    monkeypatch.setattr(api_env["router"], "chat_live_stream",
                        capture_stream)
    _chat(client, "ابحث عن أخبار الذكاء الاصطناعي اليوم")

    system_msgs = [m for m in captured.get("messages", [])
                   if m["role"] == "system"]
    assert system_msgs, "سياق المصادر يجب أن يصل النموذج"
    assert "مصادر ويب حديثة" in system_msgs[-1]["content"]
    assert "[1]" in system_msgs[-1]["content"], "ترقيم الاستشهاد موجود"


def test_web_off_disables_search(client, api_env, stub_search):
    """(§26) web=off صريح: لا بحث حتى مع صيغة طلب البحث."""
    events = _chat(client, "ابحث عن أحدث الأخبار", web="off")
    kinds = [e["kind"] for e in events]
    assert "research.started" not in kinds
    done = next(e for e in events if e["kind"] == "message_completed")
    assert done["details"]["web_used"] is False


def test_no_search_for_plain_question(client, api_env, stub_search):
    """auto بلا مؤشر بحث: رسالة عامة لا تبحث (لا شبكة بلا سبب)."""
    events = _chat(client, "اشرح لي مفهوم الذكاء الاصطناعي بإيجاز")
    kinds = [e["kind"] for e in events]
    assert "research.started" not in kinds


# ------------------------- U. المزود غير جاهز ---------------------- #

def test_web_unavailable_is_honest(client, api_env, monkeypatch):
    """(§30) فشل كل المزودين: WEB_UNAVAILABLE بالسبب — لا ملفقة."""
    from research import service as research_service
    from roles.tool_failures import ToolFailure

    def dead_search(sessions, query):
        raise ToolFailure(
            "web_search", "لا مزود بحث جاهز: ddg: محجوب؛ bing: محجوب",
            failure_class="DEPENDENCY_FAILURE",
            reason="PROVIDER_NOT_READY", stage="PROVIDER_RESOLUTION",
            retryable=False,
            details={"attempts": [], "query": query[:100]},
        )

    monkeypatch.setattr(research_service, "search", dead_search)
    events = _chat(client, "ابحث عن آخر التطورات", web="on")

    kinds = [e["kind"] for e in events]
    assert "research.unavailable" in kinds, kinds
    unavailable = next(
        e for e in events if e["kind"] == "research.unavailable"
    )
    assert unavailable["status"] == "WEB_UNAVAILABLE"
    assert unavailable["details"]["error"], "السبب الحرفي معلن"
    # لا نتائج ملفقة: لا research.used
    assert "research.used" not in kinds
    done = next(e for e in events if e["kind"] == "message_completed")
    assert done["details"]["web_used"] is False


# ------------------------- S. جلب صفحة معروفة ---------------------- #

def test_fetch_url_in_chat(client, api_env, monkeypatch):
    """(§27) رابط في الرسالة: WEB_FETCH يجلب الصفحة (مفصول عن البحث)."""
    from research import chat_research

    def fake_fetch(url, *, timeout=12.0):
        return {"ok": True, "url": url,
                "content": "محتوى الصفحة المنظّمة للاختبار"}

    monkeypatch.setattr(chat_research, "fetch_for_chat", fake_fetch)
    events = _chat(
        client, "لخص لي هذه الصفحة https://example.com/article",
        web="on",
    )

    kinds = [e["kind"] for e in events]
    assert "research.fetched" in kinds, kinds
    fetched = next(e for e in events if e["kind"] == "research.fetched")
    assert fetched["details"]["url"] == "https://example.com/article"


# ------------------------- T. البحث ≠ المتصفح ---------------------- #

def test_search_and_browser_are_distinct_capabilities(client, api_env):
    """(§27) البحث والجلب والمتصفح مفاهيم منفصلة معلنة."""
    from research import chat_research

    # كاشف النية يفرق: بحث (لا روابط) / جلب (رابط) / الاثنان
    decision = chat_research.decide_web_mode("ابحث عن أحدث الأخبار")
    assert decision["search"] is True and not decision["fetch_urls"]

    decision = chat_research.decide_web_mode(
        "اقرأ https://example.com/x فقط")
    assert decision["fetch_urls"] == ["https://example.com/x"]
    # رابط وحده لا يستلزم بحثًا
    assert decision["search"] is False

    # المتصفح قدرة منفصلة لا تُستدعى ضمن المحادثة (قدرة المشاريع)
    events = _chat(client, "ابحث عن أحدث الأخبار")
    kinds = [e["kind"] for e in events]
    assert not any(k.startswith("browser.") for k in kinds), \
        "المحادثة لا تستدعي المتصفح ضمنًا — قدرة معلنة منفصلة (§27)"
