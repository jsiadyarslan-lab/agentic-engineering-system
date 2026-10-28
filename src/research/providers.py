"""مزودو البحث الحقيقيون (الأمر 010 §25 + 013.2 — إصلاح البحث) — البحث قابل للتوفير.

أربعة مزودين حقيقيين فقط، لا أكثر ولا أقل — كل واحد بتنفيذه الفعلي:

- DuckDuckGoSearchProvider: بحث DDG متعدد الاستراتيجيات بلا مفاتيح
  (lite GET ← lite POST ← html POST) — نقطة html وحدها صارت تعيد
  صفحة تحدّ (anomaly) فيرفضها المحلل؛ الاستراتيجيات الثلاث تُجرّب
  بالترتيب مع كشف التحدّ الصريح (013.2: لا «0 روابط خام» غامضة).
- BingSearchProvider:      بحث Bing HTML بلا مفاتيح — تحليل b_algo
  + فك روابط إعادة التوجيه ck/a — احتياطي DDG المفعّل افتراضيًا
- SearxJsonSearchProvider:  مثيل SearXNG برابط يملكه المالك (JSON API)
- ApiSearchProvider:        نقطة نهاية JSON عامة يملكها المالك + مفتاح

المخطط (Planner) لا يتزوج مزودًا أبدًا (§25): يستدعي research.search()
فتُستخدم أول مزود جاهز — والفشل يعاد بتصنيف مفصل لكل مزود.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Protocol

MAX_SEARCH_RESULTS = 8
#: (AES-EXP-04 §6) مهلات البحث/الجلب — قابلة للضبط بصدق عبر
#: AES_RESEARCH_TIMEOUT_S: الشبكات المعزولة/بيئات الاختبار تضبطها بدل
#: انتظار مهلة TCP كاملة لكل مزود داخل خيط المحادثة المشترك.
_DEFAULT_SEARCH_TIMEOUT = 15.0
_DEFAULT_FETCH_TIMEOUT = 20.0


def search_timeout() -> float:
    """مهلة مزود بحث واحد — AES_RESEARCH_TIMEOUT_S."""
    raw = os.environ.get("AES_RESEARCH_TIMEOUT_S", "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_SEARCH_TIMEOUT
    return value if value > 0 else _DEFAULT_SEARCH_TIMEOUT


def fetch_timeout() -> float:
    """مهلة جلب صفحة واحدة — AES_RESEARCH_TIMEOUT_S."""
    raw = os.environ.get("AES_RESEARCH_TIMEOUT_S", "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_FETCH_TIMEOUT
    return value if value > 0 else _DEFAULT_FETCH_TIMEOUT
MAX_PAGE_BYTES = 400_000

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

#: ترويسات متصفح كاملة (013.2): النقل المجرد بلا Accept/Language كان
#: يسهّل على DDG كشف الطلب الآلي ورد صفحة التحدّ (anomaly).
_BROWSER_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

#: فشل مصنَّف موحد — نقل منفصل عن التحليل (إضافة 008 §3)
SEARCH_NOT_READY = "SEARCH_PROVIDER_NOT_READY"

#: (013.5 §L) سبب رفض صريح: المزود رد بصفحة نتائج لكنها لا تخصّ
#: الاستعلام — لا تُمرَّر للنموذج كأنها مصادر.
SEARCH_RESULTS_IRRELEVANT = "RESULTS_NOT_RELEVANT"


class ProviderNotReady(RuntimeError):
    """المزود غير جاهز — مع تفصيل كل مزود (لا «الإنترنت مقطوع»)."""

    def __init__(self, detail: str, *, reason: str = "PROVIDER_NOT_READY",
                 details: dict | None = None):
        super().__init__(detail)
        self.detail = detail
        self.reason = reason
        self.details = details or {}


# ------------------------------------------------------------------ #
# (013.5 §L) بوابة الملاءمة — «نتائج حقيقية» لا تعني «نتائج صحيحة»
# ------------------------------------------------------------------ #

#: كلمات وظيفية لا تُحتسب كدلالة (عربي مطبَّع + إنجليزي).
_STOPWORDS = frozenset("""
ما هي هو هل في من عن علي الي ان لا لم لن ثم او و هذا هذه ذلك التي الذي
كيف اين متي لماذا كم اي ايه لي ليي اريد اريدك اخبرني قل لي اعطني اكتب
the a an is are was were of for to in on at by with and or not what
which who whom whose how when where why do does did can could should
would will be been being it its this that these those me my i you your
please tell give show explain list about
""".split())

_AR_MARKS_RE = re.compile(r"[\u064B-\u0652\u0670\u0640]")
_AR_FOLD_TABLE = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ئ": "ي",
    "ؤ": "و", "ة": "ه",
})


#: (W2-T25 2026-10-28) استعلام المحرّكات منزوع أرقام الإصدارات حصرًا.
#: الدافع المقيس (تنفيذات 33-35 للمشروع #3): محركات stackoverflow/github/
#: mdn/wikipedia تبحث حرفيًا فتُسقط الاستعلامات المُرقَّمة («Next.js 14.2.0
#: package.json…» ← صفر نتائج من الجميع) بينما المنزوعة تعيد صلة حقيقية
#: (قياس حي: «React package.json peer dependencies» ← stackoverflow+mdn+mwmbl
#: بتغطية 5/5 ونتائج قوية 3). الأمان الصادق: كل ما يُنزَع هنا (أنماط
#: \d+(\.\d+)+ والأرقام المستقلة 1-2 خانة) تُسقطه الرموز الدلالية أصلًا
#: (len<3) — فبوابة الصلة تقيّم الاستعلام الأصلي نفسه ولا ترى فرقًا؛
#: والأرقام الطويلة (2024/100) لا تُمس. حدّ معلن: رقم طويل داخل نمط
#: إصدار (1.100.0) يُنزَع مع النمط كله رغم أن «100» وحدها كانت ستبقى
#: رمزًا — حالة نادرة مقايضة بصراحة مقابل محركات تجد المضمون.
_VERSION_TOKEN_RE = re.compile(r"\b\d+(?:\.\d+)+\b")
_SHORT_NUMBER_RE = re.compile(r"(?<![\d.])\b\d{1,2}\b(?![\d.])")


def engine_query(query: str) -> str:
    """نسخة الاستعلام للمحركات — بلا أرقام إصدارات (W2-T25).

    فصل صادق: ما يُنزَع غير مرئي لبوابة الصلة أصلًا (رموز <3 خانات)،
    والبوابة تُقيّم الاستعلام الأصلي كما هو — لا تمرير أوسع ولا صلة
    مدّعاة: فقط محركات تجد المضمون الذي تطلبه بلا ضجيج رقمي.
    """
    stripped = _VERSION_TOKEN_RE.sub(" ", str(query or ""))
    stripped = _SHORT_NUMBER_RE.sub(" ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped or str(query or "")


def fold_text(text: str) -> str:
    """تطبيع عربي/حالة موحّد — الأساس المشترك للمطابقة (§L)."""
    lowered = str(text or "").lower()
    return _AR_MARKS_RE.sub("", lowered).translate(_AR_FOLD_TABLE)


def query_tokens(query: str) -> list[str]:
    """رموز الاستعلام الدلالية — بلا كلمات وظيفية ولا ترقيم (§L).

    ملاحظة: الترقيم العربي (؟ ، ؛) يقع داخل نطاق الحروف العربية في
    يونيكود، فالتقسيم على ``\\w`` وحده كان يُبقي «كلاود؟» رمزًا
    مختلفًا عن «كلاود» فيفشل التطابق بلا سبب.
    """
    raw = _TOKEN_SPLIT.split(fold_text(query))
    tokens: list[str] = []
    for token in raw:
        if len(token) < 3 or token in _STOPWORDS:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


#: فاصل الرموز: حروف لاتينية/عربية/أرقام فقط — كل ترقيم يُسقط.
_TOKEN_SPLIT = re.compile(
    r"[^0-9a-z_\u0621-\u064a\u0660-\u0669\u066e-\u06d3]+"
)

#: (W2-T20) كشف لغة الاستعلام من كتابته — حروف عربية في النص = ar.
_ARABIC_SCRIPT_RE = re.compile(r"[\u0621-\u064a]")


#: كلمات عامة شائعة في الأسئلة — وجودها في نتيجة لا يُثبت صلتها.
#: «أحدث نماذج كلاود» طابق «أحدث نماذج الطائرات المسيرة» بمجموعها فقط،
#: فظهرت نتيجة لا تخصّ السؤال. الرمز النادر وحده يُثبت الصلة.
#:
#: (W2-T22 2026-10-28) إضافات الأخبار/المتابعة: «أخبار اليوم» عنوان أي
#: صفحة رئيسية لإعلامٍ ما — مرّرت بوابة الصلة لاستعلام «اخبار انتخابات
#: الكنسيت اليوم» فتوقف المزود الأول قبل SearXNG بصفحتين رئيسيتين
#: لا تحملان نتيجة واحدة (دليل conv-15 دور 1). الكلمات الإخبارية
#: العامة (اخبار/اليوم/نتائج/مباشر…) لا تُثبت الصلة وحدها؛ الرمز
#: الموضوعي (انتخابات/الكنسيت…) هو المُثبت.
_GENERIC_TOKENS = frozenset(fold_text(t) for t in (
    "احدث", "أحدث", "اخر", "آخر", "اصدار", "إصدار", "اصدارات", "إصدارات",
    "نماذج", "نموذج", "جديد", "جديدة", "مقارنة", "افضل", "أفضل", "latest",
    "new", "newest", "models", "model", "version", "versions", "release",
    "released", "compare", "best", "top", "list",
    # (W2-T22) عام إخباري/متابعة — عناوين الصفحات الرئيسية تحتها
    "اخبار", "الاخبار", "أخبار", "خبر", "اليوم", "الان", "الآن", "حاليا",
    "مباشر", "تغطية", "نتيجة", "نتائج", "ملخص", "ملخصات", "انت", "عاجل",
    "news", "today", "now", "live", "coverage", "summary", "breaking",
))


def _result_haystack(result: dict) -> str:
    return fold_text(" ".join(str(result.get(key) or "") for key in (
        "title", "url", "snippet", "href")))


#: (W2-T22) أدنى طول لرمز يستحق تسامح الإملاء — الرموز القصيرة
#: (<5) كثيرة الأشباه العرضية فتضخّم التغطية بلا دليل.
_FUZZY_MIN_LEN = 5


def _levenshtein_within(a: str, b: str, cap: int) -> bool:
    """مسافة ليفنشتاين ≤ cap بخروج مبكر — رموز قصيرة فقط (W2-T22)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > cap:
        return False
    if la > lb:
        a, b, la, lb = b, a, lb, la
    previous = list(range(lb + 1))
    for i in range(1, la + 1):
        current = [i] + [0] * lb
        best = i
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            current[j] = min(previous[j] + 1, current[j - 1] + 1,
                             previous[j - 1] + cost)
            if current[j] < best:
                best = current[j]
        if best > cap:
            return False
        previous = current
    return previous[lb] <= cap


