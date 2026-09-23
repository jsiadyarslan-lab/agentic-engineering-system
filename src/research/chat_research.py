"""بحث الويب في المحادثة العادية (013.4 §25-§30) — قدرة معلنة لا حكر للمشاريع.

المحادثة العادية تستطيع استخدام ثلاث قدرات ويب **مفصولة** (§27):

- WEB_SEARCH  : إيجاد معلومات (مصفوفة مزودين DDG→Bing→…)
- WEB_FETCH   : جلب صفحة/مستند معروف برابطه
- BROWSER     : استخدام تفاعلي للموقع (دخول/نقر/كتابة) — قدرة
  المشاريع حصرًا؛ في المحادثة تُعلن جاهزيتها لا تُستدعى ضمنًا

الكشف (§26): كاشف نية حتمي عربي/إنجليزي (auto) + خيار صريح من
المستخدم (on/off). الصدق أولًا (§30): المزود غير الجاهز يعني
WEB_UNAVAILABLE معلنة بالسبب — لا نتائج ملفقة أبدًا.
"""

from __future__ import annotations

import re
from typing import Callable

#: روابط URL داخل النص — مسار WEB_FETCH عند وجودها.
_URL_RE = re.compile(
    r"https?://[^\s<>\"')\]]+", re.IGNORECASE
)

#: (013.5 §L) تطبيع عربي قبل المطابقة — لا يفشل الكاشف بسبب الهمزة.
#: العطل الحي: سؤال المالك «ما هي احدث نماذج كلاود؟» (بلا همزة على
#: الألف) لم يطابق أي مؤشر لأن القوائم كانت مكتوبة بصيغة الهمزة
#: «أحدث» — فلم يُشغَّل بحث ويب إطلاقًا. الحل: تطبيع الطرفين
#: (التشكيل/الهمزات/التاء المربوطة/الألف المقصورة) ثم المطابقة.
_AR_MARKS = re.compile(r"[\u064B-\u0652\u0670\u0640]")
_AR_FOLD = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ئ": "ي",
    "ؤ": "و", "ة": "ه",
})


def normalize_arabic(text: str) -> str:
    """تطبيع عربي حتمي — للمطابقة لا للعرض (013.5 §L)."""
    return _AR_MARKS.sub("", str(text or "")).translate(_AR_FOLD)


#: مؤشرات البحث العربية — رسالة تطلب معلومات حديثة/خارجية.
#: مكتوبة **مطبَّعة** (بلا همزات) ليطابقها الكاشف دائمًا.
_AR_INTENT = (
    "ابحث", "بحث عن", "ابحثي", "بحث", "ما اخر", "اخر اخبار", "اخبار",
    "ما احدث", "احدث", "اليوم", "الان حاليا", "حاليا", "متاح الان",
    "ما الجديد", "الجديد في", "كم سعر", "سعر", "من هو", "ما هي احدث",
    "تطورات", "اخر تطورات", "مباشر", "علي الانترنت", "من النت",
    "من الانترنت", "روابط", "مصادر", "مصدر",
    # (013.5 §L) مفردات «الحداثة/الإصدار» التي كانت غائبة كليًا
    "اخر اصدار", "احدث اصدار", "اخر نسخه", "اخر نسخ", "احدث نسخه",
    "جديد", "الجديد", "الاصدار الاخير", "اصدارات", "نماذج", "نموذج",
    "كم عدد", "ما هي", "ما هو", "هل صدر", "صدر", "اطلق", "اعلن",
    "مقارنه", "افضل", "الافضل", "مواصفات", "هذا العام", "هذا الشهر",
    "هذا الاسبوع", "2025", "2026",
)

#: مؤشرات البحث الإنجليزية.
_EN_INTENT = (
    "search", "search for", "find the latest", "latest", "news",
    "recent", "today", "current", "what's new", "look up", "google",
    "browse the web", "find information", "up to date", "2025", "2026",
    # (013.5 §L) نفس الثغرة في الإنجليزية: إصدارات/نماذج/أسعار
    "newest", "newest models", "released", "release date", "announced",
    "version", "versions", "models", "model list", "pricing", "price",
    "benchmark", "comparison", "compare", "as of",
)

#: كلمات تستثني البحث حتى مع وجود المؤشرات (مثال: «اكتب لي بحثًا
#: عن موضوعك» بلا طلب معلومات خارجية لا يكفي وحده أحيانًا — لكن
#: البحث هنا مضرج لا ضار؛ الاستثناءات للصيغ الصريحة المحلية).
_NO_SEARCH = ("لا تبحث", "بدون بحث", "بلا بحث", "دون بحث",
              "don't search", "no search", "offline")


def extract_urls(message: str) -> list[str]:
    """الروابط داخل الرسالة — مسار WEB_FETCH (§27)."""
    return [url.rstrip(".,;:") for url in _URL_RE.findall(message or "")]


