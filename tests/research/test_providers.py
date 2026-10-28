"""اختبار مزودي البحث (الأمر 010 §24-§25) — النقل مضبوط، المسار حقيقي.

- DDG: محلل HTML حقيقي على صفحة مجمدة + فصل النقل عن التحليل.
- SearXNG: نقطة JSON + تكوين مطلوب قبل الاستخدام.
- API: أنماط tavily/brave/عام.
- الخدمة: بذر + مسبار + تجميع + بحث بأول جاهز + فشل مفصل.
"""

from __future__ import annotations

import json
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
<a rel="nofollow" class="result__a" href="https://example.org/b">عنوان أول ثانٍ</a>
<a class="result__snippet" href="">مقتطف أول ثانٍ</a>
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
<li class="b_algo"><h2><a href="https://example.org/direct">عنوان بينج مباشر</a></h2><p>مقتطف بينج ثانٍ</p></li>
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
    """الاستعلام يطابق عناوين الصفحة المجمدة — بوابة الملاءمة (013.5 §L)
    ترفض أي نتائج لا تخصّ الاستعلام، فالاختبار يمرّ باستعلام واقعي.

    (013.5 §L) البوابة صارت تُسقط النتائج الضعيفة من المخرَج، فالمجمَّد
    يحمل رمزين في النتيجة الأولى ورمزًا واحدًا في الثانية: الأولى قوية
    والثانية لا تغطي أغلب الاستعلام — وهذا هو السلوك المطلوب.
    """
    _freeze_urlopen(monkeypatch, DDG_FROZEN.encode("utf-8"))
    provider = rp.DuckDuckGoSearchProvider()
    results = provider.search("عنوان أول مقتطف")
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
    results = provider.search("عنوان لايت مقتطف")
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


def test_service_seeds_all_five_providers(sessions):
    """(013.5 §L) خمسة مزودين — أُضيفت ويكيبيديا كمصدر حي بلا مفاتيح."""
    providers_list = service.list_providers(sessions)
    kinds = {p["kind"] for p in providers_list}
    assert kinds == {"search_ddg", "search_bing", "search_wikipedia",
                     "search_searx", "search_api"}
    # (013.2) DDG وBing مفعّلان افتراضيًا — لا بحث بلا احتياط
    ddg = [p for p in providers_list if p["kind"] == "search_ddg"][0]
    bing = [p for p in providers_list if p["kind"] == "search_bing"][0]
    assert ddg["enabled"] is True
    assert bing["enabled"] is True
    # (013.5 §L) ويكيبيديا مفعّلة افتراضيًا: هي المصدر الوحيد الذي ثبت
    # أنه يرد محتوى حقيقيًا من هذا المضيف بلا مفاتيح.
    wiki = [p for p in providers_list if p["kind"] == "search_wikipedia"][0]
    assert wiki["enabled"] is True
    assert wiki["config"] == {}


def test_bing_provider_parses_algo_and_unwraps_redirects(monkeypatch):
    """Bing (013.2): تحليل b_algo + فك رابط ck/a المرمّز base64url."""
    _freeze_urlopen(monkeypatch, BING_FROZEN.encode("utf-8"))
    provider = rp.BingSearchProvider()
    results = provider.search("عنوان بينج مقتطف")
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
    """المسبار الآن يشمل الملاءمة: استعلام المسبار يجب أن تجيبه الصفحة
    فعلًا — «صفحة قابلة للتحليل» لم تعد كافية (013.5 §L)."""
    ddg = [p for p in service.list_providers(sessions)
           if p["kind"] == "search_ddg"][0]
    _freeze_urlopen(monkeypatch, DDG_FROZEN.encode("utf-8"))
    monkeypatch.setattr(rp, "PROBE_QUERY", "عنوان أول مقتطف")
    result = service.probe_provider(sessions, ddg["id"])
    assert result["status"] == "READY"
    updated = [p for p in service.list_providers(sessions)
               if p["id"] == ddg["id"]][0]
    assert updated["last_probe_status"] == "READY"
    assert updated["last_probe_at"]


def test_service_probe_distinguishes_transport_from_probe_relevance(
        sessions, monkeypatch):
    """(013.5 §L) المزود يرد ويُحلَّل لكن عبارة المسبار غير ذات صلة.

    الفرق الذي يجب ألا يُخلط: «النقل/التحليل فشل» ≠ «عبارة المسبار
    الجامدة لم تطابق شيئًا». الحالة الأولى NOT_READY، والثانية READY
    مع تفصيل صادق — وإلا بدا Bing معطّلًا وهو يجيب استعلامات حقيقية
    بنتائج سليمة (مقيس: «quantum computing» ← ويكيبيديا/IBM/GfG).
    """
    ddg = [p for p in service.list_providers(sessions)
           if p["kind"] == "search_ddg"][0]
    _freeze_urlopen(monkeypatch, DDG_FROZEN.encode("utf-8"))
    monkeypatch.setattr(rp, "PROBE_QUERY",
                        "quantum computing benchmarks")
    result = service.probe_provider(sessions, ddg["id"])
    assert result["status"] == "READY"
    assert "لم تطابق" in result["reason"]
    assert result["details"]["probe_relevance"]["relevant"] is False
    # لكن البحث الحقيقي يبقى صارمًا: نفس النتائج تُرفض لاستعلام لا تطابقه
    with pytest.raises(rp.ProviderNotReady):
        rp.require_relevant(
            "ddg", "quantum computing benchmarks",
            [{"title": "عنوان أول", "url": "https://example.com/a",
              "snippet": "مقتطف أول"}],
        )


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


# ------------------------------------------------------------------ #
# (W2-T20) بوابة الصلة × الاستعلامات الطويلة — البار القابل للتحقيق
# ------------------------------------------------------------------ #