def _fuzzy_hit(token: str, haystack_tokens) -> bool:
    """تسامح الإملاء للرموز المميزة الطويلة (W2-T22).

    الدافع الموثق (conv-15): إملاء المالك «الكنسيت» (قلب س/ي) كان يجعل
    5 من 6 نتائج SearXNG الحية عن انتخابات الكنيست «ضعيفة»
    (hit=انتخابات وحدها) فيخنق البحث إلى نتيجة واحدة — مستنسخ بكود
    التطبيق نفسه. رموز ≥7 حروف: مسافة ≤2؛ رموز 5-6: مسافة ≤1.
    """
    if len(token) < _FUZZY_MIN_LEN:
        return False
    cap = 1 if len(token) <= 6 else 2
    for candidate in haystack_tokens:
        if abs(len(candidate) - len(token)) > cap:
            continue
        if _levenshtein_within(token, candidate, cap):
            return True
    return False


def result_relevance(query: str, result: dict) -> dict:
    """صلة **نتيجة واحدة** بالاستعلام — لا مجموع النتائج.

    العطل الحي الذي يغلقه هذا القياس: سؤال «ما هي أحدث نماذج كلاود؟»
    أعاد من ويكيبيديا «تطبيقات نظام آي أو إس» و«الطائرات الإيرانية
    المسيرة» و«رسائل (أبل)»، ومجموع النتائج غطّى الرموز الثلاثة فتجاوز
    البوابة بتغطية ‏1.0 — تمرير ذلك للنموذج كـ«مصادر ويب» تلفيق خالص.
    القياس الصادق لكل نتيجة: أغلب رموز الاستعلام **فيها هي**، وأحدها
    على الأقل رمز نادر (غير عام).
    """
    tokens = query_tokens(query)
    if not tokens:
        return {"tokens": [], "hit": [], "ratio": 1.0, "specific": [],
                "strong": True}
    haystack = _result_haystack(result)
    hit = [t for t in tokens if t in haystack]
    #: (W2-T22) تسامح الإملاء — الكنسيت↔الكنيست: قلب حرفين في إملاء
    #: المستخدم أسقط نتائج حية قوية إلى «ضعيفة». يُطبق على الرموز
    #: المميزة (غير العامة) الطويلة حصراً حتى لا تتضخم التغطية بلا
    #: دليل، والرموز العامة لا تُسامَح أصلًا لأنها لا تُثبت شيئًا.
    if len(tokens) > len(hit):
        haystack_tokens: set[str] | None = None
        for token in tokens:
            if token in hit or token in _GENERIC_TOKENS:
                continue
            if haystack_tokens is None:
                haystack_tokens = {
                    part for part in _TOKEN_SPLIT.split(haystack) if part
                }
            if _fuzzy_hit(token, haystack_tokens):
                hit.append(token)
    ratio = len(hit) / len(tokens)
    specific = [t for t in hit if t not in _GENERIC_TOKENS]
    #: (W2-T22) استعلام كله كلمات عامة («أخبار اليوم»): الطلب نفسه عام
    #: فلا يوجد رمز نادر يميّز نتيجة عن أخرى — نقبل المطابق العام بدل
    #: رفض كل شيء؛ طلب «أخبار اليوم» مشروع في ذاته وتجيب عنه الصفحات
    #: الإخبارية العامة. الاستعلام ذو الرمز الموضوعي الواحد يبقى محكومًا
    #: بالقاعدة الصارمة أعلاه (حرس التلفيق لا يُمسّ).
    if tokens and not any(t not in _GENERIC_TOKENS for t in tokens):
        specific = list(hit)
    #: القاعدة: أغلب رموز الاستعلام **في هذه النتيجة** (لا في مجموع
    #: النتائج)، وأحدها على الأقل رمز مميّز.
    #:
    #: لماذا لا «كل الرموز المميّزة حاضرة»؟ لأن الاسم الأجنبي المكتوب
    #: بالعربية يطابق كلمات مركبة أخرى: «كلاود» في سؤال عن Claude
    #: موجودة فعلًا في «كلاود فلير» و«ساوند كلاود» — فمرّت نتيجة عن
    #: إنترنت الأشياء ونتيجة عن دار الإفتاء، وهو التلفيق نفسه. النسبة
    #: المجموعية تُسقطها (‏1/3) وتُبقي الصلة الحقيقية (‏رياكت، حوسبة
    #: كمومية، Claude).
    #:
    #: (W2-T20 2026-10-28) الاستعلامات الطويلة الطبيعية (>5 رموز):
    #: عتبة 60% في نتيجة واحدة غير قابلة للتحقيق رياضيًا — العناوين
    #: والمقتطفات قصيرة بطبيعتها (استعلام 17 رمزًا يطلب 10 منها في
    #: نتيجة واحدة — مستحيل حتى على صفحة نتائج ممتازة). البار الصادق
    #: المكافئ: 3 رموز فعلية في النتيجة نفسها وأحدها مميّز — يمنع
    #: تمرير نتائج عمياء ويفتح الاستعلامات الطويلة.
    #:
    #: (W2-T20 2026-10-28) الاستعلامات القصيرة والمرادفات: تطابق 60%
    #: حرفيًا يخفي صلة حقيقية عند المرادفات (وصولية/النفاذ) — نتيجة
    #: برمزين فعليين أحدهما مميّز (wcag+وصولية في «دليل WCAG الشامل
    #: للوصولية») صلة مثبتة. حرس التلفيق يبقى: رمز واحد في النتيجة
    #: (صفحة علامة تجارية/تطابق اسم أجنبي) = ضعيف كما كان.
    if len(tokens) > 5:
        strong = len(hit) >= 3 and bool(specific)
    else:
        strong = (ratio >= 0.6 or len(hit) >= 2) and bool(specific)
    return {"tokens": tokens, "hit": hit, "ratio": round(ratio, 3),
            "specific": specific, "discriminating": [
                t for t in tokens if t not in _GENERIC_TOKENS],
            "strong": bool(strong)}


