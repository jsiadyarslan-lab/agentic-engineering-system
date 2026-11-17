"""AES Chat Factory integration acceptance — source of truth is real AES API.

All model responses in these tests use the explicit, isolated scripted
router supplied by api_env. Production never imports test fixtures.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import routes
from conftest import sse_events

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "src" / "ui"


@pytest.fixture()
def client(api_env):
    return TestClient(routes.app)


def _create_project(client, name):
    response = client.post("/api/projects", json={
        "name": name,
        "objective": "إنشاء موقع هندسي قابل للاختبار والتسليم",
        "execution_policy": "STRICT_ISOLATED",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _chat(client, *, project_id, conversation_id=None):
    response = client.post("/api/chat/stream", json={
        "message": "ما الحالة المعتمدة للمشروع؟",
        "project_id": project_id,
        "conversation_id": conversation_id,
        "provider": "zai-test",
        "model": "glm-test-4.6",
    })
    return response


def test_scoped_chat_binds_before_any_stream_event(client):
    pid = _create_project(client, "Chat Factory scope A")
    response = _chat(client, project_id=pid)
    assert response.status_code == 200, response.text
    events = sse_events(response)
    assert events[0]["kind"] == "conversation.bind"
    cid = events[0]["details"]["conversation_id"]
    assert events[0]["scope"]["project_id"] == pid
    assert all(
        event.get("scope", {}).get("project_id") == pid
        for event in events if not event["kind"].startswith("stream.")
    )
    assert client.get(f"/api/conversations/{cid}").json()["project_id"] == pid
    assert len(client.get(
        f"/api/projects/{pid}/conversations"
    ).json()["conversations"]) == 1


def test_cross_project_conversation_rejected_before_append(client):
    a = _create_project(client, "Chat Factory A")
    b = _create_project(client, "Chat Factory B")
    cid = sse_events(_chat(client, project_id=a))[0]["details"]["conversation_id"]
    before = client.get(f"/api/conversations/{cid}/messages").json()["messages"]
    response = _chat(client, project_id=b, conversation_id=cid)
    assert response.status_code == 409
    after = client.get(f"/api/conversations/{cid}/messages").json()["messages"]
    assert after == before
    assert client.get(f"/api/conversations/{cid}").json()["project_id"] == a


def test_unknown_project_rejected_without_orphan_chat(client):
    before = len(client.get("/api/conversations").json()["conversations"])
    response = _chat(client, project_id=999999)
    assert response.status_code == 404
    assert len(client.get("/api/conversations").json()["conversations"]) == before


def test_chat_factory_page_and_real_assets_served(client):
    response = client.get("/workspace")
    assert response.status_code == 200
    assert "مصنع الهندسة" in response.text
    assert "chat-workspace.js" in response.text
    assert "chat-workspace.css" in response.text
    etag = response.headers["etag"]
    assert client.get("/workspace", headers={"If-None-Match": etag}).status_code == 304
    for path in ("factory_chat.html", "chat-workspace.js", "chat-workspace.css"):
        assert client.get("/static/" + path).status_code == 200


def test_interaction_contract_has_no_simulated_execution():
    html = (UI / "factory_chat.html").read_text("utf-8")
    js = (UI / "chat-workspace.js").read_text("utf-8")
    css = (UI / "chat-workspace.css").read_text("utf-8")
    for text in (
        "/api/projects", "/api/chat/stream", "/api/conversations/",
        "/artifacts/content", "/plan/generate", "/plan/approve",
        "/resume", "/preflight", "/gates/", "/api/chat/active",
        "/api/chat/events/",
    ):
        assert text in js
    for anchor in ("id=\"thread\"", "id=\"sidebar\"", "id=\"inspector\"",
                   "id=\"composer-form\"", "id=\"prompt\""):
        assert anchor in html
    assert "window.confirm(confirmText)" in js
    assert "project_id:state.route.pid||null" in js
    assert "const scope=event.scope||{}" in js
    assert "handleStreamEvent" in js
    assert "request(" in js and "data-action" in js
    assert "@media(max-width:620px)" in css
    assert "fixture" not in js.lower()
    assert "fake" not in js.lower()
    assert "محاكاة" not in js


def test_js_compiles_when_node_is_available():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js not installed on runner")
    result = subprocess.run(
        [node, "--check", str(UI / "chat-workspace.js")],
        text=True, capture_output=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
