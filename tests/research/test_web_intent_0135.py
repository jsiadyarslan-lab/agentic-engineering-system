"""اختبارات كاشف نية الويب (013.5 §L) — سؤال المالك الحقيقي يجب أن يبحث.

العطل الحي الموثّق: المالك سأل حرفيًا
    «ما هي احدث نماذج كلاود؟»
(بلا همزة على الألف) فلم يُشغَّل بحث ويب إطلاقًا، لأن ``_AR_INTENT``
كانت مكتوبة بصيغة الهمزة («أحدث» / «ما هي أحدث») والمطابقة حرفية.
النتيجة: إجابة من ذاكرة النموذج بلا مصادر — أو في الحالة الحيّة،
محتوى تاريخي غير متعلق ظهر في المحادثة.

القاعدة المقيسة هنا: الكشف العربي **مطبَّع** (لا يفشل بسبب الهمزة أو
التاء المربوطة أو الألف المقصورة)، والقرار **قابل للتفسير** (المؤشرات
المطابقة معلنة لا صامتة)، والاستثناء الصريح («لا تبحث») محترم.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from research import chat_research as cr  # noqa: E402

#: السؤال الحرفي من قاعدة الإنتاج (مشروع/محادثة المالك).
OWNER_QUESTION = "ما هي احدث نماذج كلاود؟"


def test_the_owner_question_triggers_real_web_research():
    """السؤال الحرفي بلا همزة = بحث ويب إلزامي (§L)."""
    assert cr.detect_web_intent(OWNER_QUESTION) is True
    decision = cr.decide_web_mode(OWNER_QUESTION)
    assert decision["search"] is True
    assert decision["reason"] == "auto_detected"
    assert decision["markers"], "قرار البحث يجب أن يعلن مؤشراته"
    assert "نماذج" in decision["markers"]


@pytest.mark.parametrize("variant", [
    "ما هي احدث نماذج كلاود؟",
    "ما هي أحدث نماذج كلاود؟",
    "ما هي إحدث نماذج كلاود؟",
    "ما هي احدث نماذج Claude؟",
    "ما هي أحدث إصدارات Claude؟",
    "ما هي اخر اصدارات كلاود",
    "أحدث نسخ كلود",
    "اخر نسخه من كلود",
    "what are the newest claude models?",
    "latest Claude models",
    "claude models released in 2026",
])
def test_all_hamza_and_case_variants_are_equivalent(variant):
    """(§L) صيغ الهمزة/الحالة كلها متكافئة — لا فرق بين أحدث/احدث."""
    assert cr.detect_web_intent(variant) is True, variant


@pytest.mark.parametrize("local", [
    "اكتب لي دالة بايثون للجمع",
    "اشرح لي recursion ببساطة",
    "اكتب قصيدة عن البحر",
    "",
    "   ",
])
def test_local_requests_do_not_trigger_search(local):
    """الطلبات المحلية لا تُشغّل بحثًا — لا نطارد كل رسالة."""
    assert cr.detect_web_intent(local) is False, local


def test_explicit_opt_out_is_respected():
    """«لا تبحث» تجاوز صريح — يُحترم فوق أي مؤشر."""
    assert cr.detect_web_intent("لا تبحث، اشرح لي من معرفتك") is False
    assert cr.decide_web_mode("لا تبحث عن احدث النماذج")["search"] is False
    assert cr.decide_web_mode("ما هي احدث النماذج", setting="off") == {
        "search": False, "fetch_urls": [], "reason": "off_explicit",
        "markers": [],
    }
    assert cr.decide_web_mode("مرحبا", setting="on")["search"] is True


def test_normalization_is_deterministic():
    """التطبيع حتمي وقابل للفحص — لا سحر لغوي."""
    assert cr.normalize_arabic("أحدث") == "احدث"
    assert cr.normalize_arabic("إصدار") == "اصدار"
    assert cr.normalize_arabic("آخر") == "اخر"
    assert cr.normalize_arabic("مكتبة") == "مكتبه"
    assert cr.normalize_arabic("على") == "علي"
    assert cr.normalize_arabic("أَحْدَث") == "احدث"   # التشكيل يُزال


def test_url_alone_is_fetch_not_search():
    """رابط وحده = جلب (fetch)؛ ولا يُعد بحثًا بلا مؤشر."""
    decision = cr.decide_web_mode("لخّص لي https://example.com/article")
    assert decision["fetch_urls"] == ["https://example.com/article"]
    assert decision["search"] is False


def test_markers_are_reported_for_every_positive_decision():
    """كل قرار إيجابي يحمل تفسيره — لا حكم صامت (§L)."""
    for query in (OWNER_QUESTION, "اخبار اليوم", "latest news"):
        decision = cr.decide_web_mode(query)
        assert decision["search"] is True
        assert decision["markers"], query


def test_web_unavailable_is_reported_with_a_real_reason(monkeypatch):
    """(§L) تعذّر الويب = WEB_UNAVAILABLE بسببه الحرفي — لا نتائج ملفقة."""
    from research import service as research_service

    def explode(sessions, query, **_kw):
        raise RuntimeError("كل مزودي البحث فشلوا: DDG 403 | Bing 429")

    monkeypatch.setattr(research_service, "search", explode)
    outcome = cr.search_for_chat(None, OWNER_QUESTION)
    assert outcome["ok"] is False
    assert "RuntimeError" in outcome["error"]
    assert "403" in outcome["error"]
    assert outcome["providers_tried"]


def test_search_success_returns_only_real_sources(monkeypatch):
    """(§L/§S) نجاح البحث لا يُعاد صياغته: الروابط كما أعادها المزود."""
    from research import service as research_service

    real = [
        {"title": "Claude models", "url": "https://www.anthropic.com/models",
         "snippet": "…"},
        {"title": "Release notes", "url": "https://docs.anthropic.com/releases",
         "snippet": "…"},
    ]

    def fake_search(sessions, query, **_kw):
        return {"provider": "ddg", "provider_kind": "html",
                "results": list(real), "attempts": [{"provider": "ddg"}]}

    monkeypatch.setattr(research_service, "search", fake_search)
    outcome = cr.search_for_chat(None, OWNER_QUESTION)
    assert outcome["ok"] is True
    assert outcome["provider"] == "ddg"
    assert [r["url"] for r in outcome["results"]] == \
        [r["url"] for r in real]


def test_sources_context_numbers_real_urls_for_citation():
    """(§L) سياق المصادر مرقّم بعناوين وروابط حقيقية — أساس الاستشهاد."""
    sources = [
        {"title": "عنوان أول", "url": "https://a.example/1",
         "snippet": "مقتطف أول"},
        {"title": "عنوان ثانٍ", "url": "https://b.example/2",
         "snippet": "مقتطف ثانٍ"},
    ]
    context = cr.build_sources_context(sources, [])
    assert "[1] عنوان أول — https://a.example/1" in context
    assert "[2] عنوان ثانٍ — https://b.example/2" in context
    assert "استشهد" in context


def test_empty_sources_yield_no_context():
    assert cr.build_sources_context([], []) == ""


def test_web_denied_context_forbids_pretending():
    """(§L/§30) عند فشل الويب: إعلان يمنع ادّعاء معرفة حيّة."""
    notice = cr.denied_context("bing: النتائج لا تخصّ السؤال")
    assert "تعذّر تنفيذ البحث في الويب" in notice
    assert "النتائج لا تخصّ السؤال" in notice
    assert "لا تدّع" in notice
    assert "قد تكون قديمة" in notice
    assert "لا تخترع روابط" in notice
    assert cr.WEB_DENIED_NOTICE


# ------------------------------------------------------------------ #
# (013.5 §L) بوابة الملاءمة — «نتائج حقيقية» ≠ «نتائج صحيحة»
# ------------------------------------------------------------------ #

def test_irrelevant_results_are_refused_with_a_real_reason():
    """العطل الحي: Bing يرد ‏200 بعشر نتائج لا تخصّ السؤال."""
    from research import providers as rp

    junk = [
        {"title": "أنواع ما في اللغة العربية - موضوع",
         "url": "https://mawdoo3.com/x", "snippet": ""},
        {"title": "ما هي أنواع (ما) وإعرابها؟",
         "url": "https://loghate.com/y", "snippet": ""},
        {"title": "Telekom", "url": "https://www.telekom.de/start",
         "snippet": ""},
    ]
    with pytest.raises(rp.ProviderNotReady) as caught:
        rp.require_relevant("bing", OWNER_QUESTION, junk)
    assert caught.value.reason == rp.SEARCH_RESULTS_IRRELEVANT
    assert "لا تخصّ السؤال" in caught.value.detail
    assert caught.value.details["relevance"]["covered"] == []


def test_relevant_results_pass_untouched():
    from research import providers as rp

    # نتيجة ذات صلة حقيقية: الرمز المميّز (كلاود) حاضر مع أغلب الرموز.
    good = [
        {"title": "Anthropic Claude models — أحدث نماذج كلاود",
         "url": "https://anthropic.com/x",
         "snippet": "احدث نماذج كلاود من Anthropic"},
        {"title": "أحدث نماذج كلاود: القائمة الرسمية",
         "url": "https://docs.example/y",
         "snippet": "نماذج كلاود"},
    ]
    assert rp.require_relevant("searx", OWNER_QUESTION, good) == good


def test_collection_coverage_cannot_pass_unrelated_results():
    """(013.5 §L) العطل المقيس: تغطية مجموعية ‏1.0 لنتائج لا تخصّ السؤال.

    من ويكيبيديا العربية، سؤال «ما هي أحدث نماذج كلاود؟» أعاد:
    «تطبيقات نظام آي أو إس (أبل)»، «الطائرات الإيرانية المسيرة»،
    «رسائل (أبل)» — ومجموعها غطّى الرموز الثلاثة (احدث + نماذج +
    كلاود) فتجاوز بوابة التغطية المجموعية بتغطية ‏1.0. تمرير ذلك
    للنموذج كـ«مصادر ويب حديثة» تلفيق — وهو ما يُرفض الآن.
    """
    from research import providers as rp

    junk = [
        {"title": "إنترنت الأشياء",
         "url": "https://ar.wikipedia.org/wiki/x",
         "snippet": "وفي مايو عام 2017، لاحظ جوانيد علي، وهو خبير حاسوب في "
                    "شركة كلاود فلير، وجود ثغرات أصلية في أجهزة إنترنت "
                    "الأشياء"},
        {"title": "دار الإفتاء المصرية",
         "url": "https://ar.wikipedia.org/wiki/y",
         "snippet": "الإفتاء المصرية على مواقع التواصل الاجتماعي: فيسبوك "
                    "إكس يوتيوب إنستغرام ساوند كلاود تيليجرام"},
        {"title": "تطبيقات نظام آي أو إس (أبل)",
         "url": "https://ar.wikipedia.org/wiki/z",
         "snippet": "وآيفون إكس إس أو أحدث على آي أو إس 14 أو أحدث، تمت "
                    "إعادة تصميم تطبيق الكاميرا"},
        {"title": "الطائرات الإيرانية المسيرة",
         "url": "https://ar.wikipedia.org/wiki/w",
         "snippet": "«إيران تكشف عن أحدث نماذج الطائرات المُسيرة من طراز "
                    "غزة»"},
    ]
    report = rp.relevance_report(OWNER_QUESTION, junk)
    # السnippets أعلاه هي مخرجات حقيقية من wikimedia — والمجموع يغطي
    # كل الرموز الدلالية لأن «كلاود» ترد داخل «كلاود فلير» و«ساوند
    # كلاود»، و«احدث»/«نماذج» تردان في سطور أخرى. هذا بالضبط مكمن
    # العطل: القياس المجموعي يمرّ، والنتائج لا تخصّ السؤال.
    assert report["coverage"] >= 0.6, "التغطية المجموعية عالية — سبب العطل"
    assert report["strong_results"] == 0
    assert report["relevant"] is False, "التغطية المجموعية وحدها لا تكفي"

    with pytest.raises(rp.ProviderNotReady) as caught:
        rp.require_relevant("wikipedia", OWNER_QUESTION, junk)
    assert caught.value.reason == rp.SEARCH_RESULTS_IRRELEVANT


def test_single_token_queries_need_only_that_token():
    from research import providers as rp

    assert rp.relevance_report("Claude", [
        {"title": "Claude", "url": "https://claude.com/", "snippet": ""}
    ])["relevant"] is True
    assert rp.relevance_report("quantum", [
        {"title": "Telekom", "url": "https://telekom.de", "snippet": ""}
    ])["relevant"] is False


def test_multi_token_query_needs_majority_coverage():
    """(§L) نتيجة تكرّر كلمة واحدة فقط = صفحة علامة لا بحث."""
    from research import providers as rp

    report = rp.relevance_report("Claude latest models", [
        {"title": "Claude", "url": "https://claude.com/", "snippet": ""},
        {"title": "Sign in - Claude", "url": "https://claude.ai/",
         "snippet": ""},
    ])
    assert report["tokens"] == ["claude", "latest", "models"]
    assert report["covered"] == ["claude"]
    assert report["required"] == 2
    assert report["relevant"] is False


def test_empty_results_are_a_named_failure():
    from research import providers as rp

    with pytest.raises(rp.ProviderNotReady) as caught:
        rp.require_relevant("ddg", "Claude", [])
    assert caught.value.reason == "NO_RESULTS"


def test_arabic_folding_applies_to_relevance_too():
    """«أحدث» في النتيجة يطابق «احدث» في الاستعلام — تطبيع واحد."""
    from research import providers as rp

    report = rp.relevance_report("أحدث نماذج كلاود", [
        {"title": "احدث نماذج كلاود", "url": "https://a.example/1",
         "snippet": "احدث نماذج"},
    ])
    assert report["relevant"] is True
    assert set(report["covered"]) == {"احدث", "نماذج", "كلاود"}


def test_stopwords_do_not_pollute_the_token_set():
    from research import providers as rp

    assert rp.query_tokens("ما هي أحدث نماذج كلاود؟") == [
        "احدث", "نماذج", "كلاود"]
    assert rp.query_tokens("what are the latest claude models") == [
        "latest", "claude", "models"]


# ------------------------------------------------------------------ #
# (013.5 §L) تقطير الاستعلام المُرسل للمحرك
# ------------------------------------------------------------------ #

def test_search_query_is_distilled_not_the_raw_question():
    """لا نرسل «ما هي» للمحرك — فبعض المحركات تبحث عن «ما» وحدها."""
    distilled = cr.build_search_query(OWNER_QUESTION)
    assert "ما هي" not in distilled
    assert "احدث" in distilled and "نماذج" in distilled
    assert "كلاود" in distilled


@pytest.mark.parametrize("message,expected_parts", [
    ("ما هي احدث نماذج كلاود؟", ("احدث", "نماذج", "كلاود")),
    ("ابحث لي عن أسعار GPUs في 2026", ("اسعار", "gpus")),
    ("What are the latest Claude models?", ("latest", "claude", "models")),
])
def test_distilled_query_keeps_the_meaningful_terms(message,
                                                    expected_parts):
    """التقطير يُقاس لا بحالة الأحرف (البحث لا يفرّق) — لا يُسقِط دلالة."""
    distilled = cr.normalize_arabic(cr.build_search_query(message)).lower()
    for part in expected_parts:
        assert part in distilled, (message, distilled)


def test_distillation_never_invents_words():
    """الصدق: التقطير يحذف فقط — لا يضيف كلمة لم يكتبها المستخدم."""
    message = "ما هي أحدث نماذج كلاود؟"
    distilled = cr.build_search_query(message)
    for token in distilled.split():
        assert cr.normalize_arabic(token) in cr.normalize_arabic(message)


def test_distillation_falls_back_to_the_original_when_empty():
    assert cr.build_search_query("ما هي؟") == "ما هي؟"
    assert cr.build_search_query("") == ""


def test_distilled_query_matches_fixture_style_results():
    """الاستعلام المُقطَّر + البوابة = نتيجة صادقة أو فشل صادق."""
    from research import providers as rp

    distilled = cr.build_search_query(OWNER_QUESTION)
    plausible = [{"title": "أحدث نماذج Claude — القائمة الكاملة",
                  "url": "https://docs.anthropic.com/models",
                  "snippet": "نماذج كلاود الجديدة"}]
    assert rp.require_relevant("searx", distilled, plausible) == plausible