def filter_relevant(query: str, results: list[dict]) -> list[dict]:
    """النتائج القوية فقط — بترتيبها الأصلي."""
    return [r for r in (results or []) if result_relevance(query, r)["strong"]]


def relevance_report(query: str, results: list[dict]) -> dict:
    """تغطية رموز الاستعلام في النتائج — قياس صادق لا حكم ذوقي.

    العطل الحي: Bing رد ‏200 بصفحة نتائج كاملة وبلا أي علامة تحدّ،
    لكن عناوينها لا تخصّ السؤال إطلاقًا («أنواع ما في اللغة العربية»
    لسؤال عن أحدث نماذج Claude؛ «Telekom» لـ«احدث نماذج كلاود»).
    تمرير ذلك للنموذج كـ«مصادر ويب حديثة» تلفيق. البوابة تقيس تغطية
    الرموز الدلالية **لكل نتيجة** (لا لمجموعها) وتعلن الفشل بسببه.
    """
    tokens = query_tokens(query)
    if not tokens:
        return {"tokens": [], "covered": [], "coverage": 1.0,
                "required": 0, "relevant": True, "matched_results": 0,
                "strong_results": 0}
    covered: list[str] = []
    matched_results = 0
    strong = 0
    for result in results or []:
        report = result_relevance(query, result)
        if report["hit"]:
            matched_results += 1
            for token in report["hit"]:
                if token not in covered:
                    covered.append(token)
        if report["strong"]:
            strong += 1
    coverage = len(covered) / len(tokens)
    #: العتبة: أغلب الرموز الدلالية يجب أن تظهر فعلًا في النتائج.
    #: رمز واحد في استعلام متعدد الرموز = نتيجة اسمية (brand homepage)
    #: لا بحث — وهي بالضبط ما يجب رفضه.
    #:
    #: (W2-T20 2026-10-28) سقف للعتبة عند الاستعلامات الطويلة: 60% من
    #: 17 رمزًا = 10 رموز مجموعية — غير قابل للتحقيق على أي صفحة
    #: نتائج حقيقية (العناوين قصيرة). السقف 4 رموز مميزة + نتيجة قوية
    #: واحدة (بنفسها تطلب 3 رموز فعلية) يبقى بوابة صادقة ضد التلفيق.
    required = 1 if len(tokens) == 1 else max(
        2, int(len(tokens) * 0.6 + 0.5))
    if len(tokens) > 5:
        required = min(required, 4)
    return {
        "tokens": tokens,
        "covered": covered,
        "coverage": round(coverage, 3),
        "required": required,
        "matched_results": matched_results,
        "strong_results": strong,
        #: شرطان معًا: تغطية مجموعية كافية **و**نتيجة واحدة قوية على
        #: الأقل. التغطية المجموعية وحدها أنتجت ‏1.0 لنتائج لا تخصّ
        #: السؤال — وهو التلفيق نفسه الذي يمنعه §L.
        "relevant": len(covered) >= required and strong > 0,
    }


