"""اختبارات المهمة الحية — المسار الرئيسي (الأمر 006 §1+§2+§15 Task).

العقد: المهمة تمر بالأدوار الحية عبر build_live_orchestrator حصرًا،
كل دور يستلم provider/model الخاص به (لا توريث بين الأدوار)، لا
build_mock_orchestrator في مسار الإنتاج، وتعذر المزود =
CONFIGURATION_REQUIRED صريح يسمي الدور — لا سقوط إلى mock.
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


def test_task_live_cycle_passes_and_persists_conversation(client, api_env):
    """مهمة كاملة عبر المسار الحي: دورة PASS + محادثة مرتبطة (§14)."""
    resp = client.post("/api/cycle/stream", json={
        "goal": "اكتب تقريرًا قصيرًا عن موضوع المهمة",
    })
    assert resp.status_code == 200, resp.text[:400]
    events = sse_events(resp)
    kinds = [e["kind"] for e in events]

    assert "task.conversation" in kinds
    assert "task_done" in kinds
    done = next(e for e in events if e["kind"] == "task_done")
    assert done["verdict"] == "PASS", done["details"]["verdict_reasons"]
    assert done["details"]["final_state"] == "EVIDENCED"

    # الأدوار الخمسة عملت فعلًا — أحداثها في البث
    for kind in ("plan", "review_verdict", "task_execution",
                 "task_verification"):
        assert kind in kinds, f"{kind} مفقود من البث"

    # المحادثة: قائمة حقيقية بنمط مهمة + رسالة هدف + خلاصة الحكم
    conversation_id = next(
        e for e in events if e["kind"] == "task.conversation"
    )["details"]["conversation_id"]
    listing = client.get("/api/conversations").json()["conversations"]
    mine = [c for c in listing if c["conversation_id"] == conversation_id]
    assert mine and mine[0]["mode"] == "task"
    assert "تقريرًا قصيرًا" in mine[0]["title"]

    history = client.get(
        f"/api/conversations/{conversation_id}/messages"
    ).json()["messages"]
    assert [m["role"] for m in history][:2] == ["user", "assistant"]
    # (الأمر 008 §27) الخلاصة مولَّدة من حالة الدورة: حكم + ما تم + إجراء
    assert "اكتملت المهمة" in history[1]["content"]
    assert "الحالة النهائية: EVIDENCED" in history[1]["content"]
    assert "استدعاء أداة" in history[1]["content"]


def test_task_each_role_receives_its_own_provider_and_model(client, api_env):
    """§3+§4: كل دور يستلم اختياره المستقل — لا دور يرث مزود دور آخر."""
    resp = client.post("/api/cycle/stream", json={
        "goal": "مهمة توجيه الأدوار",
        "roles": {
            "thinker": {"provider": "nvidia", "model": "model-thinker-x"},
            "reviewer": {"provider": "zai-test", "model": "model-reviewer-y"},
            "verifier": {"provider": "openrouter-test",
                         "model": "model-verifier-z"},
        },
    })
    assert resp.status_code == 200
    events = sse_events(resp)
    done = next(e for e in events if e["kind"] == "task_done")
    assert done["verdict"] == "PASS", done["details"]["verdict_reasons"]

    calls = api_env["router"].calls
    # الاستدعاءات تحمل الاختيارات المستقلة كما عُيّنت لكل دور
    by_pair = {(c["provider"], c["model"]) for c in calls}
    assert ("nvidia", "model-thinker-x") in by_pair, "المفكر لم يستلم اختياره"
    assert ("zai-test", "model-reviewer-y") in by_pair, "المدقق لم يستلم اختياره"
    assert ("openrouter-test", "model-verifier-z") in by_pair, "المراجع لم يستلم اختياره"
    # الأدوار بلا تخصيص = الافتراضي المعلن (nvidia/nemotron الافتراضي)
    assert any(c["model"] == "nvidia/nemotron-3-ultra-550b-a55b" for c in calls), (
        "الدور غير المخصص يجب أن يستخدم الافتراضي المعلن"
    )


def test_task_configuration_required_when_role_provider_missing(
    client, api_env
):
    """§1: دور بمزود غير محلول = CONFIGURATION_REQUIRED يسمي الدور."""
    api_env["router"]._providers = {"nvidia"}  # zai-test غير متاح
    resp = client.post("/api/cycle/stream", json={
        "goal": "مهمة بمزود غائب لأحد الأدوار",
        "roles": {"reviewer": {"provider": "zai-test", "model": "m"}},
    })
    assert resp.status_code == 200
    events = sse_events(resp)
    req = [e for e in events if e["kind"] == "CONFIGURATION_REQUIRED"]
    assert req, [e.get("kind") for e in events]
    assert req[0]["state"] == "FAILED_TO_START"
    assert "المدقق" in req[0]["text"], "الرسالة يجب أن تسمي الدور الفاشل"
    assert "zai-test" in req[0]["text"]
    # لا دورة بدأت أصلًا — لا استدعاءات ولا نجاح وهمي
    assert not api_env["router"].calls


def test_task_configuration_required_when_router_unresolvable(client, api_env):
    """§1: لا مزود حي قابل للحل أبدًا = إعلان صريح لا mock."""
    def broken_factory(**_kwargs):
        from router.model_router import ProviderCallError

        raise ProviderCallError(
            "لا مزود حي بمفتاح قابل للحل — احفظ مفتاحك من الإعدادات"
        )

    import api.routes as routes_mod

    original = routes_mod._test_router_factory
    routes_mod._test_router_factory = broken_factory
    try:
        resp = client.post("/api/cycle/stream", json={"goal": "مهمة بلا مزود"})
        assert resp.status_code == 200
        events = sse_events(resp)
        req = [e for e in events if e["kind"] == "CONFIGURATION_REQUIRED"]
        assert req
        assert "لا مزود حي" in req[0]["text"]
    finally:
        routes_mod._test_router_factory = original


def test_task_unknown_role_in_request_rejected(client, api_env):
    """دور غير معروف في الطلب = 422 صريح (لا تجاهل صامت)."""
    resp = client.post("/api/cycle/stream", json={
        "goal": "هدف",
        "roles": {"hacker-role": {"provider": "nvidia", "model": "m"}},
    })
    assert resp.status_code == 422
    assert "دور غير معروف" in resp.json()["detail"]


def test_task_concurrent_run_rejected(client, api_env, monkeypatch):
    """مهمة واحدة في كل لحظة — الثانية تُرفض 409 (قيد البنية)."""
    import threading

    gate = threading.Event()
    started = threading.Event()
    original = api_env["router"].chat_live

    def slow_chat_live(messages, **kwargs):
        started.set()
        gate.wait(timeout=10)  # يحتجز المهمة الأولى حتى نسمح
        return original(messages, **kwargs)

    api_env["router"].chat_live = slow_chat_live

    import threading as _t

    first_result: dict = {}

    def run_first():
        first_result["resp"] = client.post(
            "/api/cycle/stream", json={"goal": "مهمة أولى طويلة"}
        )

    thread = _t.Thread(target=run_first)
    thread.start()
    assert started.wait(timeout=10)
    second = client.post(
        "/api/cycle/stream", json={"goal": "مهمة ثانية متزامنة"}
    )
    assert second.status_code == 409
    gate.set()
    thread.join(timeout=60)
    assert first_result["resp"].status_code == 200
