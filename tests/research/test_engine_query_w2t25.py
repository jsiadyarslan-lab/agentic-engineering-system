"""اختبارات W2-T25 — استعلام المحركات المنزوع الإصدارات + إعادة توجيه سجل npm.

الدافع المقيس (تنفيذات 33-35 للمشروع #3، الخطوة 111):
- محركات البحث الحرفية (stackoverflow/github/mdn/wikipedia) تُسقط
  الاستعلامات المُرقَّمة («Next.js 14.2.0 package.json…» ← صفر نتائج)
  بينما المنزوعة الأرقام تعيد صلة حقيقية تغطي بوابة الصلة.
- www.npmjs.com يصدّ 403 بينما registry.npmjs.org (المصدر القانوني
  نفسه بواجهة JSON) يخدم بلا حظر.

العقد المدروس هنا:
1. ما يُنزَع من استعلام المحركات غير مرئي لبوابة الصلة أصلًا (رموز
   <3 خانات تُسقطها query_tokens) — البوابة تقيّم الاستعلام الأصلي.
2. إعادة توجيه npmjs→registry تحدث عند 403 حصرًا ولا تغير المضمون.
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from research import providers as rp  # noqa: E402


# ------------------------------------------------------------------ #
# engine_query — النزع الآمن حصرًا
# ------------------------------------------------------------------ #

def test_engine_query_strips_version_patterns():
    q = "Next.js 14.2.0 package.json dependencies react typescript"
    assert rp.engine_query(q) == \
        "Next.js package.json dependencies react typescript"


def test_engine_query_strips_multi_component_versions():
    assert rp.engine_query("ESLint 8.57.0 Tailwind") == "ESLint Tailwind"
    assert rp.engine_query("TypeScript 5.4 React") == "TypeScript React"


def test_engine_query_strips_standalone_short_numbers():
    assert rp.engine_query("Next.js 14 package.json") == \
        "Next.js package.json"
    assert rp.engine_query("React 18 peer") == "React peer"


def test_engine_query_keeps_long_numbers():
    """الأرقام الطويلة رموز دلالية (2024/100) — لا تُمس."""
    assert rp.engine_query("انتخابات 2024 أمريكا") == "انتخابات 2024 أمريكا"
    assert rp.engine_query("HTTP 100 continue") == "HTTP 100 continue"


def test_engine_query_keeps_digits_inside_words():
    """IPv6/IPv4 كلمة واحدة — لا حد كلمة قبل الرقم فلا يُنزَع."""
    assert rp.engine_query("IPv6 configuration") == "IPv6 configuration"
    assert rp.engine_query("تفعيل IPv4") == "تفعيل IPv4"


def test_engine_query_arabic_unchanged():
    assert rp.engine_query("أخبار اليوم العالمية") == "أخبار اليوم العالمية"


def test_engine_query_empty_falls_back_to_original():
    assert rp.engine_query("18 3 0") == "18 3 0"


def test_engine_query_version_only_query_falls_back():
    """استعلام كله إصدار («14.2.0») — لا نرسل فراغًا للمحرك."""
    assert rp.engine_query("14.2.0") == "14.2.0"


def test_engine_query_stripped_is_invisible_to_relevance_gate():
    """العقد الأهم: رموز الاستعلام الأصلي = رموز النسخة المنزوعة
    في كل الحالات الحية (الأرقام المنزوعة <3 خانات)."""
    cases = [
        "Next.js 14.2.0 package.json dependencies react typescript tailwind eslint",
        "React 18.3.0 package.json peer dependencies",
        "TypeScript 5.4.0 React 18.3.0 ESLint 8.57.0 Tailwind CSS 3.4.0 project setup",
        "Next.js 14 package.json recommended configuration dependencies scripts",
    ]
    for q in cases:
        assert rp.query_tokens(q) == rp.query_tokens(rp.engine_query(q)), q


# ------------------------------------------------------------------ #
# SearXNG — المحرك يستعلم بالمنزوع والبوابة تقيّم الأصل
# ------------------------------------------------------------------ #

class _UrlCapture:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.urls = []

    def __call__(self, request, timeout=None):
        self.urls.append(request.full_url)
        body = self.payload

        class FakeResponse:
            def read(self, _n=-1):
                return body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return FakeResponse()


def test_searx_sends_stripped_query_and_gates_original(monkeypatch):
    """الرابط يحمل الاستعلام المنزوع؛ والنتائج تُقيَّم بأصل الاستعلام —
    نتيجة تحمل رموز الأصل (react/package/json/peer/dependencies) تمر،
    ونتيجة تجرد من رموز الأصل تُرفض رغم أن المحرك بحث بها."""
    payload = (
        b'{"results": [{"title": "react package.json peer dependencies'
        b' guide", "url": "https://so.example/1",'
        b' "content": "peer dependencies in package.json for react"}]}'
    )
    capture = _UrlCapture(payload)
    monkeypatch.setattr(urllib.request, "urlopen", capture)
    provider = rp.SearxJsonSearchProvider(base_url="https://searx.test")
    results = provider.search(
        "React 18.3.0 package.json peer dependencies")
    assert len(results) == 1
    # المحرك استُعلم بالمنزوع — لا «18.3.0» في الرابط
    assert len(capture.urls) == 1
    assert "18.3.0" not in capture.urls[0]
    assert "React%20package.json%20peer%20dependencies" in capture.urls[0]


def test_searx_gate_rejects_results_lacking_original_tokens(monkeypatch):
    """نتائج لا تحمل رموز الأصل تُرفض — النزع لا يفتح بوابة أوسع."""
    payload = (
        b'{"results": [{"title": "unrelated cooking page",'
        b' "url": "https://x.example/1",'
        b' "content": "recipes and kitchen tools"}]}'
    )
    capture = _UrlCapture(payload)
    monkeypatch.setattr(urllib.request, "urlopen", capture)
    provider = rp.SearxJsonSearchProvider(base_url="https://searx.test")
    with pytest.raises(rp.ProviderNotReady):
        provider.search("React 18.3.0 package.json peer dependencies")


def test_wikipedia_sends_stripped_query(monkeypatch):
    payload = (
        b'{"query": {"search": [{"title": "React (software)",'
        b' "snippet": "react package json peer dependencies"}]}}'
    )
    capture = _UrlCapture(payload)
    monkeypatch.setattr(urllib.request, "urlopen", capture)
    provider = rp.WikipediaSearchProvider()
    results = provider.search("React 18.3.0 package.json peer dependencies")
    assert results, "ويكيبيديا تعيد النتيجة عبر البوابة"
    assert len(capture.urls) >= 1
    joined = " ".join(capture.urls)
    assert "18.3.0" not in joined
    assert "React+package.json+peer+dependencies" in joined


def test_api_provider_sends_stripped_body(monkeypatch):
    payload = (
        b'{"results": [{"title": "react package.json peer dependencies'
        b' guide", "url": "https://api.example/1", "snippet": "react'
        b' package.json peer dependencies"}]}'
    )
    bodies = []

    def fake_urlopen(request, timeout=None):
        bodies.append(request.data.decode("utf-8"))

        class FakeResponse:
            def read(self, _n=-1):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    provider = rp.ApiSearchProvider(
        endpoint="https://api.test/search", key="k", style="generic_results")
    results = provider.search("React 18.3.0 package.json peer dependencies")
    assert len(results) == 1
    assert "18.3.0" not in bodies[0]
    assert "React package.json peer dependencies" in bodies[0]


# ------------------------------------------------------------------ #
# fetch_page — إعادة توجيه سجل npm عند 403 حصرًا
# ------------------------------------------------------------------ #

def _registry_payload() -> bytes:
    return (b'{"name":"react","versions":{"18.3.0":{"version":"18.3.0"}},'
            b'"description":"React is a JavaScript library for building'
            b' user interfaces.","license":"MIT"}')


def test_fetch_page_npmjs_403_falls_back_to_registry(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout=None):
        url = request.full_url
        calls.append(url)
        if "www.npmjs.com" in url:
            raise urllib.error.HTTPError(
                url, 403, "Forbidden", hdrs=None, fp=None)

        class FakeResponse:
            def read(self, _n=-1):
                return _registry_payload()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    text = rp.fetch_page("https://www.npmjs.com/package/react/v/18.3.0")
    assert "react" in text and "18.3.0" in text
    assert calls[0].startswith("https://www.npmjs.com/package/react")
    assert calls[1] == "https://registry.npmjs.org/react/18.3.0"


def test_fetch_page_npmjs_scoped_package_registry_url(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout=None):
        url = request.full_url
        calls.append(url)
        if "www.npmjs.com" in url:
            raise urllib.error.HTTPError(
                url, 403, "Forbidden", hdrs=None, fp=None)

        class FakeResponse:
            def read(self, _n=-1):
                return _registry_payload()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    rp.fetch_page("https://www.npmjs.com/package/@babel/core")
    assert calls[1] == "https://registry.npmjs.org/%40babel%2Fcore"


def test_fetch_page_other_403_still_raises(monkeypatch):
    """403 من غير npmjs.com لا إعادة توجيه — الفشل الصادق كما كان."""

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", hdrs=None, fp=None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        rp.fetch_page("https://www.example.com/protected")


def test_fetch_page_npmjs_success_never_touches_registry(monkeypatch):
    """نجاح npmjs المباشر لا يستدعي السجل إطلاقًا."""
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)

        class FakeResponse:
            def read(self, _n=-1):
                return (b"<html><body>The React package page: library for"
                        b" building user interfaces, with hooks, server"
                        b" components and extensive documentation for the"
                        b" package.json fields of every published"
                        b" release channel.</body></html>")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    rp.fetch_page("https://www.npmjs.com/package/react")
    assert len(calls) == 1
    assert "registry.npmjs.org" not in calls[0]


def test_npm_registry_url_variants():
    assert rp._npm_registry_url(
        "https://www.npmjs.com/package/next/v/14.2.0") == \
        "https://registry.npmjs.org/next/14.2.0"
    assert rp._npm_registry_url(
        "https://npmjs.com/package/typescript") == \
        "https://registry.npmjs.org/typescript"
    assert rp._npm_registry_url(
        "https://www.npmjs.com/package/@astrojs/tailwind/v/5.0.0") == \
        "https://registry.npmjs.org/%40astrojs%2Ftailwind/5.0.0"
    # ليس صفحة حزمة → لا مقابل
    assert rp._npm_registry_url("https://www.npmjs.com/~user") is None
    assert rp._npm_registry_url("https://example.com/x") is None
    assert rp._npm_registry_url("not a url") is None