def detect_web_intent(message: str) -> bool:
    """هل تحتاج الرسالة بحثًا؟ (§26 + 013.5 §L) — حتمي: عربي/إنجليزي.

    auto الافتراضية: مؤشر صريح أو سؤال معاصر. الصادق: القرار قابل
    للتفسير (الكلمات المطابقة تسجل في القرار) والمستخدم يملك
    التجاوز الصريح من الواجهة (🌐 on/off).

    (013.5 §L) المطابقة العربية تجري على النص **المطبَّع** — «احدث»
    و«أحدث» و«إصدار» و«اصدار» كلها مؤشرات متكافئة، لأن سؤال المالك
    الحقيقي مكتوب بلا همزة وكان يسقط من الكاشف تمامًا.
    """
    text = (message or "").strip()
    if not text:
        return False
    lowered = text.lower()
    for marker in _NO_SEARCH:
        if marker in lowered:
            return False
    folded = normalize_arabic(text)
    for marker in _AR_INTENT:
        if marker in folded:
            return True
    for marker in _EN_INTENT:
        if marker in lowered:
            return True
    return False


def matched_markers(message: str) -> list[str]:
    """(013.5 §L) المؤشرات المطابقة حرفيًا — القرار قابل للتفسير.

    يظهر في الواجهة/الأحداث فلا يكون «بحث» أو «لا بحث» حكمًا صامتًا.
    """
    text = (message or "").strip()
    if not text:
        return []
    lowered = text.lower()
    folded = normalize_arabic(text)
    hits = [m for m in _AR_INTENT if m in folded]
    hits += [m for m in _EN_INTENT if m in lowered]
    return sorted(set(hits))


#: كلمات استفهامية/وظيفية تُزال قبل إرسال الاستعلام للمحرك (§L).
_QUERY_NOISE = (
    "ما هي", "ما هو", "ما احدث", "ما اخر", "هل يمكنك", "هل لك",
    "اخبرني", "أخبرني", "قل لي", "اريد ان اعرف", "أريد أن أعرف",
    "من فضلك", "لو سمحت", "ابحث لي عن", "ابحث عن", "ابحثي عن", "ابحث",
    "بحث عن", "اعطني", "أعطني", "هل", "ماذا", "ايش", "وش",
    "what is", "what are", "tell me", "please", "can you", "could you",
    "search for", "search", "give me", "show me", "find me", "find",
    "explain", "list me", "i want to know", "do you know",
)

#: كلمات وظيفية تُسقط من الاستعلام المُقطَّر (بعد إزالة الصيغ أعلاه).
_QUERY_STOP = frozenset(normalize_arabic(word) for word in (
    "في", "من", "عن", "على", "الى", "إلى", "مع", "هذا", "هذه", "ذلك",
    "التي", "الذي", "ثم", "او", "أو", "لا", "ان", "أن", "كان",
    "the", "a", "an", "of", "for", "to", "in", "on", "at", "by", "with",
    "and", "or", "is", "are", "was", "were", "it", "its", "you", "your",
    "me", "my", "i", "about",
))


def build_search_query(message: str, *, limit: int = 180) -> str:
    """(013.5 §L) استعلام بحث مُقطَّر من رسالة المستخدم.

    لماذا: إرسال الجملة الاستفهامية كما هي يجعل بعض المحركات تبحث عن
    «ما» وحدها فتعيد صفحات إعراب. التقطير يحذف الصيغ الاستفهامية
    والكلمات الوظيفية ويبقي الرموز الدلالية — فيصير الاستعلام قريبًا
    من نية المستخدم فعلًا. الصدق محفوظ: لا نضيف أي كلمة لم يكتبها.
    """
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    if not text:
        return ""
    folded = normalize_arabic(text)
    # الحذف يجري على النص المطبَّع ثم يُعاد البناء من الرموز الباقية
    for noise in sorted(_QUERY_NOISE, key=len, reverse=True):
        folded = folded.replace(normalize_arabic(noise), " ")
    folded = re.sub(r"[؟?،,.!؛;:]+", " ", folded)
    tokens = [t for t in folded.split() if t and t not in _QUERY_STOP]
    distilled = " ".join(tokens).strip()
    # احتياط: إن فرّغ التقطير الاستعلام نعود للرسالة الأصلية
    if len(distilled) < 3:
        return text[:limit]
    return distilled[:limit]


def decide_web_mode(message: str, *, setting: str = "auto") -> dict:
    """قرار الويب الكامل (§26) — {search, fetch_urls, reason}.

    setting: "auto" (كاشف النية) | "on" (صريح) | "off" (صريح).
    """
    setting = (setting or "auto").lower()
    if setting == "off":
        return {"search": False, "fetch_urls": [],
                "reason": "off_explicit", "markers": []}
    urls = extract_urls(message)
    if setting == "on":
        return {"search": True, "fetch_urls": urls,
                "reason": "on_explicit", "markers": ["explicit_on"]}
    wants_search = detect_web_intent(message)
    # رابط وحده = جلب (fetch) لا بالضرورة بحثًا؛ مؤشر + رابط = الاثنان
    return {
        "search": wants_search,
        "fetch_urls": urls,
        "reason": "auto_detected" if wants_search or urls
        else "auto_not_needed",
        # (013.5 §L) القرار قابل للتفسير — لا حكم صامت
        "markers": matched_markers(message) if wants_search else [],
    }


