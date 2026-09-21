"""اختبارات إعدادات النماذج (الأمر 006 §5+§13+§15 Configuration).

العقد: قراءة المزودين والاختيارات، حفظ اختيار لكل دور، ورفض نموذج
غير موجود ولا معلن — ولا قيمة مفتاح تظهر في أي رد أبدًا.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("httpx", reason="TestClient يتطلب httpx")

from api import routes  # noqa: E402


@pytest.fixture()
def client(api_env):
    return TestClient(routes.app)


def test_models_config_lists_roles_and_providers(client, api_env):
    """GET: كل الأدوار الستة + المزودون بحالتهم الصادقة."""
    body = client.get("/api/models/config").json()
    role_keys = [r["key"] for r in body["roles"]]
    assert role_keys == [
        "thinker", "reviewer", "implementer", "verifier", "arbiter", "chat"
    ]
    provider_ids = {p["id"] for p in body["providers"]}
    assert {"nvidia", "openai_compatible", "zai_internal"} <= provider_ids
    # الافتراضات المعلنة
    assert body["defaults"]["provider"] == "nvidia"
    assert body["defaults"]["model"] == "nemotron-3-ultra-550b-a55b"
    # كل دور يبدأ على الافتراضي المعلن
    assert all(r["is_default"] for r in body["roles"])


def test_models_config_save_selection_per_role(client, api_env):
    """PUT: حفظ اختيار مستقل لكل دور — ثم قراءته كما حُفظ."""
    resp = client.put("/api/models/config", json={
        "thinker": {"provider": "nvidia",
                    "model": "nemotron-3-ultra-550b-a55b"},
        "reviewer": {"provider": "nvidia",
                     "model": "nemotron-3-ultra-550b-a55b"},
        "chat": {"provider": "nvidia", "model": "nemotron-3-ultra-550b-a55b"},
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert set(body["saved"]) == {"thinker", "reviewer", "chat"}

    after = client.get("/api/models/config").json()
    by_key = {r["key"]: r for r in after["roles"]}
    assert by_key["thinker"]["selection"]["model"] == \
        "nemotron-3-ultra-550b-a55b"
    # الدور الذي لم يُحفظ بقي على الافتراضي
    assert by_key["implementer"]["is_default"] is True


def test_models_config_rejects_unknown_model(client, api_env):
    """رفض نموذج غير موجود ولا معلن — والرسالة تسمي الدور (§15)."""
    resp = client.put("/api/models/config", json={
        "arbiter": {"provider": "nvidia", "model": "model-does-not-exist"},
    })
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "arbiter" in detail  # الدور مسمّى (بمفتاحه اللاتيني الثابت)
    assert "model-does-not-exist" in detail
    assert "غير موجود" in detail


def test_models_config_rejects_unknown_provider(client, api_env):
    resp = client.put("/api/models/config", json={
        "thinker": {"provider": "not-a-provider", "model": "any"},
    })
    assert resp.status_code == 422
    assert "مزود غير معروف" in resp.json()["detail"]


def test_models_config_rejects_empty_body(client, api_env):
    resp = client.put("/api/models/config", json={})
    assert resp.status_code == 422


def test_models_config_never_leaks_api_keys(client, api_env):
    """§15 Security: لا قيمة مفتاح في أي رد — حتى مع مفتاح محفوظ."""
    from secrets_store import store as secrets

    secrets.set_key("nvidia", "nvapi-secret-key-value-123456")

    for method, url in (
        ("GET", "/api/models/config"),
        ("GET", "/api/providers"),
        ("PUT", "/api/models/config"),
    ):
        if method == "PUT":
            body = {"thinker": {"provider": "nvidia",
                                "model": "nemotron-3-ultra-550b-a55b"}}
            resp = client.put(url, json=body)
        else:
            resp = client.get(url)
        text = resp.text
        assert "nvapi-secret-key-value-123456" not in text, (
            f"تسريب مفتاح في {method} {url}"
        )
