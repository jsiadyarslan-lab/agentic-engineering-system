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

    def fake_search(sessions, query, **_kw):
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

    def dead_search(sessions, query, **_kw):
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


# --------------- (AES-EXP-04 §6) ميزانية البحث الكلية -------------- #

def test_chat_search_budget_bounds_hung_network(client, api_env,
                                                monkeypatch):
    """(§6) بحث المحادثة محدود بميزانية كلية — شبكة معلقة (مزود لا
    يعود) لا تحتجز خيط المحادثة: WEB_UNAVAILABLE صادقة خلال
    الميزانية والإجابة تكمل معلنة، لا مهلة اختبار كاملة (149.7ث
    القديمة كانت هذا المسار بعينه — التفريغ: v2-chat عالق في
    sock.connect داخل provider.search)."""
    import time as _time

    from research import chat_research
    from research import service as research_service

    def hung_search(sessions, query, **_kw):  # noqa: ARG001
        # شبكة سوداء محاكاة: سلسلة لا تعود أبدًا خلال الاختبار
        _time.sleep(25.0)
        return {"provider": "hung", "results": []}

    monkeypatch.setattr(research_service, "search", hung_search)
    monkeypatch.setenv("AES_CHAT_RESEARCH_BUDGET_S", "2")

    started = _time.monotonic()
    events = _chat(client, "ابحث لي عن أحدث الأخبار")
    elapsed = _time.monotonic() - started

    # الجوهر: خيط المحادثة تحرر خلال الميزانية لا خلال مهلة كاملة
    assert elapsed < 30.0, (
        f"خيط المحادثة احتُجز {elapsed:.0f}ث — الميزانية الكلية لم تعمل"
    )
    kinds = [e["kind"] for e in events]
    assert "research.unavailable" in kinds, kinds
    unavailable = next(
        e for e in events if e["kind"] == "research.unavailable"
    )
    # السبب الصادق المفصل — لا فشل مبهم ولا نجاح ملفق
    assert "الميزانية الزمنية الكلية" in unavailable["details"]["error"]
    # المحادثة أكملت من الذاكرة مع الإعلان الصريح (013.5 §L/§30)
    assert "message_completed" in kinds, kinds


# ------------------- (W2-T22) المتابعة ترث الموضوع ------------------ #

def test_followup_inherits_topic_and_question_mark_retries(
        client, api_env, stub_search):
    """(W2-T22) سيناريو المالك حرفيًا في محادثة واحدة:

    1. «اخبار انتخابات الكنسيت اليوم» ← بحث بموضوعه.
    2. «ابحث انت واعطني ملخص» ← ترث الموضوع — لا «انت و ملخص»
       (ويكيبيديا أعادت ملخصات مسلسلات في الحادثة الحقيقية).
    3. «؟» ← إعادة بحث (followup_retry) بالموضوع الموروث — لا
       إجابة من ذاكرة متقادمة «لا أملك إنترنت مباشر».
    """
    first = _chat(client, "اخبار انتخابات الكنسيت اليوم")
    kinds1 = [e["kind"] for e in first]
    assert "research.started" in kinds1, kinds1
    bind = next(e for e in first if e["kind"] == "conversation.bind")
    convo_id = bind["details"]["conversation_id"]
    started1 = next(e for e in first if e["kind"] == "research.started")
    assert started1["details"]["query"] == "اخبار انتخابات الكنسيت اليوم"
    assert started1["details"]["inherited"] is False

    # الدور 2 — طلب متابعة بلا موضوع: يرث استعلام الدور 1
    second = _chat(client, "ابحث انت واعطني ملخص",
                   conversation_id=convo_id)
    kinds2 = [e["kind"] for e in second]
    assert "research.started" in kinds2, kinds2
    started2 = next(e for e in second if e["kind"] == "research.started")
    assert started2["details"]["query"] == "اخبار انتخابات الكنسيت اليوم"
    assert started2["details"]["inherited"] is True
    assert "انت" not in started2["details"]["query"].split()
    assert "research.results" in kinds2, kinds2

    # الدور 3 — «؟» وحدها: إعادة بحث بالموضوع الموروث
    third = _chat(client, "؟", conversation_id=convo_id)
    kinds3 = [e["kind"] for e in third]
    assert "research.started" in kinds3, (
        "«؟» في محادثة ذات موضوع يجب أن تعيد البحث — لا إجابة متقادمة"
    )
    started3 = next(e for e in third if e["kind"] == "research.started")
    assert started3["details"]["reason"] == "followup_retry"
    assert started3["details"]["query"] == "اخبار انتخابات الكنسيت اليوم"
    assert started3["details"]["inherited"] is True
    assert "research.results" in kinds3, kinds3
    used3 = next(e for e in third if e["kind"] == "research.used")
    assert used3["details"]["search"] is True
    done3 = next(e for e in third if e["kind"] == "message_completed")
    assert done3["details"]["web_used"] is True


def test_followup_retry_respects_explicit_web_off(client, api_env,
                                                  stub_search):
    """(W2-T22) web=off الصريح يظل محترمًا — المتابعة لا تتجاوزه."""
    first = _chat(client, "اخبار انتخابات الكنسيت اليوم")
    bind = next(e for e in first if e["kind"] == "conversation.bind")
    convo_id = bind["details"]["conversation_id"]
    events = _chat(client, "؟", conversation_id=convo_id, web="off")
    kinds = [e["kind"] for e in events]
    assert "research.started" not in kinds, kinds
    done = next(e for e in events if e["kind"] == "message_completed")
    assert done["details"]["web_used"] is False
