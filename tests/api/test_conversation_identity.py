"""اختبار هوية المحادثة (الأمر 010 §1-§2) — الجذر الأول للمشكلة الحرجة.

السيناريو المرجعي (§1 Acceptance): أربع رسائل متتالية داخل محادثة
واحدة — conversation.bind أول حدث في كل تيار، والمحادثة في القائمة
مرة واحدة، والرسائل كلها داخلها، والاسترداد بعد «تحديث» يعيدها.
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


def _send_chat(client, message, conversation_id=None):
    body = {"message": message}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    resp = client.post("/api/chat/stream", json=body)
    assert resp.status_code == 200
    return sse_events(resp)


def test_four_messages_one_conversation_with_bind_first(api_env):
    """§1: 4 رسائل → محادثة واحدة + bind أول حدث — لا محادثة لكل رسالة."""
    from fastapi.testclient import TestClient
    client = TestClient(routes.app)

    def list_conversations():
        out = client.get("/api/conversations")
        assert out.status_code == 200
        return out.json()["conversations"]

    before = len(list_conversations())

    conv_id = None
    for i, message in enumerate(
        ["مرحبا", "اشرح فكرة واحدة", "أكمل بمثال", "لدي سؤال آخر"], 1,
    ):
        events = _send_chat(client, message, conv_id)
        kinds = [e["kind"] for e in events]
        # bind أول حدث عرض على الإطلاق — الهوية قبل أي شيء
        assert "conversation.bind" in kinds, f"msg {i}: لا حدث ربط"
        bind_index = kinds.index("conversation.bind")
        assert bind_index == 0, f"msg {i}: الربط ليس أول حدث (#{bind_index})"
        bound = events[bind_index]["details"]["conversation_id"]
        if conv_id is None:
            conv_id = bound
            assert events[bind_index]["details"]["created"] is True
        else:
            assert bound == conv_id, (
                f"msg {i}: انشأت محادثة جديدة {bound} بدل {conv_id}"
            )
            assert events[bind_index]["details"]["created"] is False
        # الرسالة اكتملت داخل نفس التيار (المنفذ المخطوط فوري)
        assert "message_completed" in kinds

    after = list_conversations()
    assert len(after) == before + 1, (
        f"محادثات جديدة {len(after) - before} — الهوية مكسورة"
    )
    # الرسائل الثمانية كلها داخل المحادثة نفسها
    msgs = client.get(f"/api/conversations/{conv_id}/messages").json()
    roles = [m["role"] for m in msgs["messages"]]
    assert roles.count("user") == 4
    assert roles.count("assistant") == 4
    # القائمة تعرض المحادثة مرة واحدة
    assert sum(1 for c in after if c["conversation_id"] == conv_id) == 1


def test_conversation_metadata_endpoint(api_env):
    """§2: بيانات المحادثة من معرفها وحده — للتنقل الدائم."""
    from fastapi.testclient import TestClient
    client = TestClient(routes.app)
    events = _send_chat(client, "رسالة أولى للبيانات الوصفية")
    conv_id = events[0]["details"]["conversation_id"]
    out = client.get(f"/api/conversations/{conv_id}")
    assert out.status_code == 200
    meta = out.json()
    assert meta["conversation_id"] == conv_id
    assert meta["mode"] == "chat"
    assert "رسالة أولى" in meta["title"]
    assert client.get("/api/conversations/999999").status_code == 404


def test_unknown_conversation_id_is_404_not_new(api_env):
    """معرف غائب = 404 صريح — لا إنشاء محادثة جديدة بصمت (§1)."""
    from fastapi.testclient import TestClient
    client = TestClient(routes.app)
    resp = client.post(
        "/api/chat/stream",
        json={"message": "رسالة", "conversation_id": 999999},
    )
    assert resp.status_code == 404


def test_task_bind_happens_even_when_preflight_blocks(api_env):
    """المهمة المحجوبة تربط محادثتها أيضًا — لا محادثة يتيمة لكل رسالة."""
    from fastapi.testclient import TestClient
    client = TestClient(routes.app)
    from readiness.probes import ProbeResult
    from readiness import registry
    import datetime as _dt

    def blocking_probe(sessions, capability_id, **_kw):
        return registry.record_probe(
            sessions, capability_id,
            ProbeResult(
                status="NOT_READY", reason="مضبوط: بيئة معزولة للاختبار",
                checked_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
            ),
        )

    from api import routes as routes_module

    original = routes_module._preflight_probe_fn
    routes_module._preflight_probe_fn = blocking_probe
    try:
        resp = client.post("/api/cycle/stream", json={"goal": "مهمة تُحجب"})
        assert resp.status_code == 200
        events = sse_events(resp)
        kinds = [e["kind"] for e in events]
        assert "task.conversation" in kinds
        assert kinds.index("task.conversation") < kinds.index(
            "preflight.blocked"
        ), "الربط يجب أن يسبق الحجب"
        conv_id = [
            e for e in events if e["kind"] == "task.conversation"
        ][0]["details"]["conversation_id"]
        # رسالة مستخدم داخل المحادثة رغم الحجب
        msgs = client.get(
            f"/api/conversations/{conv_id}/messages"
        ).json()["messages"]
        assert any(m["role"] == "user" for m in msgs)
    finally:
        routes_module._preflight_probe_fn = original


def test_messages_recover_after_refresh(api_env):
    """§1 Refresh: GET messages يعيد بناء المحادثة كاملة (الاسترداد)."""
    from fastapi.testclient import TestClient
    client = TestClient(routes.app)
    events = _send_chat(client, "سؤال الاسترداد")
    conv_id = events[0]["details"]["conversation_id"]
    _send_chat(client, "سؤال ثانٍ", conv_id)
    msgs = client.get(f"/api/conversations/{conv_id}/messages").json()
    roles = [m["role"] for m in msgs["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]
    contents = [m["content"] for m in msgs["messages"]]
    assert contents[0] == "سؤال الاسترداد"
    assert contents[2] == "سؤال ثانٍ"
