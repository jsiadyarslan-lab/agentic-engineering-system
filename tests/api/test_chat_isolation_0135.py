"""اختبارات عزل تيار المحادثة وثبات الرسائل (013.5 §E+§F+§G+§H).

العطل الحي الموثّق (من قاعدة الإنتاج):
    المحادثة #10 فيها سؤال «ما هي احدث نماذج كلاود؟» ثم ظهر في
    الواجهة محتوى تاريخي غير متعلق: «Confirmation of Completion /
    A15 registration / HASH-MANIFEST» (رسائل قديمة من 08:31 في
    نفس المحادثة).

الجذر الحقيقي (سلسلتان مستقلتان):
  1. ``ChatLive.resumeIfRunning`` كان يستأنف بـ ``after=0`` — أي
     **إعادة بث تاريخ المحادثة كله**، فيُعاد رسمه كأنه ردٌّ جديد
     (``message_delta`` قديم ← فقاعة جديدة).
  2. لا حرس نطاق في العميل: أي حدث يُمرَّر لكل معالج بلا تحقق من
     ``conversation_id``/``message_id``/``project_id``.

هذه الاختبارات تثبت: النطاق الصريح على كل حدث، موضع الاستئناف
الحقيقي، عزل تيار محادثة عن أخرى، ودوام الرسالة الفاشلة/المكتملة.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("httpx", reason="TestClient يتطلب httpx")

from api import routes  # noqa: E402
from tests.api.conftest import sse_events  # noqa: E402


@pytest.fixture()
def client(api_env):
    return TestClient(routes.app)


def _chat(client, message, **extra):
    body = {"message": message, "provider": "zai-test",
            "model": "glm-test-4.6"}
    body.update(extra)
    resp = client.post("/api/chat/stream", json=body)
    assert resp.status_code == 200, resp.text[:300]
    return sse_events(resp)


# ------------------------------------------------------------------ #
# §E  النطاق الصريح على كل حدث
# ------------------------------------------------------------------ #

def test_every_chat_event_carries_an_explicit_scope(client):
    """(§E) لا حدث محادثة بلا scope كامل — التوجيه لا الفلترة البصرية."""
    events = _chat(client, "سؤال عزل النطاق")
    assert events, "لا أحداث في البث"

    for event in events:
        if event.get("kind", "").startswith("stream."):
            continue
        scope = event.get("scope")
        assert isinstance(scope, dict), \
            f"حدث بلا نطاق صريح: {event.get('kind')}"
        assert scope["conversation_id"] is not None, event.get("kind")
        assert scope["stream"] == f"chat-{scope['conversation_id']}"
        assert scope["message_id"], event.get("kind")
        assert "project_id" in scope and "run_id" in scope \
            and "job_id" in scope
        # التسلسل معلن باسمين — لا لبس في المصالحة
        assert event["sequence"] == event["seq"]


def test_scope_message_id_matches_streamed_message(client):
    events = _chat(client, "تحقق من هوية الرسالة")
    started = [e for e in events if e["kind"] == "message_started"][0]
    delta = [e for e in events if e["kind"] == "message_delta"][0]
    assert started["scope"]["message_id"] == started["message_id"]
    assert delta["scope"]["message_id"] == delta["message_id"]
    assert delta["scope"]["message_id"] == started["message_id"]


# ------------------------------------------------------------------ #
# §E  عزل محادثة عن أخرى — على مستوى التيار الدائم
# ------------------------------------------------------------------ #

def test_conversation_stream_never_returns_another_conversation(client):
    """(§E) تيار المحادثة أ يفقط أحداث أ — لا تسرّب من ب."""
    first = _chat(client, "المحادثة الأولى")
    second = _chat(client, "المحادثة الثانية")

    convo_a = [e for e in first if e["kind"] == "message_started"][0][
        "details"]["conversation_id"]
    convo_b = [e for e in second if e["kind"] == "message_started"][0][
        "details"]["conversation_id"]
    assert convo_a != convo_b

    replay = client.get(f"/api/chat/events/{convo_a}?after=0")
    assert replay.status_code == 200
    events = sse_events(replay)
    others = [
        e for e in events
        if not e.get("kind", "").startswith("stream.")
        and e.get("scope", {}).get("conversation_id") not in (None, convo_a)
    ]
    assert others == [], f"تسرّب أحداث محادثة أخرى: {others[:2]}"
    assert all(
        e.get("cycle_id") == f"chat-{convo_a}"
        for e in events
        if not e.get("kind", "").startswith("stream.")
    )


# ------------------------------------------------------------------ #
# §E/§G  موضع الاستئناف الحقيقي — لا after=0
# ------------------------------------------------------------------ #

def test_active_endpoint_gives_a_real_resume_position(client):
    """(§G) ``/api/chat/active`` يعطي last_seq و message_id — لا صفر."""
    events = _chat(client, "سؤال موضع الاستئناف")
    convo = [e for e in events if e["kind"] == "message_started"][0][
        "details"]["conversation_id"]

    out = client.get(f"/api/chat/active?conversation_id={convo}").json()
    assert out["running"] is False        # انتهى التوليد
    assert out["stream"] == f"chat-{convo}"
    assert out["last_seq"] > 0, \
        "موضع الاستئناف صفر — هذا هو جذر إعادة بث التاريخ"


def test_resume_after_last_seq_replays_nothing_historical(client):
    """(§E) after=last_seq = لا إعادة بث تاريخية (لا تلوّث)."""
    events = _chat(client, "سؤال إعادة البث")
    convo = [e for e in events if e["kind"] == "message_started"][0][
        "details"]["conversation_id"]
    last_seq = client.get(
        f"/api/chat/active?conversation_id={convo}").json()["last_seq"]

    replay = client.get(f"/api/chat/events/{convo}?after={last_seq}")
    replayed = [
        e for e in sse_events(replay)
        if not e.get("kind", "").startswith("stream.")
    ]
    assert replayed == [], \
        f"أُعيد بث {len(replayed)} حدثًا تاريخيًا بعد last_seq"

    # وبعد الصفر: الأرشيف الحقيقي موجود (الدوام لا يُنقص)
    archive = sse_events(client.get(f"/api/chat/events/{convo}?after=0"))
    kinds = {e.get("kind") for e in archive}
    assert "message_delta" in kinds and "message_completed" in kinds


def test_historical_replay_is_flagged_with_its_own_message_id(client):
    """(§F) كل حدث مؤرشف يحمل message_id الخاص به — لا يُنسب للجاري."""
    events = _chat(client, "رسالة أولى")
    convo = [e for e in events if e["kind"] == "message_started"][0][
        "details"]["conversation_id"]
    first_id = [e for e in events if e["kind"] == "message_started"][0][
        "message_id"]

    _chat(client, "رسالة ثانية", conversation_id=convo)

    archive = sse_events(client.get(f"/api/chat/events/{convo}?after=0"))
    deltas = [e for e in archive if e.get("kind") == "message_delta"]
    assert deltas, "لا قطع مؤرشفة"
    ids = {e.get("message_id") for e in deltas}
    assert first_id in ids, "معرّف الرسالة الأولى ضاع من الأرشيف"
    assert all(e.get("scope", {}).get("message_id") == e.get("message_id")
               for e in deltas), "نطاق الأرشيف لا يطابق رسالته"


# ------------------------------------------------------------------ #
# §F/§G  ثبات الرسالة ودوام الفشل
# ------------------------------------------------------------------ #

def test_completed_message_is_durable_and_badged(client):
    """(§F/§G) الرسالة المكتملة محفوظة بحكم COMPLETED — لا تتغير."""
    events = _chat(client, "سؤال الثبات")
    convo = [e for e in events if e["kind"] == "message_started"][0][
        "details"]["conversation_id"]
    completed = [e for e in events if e["kind"] == "message_completed"][0]
    streamed_text = "".join(
        e.get("delta") or e.get("text") or ""
        for e in events if e["kind"] == "message_delta"
    )

    stored = client.get(f"/api/conversations/{convo}/messages").json()
    assistants = [m for m in stored["messages"] if m["role"] == "assistant"]
    assert len(assistants) == 1, "الرسالة المكتملة غير محفوظة أو مكررة"
    assert assistants[0]["state_badge"] == "COMPLETED"
    assert assistants[0]["content"] == streamed_text
    assert completed["message_id"]

    # §F: لا حدث لاحق يبدّل محتوى رسالة مكتملة
    stored2 = client.get(f"/api/conversations/{convo}/messages").json()
    assert stored2 == stored, "محتوى الرسالة المكتملة تغيّر بعد الاكتمال"


def test_failed_chat_is_persisted_so_the_answer_never_vanishes(
        client, api_env, monkeypatch):
    """(§G) فشل المزود يُدوَّن بحكم FAILED — لا اختفاء إجابة عند التحديث."""
    router = api_env["router"]

    def boom(messages, *, provider_id=None, model=None, on_delta=None,
             **_kw):
        raise RuntimeError("مهلة/اتصال فشل مع المزود: read timed out")

    monkeypatch.setattr(router, "chat_live_stream", boom)
    monkeypatch.setattr(router, "chat_live", boom)

    events = _chat(client, "سؤال سيفشل")
    errors = [e for e in events if e["kind"] == "chat.error"]
    assert errors, [e.get("kind") for e in events]
    convo = errors[0]["details"]["conversation_id"]
    assert errors[0]["details"]["persisted"] is True

    stored = client.get(f"/api/conversations/{convo}/messages").json()
    assistants = [m for m in stored["messages"] if m["role"] == "assistant"]
    assert len(assistants) == 1, \
        "الفشل لم يُدوَّن — السؤال يبقى بلا رد ويُفهم كاختفاء إجابة"
    assert assistants[0]["state_badge"] == "FAILED"
    assert "فشل الاستدعاء الحي" in assistants[0]["content"]
    assert errors[0]["details"]["error_class"], \
        "الفشل بلا تصنيف — لا error_class في الحدث"


def test_partial_stream_then_failure_keeps_the_partial_text(
        client, api_env, monkeypatch):
    """(§G) نص جزئي وصل ثم فشل: يُدوَّن بحكم PARTIAL كما رآه المالك."""
    router = api_env["router"]

    def partial_then_fail(messages, *, provider_id=None, model=None,
                          on_delta=None, **_kw):
        if on_delta is not None:
            on_delta("إجابة جزئية وصلت ")
            on_delta("ثم انقطع المزود")
        raise RuntimeError("مهلة/اتصال فشل: read timed out")

    monkeypatch.setattr(router, "chat_live_stream", partial_then_fail)
    monkeypatch.setattr(router, "chat_live", partial_then_fail)

    events = _chat(client, "سؤال جزئي")
    errors = [e for e in events if e["kind"] == "chat.error"]
    assert errors
    convo = errors[0]["details"]["conversation_id"]
    assert errors[0]["details"]["partial_chars"] > 0

    stored = client.get(f"/api/conversations/{convo}/messages").json()
    assistant = [m for m in stored["messages"] if m["role"] == "assistant"][0]
    assert assistant["state_badge"] == "PARTIAL"
    assert "إجابة جزئية وصلت" in assistant["content"]


def test_configuration_required_is_persisted_too(client, api_env):
    """(§G) مزود غير متاح: الحالة تُدوَّن — لا محادثة بلا رد صامت."""
    events = _chat(client, "سؤال مزود مفقود",
                   provider="ghost-provider", model="ghost-model")
    errors = [e for e in events if e["kind"] == "chat.error"]
    assert errors
    assert errors[0]["code"] == "CONFIGURATION_REQUIRED"
    assert errors[0]["details"]["persisted"] is True
    convo = errors[0]["details"]["conversation_id"]
    stored = client.get(f"/api/conversations/{convo}/messages").json()
    assistants = [m for m in stored["messages"] if m["role"] == "assistant"]
    assert len(assistants) == 1
    assert assistants[0]["state_badge"] == "FAILED"


# ------------------------------------------------------------------ #
# §H  إسقاطان منفصلان — حدث مشروع لا يصبح رسالة محادثة
# ------------------------------------------------------------------ #

def test_project_events_do_not_enter_a_chat_stream(client, api_env):
    """(§H) حدث سير عمل لا يظهر في تيار محادثة أبدًا."""
    from workflow import service as wf_service

    sessions = routes._sessions
    project = wf_service.create_project(
        sessions, name="مشروع عزل", objective="هدف"
    )
    wf_service.add_event(sessions, project["id"], "PLAN_CREATED",
                         {"plan_id": 1})

    events = _chat(client, "سؤال محادثة نظيفة")
    convo = [e for e in events if e["kind"] == "message_started"][0][
        "details"]["conversation_id"]
    archive = sse_events(client.get(f"/api/chat/events/{convo}?after=0"))

    leaked = [
        e for e in archive
        if e.get("kind") in ("PLAN_CREATED", "PLANNING_STARTED",
                             "JOB_CREATED", "WORKFLOW_DIAGNOSED")
        or (e.get("scope") or {}).get("project_id") is not None
    ]
    assert leaked == [], f"حدث سير عمل تسرّب إلى تيار المحادثة: {leaked[:2]}"


# ------------------------------------------------------------------ #
# بنية العميل: بوابة العزل وموضع الاستئناف (013.5 §E/§G)
# ------------------------------------------------------------------ #

def test_client_enforces_scope_and_uses_real_resume_position():
    """عقد الواجهة: بوابة نطاق صريحة + استئناف بـ last_seq لا بالصفر."""
    from pathlib import Path

    ui = Path(__file__).resolve().parents[2] / "src" / "ui"
    app_js = (ui / "app.js").read_text(encoding="utf-8")
    chat_js = (ui / "chat-stream.js").read_text(encoding="utf-8")

    assert "function eventInActiveScope" in app_js, \
        "لا بوابة عزل نطاق في النواة"
    assert "eventInActiveScope(event)" in app_js, \
        "البوابة غير موصولة بتوجيه الأحداث"
    assert "eventInActiveScope: eventInActiveScope" in app_js, \
        "البوابة غير مصدَّرة — لا يستطيع أي مكوّن آخر تطبيقها"

    assert "out.j.last_seq" in chat_js, \
        "الاستئناف لا يقرأ موضع الاستئناف الحقيقي"
    assert 'attachStream(conversationId, from)' in chat_js, \
        "الاستئناف لا يستخدم الموضع الحقيقي"
    assert "attachStream(conversationId, 0)" not in chat_js, \
        "استئناف من الصفر ما زال موجودًا — جذر إعادة بث التاريخ"
    assert "messageAllowed" in chat_js, \
        "لا حارس ثبات/عزل للرسالة الجارية"
    assert "data-msg-state" in chat_js, \
        "لا وسم حالة الرسالة (ثبات §F)"


def test_failure_persistence_uses_classified_error_class(client, api_env,
                                                         monkeypatch):
    """(§B/§G) فشل المحادثة يحمل تصنيفًا من الخريطة المعتمدة."""
    from router.call_tracker import classify_failure
    from router.model_router import ProviderCallError

    router = api_env["router"]

    def timeout(messages, *, provider_id=None, model=None, on_delta=None,
                **_kw):
        raise ProviderCallError("مهلة", is_timeout=True)

    monkeypatch.setattr(router, "chat_live_stream", timeout)
    monkeypatch.setattr(router, "chat_live", timeout)
    assert classify_failure(ProviderCallError("مهلة", is_timeout=True))[0] \
        == "MODEL_TIMEOUT"

    events = _chat(client, "سؤال مهلة")
    error = [e for e in events if e["kind"] == "chat.error"][0]
    assert error["code"] == "MODEL_TIMEOUT"
    assert json.dumps(error)  # قابل للتسلسل — لا كائنات غريبة
