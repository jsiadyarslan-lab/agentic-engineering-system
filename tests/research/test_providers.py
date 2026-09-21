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
    _freeze_urlopen(monkeypatch, b"<html>empty page</html>")
    provider = rp.DuckDuckGoSearchProvider()
    with pytest.raises(rp.ProviderNotReady) as caught:
        provider.search("استعلام")
    assert caught.value.reason == "RESULTS_NOT_ANALYZABLE"
    assert caught.value.details["transport"] == "SUCCESS"
    assert caught.value.details["links_extracted"] == 0


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


def test_service_seeds_three_providers(sessions):
    providers_list = service.list_providers(sessions)
    kinds = {p["kind"] for p in providers_list}
    assert kinds == {"search_ddg", "search_searx", "search_api"}
    # DDG مفعّل افتراضيًا؛ الآخران يحتاجان تكوين المالك
    ddg = [p for p in providers_list if p["kind"] == "search_ddg"][0]
    assert ddg["enabled"] is True


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
    assert "مقطوع" in aggregate["reason"] or "غير جاهزين" in aggregate["reason"]


def test_search_uses_first_ready_provider(sessions, monkeypatch):
    service.configure_provider(
        sessions, _provider_id(sessions, "search_searx"),
        config={"base_url": "https://searx.test"}, enabled=True,
    )
    # DDG معطل → searx جاهز (بمسبار مضبوط) → البحث يخدم منه
    service.configure_provider(
        sessions, _provider_id(sessions, "search_ddg"), enabled=False,
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
