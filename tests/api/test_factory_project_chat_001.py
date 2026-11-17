"""Regression: AES chat binds project context before model generation and preserves partial output."""
from fastapi.testclient import TestClient
from api import routes
from workflow import service
from tests.api.conftest import sse_events
from router.model_router import ProviderCallError


def test_project_chat_is_bound_before_first_delta(api_env, monkeypatch):
    project = service.create_project(
        api_env["sessions"], name="موقع إنتاج حقيقي",
        objective="إنشاء موقع أخبار مع صفحات ومخرجات قابلة للفحص",
    )
    router = api_env["router"]
    received = []
    original = router.chat_live_stream

    def capture(messages, **kwargs):
        received.extend(messages)
        return original(messages, **kwargs)

    monkeypatch.setattr(router, "chat_live_stream", capture)
    client = TestClient(routes.app)
    response = client.post("/api/chat/stream", json={
        "message": "ماذا تفعل؟", "project_id": project["id"]
    })
    assert response.status_code == 200
    events = sse_events(response)
    bind = next(e for e in events if e["kind"] == "conversation.bind")
    cid = bind["scope"]["conversation_id"]
    assert bind["scope"]["project_id"] == project["id"]
    assert next(e for e in events if e["kind"] == "message_completed")
    assert received[0].role == "system"
    assert "مصنع الهندسة" in received[0].content
    assert project["name"] in received[0].content
    assert project["objective"] in received[0].content
    assert project["status"] in received[0].content
    conv = client.get(f"/api/conversations/{cid}")
    assert conv.json()["project_id"] == project["id"]
    assert client.get(f"/api/projects/{project['id']}/conversations").json()["conversations"]


def test_project_chat_rejects_foreign_or_missing_project_without_message(api_env):
    p = service.create_project(api_env["sessions"], name="موقع أ", objective="بناء موقع أ")
    q = service.create_project(api_env["sessions"], name="موقع ب", objective="بناء موقع ب")
    client = TestClient(routes.app)
    assert client.post("/api/chat/stream", json={
        "message": "مرحبا", "project_id": 999999
    }).status_code == 404
    response = client.post("/api/chat/stream", json={
        "message": "مرحبا", "project_id": p["id"]
    })
    assert response.status_code == 200
    cid = next(e for e in sse_events(response)
               if e["kind"] == "conversation.bind")["scope"]["conversation_id"]
    first = client.get(f"/api/conversations/{cid}/messages").json()["messages"]
    conflict = client.post("/api/chat/stream", json={
        "message": "لن يضاف", "project_id": q["id"], "conversation_id": cid
    })
    assert conflict.status_code == 409
    assert client.get(f"/api/conversations/{cid}/messages").json()["messages"] == first


def test_partial_provider_abort_is_not_retried_or_presented_as_completed(api_env, monkeypatch):
    client = TestClient(routes.app)
    router = api_env["router"]
    full_calls = []

    def broken_stream(_messages, *, on_delta=None, **_kwargs):
        on_delta("رد حقيقي جزئي ثم ")
        raise ProviderCallError("signal is aborted without reason", is_server_error=True)

    def forbidden_fallback(*_args, **_kwargs):
        full_calls.append(True)
        raise AssertionError("Must not silently retry after partial delta")

    monkeypatch.setattr(router, "chat_live_stream", broken_stream)
    monkeypatch.setattr(router, "chat_live", forbidden_fallback)
    response = client.post("/api/chat/stream", json={"message": "ماذا تفعل؟"})
    assert response.status_code == 200
    events = sse_events(response)
    assert any(e["kind"] == "chat.error" for e in events)
    assert not any(e["kind"] == "message_completed" for e in events)
    assert not full_calls
    cid = next(e for e in events if e["kind"] == "conversation.bind")["scope"]["conversation_id"]
    messages = client.get(f"/api/conversations/{cid}/messages").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[-1]["state_badge"] == "PARTIAL"
    assert messages[-1]["content"] == "رد حقيقي جزئي ثم "


def test_partial_reply_not_reported_saved_when_storage_fails(api_env, monkeypatch):
    client = TestClient(routes.app)
    router = api_env["router"]
    append = routes.convo.append_message

    def broken_stream(_messages, *, on_delta=None, **_kwargs):
        on_delta("نص وصل إلى المتصفح")
        raise ProviderCallError("stream disconnected", is_server_error=True)

    def write_user_only(*args, **kwargs):
        if kwargs.get("role") == "assistant":
            raise OSError("storage unavailable")
        return append(*args, **kwargs)

    monkeypatch.setattr(router, "chat_live_stream", broken_stream)
    monkeypatch.setattr(routes.convo, "append_message", write_user_only)
    response = client.post("/api/chat/stream", json={"message": "اختبار الحفظ"})
    assert response.status_code == 200
    events = sse_events(response)
    failure = next(e for e in events if e["kind"] == "chat.error")
    assert failure["details"]["persisted"] is False
    assert failure["details"]["partial_chars"] == len("نص وصل إلى المتصفح")
    assert not any(e["kind"] == "message_completed" for e in events)
    cid = failure["scope"]["conversation_id"]
    messages = client.get(f"/api/conversations/{cid}/messages").json()["messages"]
    assert [m["role"] for m in messages] == ["user"]
