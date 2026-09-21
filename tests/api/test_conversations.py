"""اختبارات المحادثات الحقيقية (الأمر 006 §14 + §15).

العقد: القائمة حقيقية من SQLite (بلا قائمة فارغة أبدية)، الرسائل
مرتبطة بمحادثاتها، والحقول المطلوبة كاملة: conversation_id/title/
mode/created_at/updated_at. 404 صريح لمحادثة مجهولة.
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


def _start_chat(client, message):
    resp = client.post("/api/chat/stream", json={"message": message})
    assert resp.status_code == 200, resp.text[:300]
    events = sse_events(resp)
    return next(e for e in events if e["kind"] == "message_started")


def test_conversations_list_is_real_not_placeholder(client, api_env):
    """القائمة تعكس المحادثات الفعلية — لا قائمة فارغة وهمية."""
    listing = client.get("/api/conversations").json()["conversations"]
    assert isinstance(listing, list)  # قد تكون فارغة قبل أول محادثة

    _start_chat(client, "أول محادثة حقيقية في القائمة")
    listing = client.get("/api/conversations").json()["conversations"]
    assert len(listing) >= 1
    entry = listing[0]
    assert set(entry) >= {
        "conversation_id", "title", "mode", "created_at", "updated_at"
    }
    assert entry["mode"] == "chat"
    assert "أول محادثة حقيقية" in entry["title"]


def test_conversations_ordered_by_latest_activity(client, api_env):
    """الأحدث نشاطًا أولًا — إرسال رسالة في محادثة قديمة يرفعها."""
    first = _start_chat(client, "محادثة قديمة جدًا")
    second = _start_chat(client, "محادثة أحدث")
    first_id = first["details"]["conversation_id"]
    second_id = second["details"]["conversation_id"]

    listing = client.get("/api/conversations").json()["conversations"]
    ids = [c["conversation_id"] for c in listing]
    assert ids.index(second_id) < ids.index(first_id)

    # نشاط في الأولى يرفعها أعلى القائمة (updated_at)
    client.post("/api/chat/stream", json={
        "message": "رسالة جديدة في القديمة",
        "conversation_id": first_id,
    })
    listing = client.get("/api/conversations").json()["conversations"]
    assert listing[0]["conversation_id"] == first_id


def test_conversation_messages_linked_and_ordered(client, api_env):
    """الرسائل مرتبطة بمحادثتها وتُعاد بالترتيب الأقدم أولًا."""
    start = _start_chat(client, "سؤال مترابط")
    conversation_id = start["details"]["conversation_id"]
    client.post("/api/chat/stream", json={
        "message": "سؤال ثانٍ في المحادثة نفسها",
        "conversation_id": conversation_id,
    })

    messages = client.get(
        f"/api/conversations/{conversation_id}/messages"
    ).json()["messages"]
    assert [m["role"] for m in messages] == [
        "user", "assistant", "user", "assistant"
    ]
    assert messages[0]["content"] == "سؤال مترابط"


def test_conversation_messages_unknown_404(client, api_env):
    resp = client.get("/api/conversations/987654/messages")
    assert resp.status_code == 404
    assert "غير معروفة" in resp.json()["detail"]


def test_task_conversation_mode_is_task(client, api_env):
    """محادثة المهمة تُنشأ بنمط task — التمييز في القائمة (§2)."""
    resp = client.post("/api/cycle/stream", json={
        "goal": "هدف مهمة لاختبار النمط",
    })
    assert resp.status_code == 200
    events = sse_events(resp)
    conversation_id = next(
        e for e in events if e["kind"] == "task.conversation"
    )["details"]["conversation_id"]

    listing = client.get("/api/conversations").json()["conversations"]
    mine = [c for c in listing if c["conversation_id"] == conversation_id]
    assert mine and mine[0]["mode"] == "task"
