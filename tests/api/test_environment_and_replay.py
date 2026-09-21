"""اختبارات واجهة البيئة + إعادة تشغيل الأحداث + اكتشاف النماذج
(الأمر 008 §18-§19+§35، والأمر 009 §22-§23).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("httpx", reason="TestClient يتطلب httpx")

from api import routes  # noqa: E402
from conftest import sse_events  # noqa: E402


@pytest.fixture()
def client(api_env):
    return TestClient(routes.app)


# ------------------------------------------------------------------ #
# البيئة والجاهزية (009 §22-§23)
# ------------------------------------------------------------------ #

def test_environment_readiness_lists_inventory(client, api_env):
    resp = client.get("/api/environment/readiness")
    assert resp.status_code == 200
    body = resp.json()
    ids = {c["capability_id"] for c in body["capabilities"]}
    assert {"llm", "web_search", "sandbox", "browser"} <= ids
    # الأداة غير المنفذة صادقة (§3)
    browser = [c for c in body["capabilities"]
               if c["capability_id"] == "browser"][0]
    assert browser["readiness_status"] == "UNAVAILABLE"
    assert "summary" in body


def test_environment_probe_single_writes_result(client, api_env):
    resp = client.post("/api/environment/probe", json={
        "capability_id": "filesystem",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["readiness_status"] == "READY"  # فحص ملفات حقيقي نجح
    assert body["last_probe_at"]

    state = client.get("/api/environment/readiness").json()
    fs = [c for c in state["capabilities"]
          if c["capability_id"] == "filesystem"][0]
    assert fs["readiness_status"] == "READY"
    assert fs["last_probe_at"]


def test_environment_probe_unknown_404(client, api_env):
    resp = client.post("/api/environment/probe", json={
        "capability_id": "nonexistent",
    })
    assert resp.status_code == 404


def test_environment_inventory_real_values(client, api_env):
    resp = client.get("/api/environment/inventory")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items["os"]["status"] == "READY"
    assert "Linux" in items["os"]["version"] or items["os"]["version"]
    assert items["python"]["version"]
    assert items["browser_runtime"]["status"] == "UNAVAILABLE"
    assert "network_dns" in items and "repository_access" in items


def test_environment_metrics_endpoint(client, api_env):
    resp = client.get("/api/environment/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "tool_invocations" in body["metrics"]
    assert "failure_by_class" in body


def test_readiness_survives_restart(api_env):
    """(009 §28 Restart) قراءة المسبار تبقى بعد إعادة بناء الجلسة."""
    first = TestClient(routes.app)
    first.post("/api/environment/probe", json={
        "capability_id": "git"})
    # جلسة جديدة فوق نفس القاعدة — القراءة باقية
    state = first.get("/api/environment/readiness").json()
    git = [c for c in state["capabilities"]
           if c["capability_id"] == "git"][0]
    assert git["readiness_status"] in ("READY", "NOT_READY")
    assert git["last_probe_at"] is not None


# ------------------------------------------------------------------ #
# إعادة تشغيل الأحداث (008 §19+§33)
# ------------------------------------------------------------------ #

def test_cycle_events_replay_after_seq(client, api_env):
    """بعد اكتمال مهمة: طلب الأحداث بعد seq يعيد ما بعده حصرًا —
    لا إعادة من الصفر ولا فقد (§19)."""
    run = client.post("/api/cycle/stream", json={
        "goal": "اكتب تقريرًا قصيرًا عن موضوع المهمة"})
    assert run.status_code == 200
    events = sse_events(run)
    assert any(e["kind"] == "task_done" for e in events)
    seqs = [e["seq"] for e in events if e.get("seq")]
    cycle_id = next(e["cycle_id"] for e in events if e.get("cycle_id"))

    # إعادة التشغيل الكاملة: كل الأحداث بلا تكرار seq
    full = sse_events(client.get(
        f"/api/cycle/events/{cycle_id}?after=0"))
    # stream.done علامة تحكم (تحمل seq آخر حدث) — ليست حدث محتوى
    full_seqs = [e["seq"] for e in full
                 if e.get("seq") and e.get("kind") != "stream.done"]
    assert full_seqs == sorted(full_seqs)
    assert len(full_seqs) == len(set(full_seqs))   # لا نسخ مكررة
    assert any(e["kind"] == "task_done" for e in full)

    # بعد seq معين: ما بعده حصرًا
    cut = full_seqs[len(full_seqs) // 2]
    tail = sse_events(client.get(
        f"/api/cycle/events/{cycle_id}?after={cut}"))
    tail_seqs = [e["seq"] for e in tail if e.get("seq")]
    assert tail_seqs and min(tail_seqs) > cut
    assert all(s > cut for s in tail_seqs)


def test_chat_events_replay_no_duplicate_chunks(client, api_env):
    """محادثة: إعادة تشغيل أحداثها بعد seq — بلا قطع مكررة (§19)."""
    first = sse_events(client.post("/api/chat/stream", json={
        "message": "سؤال إعادة التشغيل"}))
    started = [e for e in first if e["kind"] == "message_started"][0]
    conversation_id = started["details"]["conversation_id"]

    replay = sse_events(client.get(
        f"/api/chat/events/{conversation_id}?after=0"))
    deltas = [e for e in replay if e["kind"] == "message_delta"]
    assert deltas
    seqs = [e["seq"] for e in replay
            if e.get("seq") and e.get("kind") != "stream.done"]
    assert len(seqs) == len(set(seqs))             # لا تكرار
    # النص المُعاد تركيبه = نفس النص الكامل (بلا فقد قطع)
    rebuilt = "".join(d["delta"] for d in deltas)
    assert rebuilt.strip()
    assert any(e["kind"] == "message_completed" for e in replay)


def test_cycle_active_reports_running_or_idle(client, api_env):
    resp = client.get("/api/cycle/active")
    assert resp.status_code == 200
    assert resp.json()["running"] in (True, False)


# ------------------------------------------------------------------ #
# اكتشاف النماذج (008 §7-§9+§35) — لا قائمة من نموذجين
# ------------------------------------------------------------------ #

def test_configuration_models_live_discovery_merges(client, api_env):
    """اكتشاف حي: القائمة المكتشفة تُدمج مع المعلنة — أكثر من
    نموذجين، بلا اقتطاع (§35: العدد الفعلي لا رقم مزروع)."""
    # تكوين بموديلين معلنين فقط — كما كانت المشكلة
    providers = client.get("/api/providers").json()["providers"]
    target = providers[0]
    cfg = target["configurations"][0]
    declared = cfg["models"] or [cfg["default_model"]]

    stub_models = [f"vendor/model-{i}" for i in range(7)]  # > 2 حصرًا

    def fake_refresh(sessions, config_id, **_kw):
        from providers_registry import registry as reg
        merged = sorted(set(stub_models) | set(declared))
        reg.update_configuration(sessions, config_id, models=merged)
        return {"ok": True, "source": "live",
                "model_ids": merged[:200], "models_count": len(merged)}

    from providers_registry import registry as reg
    original = reg.refresh_models
    reg.refresh_models = fake_refresh
    try:
        resp = client.get(
            f"/api/provider-configurations/{cfg['id']}/models?live=1")
    finally:
        reg.refresh_models = original

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["models_count"] >= 7            # القائمة الكاملة لا نموذجان
    assert len(body["model_ids"]) == body["models_count"]
    # المكتشف دُمج في القاعدة — اختياره يصبح صالحًا فورًا
    state = client.get("/api/models/config").json()
    provider = [p for p in state["providers"]
                if p["id"] == target["name"]][0]
    models_now = provider["configurations"][0]["models"]
    assert len(models_now) >= 7
    assert "vendor/model-3" in models_now


def test_manual_model_still_works_when_discovery_fails(client, api_env):
    """فشل الاكتشاف = رسالة صادقة، والمعلن يبقى متاحًا (§9)."""
    providers = client.get("/api/providers").json()["providers"]
    cfg = providers[0]["configurations"][0]

    from providers_registry import registry as reg

    def broken_refresh(sessions, config_id, **_kw):
        return {"ok": False, "source": "declared",
                "model_ids": reg._cfg_models(
                    reg.get_configuration(sessions, config_id)),
                "message": "تعذر الجلب الحي — النماذج المعلنة فقط"}

    original = reg.refresh_models
    reg.refresh_models = broken_refresh
    try:
        resp = client.get(
            f"/api/provider-configurations/{cfg['id']}/models?live=1")
    finally:
        reg.refresh_models = original

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "تعذر" in body["message"]
    assert body["model_ids"]                  # المعلن بقي متاحًا
