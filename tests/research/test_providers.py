"""اختبار مزودي البحث (الأمر 010 §24-§25) — النقل مضبوط، المسار حقيقي.

- DDG: محلل HTML حقيقي على صفحة مجمدة + فصل النقل عن التحليل.
- SearXNG: نقطة JSON + تكوين مطلوب قبل الاستخدام.
- API: أنماط tavily/brave/عام.
- الخدمة: بذر + مسبار + تجميع + بحث بأول جاهز + فشل مفصل.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from research import providers as rp  # noqa: E402
from research import service  # noqa: E402
from persistence.database import (  # noqa: E402
    build_engine, init_db, make_session_factory,
)

DDG_FROZEN = """
<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&amp;rut=x">عنوان أول</a>
<a class="result__snippet" href="">مقتطف أول</a>
<a rel="nofollow" class="result__a" href="https://example.org/b">Second</a>
<a class="result__snippet" href="">snippet two</a>
"""

#: (013.2) صفحة lite المجمدة — ترميز الجدول البسيط للنقطة lite
DDG_LITE_FROZEN = """
<table>
<tr><td><a class="result-link" href="https://example.com/lite1">عنوان لايت</a></td></tr>
<tr><td class="result-snippet">مقتطف لايت أول</td></tr>
</table>
"""

#: (013.2) صفحة Bing المجمدة — كتل b_algo مع رابط إعادة توجيه ck/a
BING_FROZEN = """
<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?!&amp;&amp;p=abc&amp;u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9iaW5nMQ==&amp;ntb=1">عنوان بينج</a></h2><p>مقتطف بينج أول</p></li>
<li class="b_algo"><h2><a href="https://example.org/direct">Direct Link</a></h2><p>second snippet</p></li>
"""


@pytest.fixture()
def sessions(tmp_path):
    engine = build_engine(tmp_path / "research-test.db")
    init_db(engine)
    return make_session_factory(engine)


def _freeze_urlopen(monkeypatch, payload):
    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def read(self, _n=-1):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        rp.urllib.request, "urlopen",
        lambda req, timeout=None: FakeResponse(payload),
    )


def test_ddg_provider_parses_and_unwraps_redirects(monkeypatch):
    _freeze_urlopen(monkeypatch, DDG_FROZEN.encode("utf-8"))
    provider = rp.DuckDuckGoSearchProvider()
    results = provider.search("استعلام")
    assert len(results) == 2
    assert results[0]["url"] == "https://example.com/a"
    assert results[0]["title"] == "عنوان أول"


def test_ddg_no_analyzable_results_is_analyzable_failure(monkeypatch):
    """صفحة فارغة من كل الاستراتيجيات = فشل تحليل مفصل لكل استراتيجية."""
    _freeze_urlopen(monkeypatch, b"<html>empty page</html>")
    provider = rp.DuckDuckGoSearchProvider()
    with pytest.raises(rp.ProviderNotReady) as caught:
        provider.search("استعلام")
    assert caught.value.reason == "RESULTS_NOT_ANALYZABLE"
    # (013.2) تفصيل كل استراتيجية مسماة — لا «0 روابط خام» غامضة
    attempts = caught.value.details["attempts"]
    assert {a["strategy"] for a in attempts} == {
        "lite-get", "lite-post", "html-post"}
    assert all(a["error"] for a in attempts)


def test_ddg_challenge_page_is_classified_not_mystical(monkeypatch):
    """صفحة التحدّ (anomaly) تُصنّف باسمها (013.2) — كان النقل ينجح
    ويقول المحلل «0 روابط خام» بلا سبب معروف."""
    _freeze_urlopen(
        monkeypatch,
        b"<html><body><div class='anomaly-modal__box'>challenge</div>"
        b"</body></html>",
    )
    provider = rp.DuckDuckGoSearchProvider()
    with pytest.raises(rp.ProviderNotReady) as caught:
        provider.search("استعلام")
    attempts = caught.value.details["attempts"]
    assert all("تحدّ" in a["error"] for a in attempts)


def test_ddg_lite_markup_is_parsed(monkeypatch):
    """ترميز lite (result-link) يُحلّل كترميز html — الاستراتيجية الأولى."""
    _freeze_urlopen(monkeypatch, DDG_LITE_FROZEN.encode("utf-8"))
    provider = rp.DuckDuckGoSearchProvider()
    results = provider.search("استعلام")
    assert results[0]["url"] == "https://example.com/lite1"
    assert results[0]["title"] == "عنوان لايت"
    assert "مقتطف لايت" in results[0]["snippet"]


def test_searx_provider_requires_configuration():
    provider = rp.SearxJsonSearchProvider(base_url="")
    with pytest.raises(rp.ProviderNotReady, match="base_url"):
        provider.search("q")


def test_searx_provider_parses_json(monkeypatch):
    payload = (
        b'{"results": [{"title": "T1", "url": "https://a.example/1",'
        b' "content": "c1"}, {"title": "T2",'
        b' "url": "https://b.example/2", "content": "c2"}]}'
    )
    _freeze_urlopen(monkeypatch, payload)
    provider = rp.SearxJsonSearchProvider(base_url="https://searx.test")
    results = provider.search("q")
    assert len(results) == 2
    assert results[0]["title"] == "T1"


@pytest.mark.parametrize("style", ["tavily", "brave", "generic_results"])
def test_api_provider_parses_all_styles(monkeypatch, style):
    if style == "tavily":
        payload = (b'{"results": [{"title": "A", "url": "https://x.example/a",'
                   b' "content": "ca"}]}')
    elif style == "brave":
        payload = (b'{"web": {"results": [{"title": "B",'
                   b' "url": "https://x.example/b", "description": "cb"}]}}')
    else:
        payload = (b'{"results": [{"title": "C", "url": "https://x.example/c",'
                   b' "snippet": "cc"}]}')
    _freeze_urlopen(monkeypatch, payload)
    provider = rp.ApiSearchProvider(
        endpoint="https://api.test/search", key="k", style=style,
    )
    results = provider.search("q")
    assert len(results) == 1
    assert results[0]["url"].startswith("https://x.example/")


def test_service_seeds_four_providers(sessions):
    providers_list = service.list_providers(sessions)
    kinds = {p["kind"] for p in providers_list}
    assert kinds == {"search_ddg", "search_bing", "search_searx",
                     "search_api"}
    # (013.2) DDG وBing مفعّلان افتراضيًا — لا بحث بلا احتياط
    ddg = [p for p in providers_list if p["kind"] == "search_ddg"][0]
    bing = [p for p in providers_list if p["kind"] == "search_bing"][0]
    assert ddg["enabled"] is True
    assert bing["enabled"] is True


def test_bing_provider_parses_algo_and_unwraps_redirects(monkeypatch):
    """Bing (013.2): تحليل b_algo + فك رابط ck/a المرمّز base64url."""
    _freeze_urlopen(monkeypatch, BING_FROZEN.encode("utf-8"))
    provider = rp.BingSearchProvider()
    results = provider.search("استعلام")
    assert len(results) == 2
    # a1aHR0cHM6Ly9leGFtcGxlLmNvbS9iaW5nMQ== → https://example.com/bing1
    assert results[0]["url"] == "https://example.com/bing1"
    assert results[0]["title"] == "عنوان بينج"
    assert "مقتطف بينج" in results[0]["snippet"]
    assert results[1]["url"] == "https://example.org/direct"


def test_bing_challenge_page_classified(monkeypatch):
    _freeze_urlopen(
        monkeypatch,
        b"<html><body>challenge page</body></html>",
    )
    provider = rp.BingSearchProvider()
    with pytest.raises(rp.ProviderNotReady, match="تحدّ"):
        provider.search("استعلام")


def test_service_probe_writes_result(sessions, monkeypatch):
    ddg = [p for p in service.list_providers(sessions)
           if p["kind"] == "search_ddg"][0]
    _freeze_urlopen(monkeypatch, DDG_FROZEN.encode("utf-8"))
    result = service.probe_provider(sessions, ddg["id"])
    assert result["status"] == "READY"
    updated = [p for p in service.list_providers(sessions)
               if p["id"] == ddg["id"]][0]
    assert updated["last_probe_status"] == "READY"
    assert updated["last_probe_at"]


def test_aggregate_not_ready_when_all_providers_down(sessions, monkeypatch):
    """كل المزودين فاشلين → NOT_READY بتفصيل لكل مزود (§24)."""

    def failing_open(req, timeout=None):
        raise OSError("timed out")

    monkeypatch.setattr(rp.urllib.request, "urlopen", failing_open)
    ddg = [p for p in service.list_providers(sessions)
           if p["kind"] == "search_ddg"][0]
    service.probe_provider(sessions, ddg["id"])
    aggregate = service.aggregate_capability(sessions)
    assert aggregate["status"] == "NOT_READY"
    assert any(p["status"] == "NOT_READY" for p in aggregate["per_provider"])
    # (013.2) السبب الصادق: حجب تحدّ + طريق الاحتياط الدائم معلن
    assert "محجوبين" in aggregate["reason"]
    assert "SearXNG" in aggregate["reason"]


def test_search_uses_first_ready_provider(sessions, monkeypatch):
    service.configure_provider(
        sessions, _provider_id(sessions, "search_searx"),
        config={"base_url": "https://searx.test"}, enabled=True,
    )
    # DDG وBing معطلان → searx جاهز (بمسبار مضبوط) → البحث يخدم منه
    service.configure_provider(
        sessions, _provider_id(sessions, "search_ddg"), enabled=False,
    )
    service.configure_provider(
        sessions, _provider_id(sessions, "search_bing"), enabled=False,
    )
    searx = rp.SearxJsonSearchProvider(base_url="https://searx.test")

    class SeamedProvider:
        provider_id = "searx"
        kind = "search_searx"

        def search(self, query, *, timeout=15):
            return [{"title": "نتيجة سيَركس", "url": "https://s.example/1",
                     "snippet": "s"}]

        def describe(self):
            return {"provider_id": "searx"}

    monkeypatch.setattr(
        service, "build_provider",
        lambda record: SeamedProvider() if record["kind"] == "search_searx"
        else rp.DuckDuckGoSearchProvider(),
    )
    outcome = service.search(sessions, "استعلام")
    assert outcome["provider_kind"] == "search_searx"
    assert outcome["results"][0]["title"] == "نتيجة سيَركس"


def test_search_falls_through_ddg_to_bing(sessions, monkeypatch):
    """(013.2) DDG محجوب بتحدّ → Bing يخدم — لا تعطل كليًا بعد اليوم."""
    calls = {"ddg": 0, "bing": 0}

    class BlockedDDG:
        provider_id = "ddg"
        kind = "search_ddg"

        def search(self, query, *, timeout=15):
            calls["ddg"] += 1
            raise rp.ProviderNotReady(
                "ddg: كل الاستراتيجيات فشلت — تحدّ",
                reason="RESULTS_NOT_ANALYZABLE",
            )

        def describe(self):
            return {"provider_id": "ddg"}

    class WorkingBing:
        provider_id = "bing"
        kind = "search_bing"

        def search(self, query, *, timeout=15):
            calls["bing"] += 1
            return [{"title": "نتيجة بينج", "url": "https://b.example/1",
                     "snippet": "snip"}]

        def describe(self):
            return {"provider_id": "bing"}

    def build(record):
        return BlockedDDG() if record["kind"] == "search_ddg" \
            else WorkingBing()

    monkeypatch.setattr(service, "build_provider", build)
    outcome = service.search(sessions, "استعلام")
    assert outcome["provider_kind"] == "search_bing"
    assert calls == {"ddg": 1, "bing": 1}
    assert outcome["results"][0]["title"] == "نتيجة بينج"


def _provider_id(sessions, kind):
    return [p for p in service.list_providers(sessions)
            if p["kind"] == kind][0]["id"]


def test_search_failure_details_every_provider(sessions, monkeypatch):
    """فشل الجميع يعاد مفصلًا لكل مزود — لا «الإنترنت مقطوع» (§24)."""
    from roles.tool_failures import ToolFailure

    def failing_open(req, timeout=None):
        raise OSError("timed out")

    monkeypatch.setattr(rp.urllib.request, "urlopen", failing_open)
    service.configure_provider(
        sessions, _provider_id(sessions, "search_searx"),
        config={"base_url": "https://searx.test"}, enabled=True,
    )
    with pytest.raises(ToolFailure) as caught:
        service.search(sessions, "استعلام")
    assert caught.value.reason == rp.SEARCH_NOT_READY
    assert caught.value.details["attempts"], "لا تفصيل محاولات"
    assert len(caught.value.details["attempts"]) >= 2
