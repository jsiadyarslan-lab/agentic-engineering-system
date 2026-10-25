"""اختبارات إدارة المزودين (الأمر 007.1) — CRUD + جاهزية + عزل + أسرار.

كل سيناريو مطلوب في §19 من الأمر 007.1: إنشاء/تعديل/حذف المزود
والتكوينات، تصنيف الجاهزية الصادق (READY/AUTH_FAILED/NOT_FOUND/
RATE_LIMITED/MODEL_NOT_FOUND/NETWORK_ERROR/INVALID_CONFIGURATION)،
عزل إخفاق المزود الفاشل عن السليم، دوام الربط بعد إعادة التشغيل،
وتشخيص NVIDIA المنظم (§7) — وتقنيع الأسرار في كل مخرج.
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path

import pytest

pytest.importorskip("httpx", reason="TestClient يتطلب httpx")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from api import routes  # noqa: E402
from providers_registry import registry  # noqa: E402


@pytest.fixture()
def prov_env(tmp_path, monkeypatch):
    """قاعدة معزولة + مخزن أسرار معزول — لا اعتماد على حالة الجهاز."""
    from persistence.database import build_engine, init_db, make_session_factory
    from secrets_store import store as store_mod

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(store_mod, "RUNTIME_DIR", tmp_path)
    store_mod._invalidate_known_cache()

    engine = build_engine(tmp_path / "providers.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    monkeypatch.setattr(routes, "_sessions", sessions)
    registry.ensure_seeded(sessions)
    yield {"sessions": sessions, "db_path": tmp_path / "providers.db",
           "tmp_path": tmp_path}
    store_mod._invalidate_known_cache()


@pytest.fixture()
def client(prov_env):
    return TestClient(routes.app)


def _provider_id(client, name: str) -> int:
    for provider in client.get("/api/providers").json()["providers"]:
        if provider["name"] == name:
            return provider["id"]
    raise AssertionError(f"مزود غير موجود: {name}")


def _primary_config_id(client, name: str) -> int:
    providers = client.get("/api/providers").json()["providers"]
    for provider in providers:
        if provider["name"] == name:
            for cfg in provider["configurations"]:
                if cfg["is_primary"]:
                    return cfg["id"]
    raise AssertionError(f"لا تكوين أساسي لـ: {name}")


# ------------------------------------------------------------------ #
# §19 Provider — إنشاء/دوام/تعديل/حذف
# ------------------------------------------------------------------ #

def test_create_provider_and_persist_after_restart(client, prov_env):
    """إنشاء مزود من الواجهة ← دوام بعد إعادة تشغيل (قاعدة جديدة)."""
    created = client.post("/api/providers", json={
        "name": "my_provider", "display_name": "مزودي الخاص",
        "base_url": "https://api.example.com/v1",
        "default_model": "model-x", "models": ["model-x"],
        "api_key": "sk-test-12345678",
    })
    assert created.status_code == 201, created.text
    provider = created.json()["provider"]
    assert provider["name"] == "my_provider"
    assert provider["has_key"] is True
    assert provider["key_masked"] == "****5678"
    assert "sk-test-12345678" not in json.dumps(provider)  # لا سرّ أبدًا

    # إعادة تشغيل محاكاة: مصنع جلسات جديد على نفس الملف
    from persistence.database import make_session_factory
    from sqlalchemy import create_engine

    engine2 = create_engine(
        f"sqlite:///{prov_env['db_path']}",
        connect_args={"check_same_thread": False},
    )
    sessions2 = make_session_factory(engine2)
    reloaded = registry.get_provider(sessions2, provider["id"])
    assert reloaded is not None, "المزود ضاع بعد إعادة التشغيل!"
    assert reloaded["name"] == "my_provider"
    assert reloaded["configurations"][0]["base_url"] == \
        "https://api.example.com/v1"
    # المفتاح في مخزن الأسرار لا في القاعدة
    from secrets_store import store as store_mod

    assert store_mod.get_key("my_provider") == "sk-test-12345678"
    with open(prov_env["db_path"], "rb") as handle:
        assert b"sk-test-12345678" not in handle.read(), \
            "المفتاح تسرب إلى ملف القاعدة!"


def test_update_and_delete_provider(client):
    """تعديل المزود ثم حذفه — المحمي بالربط يُرفض حذفه."""
    pid = _provider_id(client, "openai_compatible")
    updated = client.put(f"/api/providers/{pid}", json={
        "display_name": "OpenRouter المعدل",
    })
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "OpenRouter المعدل"

    # nvidia مرتبط بكل الأدوار (البذر) — الحذف مرفوض
    nvidia_id = _provider_id(client, "nvidia")
    clash = client.delete(f"/api/providers/{nvidia_id}")
    assert clash.status_code == 422
    assert "الأدوار" in clash.json()["detail"]

    # openai_compatible غير مرتبط — الحذف ينجح
    deleted = client.delete(f"/api/providers/{pid}")
    assert deleted.status_code == 200
    assert client.get(f"/api/providers/{pid}").status_code == 404


def test_duplicate_and_invalid_names_rejected(client):
    clash = client.post("/api/providers", json={
        "name": "nvidia", "base_url": "https://x.example.com/v1",
    })
    assert clash.status_code == 422
    bad = client.post("/api/providers", json={
        "name": "Invalid Name!", "base_url": "https://x.example.com/v1",
    })
    assert bad.status_code == 422


# ------------------------------------------------------------------ #
# §19 Configuration — إضافة/تعديل/حذف Base URL
# ------------------------------------------------------------------ #

def test_add_edit_delete_base_url(client):
    """إضافة تكوين ← تعديل عنوانه ← حذفه — كله من الواجهة بلا كود."""
    pid = _provider_id(client, "nvidia")
    # إضافة تكوين ثانٍ (Base URL بديل لنفس المزود)
    added = client.post(f"/api/providers/{pid}/configurations", json={
        "name": "nvidia-custom-endpoint",
        "base_url": "https://alt.api.nvidia.com/v1",
        "default_model": "alt-model", "models": ["alt-model"],
    })
    assert added.status_code == 201, added.text
    cfg_id = added.json()["configuration"]["id"]

    # تعديل الـBase URL — من الواجهة لا من المصدر (§4)
    edited = client.put(f"/api/provider-configurations/{cfg_id}", json={
        "base_url": "https://alt2.api.nvidia.com/v1",
    })
    assert edited.status_code == 200
    assert edited.json()["base_url"] == "https://alt2.api.nvidia.com/v1"

    # عنوان غير صالح يُرفض بصراحة
    invalid = client.put(f"/api/provider-configurations/{cfg_id}", json={
        "base_url": "not-a-url",
    })
    assert invalid.status_code == 422

    # الحذف ينجح (غير مستخدم بأي دور)
    deleted = client.delete(f"/api/provider-configurations/{cfg_id}")
    assert deleted.status_code == 200

    # التكوين الوحيد لا يُحذف
    primary = _primary_config_id(client, "nvidia")
    alone = client.delete(f"/api/provider-configurations/{primary}")
    assert alone.status_code == 422
    assert "التكوين الوحيد" in alone.json()["detail"]


def test_configured_configuration_protected_from_delete(client):
    """التكوين المستخدم من دور ما محمي من الحذف غير الآمن (§4)."""
    pid = _provider_id(client, "nvidia")
    added = client.post(f"/api/providers/{pid}/configurations", json={
        "name": "nvidia-prod", "base_url": "https://prod.example.com/v1",
        "default_model": "p-model", "models": ["p-model"],
    })
    cfg_id = added.json()["configuration"]["id"]
    # اربط دور المفكر بهذا التكوين
    saved = client.put("/api/models/config", json={
        "thinker": {"provider": "nvidia",
                    "configuration": "nvidia-prod",
                    "model": "p-model"},
    })
    assert saved.status_code == 200, saved.text
    clash = client.delete(f"/api/provider-configurations/{cfg_id}")
    assert clash.status_code == 422
    assert "مستخدم" in clash.json()["detail"]


# ------------------------------------------------------------------ #
# §19 Readiness — التصنيف الصادق لكل حالة
# ------------------------------------------------------------------ #

def _probe_with(client, prov_env, provider_name, responder):
    """تشغيل مسبار الجاهزية بنقل مزيف — يصنف استجابة المزود."""
    config_id = _primary_config_id(client, provider_name)
    monkey_holder = {}

    def fake_fetch(url, headers, timeout, method="GET", body=None):
        return responder(url, headers, method, body, monkey_holder)

    import unittest.mock as mock

    with mock.patch.object(registry, "_http_fetch_real", fake_fetch):
        result = client.post(
            f"/api/provider-configurations/{config_id}/test"
        ).json()
    return result, monkey_holder


def test_readiness_ready_with_models(client, prov_env):
    """200 مع نماذج ← READY — ولا MODEL_NOT_FOUND للنموذج المعلن."""
    from secrets_store import store as store_mod

    store_mod.set_key("nvidia", "nvapi-KEY-000111")

    def ok_models(url, headers, method, body, holder):
        holder["url"] = url
        holder["auth"] = headers.get("Authorization", "")
        return 200, json.dumps(
            {"data": [{"id": "nvidia/nemotron-3-ultra-550b-a55b"}]}
        )

    result, holder = _probe_with(client, prov_env, "nvidia", ok_models)
    assert result["status"] == "READY"
    assert result["http_status"] == 200
    assert result["error_code"] is None
    # التشخيص المنظم (§7): العنوان النهائي والمصادقة المقنعة
    assert holder["url"] == "https://integrate.api.nvidia.com/v1/models"
    assert holder["auth"] == "Bearer nvapi-KEY-000111"
    assert result["diagnosis"]["auth"] == "Authorization: Bearer [REDACTED]"
    assert "nvapi-KEY" not in json.dumps(result), "المفتاح تسرب في النتيجة!"
    # الجاهزية دوّمت على التكوين
    config_id = _primary_config_id(client, "nvidia")
    providers = client.get("/api/providers").json()["providers"]
    for provider in providers:
        if provider["name"] == "nvidia":
            for cfg in provider["configurations"]:
                if cfg["id"] == config_id:
                    assert cfg["readiness"]["status"] == "READY"


def test_readiness_classification_matrix(client, prov_env):
    """كل حالة HTTP ← تصنيفها الصريح (§8) — لا «LIVE» كذبًا."""
    from secrets_store import store as store_mod

    store_mod.set_key("nvidia", "nvapi-KEY-000111")
    cases = [
        (401, "AUTH_FAILED"), (403, "AUTH_FAILED"), (404, None),
        (429, "RATE_LIMITED"), (503, "UNKNOWN_ERROR"),
    ]
    for status, expected in cases:
        def responder(url, headers, method, body, holder,
                      _status=status):
            if _status == 404:
                # 404 على /models: مسبار chat يحدد موقع المشكلة فعلًا
                if url.endswith("/chat/completions"):
                    raise urllib.error.HTTPError(
                        url, 404, "404 page not found", {}, None
                    )  # type: ignore[arg-type]
                raise urllib.error.HTTPError(
                    url, 404, "404 page not found", {}, None
                )  # type: ignore[arg-type]
            raise urllib.error.HTTPError(
                url, _status, f"HTTP {_status}", {}, None
            )  # type: ignore[arg-type]

        result, _ = _probe_with(client, prov_env, "nvidia", responder)
        if expected:
            assert result["status"] == expected, (
                f"HTTP {status} صنف {result['status']} بدل {expected}"
            )
        else:
            # 404 على المسارين معًا = NOT_FOUND (حالة NVIDIA الحرفية)
            assert result["status"] == "NOT_FOUND"
            assert result["diagnosis"]["problem"] == "url"


def test_readiness_model_not_found(client, prov_env):
    """/models يعمل لكن النموذج غير موجود في القائمة ← MODEL_NOT_FOUND."""
    from secrets_store import store as store_mod

    store_mod.set_key("nvidia", "nvapi-KEY-000111")

    def models_without_ours(url, headers, method, body, holder):
        return 200, json.dumps({"data": [{"id": "other-model-1"},
                                         {"id": "other-model-2"}]})

    result, _ = _probe_with(client, prov_env, "nvidia", models_without_ours)
    assert result["status"] == "MODEL_NOT_FOUND"
    assert "nemotron" in result["error_message"]
    assert result["diagnosis"]["problem"] == "model"
    assert result["diagnosis"]["available_models_sample"] == [
        "other-model-1", "other-model-2",
    ]


def test_readiness_network_and_invalid(client, prov_env):
    """خطأ شبكة ← NETWORK_ERROR — ومفتاح مفقود ← INVALID_CONFIGURATION."""
    from secrets_store import store as store_mod

    store_mod.set_key("nvidia", "nvapi-KEY-000111")

    def network_down(url, headers, method, body, holder):
        raise ConnectionError("no route to host")

    result, _ = _probe_with(client, prov_env, "nvidia", network_down)
    assert result["status"] == "NETWORK_ERROR"
    assert result["diagnosis"]["problem"] == "network"

    # حذف المفتاح ← فحص المصادقة يسبق الشبكة (لا نداء أعمى بلا مفتاح)
    store_mod.delete_key("nvidia")

    def never_called(url, headers, method, body, holder):
        raise AssertionError("المسبار نادى الشبكة بلا مفتاح!")

    result, _ = _probe_with(client, prov_env, "nvidia", never_called)
    assert result["status"] == "INVALID_CONFIGURATION"
    assert "لا مفتاح" in result["error_message"]
    assert result["diagnosis"]["problem"] == "authentication"


def test_readiness_unsupported_api_style(client, prov_env):
    """نمط API غير مدعوم ← UNSUPPORTED — المحول مسؤول عن الطلب (§6)."""
    pid = _provider_id(client, "nvidia")
    added = client.post(f"/api/providers/{pid}/configurations", json={
        "name": "weird-style", "base_url": "https://x.example.com/v1",
        "api_style": "grpc",
    })
    assert added.status_code == 422  # نمط غير معروف يُرفض عند الإضافة

    # custom مقبول كنمط مفهوم لكن لا محول مسجل له بعد — المسبار
    # يعلن UNSUPPORTED بصدق ولا يستدعي الشبكة عمياء (§6)
    added2 = client.post(f"/api/providers/{pid}/configurations", json={
        "name": "custom-style", "base_url": "https://y.example.com/v1",
        "api_style": "custom",
    })
    assert added2.status_code == 201
    import unittest.mock as mock

    def never_called(*args, **kwargs):
        raise AssertionError("نُودي النقل رغم نمط API بلا محول!")

    with mock.patch.object(registry, "_http_fetch_real", never_called):
        result = client.post(
            f"/api/provider-configurations/{added2.json()['configuration']['id']}/test"
        ).json()
    assert result["status"] == "UNSUPPORTED"
    assert result["diagnosis"]["problem"] == "api_style"
    assert "لا محول" in result["error_message"]

    # التكوين بنمط custom لا يُسجل كنقل حي أبدًا (لا استدعاء أعمى)
    specs = registry.resolve_provider_specs(prov_env["sessions"])
    assert not any("custom-style" in key for key in specs)


# ------------------------------------------------------------------ #
# §19 Role mapping — ربط الأدوار يدوم
# ------------------------------------------------------------------ #

def test_role_mapping_persists_and_reloads(client, prov_env):
    """ربط دور ← مزود/تكوين/نموذج يدوم بعد إعادة التشغيل (§10+§15)."""
    saved = client.put("/api/models/config", json={
        "thinker": {"provider": "zai_internal", "model": "glm-4.6"},
        "reviewer": {"provider": "zai_internal", "model": "glm-4.6"},
        "chat": {"provider": "zai_internal", "model": "glm-4.6"},
    })
    assert saved.status_code == 200, saved.text

    # إعادة تشغيل: جلسة جديدة على نفس الملف
    from persistence.database import make_session_factory
    from sqlalchemy import create_engine

    engine2 = create_engine(
        f"sqlite:///{prov_env['db_path']}",
        connect_args={"check_same_thread": False},
    )
    sessions2 = make_session_factory(engine2)
    mappings = registry.get_mappings(sessions2)
    assert mappings["thinker"] == {
        "provider": "zai_internal", "configuration": "", "model": "glm-4.6",
    }
    assert mappings["chat"]["model"] == "glm-4.6"
    # الدور الذي لم يُحدد بقي على الافتراضي
    assert mappings["implementer"]["provider"] == "nvidia"


# ------------------------------------------------------------------ #
# §19 Failure isolation — المزود الفاشل لا يمنع السليم
# ------------------------------------------------------------------ #

def test_failing_provider_does_not_block_healthy_one(client, prov_env):
    """NVIDIA غير جاهز وzai جاهز ← zai يُستخدم بلا تبدل ولا mock (§9).

    مصادقة zai_internal عبر مسار ملف الإعدادات الحقيقي نفسه (JSON:
    apiKey) لكن من ملف مؤقت يكتبه الاختبار — الاعتماد على ملف المضيف
    /etc/.z-ai-config (منشأة الحاوية حصرًا) جعل الاختبار يفشل على أي
    مضيف بلا الملف كأن السليم استُبعد؛ هنا الآلية حقيقية والحتمية
    عبر المنصات.
    """
    sessions = prov_env["sessions"]
    factory_cfg = prov_env["tmp_path"] / "zai_factory_auth.json"
    factory_cfg.write_text(json.dumps({
        "baseUrl": "https://internal-api.z.ai/v1",
        "apiKey": "test-factory-key-013",
    }, ensure_ascii=False), encoding="utf-8")
    updated = client.put(
        f"/api/provider-configurations/"
        f"{_primary_config_id(client, 'zai_internal')}",
        json={"config_file": str(factory_cfg)},
    )
    assert updated.status_code == 200, updated.text
    # nvidia بلا مفتاح في هذا المخزن المعزول ← مستبعد من الحل
    # zai_internal: مصادقته من ملف الإعدادات (المسار المحدّث) ← يُحل
    specs = registry.resolve_provider_specs(sessions)
    assert "zai_internal" in specs, "السليم استُبعد مع الفاشل!"
    assert specs["zai_internal"]["base_url"].startswith("https://")
    assert specs["zai_internal"].get("api_key"), "ملف المصادقة لم يُحل"
    # nvidia بلا مفتاح: لا نقل له — لا يُنادى أبدًا
    assert "nvidia" not in specs or specs["nvidia"].get("api_key"), (
        "nvidia حُل بلا مفتاح — انتهاك الفشل الصريح"
    )


def test_transport_key_per_configuration(client, prov_env):
    """تكوينات متعددة ← مفاتيح نقل متعددة (مزود::تكوين) — §5."""
    pid = _provider_id(client, "nvidia")
    added = client.post(f"/api/providers/{pid}/configurations", json={
        "name": "nvidia-eu", "base_url": "https://eu.api.nvidia.com/v1",
        "default_model": "eu-model", "models": ["eu-model"],
    })
    assert added.status_code == 201
    from router.role_config import RoleSelection

    primary = RoleSelection("nvidia", "model-a")
    secondary = RoleSelection("nvidia", "model-b", "nvidia-eu")
    assert primary.transport_key() == "nvidia"
    assert secondary.transport_key() == "nvidia::nvidia-eu"


# ------------------------------------------------------------------ #
# §22 الأسرار — لا مفتاح في أي مخرج
# ------------------------------------------------------------------ #

def test_no_secret_anywhere_in_responses(client, prov_env):
    """المفتاح لا يظهر في أي نقطة: قائمة/تفصيل/اختبار/نماذج (§22)."""
    from secrets_store import store as store_mod

    secret = "nvapi-SUPERSECRET-424242"
    store_mod.set_key("nvidia", secret)
    config_id = _primary_config_id(client, "nvidia")

    import unittest.mock as mock

    def fake_fetch(url, headers, timeout, method="GET", body=None):
        return 200, json.dumps({"data": [{"id": "m"}]})

    with mock.patch.object(registry, "_http_fetch_real", fake_fetch):
        for response in (
            client.get("/api/providers"),
            client.get(f"/api/providers/{_provider_id(client, 'nvidia')}"),
            client.get("/api/models/config"),
            client.post(f"/api/provider-configurations/{config_id}/test"),
            client.post(
                f"/api/providers/{_provider_id(client, 'nvidia')}/models/refresh"
            ),
        ):
            assert secret not in response.text, (
                f"المفتاح ظهر في {response.request.url}"
            )


def test_provider_events_logged_without_secrets(client, prov_env):
    """أحداث المزودين مسجلة (007.1 §16) — وبلا أسرار."""
    created = client.post("/api/providers", json={
        "name": "logged_provider", "base_url": "https://log.example.com/v1",
        "api_key": "sk-LOGKEY-999999",
    })
    assert created.status_code == 201
    with prov_env["sessions"]() as session:
        from sqlalchemy import select

        from persistence.models import Event

        rows = session.scalars(
            select(Event).where(Event.role == "provider")
            .order_by(Event.id.desc())
        ).all()
        kinds = [row.kind for row in rows]
        assert "PROVIDER_CREATED" in kinds
        for row in rows:
            assert "sk-LOGKEY" not in row.payload, "سر في سجل الأحداث!"