def require_relevant(provider_name: str, query: str,
                     results: list[dict]) -> list[dict]:
    """يرفض نتائج لا تخصّ الاستعلام — لا «نجاح» بنتائج عمياء (§L).

    (013.5 §L) يُعيد **النتائج القوية فقط**: تمرير نتائج ضعيفة مع
    القوية يُبقي التلفيق ممكنًا لأن النموذج يقرأ كل ما يُمرَّر.
    """
    if not results:
        raise ProviderNotReady(
            f"{provider_name}: صفر نتائج — لا مصادر لتمريرها",
            reason="NO_RESULTS",
            details={"query": query[:200]},
        )
    report = relevance_report(query, results)
    if report["relevant"]:
        strong = filter_relevant(query, results)
        # النتائج القوية فقط تصل للنموذج — البقية تُسقَط ولا تُمرَّر.
        return strong or results
    raise ProviderNotReady(
        f"{provider_name}: {len(results)} نتيجة لكن تغطية الاستعلام "
        f"{len(report['covered'])}/{len(report['tokens'])} "
        f"(المطلوب {report['required']}، ونتائج قوية "
        f"{report.get('strong_results', 0)}) — النتائج لا تخصّ السؤال",
        reason=SEARCH_RESULTS_IRRELEVANT,
        details={"query": query[:200], "relevance": report,
                 "sample_titles": [
                     (r.get("title") or "")[:80] for r in results[:4]]},
    )


class SearchProvider(Protocol):
    """عقد مزود بحث (§25) — search واحد صادق لكل مزود."""

    provider_id: str
    kind: str

    def search(self, query: str, *, timeout: float | None = None) -> list[dict]:
        if timeout is None:
            timeout = search_timeout()
        """[{title, url, snippet}] — بلا نتائج تحليلية = خطأ مصنّف."""

    def describe(self) -> dict:
        """وصف المزود — بلا أسرار أبدًا."""


