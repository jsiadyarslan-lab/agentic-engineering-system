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
def client(store_dir):
    from fastapi.testclient import TestClient

    from api import providers as providers_mod
    from api import routes

    providers_mod._models_cache.clear()
    yield TestClient(routes.app)
    providers_mod._models_cache.clear()


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
    """على منصة غير مدعومة: المدير يُنشأ، وكل تنفيذ يسجل فشلًا صادقًا."""
    import substrate.local_substrate as ls

    monkeypatch.setattr(ls, "_SUPPORTED_ARCH", False)
    manager = ls.local_sandbox_manager()  # لا RuntimeError — لا انهيار
    from substrate.limits import E1_LIMITS_DEFAULTS
    from substrate.sandbox import NetworkMode, SandboxRequest

    image = next(iter(manager.image_allowlist))
    request = SandboxRequest(
        sandbox_id="order005-unsupported-1",
        image=image,
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


# ------------------------------------------------------------------ #
# §2 — قائمة النماذج: التراجع المعلن عند تعذر الحي
# ------------------------------------------------------------------ #

def test_provider_cards_expose_known_models(client):
    """البطاقات تكشف نماذجها المعلنة — الواجهة تعرضها فورًا."""
    body = client.get("/api/providers").json()
    for card in body["providers"]:
        assert card["known_models"], f"البطاقة {card['id']} بلا نماذج معلنة"
        assert card["model"] in card["known_models"]


def test_models_without_key_falls_back_to_declared(client):
    """بلا مفتاح محفوظ: القائمة المعلنة تُعرض بمصدر declared لا فراغ صامت."""
    body = client.get("/api/providers/nvidia/models?refresh=1").json()
    assert body["source"] == "declared"
    assert body["model_ids"] == ["nemotron-3-ultra-550b-a55b"]
    assert "لا مفتاح محفوظ" in body["message"]
    assert "معلنة" in body["message"]


def test_models_live_404_falls_back_to_declared(client):
    """404 من نقطة النماذج (منشأة zai بلا نقطة نماذج): تراجع معلن بصدق."""
    body = client.get("/api/providers/zai_internal/models?refresh=1").json()
    assert body["source"] == "declared"
    assert "glm-4.6" in body["model_ids"]
    assert "404" in body["message"], "سبب تعذر الحي يجب أن يظهر حرفيًا"


def test_models_live_success_labels_source_live(client, monkeypatch):
    """نجاح الجلب الحي: المصدر live والعدد من الخادم فعلًا."""

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            import json as json_mod
            return json_mod.dumps(self._payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=15):  # noqa: ANN001, ARG001
        return _FakeResponse({"data": [{"id": "model-a"}, {"id": "model-b"}]})

    from api import providers as providers_mod

    monkeypatch.setattr(providers_mod.urllib.request, "urlopen", fake_urlopen)
    store_key = "nvapi-LIVEKEY-000111"
    providers_mod.secrets.set_key("nvidia", store_key)
    body = client.get("/api/providers/nvidia/models?refresh=1").json()
    assert body["source"] == "live"
    assert body["ok"] is True
    assert body["model_ids"] == ["model-a", "model-b"]
    assert body["models_count"] == 2


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