# ------------------------------------------------------------------ #
# مسار البحث — مزود حقيقي بمسبار صادق (§30)
# ------------------------------------------------------------------ #

def search_for_chat(sessions, query: str) -> dict:
    """بحث للمحادثة عبر مصفوفة المزودين (§26) — فشل مفصل لا ملفق.

    يعيد {ok, provider, results} عند النجاح أو {ok: False, error,
    providers_tried} عند فشل الجميع — الواجهة تعرض WEB_UNAVAILABLE
    بالسبب الحرفي، لا نتائج وهمية أبدًا.
    """
    from research import service as research_service
    from research.providers import ProviderNotReady

    try:
        outcome = research_service.search(sessions, query)
        return {
            "ok": True,
            "provider": outcome.get("provider", ""),
            "provider_kind": outcome.get("provider_kind", ""),
            "results": outcome.get("results", [])[:8],
            "attempts": outcome.get("attempts", []),
        }
    except Exception as error:  # noqa: BLE001 — فشل مفصل لا ملفق
        reason = ""
        if isinstance(error, ProviderNotReady):
            reason = error.detail
        else:
            from roles.tool_failures import ToolFailure

            if isinstance(error, ToolFailure):
                reason = str(error)
            else:
                reason = f"{type(error).__name__}: {error}"
        return {"ok": False, "error": reason[:400],
                "providers_tried": ["ddg", "bing"]}


def fetch_for_chat(url: str, *, timeout: float = 12.0) -> dict:
    """جلب صفحة معروفة (§27 WEB_FETCH) — نص مستخلص أو فشل صريح."""
    from research.providers import fetch_page

    try:
        text = fetch_page(url, timeout=timeout)
        return {"ok": True, "url": url, "content": text[:6000]}
    except Exception as error:  # noqa: BLE001 — فشل صريح
        return {"ok": False, "url": url,
                "error": f"{type(error).__name__}: {error}"[:300]}


#: صيغة سياق المصادر للنموذج — روابط وعناوين ومقتطفات مرقمة.
def build_sources_context(sources: list[dict],
                          fetched: list[dict]) -> str:
    """سياق المصادر لرسالة النموذج (§26) — مرقم للاستشهاد."""
    blocks: list[str] = []
    for index, source in enumerate(sources, start=1):
        blocks.append(
            f"[{index}] {source.get('title', '')} — "
            f"{source.get('url', '')}\n{source.get('snippet', '')}"
        )
    for fetched_page in fetched:
        if fetched_page.get("ok"):
            blocks.append(
                f"[صفحة: {fetched_page['url']}]\n"
                f"{fetched_page['content'][:2500]}"
            )
    if not blocks:
        return ""
    return "مصادر ويب حديثة (استشهد بأرقامها [1]… في إجابتك):\n\n" \
        + "\n\n".join(blocks)


#: (013.5 §L/§30) إعلان إلزامي للنموذج عند تعذّر الويب.
#: بدونه يجيب النموذج من ذاكرته بينما المستخدم يظن أنه بحث — وهذا
#: بالضبط «الادّعاء» الممنوع. النص يمنع أي إيحاء بمعرفة حديثة.
WEB_DENIED_NOTICE = (
    "تعذّر تنفيذ البحث في الويب لهذا الطلب (السبب الحرفي: {reason}). "
    "لا تملك أي مصادر خارجية الآن. التزم حرفيًا بما يلي: "
    "(1) لا تدّع أنك اطلعت على الويب أو أن لك مصادر؛ "
    "(2) اذكر في أول إجابتك صراحةً أن هذه معرفة مدرَّبة قد تكون قديمة "
    "وأن التحقق الحي لم ينجح؛ "
    "(3) لا تخترع روابط أو أرقام إصدارات أو تواريخ حديثة، وإن لم تكن "
    "متأكدًا فقل ذلك بدل التخمين."
)


def denied_context(reason: str) -> str:
    """رسالة نظام عند فشل الويب — لا إجابة توحي بمعرفة حيّة (§L)."""
    return WEB_DENIED_NOTICE.format(reason=(reason or "غير معلن")[:200])


__all__ = [
    "WEB_DENIED_NOTICE",
    "build_search_query",
    "build_sources_context",
    "decide_web_mode",
    "denied_context",
    "detect_web_intent",
    "extract_urls",
    "fetch_for_chat",
    "matched_markers",
    "normalize_arabic",
    "search_for_chat",
]
