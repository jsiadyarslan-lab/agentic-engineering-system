"""اختبارات الأمر 005 — جودة الواجهة + إصلاح المشاكل الظاهرة.

تغطي الإصلاحات الثلاثة الموثقة:
§1 خطأ ``No module named 'resource'`` — استيراد الركيزة المحلية ينجو
   من غياب الوحدة (كما على Windows) ويفشل كل طلب تنفيذ بصدق بدل الانهيار.
§2 قائمة النماذج — التراجع المعلن (source=declared) عند تعذر الجلب الحي:
   بلا مفتاح، أو نقطة نماذج غير موجودة (404)، مع بطاقات تكشف known_models.
§3 الكاش — ترويسات no-cache + أصول مرقّمة بالإصدار (درس v1 المنقول).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def store_dir(tmp_path, monkeypatch):
    """عزل المخزن في مجلد اختبار + تصفير الكاش."""
    from secrets_store import store as store_mod

    monkeypatch.setattr(store_mod, "RUNTIME_DIR", tmp_path)
    store_mod._invalidate_known_cache()
    yield tmp_path
    store_mod._invalidate_known_cache()


@pytest.fixture()
def client(store_dir, monkeypatch, tmp_path):
    """عميل معزول بالكامل (الأمر 007.1): مخزن أسرار مؤقت + قاعدة مزودين
    مؤقتة — البطاقات من السجل الدائم لا من كود، والاختبار لا يعتمد
    على حالة الجهاز أبدًا."""
    from fastapi.testclient import TestClient

    from api import routes
    from persistence.database import build_engine, init_db, make_session_factory

    engine = build_engine(tmp_path / "order005-providers.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    monkeypatch.setattr(routes, "_sessions", sessions)
    yield TestClient(routes.app)


# ------------------------------------------------------------------ #
# §1 — خطأ resource: الاستيراد ينجو والفشل صادق لكل طلب
# ------------------------------------------------------------------ #

def test_local_substrate_import_survives_missing_resource(monkeypatch):
    """محاكاة Windows: حجب resource لا يكسر استيراد الوحدة."""
    import substrate.local_substrate as ls

    saved = {
        name: mod for name, mod in sys.modules.items()
        if name == "substrate.local_substrate"
    }
    # None في sys.modules يجعل `import resource` يرفع ImportError
    monkeypatch.setitem(sys.modules, "resource", None)
    monkeypatch.delitem(sys.modules, "substrate.local_substrate")
    try:
        fresh = importlib.import_module("substrate.local_substrate")
        assert fresh.resource is None, "الحراسة يجب أن تجعل resource=None"
    finally:
        # استعادة الوحدة الأصلية للجلسة (الهوية التي يحملها الباقي)
        for name, mod in saved.items():
            sys.modules[name] = mod
        monkeypatch.undo()


def test_unsupported_platform_fails_closed_per_request(monkeypatch):
    """على منصة غير مدعومة: لا صور افتراضية، وكل تنفيذ يسجل فشلًا صادقًا.

    الأمر 006 §11 حدّث العقد: default_local_images تعيد {} (لا
    ValueError خام من LocalImage أبدًا)، والمدير يُنشأ، وأي طلب تنفيذ
    بصورة مسجلة يدويًا يفشل FAILED_TO_START بالسبب الكامل.
    """
    import substrate.local_substrate as ls

    monkeypatch.setattr(ls, "_SUPPORTED_ARCH", False)
    # العقد الجديد: بلا صور افتراضية — لا انفجار ValueError خام
    assert ls.default_local_images() == {}
    manager = ls.local_sandbox_manager()  # لا RuntimeError — لا انهيار
    from substrate.limits import E1_LIMITS_DEFAULTS
    from substrate.sandbox import NetworkMode, SandboxRequest

    # صورة مسجلة يدويًا: الرفض عند التنفيذ (FAILED_TO_START بالسبب)
    # لا عند البناء — نفس مبدأ الأمر 005 محفوظًا
    import sys

    image = ls.LocalImage(
        name="python", interpreter=sys.executable, read_only_roots=("/",)
    )
    manager = ls.local_sandbox_manager(images={"python": image})
    request = SandboxRequest(
        sandbox_id="order006-unsupported-1",
        image="python",
        command=("python", "-c", "print(1)"),
        limits=E1_LIMITS_DEFAULTS,
        env_names=frozenset({"PATH"}),
        network=NetworkMode.NONE,
        workspace_root="/tmp",
        artifacts_dir="/tmp",
    )
    outcome = manager.execute(request)
    assert outcome.outcome.value == "FAILED"
    assert outcome.record.termination.value == "FAILED_TO_START"
    # السبب الصادق الكامل في أدلة التنفيذ الخاصة بمحوّل المدير نفسه
    adapter = manager.substrate
    evidence = adapter.execution_evidence(request.sandbox_id)
    assert "WSL2" in str(evidence.get("failure_reason", "")), \
        "الرسالة يجب أن توجه إلى WSL2"
    assert "linux/x86_64" in str(evidence.get("failure_reason", ""))

    # وgit_image يرفض بوضوح لا بـValueError خام (§11)
    import pytest as _pytest

    with _pytest.raises(ls.SubstrateUnavailable):
        ls.local_git_image()


# ------------------------------------------------------------------ #
# §2 — قائمة النماذج: التراجع المعلن عند تعذر الحي (007.1: عبر السجل الدائم)
# ------------------------------------------------------------------ #

def _provider_by_name(client, name: str) -> dict:
    body = client.get("/api/providers").json()
    for provider in body["providers"]:
        if provider["name"] == name:
            return provider
    raise AssertionError(f"المزود غير مبذور: {name}")


def _primary_config(provider: dict) -> dict:
    configs = [c for c in provider["configurations"] if c["is_primary"]]
    assert configs, "لا تكوين أساسي للمزود"
    return configs[0]


def test_provider_cards_expose_known_models(client):
    """البطاقات (من السجل الدائم) تكشف نماذجها المعلنة — الواجهة تعرضها فورًا."""
    body = client.get("/api/providers").json()
    assert body["providers"], "لا مزودين مبذورين"
    for provider in body["providers"]:
        cfg = _primary_config(provider)
        assert cfg["models"], f"المزود {provider['name']} بلا نماذج معلنة"
        if cfg["default_model"]:
            assert cfg["default_model"] in cfg["models"]


def test_models_without_key_falls_back_to_declared(client):
    """بلا مفتاح محفوظ: القائمة المعلنة تُعرض بمصدر declared لا فراغ صامت."""
    provider = _provider_by_name(client, "nvidia")
    cfg = _primary_config(provider)
    body = client.post(
        f"/api/providers/{provider['id']}/models/refresh"
    ).json()
    assert body["source"] == "declared"
    # المعلن في البذر: النسخة الصحيحة بالبادئة + القديمة (توافق)
    assert "nvidia/nemotron-3-ultra-550b-a55b" in body["model_ids"]
    assert "لا مفتاح" in body["message"]
    assert cfg["models"]


def test_models_live_404_falls_back_to_declared(client, monkeypatch):
    """404 من نقطة النماذج: تراجع معلن بصدق — لا فراغ صامت ولا ادعاء حي."""
    import urllib.error

    def fake_fetch(url, headers, timeout, method="GET", body=None):
        raise urllib.error.HTTPError(
            url, 404, "404 page not found", {}, None  # type: ignore[arg-type]
        )

    from providers_registry import registry

    monkeypatch.setattr(registry, "_http_fetch_real", fake_fetch)
    provider = _provider_by_name(client, "zai_internal")
    # منشأة معلنة: مصادقتها تُحل ثم يفشل الجلب بـ 404 ← التراجع المعلن
    body = client.post(
        f"/api/providers/{provider['id']}/models/refresh"
    ).json()
    assert body["source"] == "declared"
    assert "glm-4.6" in body["model_ids"]
    assert "404" in body["message"], "سبب تعذر الحي يجب أن يظهر حرفيًا"


def test_models_live_success_labels_source_live(client, monkeypatch):
    """نجاح الجلب الحي: المصدر live والعدد من الخادم فعلًا."""

    def fake_fetch(url, headers, timeout, method="GET", body=None):
        import json as json_mod

        return 200, json_mod.dumps(
            {"data": [{"id": "model-a"}, {"id": "model-b"}]}
        )

    from providers_registry import registry

    monkeypatch.setattr(registry, "_http_fetch_real", fake_fetch)
    provider = _provider_by_name(client, "nvidia")
    from secrets_store import store as secrets

    secrets.set_key("nvidia", "nvapi-LIVEKEY-000111")
    body = client.post(
        f"/api/providers/{provider['id']}/models/refresh"
    ).json()
    assert body["source"] == "live"
    assert body["ok"] is True
    assert "model-a" in body["model_ids"] and "model-b" in body["model_ids"]
    # الدمج الصادق: المكتشف حيًا + المعلن سابقًا (نسختا nemotron) = 4
    assert body["models_count"] == 4


# ------------------------------------------------------------------ #
# §3 — الكاش: ترويسات + أصول مرقّمة (درس v1 المنقول إلى v2)
# ------------------------------------------------------------------ #

def test_index_and_static_send_no_cache(client):
    """/ و/static/* بلا تخزين أعمى — أي تحديث يظهر فور git pull."""
    for path in ("/", "/static/app.js", "/static/styles.css"):
        response = client.get(path)
        assert response.headers.get("cache-control") == "no-cache", path


def test_index_html_assets_are_versioned():
    """الأصول مرقّمة بالإصدار — طبقة دفاع ثانية ضد كاش المتصفح."""
    html = (REPO / "src" / "ui" / "index.html").read_text(encoding="utf-8")
    assert "styles.css?v=" in html
    assert "app.js?v=" in html
    assert "fonts.css?v=" in html


def test_ui_ids_complete():
    """كل المعرفات التي تعتمد عليها app.js موجودة في index.html.

    يمنع كسر الواجهة صامتًا عند أي إعادة هيكلة للأزرار (الأمر 005).
    """
    html = (REPO / "src" / "ui" / "index.html").read_text(encoding="utf-8")
    js = (REPO / "src" / "ui" / "app.js").read_text(encoding="utf-8")
    import re

    used = set(re.findall(r'\$\("([a-z0-9-]+)"\)', js))
    # working-indicator يُنشأ ديناميكيًا في addWorking() — ليس في HTML
    used.discard("working-indicator")
    defined = set(re.findall(r'id="([a-z0-9-]+)"', html))
    missing = used - defined
    assert not missing, f"معرفات مفقودة في index.html: {sorted(missing)}"


def test_no_demo_disclosure_in_index():
    """لا نصوص تجريبية/كشف أوامر داخلية في الواجهة — مظهر منتج لا ديمو."""
    html = (REPO / "src" / "ui" / "index.html").read_text(encoding="utf-8")
    for banned in ("mock", "الأمر الثالث", "الأمر الرابع", "الأمر السادس",
                   "ديمو", "نقل mock"):
        assert banned not in html, f"نص تجريبي بقي في الواجهة: {banned}"