#: الاستعلام الفاشل الحقيقي من قاعدة الإنتاج (tool_invocations #207)
LONG_QUERY = (
    "news website page structure homepage world politics business "
    "technology sports entertainment article detail search results "
    "best practices"
)


def test_long_query_single_result_bar_is_achievable():
    """(W2-T20) استعلام 17 رمزًا: نتيجة فيها 3 رموز فعلية = قوية.

    العتبة القديمة كانت تطلب 60% (10 رموز) في نتيجة واحدة — مستحيلة
    رياضيًا على عناوين/مقتطفات قصيرة، فكانت الاستعلامات الطبيعية
    الطويلة تُرفض كلها حتى من محرك ممتاز.
    """
    result = {
        "title": "News Website Page Structure Best Practices",
        "url": "https://example.com/news-structure",
        "snippet": "homepage sections: world, politics, business, technology",
    }
    report = rp.result_relevance(LONG_QUERY, result)
    tokens = report["tokens"]
    assert len(tokens) > 5, "الاستعلام يجب أن يبقى طويلًا"
    assert len(report["hit"]) >= 3
    assert report["specific"], "أحدها مميّز (غير عام)"
    assert report["strong"] is True


def test_long_query_required_coverage_capped():
    """(W2-T20) المطلوب المجموعي لاستعلام طويل مسقف عند 4 رموز."""
    report = rp.relevance_report(LONG_QUERY, [])
    assert report["required"] <= 4
    assert report["required"] >= 2, "لا ينهار إلى 1 — يبقى بوابة"


def test_short_query_thresholds_unchanged():
    """(W2-T20) الاستعلامات القصيرة تبقى على العتبة الصارمة 60%."""
    query = "أحدث نماذج كلاود"
    result = {
        "title": "كلاود فلير شبكة توصيل محتوى",
        "url": "https://example.com/cdn",
        "snippet": "شبكة كلاود",
    }
    report = rp.result_relevance(query, result)
    assert report["ratio"] < 0.6
    assert report["strong"] is False, "نتيجة اسمية تُرفض كما كانت"
    required = rp.relevance_report(query, [])["required"]
    assert required == max(2, int(len(report["tokens"]) * 0.6 + 0.5))


def test_require_relevant_passes_realistic_long_query_results():
    """(W2-T20) صفحة نتائج واقعية لاستعلام طويل تمر — لا تُرفض جملة.

    كل نتيجة تحوي 3-4 رموز فعلية (كما ترد فعلاً من محرك حقيقي)،
    والتغطية المجموعية فوق السقف — البوابة تمرر القوية فقط.
    """
    results = [
        {"title": "News Website Page Structure — homepage and sections",
         "url": "https://example.com/a",
         "snippet": "world politics business technology sports entertainment"},
        {"title": "Best practices for news article detail pages",
         "url": "https://example.org/b",
         "snippet": "search results layout and structure for news websites"},
        {"title": "Responsive news site: politics and sports sections",
         "url": "https://example.net/c",
         "snippet": "article page structure with related results"},
    ]
    kept = rp.require_relevant("searx", LONG_QUERY, results)
    assert kept, "النتائج الواقعية يجب أن تمر البوابة"
    assert all(r["url"].startswith("http") for r in kept)


def test_require_relevant_still_rejects_blind_long_query_results():
    """(W2-T20) البوابة ما زالت صادقة: نتائج لا تخص الاستعلام تُرفض."""
    irrelevant = [
        {"title": "أنواع ما في اللغة العربية",
         "url": "https://example.com/grammar",
         "snippet": "قواعد النحو والصرف"},
        {"title": "Telekom tariffs 2026",
         "url": "https://example.com/telekom",
         "snippet": "mobile contracts"},
    ]
    with pytest.raises(rp.ProviderNotReady) as caught:
        rp.require_relevant("searx", LONG_QUERY, irrelevant)
    assert caught.value.reason == rp.SEARCH_RESULTS_IRRELEVANT


# ------------------------------------------------------------------ #
# (W2-T20) لغة استعلام SearXNG من كتابته — عربي → language=ar
# ------------------------------------------------------------------ #

def test_searx_language_follows_query_script(monkeypatch):
    """(W2-T20) استعلام عربي → language=ar · إنجليزي → en.

    الصلب على en كان يجلب نتائج إنجليزية لاستعلام عربي فترفضها
    بوابة الصلة بتغطية 0/N — والاستعلامات الفعلية للنموذج عربية.
    """
    captured = {}

    def fake_open(req, timeout=None):
        captured["url"] = req.full_url
        is_arabic = "language=ar" in req.full_url
        payload = {
            "results": ([{
                "title": "تصميم موقع إخباري وصولية WCAG",
                "url": "https://example.org/news-a11y",
                "content": "متطلبات وصولية موقع أخبار WCAG 2.1",
            }] if is_arabic else [{
                "title": "News website page structure best practices",
                "url": "https://example.com/news-structure",
                "content": "news website page structure homepage layout",
            }]),
        }

        class R:
            def read(self, _n=-1):
                return json.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return R()

    monkeypatch.setattr(rp.urllib.request, "urlopen", fake_open)
    provider = rp.SearxJsonSearchProvider(base_url="http://searx.test")
    results = provider.search("متطلبات وصولية موقع أخبار WCAG")
    assert "language=ar" in captured["url"], captured["url"]
    assert results, "نتيجة عربية ذات صلة يجب أن تمر"

    results_en = provider.search("news website page structure")
    assert "language=en" in captured["url"], captured["url"]
    assert results_en, "نتيجة إنجليزية ذات صلة يجب أن تمر"
