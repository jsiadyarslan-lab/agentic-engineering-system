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


def test_provider_transport_error_does_not_start_hidden_second_call(api_env, monkeypatch):
    """429, timeout and server errors are not evidence of no-stream support."""
    router = api_env["router"]
    client = TestClient(routes.app)
    problems = [
        ProviderCallError("429 rate limited", code=429, is_throttle=True),
        ProviderCallError("read timed out", is_timeout=True),
        ProviderCallError("upstream 503", code=503, is_server_error=True),
        ProviderCallError("invalid key", code=401),
    ]
    for fault in problems:
        fallback_calls = []
        def unavailable_stream(*_args, **_kwargs):
            raise fault
        def unexpected_fallback(*_args, **_kwargs):
            fallback_calls.append(True)
            raise AssertionError("A transport failure is not a streaming capability failure")
        monkeypatch.setattr(router, "chat_live_stream", unavailable_stream)
        monkeypatch.setattr(router, "chat_live", unexpected_fallback)
        response = client.post("/api/chat/stream", json={"message": "فحص خطأ اتصال"})
        assert response.status_code == 200
        events = sse_events(response)
        assert len([e for e in events if e["kind"] == "chat.error"]) == 1
        assert not any(e.get("status") == "stream_fallback" for e in events)
        assert not any(e["kind"] == "message_completed" for e in events)
        assert not fallback_calls


def test_explicitly_unsupported_stream_allows_declared_single_fallback(api_env, monkeypatch):
    """An explicitly unsupported streaming transport can use one full call."""
    router = api_env["router"]
    client = TestClient(routes.app)
    calls = []
    original_full = router.chat_live

    def unsupported_stream(*_args, **_kwargs):
        raise ProviderCallError("streaming not supported", code=400)

    def one_full_call(*args, **kwargs):
        calls.append(True)
        return original_full(*args, **kwargs)

    monkeypatch.setattr(router, "chat_live_stream", unsupported_stream)
    monkeypatch.setattr(router, "chat_live", one_full_call)
    response = client.post("/api/chat/stream", json={"message": "فحص مسار تراجع معلن"})
    events = sse_events(response)
    assert response.status_code == 200
    assert len(calls) == 1
    assert any(e.get("status") == "stream_fallback" for e in events)
    assert any(e["kind"] == "message_completed" for e in events)
    assert not any(e["kind"] == "chat.error" for e in events)


def test_same_conversation_rejects_parallel_generation_without_duplicate_user_message(api_env):
    """Second concurrent HTTP POST must not append a duplicate question."""
    from threading import Event
    from persistence import conversations as convo
    client = TestClient(routes.app)
    p = service.create_project(api_env["sessions"],
                               name="مشروع اختبار ازدواج", objective="مراجعة الاستجابة")
    c = convo.create_conversation(api_env["sessions"], title="اختبار",
                                  project_id=p["id"])
    key = "test-pending-same-chat"
    routes._chat_active[key] = {"done": Event(), "stream": f"chat-{c.id}"}
    try:
        reply = client.post("/api/chat/stream", json={
            "message": "هل يصل مرتين؟",
            "conversation_id": c.id,
            "project_id": p["id"],
        })
        assert reply.status_code == 409
        assert "توليد رد جارٍ" in reply.json()["detail"]
        saved = client.get(f"/api/conversations/{c.id}/messages").json()["messages"]
        assert saved == []
    finally:
        routes._chat_active.pop(key, None)


def _record_output(sessions, project, filename):
    # Seed a linked legacy acceptance (the output projection does not trust
    # a naked evidence row without its attempt, step and mechanical verdict).
    pid = project["id"]
    plan = service.create_plan(
        sessions, pid,
        {"phases": [{"title": filename, "steps": [{"objective": filename}]}]},
    )
    service.materialize_plan(sessions, plan)
    phase = service.active_phases(sessions, plan["id"])[0]
    step = service.phase_steps(sessions, phase["id"])[0]
    execution = service.create_execution(
        sessions, step["id"], attempt=1, provider="fixture", model="", workspace=".",
    )
    record = service.create_evidence(
        sessions, execution_id=execution, step_id=step["id"], project_id=pid,
        files={filename: {"sha256": "a" * 64, "bytes": 40}},
        tool_calls=[], verification={}, review_result={}, commit="",
        evidence_path="/local/evidence.json", evidence_sha256="",
        verdict="PASS", logs=["private trace not for model"],
    )
    service.create_audit(
        sessions, project_id=pid, phase_id=phase["id"], step_id=step["id"],
        execution_id=execution, plan_version=plan["version"], findings={},
        evidence_refs=[record], commit_sha="", tests={}, verdict="PASS",
    )
    service.update_execution(sessions, execution, status="COMPLETED")
    service.update_step(sessions, step["id"], status="COMPLETED",
                        evidence_id=record, current_execution_id=execution)
    return record