def _tag(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


# ------------------------------------------------------------------ #
# ويكيبيديا — بحث حي حقيقي بلا مفاتيح (013.5 §L)
# ------------------------------------------------------------------ #

class WikipediaSearchProvider:
    """بحث ويكيبيديا الحقيقي عبر واجهة MediaWiki العامة بلا مفاتيح.

    السبب المقيس: كل محركات البحث العامة من هذا المضيف ترد بصفحة تحدٍّ
    أو حجب (‏DuckDuckGo anomaly، Mojeek captcha، Brave ‏429، Ecosia
    ‏403)، ومعها لا «بحث ويب حي» في المحادثة العادية — وهو طلب §L
    الصريح. واجهة MediaWiki ترد ‏200 بمحتوى حقيقي من نفس المضيف،
    وتغطي ما يسأل عنه المالك فعلًا (النماذج/المكتبات/الأحداث الجارية).

    **ليست بحثًا عامًا**: هي مصدر موسوعي حقيقي ومعلن — والوصف يقول ذلك
    حرفيًا، فلا يُدَّعى تعميم لا يملكه المزود.
    """

    provider_id = "wikipedia"
    kind = "search_wikipedia"

    #: النسخ المدعومة — العربية أولًا (المالك يسأل بالعربية) ثم الإنجليزية.
    _WIKIS: tuple[tuple[str, str], ...] = (
        ("ar", "https://ar.wikipedia.org/w/api.php"),
        ("en", "https://en.wikipedia.org/w/api.php"),
    )

    def __init__(self, endpoint: str = "", limit: int = 6):
        self.endpoint = endpoint
        self.limit = int(limit or 6)

    def describe(self) -> dict:
        return {
            "provider_id": self.provider_id, "kind": self.kind,
            "name": "ويكيبيديا (بحث موسوعي حي، بلا مفاتيح)",
            "requires_key": False,
            "note": "مصدر موسوعي معلن — ليس بحثًا عامًا على الويب",
            # (013.5 §L) حدّ صريح لا يُخفى: المطابقة نصية على الرموز،
            # فاسم أجنبي مكتوب بالعربية قد يطابق كلمة مركبة أخرى —
            # «كلاود» في سؤال عن ‏Claude تطابق «كلاود فلير» و«ساوند
            # كلاود». البوابة تُسقط ما لا يحمل أي رمز مميّز، لكن
            # التطابق الدلالي الكامل يحتاج مترجمًا/تحويل حروف لاتينية
            # (غير متاح هنا) — فالتقرير يعلن هذا الحدّ بدل ادعاء دقة.
            "relevance_caveat": (
                "مطابقة نصية على رموز الاستعلام؛ التطابق الدلالي "
                "(ترجمة/نقل حرفي) غير مدعوم"
            ),
            "config": {
                "wikis": [w[0] for w in self._WIKIS]
                if not self.endpoint else ["custom"],
                "endpoint": self.endpoint or "auto (ar/en MediaWiki API)",
                "limit": self.limit,
            },
        }

    def _endpoints(self) -> list[tuple[str, str]]:
        if self.endpoint:
            return [("custom", self.endpoint)]
        return list(self._WIKIS)

    def _search_one(self, label: str, endpoint: str, query: str,
                    timeout: float) -> list[dict]:
        # (W2-T25) المحرك يبحث بالنسخة المنزوعة الأرقام — بوابة الصلة
        # في search() تقيّم الاستعلام الأصلي نفسه.
        url = endpoint + "?" + urllib.parse.urlencode({
            "action": "query", "list": "search",
            "srsearch": engine_query(query),
            "format": "json", "srlimit": self.limit,
        })
        request = urllib.request.Request(url, headers={
            "User-Agent": _USER_AGENT, "Accept": "application/json",
        })
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        hits = ((payload.get("query") or {}).get("search") or [])
        results: list[dict] = []
        for hit in hits:
            title = str(hit.get("title") or "").strip()
            if not title:
                continue
            page = urllib.parse.quote(title.replace(" ", "_"))
            results.append({
                "title": title,
                "url": f"https://{label}.wikipedia.org/wiki/{page}",
                "snippet": _tag(str(hit.get("snippet") or "")).strip(),
                "source": f"wikipedia-{label}",
            })
        return results

    def search(self, query: str, *, timeout: float | None = None) -> list[dict]:
        if timeout is None:
            timeout = search_timeout()
        attempts: list[dict] = []
        collected: list[dict] = []
        seen: set[str] = set()
        for label, endpoint in self._endpoints():
            try:
                found = self._search_one(label, endpoint, query, timeout)
            except Exception as error:  # noqa: BLE001 — تصنيف صريح
                attempts.append({"wiki": label, "ok": False,
                                 "error": f"{type(error).__name__}: "
                                          f"{str(error)[:160]}"})
                continue
            attempts.append({"wiki": label, "ok": True, "count": len(found)})
            for item in found:
                if item["url"] in seen:
                    continue
                seen.add(item["url"])
                collected.append(item)
        if not collected:
            raise ProviderNotReady(
                "wikipedia: صفر نتائج حقيقية — "
                + json.dumps(attempts, ensure_ascii=False)
            )
        report = relevance_report(query, collected)
        if report["relevant"]:
            return collected
        # الاستعلام بالعربية قد لا يطابق عناوين النسخة العربية (سؤال
        # «أحدث نماذج كلاود» ← مقالة «كلود (نموذج لغوي)»). نُعلن عدم
        # الصلة صراحةً بدل تمرير نتائج لا تُثبت السؤال.
        raise ProviderNotReady(
            "wikipedia: نتائج غير ذات صلة — "
            + json.dumps({**report, "attempts": attempts},
                         ensure_ascii=False)[:400]
        )


# ------------------------------------------------------------------ #
# DuckDuckGo — متعدد الاستراتيجيات بلا مفاتيح (013.2: إصلاح البحث)
# ------------------------------------------------------------------ #

class DuckDuckGoSearchProvider:
    """بحث DuckDuckGo — ثلاث استراتيجيات تُجرّب بالترتيب (013.2).

    نقطة ``html`` بـPOST كانت تعيد صفحة تحدّ (anomaly-modal) لطلبات
    الأتمتة — نقل ناجح وصفر روابط «لا نتائج قابلة للتحليل». الآن:
    lite GET ← lite POST ← html POST، بترويسات متصفح كاملة، وكشف
    التحدّ مصنفًا باسمه — وأي استراتيجية تنجح تُستخدم نتائجها.
    """

    provider_id = "ddg"
    kind = "search_ddg"

    _STRATEGIES: tuple[tuple[str, str, str], ...] = (
        # (اسم الاستراتيجية، نقطة النهاية، الطريقة)
        ("lite-get", "https://lite.duckduckgo.com/lite/", "GET"),
        ("lite-post", "https://lite.duckduckgo.com/lite/", "POST"),
        ("html-post", "https://html.duckduckgo.com/html/", "POST"),
    )

    def __init__(self, endpoint: str = ""):
        #: endpoint مخصص (اختبارات/وكيل) يلغي الاستراتيجيات المتعددة
        self.endpoint = endpoint

    def describe(self) -> dict:
        return {
            "provider_id": self.provider_id, "kind": self.kind,
            "name": "DuckDuckGo (بلا مفاتيح)",
            "requires_key": False,
            "config": {
                "endpoint": self.endpoint or "auto (lite/html ×3)",
                "strategies": [s[0] for s in self._STRATEGIES]
                if not self.endpoint else ["custom"],
            },
        }

    def _fetch(self, endpoint: str, method: str, query: str,
               timeout: float) -> str:
        if method == "POST":
            data = urllib.parse.urlencode({"q": query}).encode("utf-8")
            headers = {
                **_BROWSER_HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
            }
            request = urllib.request.Request(
                endpoint, data=data, method="POST", headers=headers,
            )
        else:
            url = endpoint + "?q=" + urllib.parse.quote(query)
            request = urllib.request.Request(
                url, headers=dict(_BROWSER_HEADERS),
            )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")

    def search(self, query: str, *, timeout: float | None = None) -> list[dict]:
        if timeout is None:
            timeout = search_timeout()
        attempts: list[dict] = []
        #: آخر نتائج حُلّلت ورُفضت لعدم الصلة — تُرفق في التفصيل
        last_results: list[dict] = []
        if self.endpoint:
            strategies = [("custom", self.endpoint, "POST")]
        else:
            strategies = list(self._STRATEGIES)
        for name, endpoint, method in strategies:
            try:
                page = self._fetch(endpoint, method, query, timeout)
            except Exception as error:  # noqa: BLE001 — جرب التالية
                attempts.append({
                    "strategy": name,
                    "error": f"{type(error).__name__}: {error}"[:140],
                })
                continue
            if _is_challenge_page(page):
                attempts.append({
                    "strategy": name,
                    "error": "صفحة تحدّ (anomaly) — DDG حجب هذا "
                            "المضيف مؤقتًا",
                })
                continue
            try:
                results = _ddg_parse(page, query)
            except ProviderNotReady as error:
                attempts.append({
                    "strategy": name,
                    "error": str(error)[:140],
                })
                continue
            if results:
                # (013.5 §L) جودة لا كمية: استراتيجية ترد نتائج لا تخصّ
                # الاستعلام تُرفض وتُجرَّب التالية — لا تمرير أعمى.
                try:
                    return require_relevant("ddg", query, results)
                except ProviderNotReady as error:
                    attempts.append({
                        "strategy": name,
                        "error": str(error)[:160],
                        "reason": error.reason,
                    })
                    last_results = results
                    continue
            attempts.append({
                "strategy": name, "error": "لا نتائج قابلة للتحليل",
            })
        detail = "؛ ".join(
            f"{a['strategy']}: {a['error']}" for a in attempts
        ) or "لا استراتيجيات"
        # (013.5 §L) إن كان سبب فشل كل الاستراتيجيات هو **عدم الصلة**
        # فالتصنيف الصادق هو RESULTS_NOT_RELEVANT لا «تعذّر التحليل»:
        # المزود ردّ وحُلّل فعلًا، والرفض جاء من بوابة الملاءمة —
        # والفرق يظهر في المسبار والتقرير.
        only_irrelevant = bool(attempts) and all(
            a.get("reason") == SEARCH_RESULTS_IRRELEVANT for a in attempts
        )
        details: dict = {"query": query[:200], "attempts": attempts}
        if only_irrelevant:
            # القياس الصادق مرفق: المسبار والتقرير يقرآن **لماذا** رُفضت
            details["relevance"] = relevance_report(query, last_results)
            details["sample_titles"] = [
                (r.get("title") or "")[:80] for r in last_results[:4]]
        raise ProviderNotReady(
            f"ddg: كل الاستراتيجيات فشلت — {detail}",
            reason=(SEARCH_RESULTS_IRRELEVANT if only_irrelevant
                    else "RESULTS_NOT_ANALYZABLE"),
            details=details,
        )


def _is_challenge_page(page: str) -> bool:
    """هل الصفحة تحدّ/كابتشا لا نتائج؟ (013.2 — تصنيف صادق)"""
    head = page[:6000].lower()
    return (
        "anomaly" in head
        or "challenge" in head
        or "js-anomaly" in page
        or "captcha" in head
    )


_RESULT_LINK = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_RESULT_SNIPPET = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.DOTALL
)