def test_project_status_and_latest_output_from_same_evidence_as_ui(api_env, monkeypatch):
    sessions = api_env["sessions"]
    project = service.create_project(sessions, name="مشروع قبول", objective="بناء موقع")
    other = service.create_project(sessions, name="مشروع ثان", objective="مهمة أخرى")
    _record_output(sessions, project, "older.html")
    newest = _record_output(sessions, project, "latest.html")
    _record_output(sessions, other, "other-project.html")
    captured = []

    # Controlled test provider, not production model evidence. Generate the
    # response only from the context actually delivered by the chat handler.
    def capture(messages, *, on_delta, **kwargs):
        import json

        note = messages[0].content
        captured.append(note)
        label = "أحدث المخرجات المسجّلة للمشروع، مرتبة من الأحدث: "
        rows = json.loads(note.split(label, 1)[1].splitlines()[0])
        status_line = next(line for line in note.splitlines() if line.startswith("الحالة: "))
        answer = f"{status_line}\nآخر مخرج مسجّل: {rows[0]['name']}"
        on_delta(answer)
        return api_env["router"]._wrap(answer, kwargs["provider_id"], kwargs["model"]) | {"streamed": True}

    monkeypatch.setattr(api_env["router"], "chat_live_stream", capture)
    client = TestClient(routes.app)
    api_url = f"/api/projects/{project['id']}"
    state_before = client.get(api_url + "/state").json()
    outputs = client.get(api_url + "/artifacts").json()["artifacts"]
    assert outputs[0]["name"] == "latest.html" and outputs[0]["evidence_id"] == newest
    response = client.post("/api/chat/stream", json={
        "message": "ما حالة هذا المشروع، وما آخر مخرج محفوظ؟",
        "project_id": project["id"], "web": "off",
    })
    assert response.status_code == 200
    events = sse_events(response)
    assert any(e["kind"] == "message_completed" for e in events)
    cid = next(e for e in events if e["kind"] == "conversation.bind")["scope"]["conversation_id"]
    assert len(captured) == 1
    note = captured[0]
    assert f"الحالة: {project['status']}" in note
    assert note.index("latest.html") < note.index("older.html")
    assert f'"evidence_id": {newest}' in note
    assert "other-project.html" not in note
    assert "private trace not for model" not in note
    assert "/local/evidence.json" not in note
    saved = client.get(f"/api/conversations/{cid}/messages").json()["messages"]
    assert saved[-1]["role"] == "assistant" and saved[-1]["state_badge"] == "COMPLETED"
    assert saved[-1]["content"] == f"الحالة: {project['status']}\nآخر مخرج مسجّل: latest.html"
    assert client.get(api_url + "/state").json() == state_before


def test_outputs_context_omitted_unless_requested_and_unavailable_not_empty(api_env, monkeypatch):
    from api import projects

    p = service.create_project(
        api_env["sessions"], name="مشروع بلا مخرجات", objective="مراجعة خطة",
    )
    assert routes._project_chat_outputs(p["id"], "ماذا تفعل؟") == ""
    assert "لا تظهر مخرجات محفوظة" in routes._project_chat_outputs(p["id"], "ما آخر مخرج؟")

    def failed_read(_project_id):
        raise RuntimeError("private connection details")

    monkeypatch.setattr(projects, "project_artifacts", failed_read)
    note = routes._project_chat_outputs(p["id"], "ما آخر مخرج؟")
    assert "تعذّر قراءة سجل المخرجات" in note
    assert "لا تظهر مخرجات" not in note
    assert "private connection details" not in note