#: صفحة lite: الروابط بخلاصة result-link والنصوص في خلايا td تالية
_LITE_LINK = re.compile(
    r'<a[^>]+class="[^"]*result-link[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_LITE_SNIPPET = re.compile(
    r'class="result-snippet"[^>]*>(.*?)</td>', re.DOTALL
)


def _ddg_redirect_url(raw: str) -> str:
    try:
        if "uddg=" in raw:
            query = urllib.parse.urlparse(raw).query
            value = urllib.parse.parse_qs(query).get("uddg", [""])[0]
            return urllib.parse.unquote(value) if value else raw
    except ValueError:
        pass
    return raw


def _ddg_parse(page: str, query: str) -> list[dict]:
    """تحليل صفحات DDG — ترميز html (result__a) وترميز lite (result-link)."""
    links = _RESULT_LINK.findall(page)
    snippets = _RESULT_SNIPPET.findall(page)
    markup = "html"
    if not links:
        links = _LITE_LINK.findall(page)
        snippets = _LITE_SNIPPET.findall(page)
        markup = "lite"
    results: list[dict] = []
    for index, (raw_url, title_html) in enumerate(links[:MAX_SEARCH_RESULTS]):
        title = html_lib.unescape(_tag(title_html)).strip()
        url = _ddg_redirect_url(html_lib.unescape(raw_url))
        snippet = ""
        if index < len(snippets):
            snippet = html_lib.unescape(
                _tag(snippets[index])
            ).strip()[:300]
        if title and url.startswith("http"):
            results.append({"title": title, "url": url, "snippet": snippet})
    if not results:
        raise ProviderNotReady(
            f"ddg ({markup}): لا نتائج قابلة للتحليل "
            f"({len(links)} روابط خام) لاستعلام: {query[:60]}",
            reason="RESULTS_NOT_ANALYZABLE",
            details={"query": query[:200], "transport": "SUCCESS",
                     "markup": markup, "page_chars": len(page),
                     "links_extracted": len(links),
                     "snippets_extracted": len(snippets)},
        )
    return results


# ------------------------------------------------------------------ #
# Bing — HTML بلا مفاتيح (013.2: الاحتياطي المفعّل لبحث يعمل فعلًا)
# ------------------------------------------------------------------ #

class BingSearchProvider:
    """بحث Bing HTML بلا مفاتيح — تحليل b_algo مع فك روابط ck/a.

    DDG صار يحجب الأتمتة بصفحات تحدّ متكررة؛ Bing يرد صفحة نتائج
    قابلة للتحليل — فيصير المسار الافتراضي: ddg ثم bing ثم searx/api.
    روابط Bing معادة التوجيه (bing.com/ck/a؟...&u=a1<base64url>)
    تُفك للموقع الحقيقي قبل إعادته.
    """

    provider_id = "bing"
    kind = "search_bing"

    def __init__(self, endpoint: str = "https://www.bing.com/search"):
        self.endpoint = endpoint

    def describe(self) -> dict:
        return {
            "provider_id": self.provider_id, "kind": self.kind,
            "name": "Bing (بلا مفاتيح)",
            "requires_key": False,
            "config": {"endpoint": self.endpoint},
        }

    def search(self, query: str, *, timeout: float | None = None) -> list[dict]:
        if timeout is None:
            timeout = search_timeout()
        import base64

        url = (self.endpoint + "?q=" + urllib.parse.quote(query)
               + "&count=10")
        request = urllib.request.Request(
            url, headers=dict(_BROWSER_HEADERS),
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                page = response.read().decode("utf-8", "replace")
        except Exception as error:  # noqa: BLE001 — تصنيف واحد
            raise ProviderNotReady(
                f"bing: نقل فاشل — {type(error).__name__}: {error}"
            ) from error
        if _is_challenge_page(page):
            raise ProviderNotReady(
                "bing: صفحة تحدّ — حجب مؤقت لهذا المضيف",
                reason="RESULTS_NOT_ANALYZABLE",
            )
        blocks = re.findall(
            r'<li class="b_algo".*?</li>', page, re.DOTALL,
        )
        results: list[dict] = []
        for block in blocks[:MAX_SEARCH_RESULTS]:
            heading = re.search(
                r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                block, re.DOTALL,
            )
            if not heading:
                continue
            href = html_lib.unescape(heading.group(1))
            real_url = href
            if "bing.com/ck/" in href:
                try:
                    query_string = urllib.parse.urlparse(href).query
                    encoded = urllib.parse.parse_qs(query_string).get(
                        "u", [""])[0]
                    if encoded.startswith("a1"):
                        padded = encoded[2:] + "=" * (
                            -len(encoded[2:]) % 4)
                        real_url = base64.urlsafe_b64decode(
                            padded).decode("utf-8", "replace")
                except Exception:  # noqa: BLE001 — الرابط الخام يبقى
                    real_url = href
            title = _tag(heading.group(2)).strip()
            snippet = ""
            para = re.search(r"<p[^>]*>(.*?)</p>", block, re.DOTALL)
            if para:
                snippet = html_lib.unescape(
                    _tag(para.group(1))).strip()[:300]
            if title and real_url.startswith("http"):
                results.append({
                    "title": title, "url": real_url, "snippet": snippet,
                })
        if not results:
            raise ProviderNotReady(
                f"bing: لا نتائج قابلة للتحليل ({len(blocks)} كتلة خام) "
                f"لاستعلام: {query[:60]}",
                reason="RESULTS_NOT_ANALYZABLE",
                details={"query": query[:200], "transport": "SUCCESS",
                         "blocks": len(blocks), "page_chars": len(page)},
            )
        # (013.5 §L) Bing يرد ‏200 بصفحة نتائج كاملة وبلا علامة تحدّ،
        # لكن عناوينها كثيرًا ما تكون تنقّلًا إلى موقع العلامة وحدها
        # («Claude» ← claude.com؛ «Telekom» لاستعلام عربي غير مفهوم).
        # تمرير ذلك كـ«مصادر ويب» تلفيق — البوابة ترفضه بسببه.
        return require_relevant("bing", query, results)


# ------------------------------------------------------------------ #
# SearXNG — مثيل يملكه المالك (JSON API)
# ------------------------------------------------------------------ #

class SearxJsonSearchProvider:
    """مثيل SearXNG — يملك المالك رابطه (مثيله الخاص أو موثوق)."""

    provider_id = "searx"
    kind = "search_searx"

    def __init__(self, base_url: str = ""):
        self.base_url = base_url.rstrip("/")

    def describe(self) -> dict:
        return {
            "provider_id": self.provider_id, "kind": self.kind,
            "name": "SearXNG (JSON)",
            "requires_key": False,
            "config": {"base_url": self.base_url or "غير مُعد — عيّن الرابط"},
        }

    def search(self, query: str, *, timeout: float | None = None) -> list[dict]:
        if timeout is None:
            timeout = search_timeout()
        if not self.base_url:
            raise ProviderNotReady(
                "searx: بلا رابط مثيل — عيّن base_url من إعدادات البحث"
            )
        # (W2-T20) لغة الاستعلام من نصّه: عربي → ar (وإلا en). الصلب
        # على en كان يجلب نتائج إنجليزية لاستعلام عربي فترفضها بوابة
        # الصلة بتغطية 0/5 بصدق — والاستعلامات الفعلية للنموذج عربية.
        language = "ar" if _ARABIC_SCRIPT_RE.search(query) else "en"
        # (W2-T25) المحركات تُستعلم بالنسخة المنزوعة أرقام الإصدارات —
        # المطابقة الحرفية لـ«14.2.0» تُسقط المحركات كلها؛ بوابة الصلة
        # أدناه تقيّم الاستعلام الأصلي كما هو.
        engine_q = engine_query(query)
        url = (
            f"{self.base_url}/search?q={urllib.parse.quote(engine_q)}"
            f"&format=json&language={language}"
        )
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            raise ProviderNotReady(
                f"searx: المثيل رد {error.code} — "
                "قد تكون JSON API معطلة في هذا المثيل"
            ) from error
        except Exception as error:  # noqa: BLE001
            raise ProviderNotReady(
                f"searx: نقل فاشل — {type(error).__name__}: {error}"
            ) from error
        results: list[dict] = []
        for item in data.get("results", [])[:MAX_SEARCH_RESULTS]:
            title = str(item.get("title", "")).strip()
            link = str(item.get("url", ""))
            if title and link.startswith("http"):
                results.append({
                    "title": title, "url": link,
                    "snippet": str(item.get("content", ""))[:300],
                })
        if not results:
            raise ProviderNotReady(
                f"searx: لا نتائج قابلة للتحليل لاستعلام: {query[:60]}",
                reason="RESULTS_NOT_ANALYZABLE",
            )
        return require_relevant("searx", query, results)


# ------------------------------------------------------------------ #
# API عام — نقطة نهاية يملكها المالك + مفتاح
# ------------------------------------------------------------------ #

#: أنماط الرد المدعومة — كل نمط له تحليله الحقيقي
API_STYLES = ("generic_results", "tavily", "brave")


class ApiSearchProvider:
    """نقطة نهاية JSON عامة بمفتاح (يفهم صيغ tavily/brave/عام)."""

    provider_id = "api"
    kind = "search_api"

    def __init__(self, endpoint: str = "", key: str = "", style: str = "generic_results"):
        self.endpoint = endpoint
        self.key = key
        self.style = style if style in API_STYLES else "generic_results"

    def describe(self) -> dict:
        return {
            "provider_id": self.provider_id, "kind": self.kind,
            "name": "Search API (مفتاح)",
            "requires_key": True,
            "config": {
                "endpoint": self.endpoint or "غير مُعد",
                "style": self.style,
                "key": "****" if self.key else "غير محفوظ",
            },
        }

    def search(self, query: str, *, timeout: float | None = None) -> list[dict]:
        if timeout is None:
            timeout = search_timeout()
        if not self.endpoint:
            raise ProviderNotReady(
                "api: بلا نقطة نهاية — عيّنها من إعدادات البحث"
            )
        # (W2-T25) نقطة النهاية تُستعلم بالنسخة المنزوعة أرقام الإصدارات —
        # هي غلاف فوق SearXNG فتتوارث مطابقته الحرفية؛ البوابة تقيّم
        # الاستعلام الأصلي.
        engine_q = engine_query(query)
        body = json.dumps({"query": engine_q, "q": engine_q,
                           "max_results": MAX_SEARCH_RESULTS}).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.key}" if self.key else "",
                "X-API-Key": self.key,
                "User-Agent": _USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            raise ProviderNotReady(
                f"api: النقطة ردت {error.code}"
                + (" (401/403 = مفتاح غير صالح)" if error.code in (401, 403) else "")
            ) from error
        except Exception as error:  # noqa: BLE001
            raise ProviderNotReady(
                f"api: نقل فاشل — {type(error).__name__}: {error}"
            ) from error
        results = _parse_api_payload(data, self.style)
        if not results:
            raise ProviderNotReady(
                f"api: الرد بلا نتائج قابلة للتحليل (style={self.style})",
                reason="RESULTS_NOT_ANALYZABLE",
            )
        return require_relevant("api", query, results)


def _parse_api_payload(data: dict, style: str) -> list[dict]:
    out: list[dict] = []
    if style == "tavily":
        items = data.get("results", [])
        for item in items[:MAX_SEARCH_RESULTS]:
            title = str(item.get("title", "")).strip()
            url = str(item.get("url", ""))
            if title and url.startswith("http"):
                out.append({
                    "title": title, "url": url,
                    "snippet": str(item.get("content", ""))[:300],
                })
    elif style == "brave":
        items = (data.get("web") or {}).get("results", [])
        for item in items[:MAX_SEARCH_RESULTS]:
            title = str(item.get("title", "")).strip()
            url = str(item.get("url", ""))
            if title and url.startswith("http"):
                out.append({
                    "title": title, "url": url,
                    "snippet": str(item.get("description", ""))[:300],
                })
    else:
        items = data.get("results") or data.get("data") or []
        if isinstance(items, dict):
            items = items.get("results", [])
        for item in items[:MAX_SEARCH_RESULTS]:
            if not isinstance(item, dict):
                continue
            title = str(
                item.get("title") or item.get("name") or ""
            ).strip()
            url = str(item.get("url") or item.get("link") or "")
            if title and url.startswith("http"):
                out.append({
                    "title": title, "url": url,
                    "snippet": str(
                        item.get("snippet") or item.get("content")
                        or item.get("description") or ""
                    )[:300],
                })
    return out


# ------------------------------------------------------------------ #
# FetchProvider — جلب الصفحات (منقول سلوكه من web_tools مع نفس العقد)
# ------------------------------------------------------------------ #

#: (W2-T25 2026-10-28) www.npmjs.com يصدّ أتمتتنا بـ403 (موثق ثلاث مرات
#: في تنفيذات 33-35 للمشروع #3). registry.npmjs.org هو المصدر القانوني
#: نفسه لواجهة JSON بلا حظر — إعادة توجيه للمضمون ذاته لا بديل محتوى.
_NPMJS_URL_RE = re.compile(
    r"^(https?)://(?:www\.)?npmjs\.com/package/"
    r"((?:@[^/?#]*/)?[^/?#]*)"
    r"(?:/v/([^/?#]+))?",
    re.IGNORECASE,
)


def _npm_registry_url(url: str) -> str | None:
    """مقابل سجل npm JSON لصفحة حزمة npmjs.com — أو None."""
    without_fragment = str(url or "").split("#", 1)[0].split("?", 1)[0]
    match = _NPMJS_URL_RE.match(without_fragment)
    if not match:
        return None
    package = urllib.parse.unquote(match.group(2) or "")
    if not package or "/" in package and not package.startswith("@"):
        return None
    encoded = urllib.parse.quote(package, safe="")
    version = match.group(3)
    if version:
        encoded_version = urllib.parse.quote(
            urllib.parse.unquote(version), safe="")
        return f"https://registry.npmjs.org/{encoded}/{encoded_version}"
    return f"https://registry.npmjs.org/{encoded}"


def fetch_page(
    url: str, *, timeout: float | None = None,
    max_bytes: int = MAX_PAGE_BYTES,
) -> str:
    """جلب صفحة واستخلاص نصها — نفس عقد web_tools.fetch_page."""
    if timeout is None:
        timeout = fetch_timeout()
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"رابط غير مدعوم: {url[:80]}")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
    except urllib.error.HTTPError as error:
        # (W2-T25) 403 من npmjs.com (حظر روبوتات) — المصدر القانوني
        # نفسه (registry.npmjs.org بواجهة JSON) يخدم بلا حظر. نُحاول
        # مقابل السجل قبل إعلان الفشل — المضمون ذاته لا بديل مختلق.
        registry_url = _npm_registry_url(url)
        if error.code == 403 and registry_url:
            request = urllib.request.Request(
                registry_url,
                headers={"User-Agent": _USER_AGENT,
                         "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(max_bytes + 1)
        else:
            raise
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
    text = raw.decode("utf-8", "replace")
    text = re.sub(
        r"<(script|style)[^>]*>.*?</\1>", " ", text,
        flags=re.DOTALL | re.I,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 120:
        raise ValueError(f"الصفحة شبه فارغة بعد الاستخلاص: {url[:80]}")
    return text


#: استعلام المسبار — نتائجه قابلة للتحليل بالتأكيد إن عمل المزود
PROBE_QUERY = "agentic engineering system software"

#: حقن النقل للاختبارات (نفس المسار بمصادر مضبوطة)
Transport = Callable[[str], list[dict]]


def probe_provider(provider: SearchProvider) -> dict:
    """مسبار مزود واحد — بحث فعلي بنتائج قابلة للتحليل (§24).

    (013.5 §L) تمييز جوهري بين «النقل/التحليل فشل» و«استعلام المسبار
    لم يُنتج نتائج ذات صلة». الثاني يعني أن المزود **يعمل** فعلًا (ردّ
    وحُلّل) لكن عبارة المسبار الجامدة لم تطابق شيئًا — ووسمه NOT_READY
    كان يجعل Bing يبدو معطّلًا وهو يجيب استعلامات حقيقية بنتائج سليمة.
    الحالة تُعلن READY مع تفصيل صادق يقول إن صلة عبارة المسبار لم تُثبت.
    """
    import time

    started = time.monotonic()
    try:
        results = provider.search(PROBE_QUERY)
        ok = bool(results) and all(
            r.get("title") and r.get("url", "").startswith("http")
            for r in results[:3]
        )
        return {
            "status": "READY" if ok else "NOT_READY",
            "reason": "" if ok else "نتائج بلا مادة قابلة للتحليل",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "details": {
                "provider": provider.provider_id,
                "results": len(results),
                "first": results[0]["title"][:80] if results else "",
            },
        }
    except ProviderNotReady as error:
        reason = getattr(error, "reason", "")
        if reason == SEARCH_RESULTS_IRRELEVANT:
            # المزود ردّ وحُلّل — الفشل في صلة عبارة المسبار لا في المزود
            details = getattr(error, "details", {}) or {}
            return {
                "status": "READY",
                "reason": "النقل والتحليل يعملان — عبارة المسبار لم تطابق "
                          "نتائج ذات صلة (لا يعني عطل المزود)",
                "latency_ms": int((time.monotonic() - started) * 1000),
                "details": {
                    "provider": provider.provider_id,
                    "probe_query": PROBE_QUERY,
                    "probe_relevance": details.get("relevance", {}),
                    "sample_titles": details.get("sample_titles", []),
                },
            }
        return {
            "status": "NOT_READY",
            "reason": error.detail[:300],
            "latency_ms": int((time.monotonic() - started) * 1000),
            "details": {"provider": provider.provider_id},
        }
    except Exception as error:  # noqa: BLE001 — مسبار لا يموت
        return {
            "status": "NOT_READY",
            "reason": f"{type(error).__name__}: {error}"[:300],
            "latency_ms": int((time.monotonic() - started) * 1000),
            "details": {"provider": provider.provider_id},
        }


__all__ = [
    "API_STYLES",
    "ApiSearchProvider",
    "BingSearchProvider",
    "DuckDuckGoSearchProvider",
    "PROBE_QUERY",
    "ProviderNotReady",
    "SEARCH_NOT_READY",
    "SEARCH_RESULTS_IRRELEVANT",
    "SearchProvider",
    "SearxJsonSearchProvider",
    "WikipediaSearchProvider",
    "engine_query",
    "fetch_page",
    "filter_relevant",
    "fold_text",
    "probe_provider",
    "query_tokens",
    "relevance_report",
    "require_relevant",
    "result_relevance",
]
