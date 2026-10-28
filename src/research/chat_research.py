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

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeout
from typing import Callable

#: (AES-EXP-04 §6) الميزانية الزمنية الكلية لبحث المحادثة — خيط
#: المحادثة لا يُحتجز أبدًا خلف سلسلة مزودين على شبكة متدهورة:
#: 3 مزودين مزروعين × مهلة اتصال لكل محاولة × عناوين IP متعددة
#: لكل مزود كانت تتجاوز 150ث على مضيف بلا خروج صريح (التفريغات
#: مثبتة: v2-chat عالق في sock.connect داخل provider.search) —
#: بصمة مهلات 149.7ث المتكررة القديمة نفسها. قابل للضبط عبر
#: AES_CHAT_RESEARCH_BUDGET_S؛ تجاوزها = WEB_UNAVAILABLE صادقة
#: والإجابة تكمل من الذاكرة مع الإعلان (لا نتائج ملفقة أبدًا).
_DEFAULT_CHAT_SEARCH_BUDGET_S = 20.0

_CHAT_RESEARCH_POOL: dict = {"pool": None, "lock": threading.Lock()}


def _chat_research_pool() -> ThreadPoolExecutor:
    """منفّذ بحث المحادثة — خيوط قليلة مخصصة؛ خيط المحادثة نفسه
    لا ينتظر السلسلة أبدًا بل حتى الميزانية فقط."""
    with _CHAT_RESEARCH_POOL["lock"]:
        if _CHAT_RESEARCH_POOL["pool"] is None:
            _CHAT_RESEARCH_POOL["pool"] = ThreadPoolExecutor(
                max_workers=3, thread_name_prefix="aes-chat-research",
            )
        return _CHAT_RESEARCH_POOL["pool"]


def chat_search_budget_s() -> float:
    """ميزانية بحث المحادثة الكلية — AES_CHAT_RESEARCH_BUDGET_S."""
    raw = os.environ.get("AES_CHAT_RESEARCH_BUDGET_S", "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_CHAT_SEARCH_BUDGET_S
    return value if value > 0 else _DEFAULT_CHAT_SEARCH_BUDGET_S

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
#: (RLR-005b) عبارات القناة والتوجيه («في الويب»، «في ويكيبيديا») وأذيال
#: التعليمات («واذكر … مع مصادرك») كانت تتسرب إلى الاستعلام فتفسده
#: مرتين معًا: تلوّث ما يُرسَل للمحرك، وتُحتسَب رموزًا دلالية في تحقق
#: الصلة (require_relevant) فترفع العتبة فوق ما تستطيع النتائج تغطيته —
#: فيُرفض البحث الصالح نفسه. الإضافات عبارات **آمنة كاستبدال نصي**
#: (لا تبتلع كلمة داخل كلمة)؛ أما الرموز المفردة القصيرة فتُضاف
#: إلى _QUERY_STOP حيث المطابقة على الرمز الكامل حصرًا.
_QUERY_NOISE = (
    "ما هي", "ما هو", "ما احدث", "ما اخر", "هل يمكنك", "هل لك",
    "اخبرني", "أخبرني", "قل لي", "اريد ان اعرف", "أريد أن أعرف",
    "من فضلك", "لو سمحت", "ابحث لي عن", "ابحث عن", "ابحثي عن", "ابحث",
    "بحث عن", "اعطني", "أعطني", "هل", "ماذا", "ايش", "وش",
    # (RLR-005b) قناة البحث/التوجيه — تُحذف قبل التقطير لا بعده
    "ابحث لي في الويب عن", "ابحث لي في الانترنت عن",
    "ابحث في الويب عن", "ابحث في الانترنت عن",
    "ابحث في ويكيبيديا عن", "ابحث لي في", "ابحث لي من", "ابحث لي عبر",
    "في الويب", "من الويب", "على الويب", "عبر الويب",
    "في الانترنت", "من الانترنت", "على الانترنت", "عبر الانترنت",
    "في ويكيبيديا", "من ويكيبيديا", "في الموسوعة",
    # (RLR-005b) أذيال التعليمات ومطالب المصادر
    "واذكر لي", "اذكر لي", "مع مصادرك", "مع المصادر", "مع مصادر",
    "ومصادر", "مع مراجعك",
    "what is", "what are", "tell me", "please", "can you", "could you",
    "search for", "search", "give me", "show me", "find me", "find",
    "explain", "list me", "i want to know", "do you know",
    # (W2-T22) حثّ المتابعة الإنجليزي — كلمات طلب لا موضوع
    "try again", "again", "retry", "now",
    # (RLR-005b) قناة/تعليمات إنجليزية
    "on the web", "from the web", "on the internet", "from the internet",
    "in wikipedia", "from wikipedia", "on wikipedia", "with sources",
    "cite your sources", "your sources", "and mention",
)

#: كلمات وظيفية تُسقط من الاستعلام المُقطَّر (بعد إزالة الصيغ أعلاه).
_QUERY_STOP = frozenset(normalize_arabic(word) for word in (
    "في", "من", "عن", "على", "الى", "إلى", "مع", "هذا", "هذه", "ذلك",
    "التي", "الذي", "ثم", "او", "أو", "لا", "ان", "أن", "كان",
    # (RLR-005b) رموز قناة/تعليمات متبقية — مطابقة الرمز الكامل حصرًا
    # فلا تُصيب «ليبيا» ولا «مليون» (على خلاف الاستبدال النصي)
    "لي", "الويب", "ويب", "ويكيبيديا", "الموسوعة",
    "الانترنت", "انترنت", "واذكر", "اذكر", "وذكر",
    "مصادرك", "مصادر", "المصادر", "مصدرك", "ومصادر", "مراجعك",
    "the", "a", "an", "of", "for", "to", "in", "on", "at", "by", "with",
    "and", "or", "is", "are", "was", "were", "it", "its", "you", "your",
    "me", "my", "i", "about",
    # (RLR-005b) رموز قناة/تعليمات إنجليزية
    "wikipedia", "web", "internet", "sources", "source", "mention",
    "cite",
    # (W2-T22) ضمائر/وصل/كلمات طلب — «ابحث انت واعطني ملخص» كانت
    # تُقطَّر إلى «انت و ملخص» فيسأل المحرك عن «أنت» و«ملخص» (دليل
    # conv-15 دور 2: ويكيبيديا أعاد ملخصات مسلسلات «أنت أطرق بابي»)
    "انت", "انتي", "انتم", "و", "او", "ملخص", "ملخصات", "خلاصة",
    "قم", "نفذ",
))


def _distill_tokens(message: str) -> list[str]:
    """(W2-T22) التقطير الخام — رموز الرسالة بعد إزالة الصيغ الاستفهامية
    والكلمات الوظيفية، **بلا** احتياط العودة للنص الأصلي.

    الفرق عن build_search_query: هذه للفحص الموضوعي (هل تحمل الرسالة
    موضوعًا خاصًا؟) — فالعودة إلى النص الأصلي عند فراغ التقطير كانت
    تخفي أن الرسالة كلها صيغ طلب بلا موضوع («ابحث انت واعطني ملخص»).
    """
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    if not text:
        return []
    folded = normalize_arabic(text)
    for noise in sorted(_QUERY_NOISE, key=len, reverse=True):
        folded = folded.replace(normalize_arabic(noise), " ")
    folded = re.sub(r"[؟?،,.!؛;:]+", " ", folded)
    return [t for t in folded.split() if t and t not in _QUERY_STOP]


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
    distilled = " ".join(_distill_tokens(text)).strip()
    # احتياط: إن فرّغ التقطير الاستعلام نعود للرسالة الأصلية
    if len(distilled) < 3:
        return text[:limit]
    return distilled[:limit]


#: (RLR-005) كلمات الساعة/التاريخ الصرفة + أدوات الاستفهام المرافقة
#: لها فقط — إن لم يبقَ بعد التقطير سواها فالسؤال سؤال ساعة صِرف.
_CLOCK_TOKENS = frozenset(normalize_arabic(word) for word in (
    "اليوم", "التاريخ", "الساعة", "الوقت", "الآن", "الان",
    "تاريخ", "ساعة", "وقت", "يوم", "كم", "متى", "اي", "أي",
    "ما", "نحن", "فيه", "هو", "هي",
    "today", "todays", "date", "time", "now", "day", "what", "whats",
))


def is_clock_question(message: str) -> bool:
    """(RLR-005) هل السؤال سؤال تاريخ/وقت صِرف يجيب عنه نظام الساعة؟

    الدافع الموثق (2026-10-26): «ما هو اليوم؟» يُقطَّر إلى «اليوم»
    فأعاد البحث 8 نتائج ويكيبيديا عن كلمة «يوم» («يوم»، «قناة
    اليوم»، «اليوم الوطني السعودي»، «خيل (جنس)»…) — لا واحدة منها
    تحمل التاريخ الحالي. محركات البحث لا تجيب «تاريخ اليوم» عن
    كلمة «اليوم»؛ ساعة النظام هي المصدر الموثوق لهذا الصنف،
    وسياقها يُحقن في مسار المحادثة (routes: ساعة النظام الآن…).

    التمييز الصادق: أسئلة مثل «أخبار اليوم» أو «أسعار الذهب اليوم»
    تبقي كلماتها الدلالية بعد التقطير (أخبار/أسعار/الذهب) فلا
    تُعد سؤال ساعة — الويب يبقى مسارها الصحيح. كذلك أي رسالة تحمل
    رابط URL لا تُعد سؤال ساعة (الجلب معلومات حية فعلًا).
    """
    distilled = build_search_query(message)
    if not distilled:
        return False
    tokens = [t for t in distilled.split() if t]
    return bool(tokens) and all(t in _CLOCK_TOKENS for t in tokens)


# ------------------------------------------------------------------ #
# (W2-T22) الاستعلام الواعي بسياق المحادثة + حثّ المتابعة
# ------------------------------------------------------------------ #

#: عمق النظر في تاريخ المستخدم بحثًا عن موضوع المحادثة — آخر 6 رسائل
#: تكفي؛ الأقدم من ذلك غالبًا موضوع آخر لا علاقة له بالمتابعة.
_INHERIT_SCAN_DEPTH = 6


def _topical_tokens(tokens: list[str]) -> list[str]:
    """(W2-T22) رموز موضوعية — غير الكلمات العامة (أخبار/اليوم/…).

    كلمة «أخبار» أو «اليوم» في رسالة لا تجعلها موضوعًا؛ الموضوع ما
    يحدد ماذا عن («انتخابات الكنسيت») — والمؤشرات العامة وحدها
    تعني «رسالة طلب/متابعة بلا موضوع» ترث موضوع المحادثة.
    """
    from research.providers import _GENERIC_TOKENS
    return [t for t in (tokens or [])
            if len(t) >= 2 and t not in _GENERIC_TOKENS]


def build_contextual_search_query(message: str, user_history,
                                  *, limit: int = 180) -> dict:
    """(W2-T22) استعلام بحث واعٍ بسياق المحادثة.

    الدافع الموثق (conv-15 دور 2): «ابحث انت واعطني ملخص» قُطِّرت
    إلى «انت و ملخص» — رسالة متابعة أمرية بلا موضوع، فسألنا المحركات
    عن «أنت» و«ملخص» وأجابت بملخصات مسلسلات بدل أخبار انتخابات
    الكنيست التي طلبها المستخدم قبلها بدقيقة واحدة. القاعدة:

    - الرسالة التي تحمل موضوعًا (رمز موضوعي واحد على الأقل بعد
      التقطير) تُستخدم كما هي — حتى لو كانت كلمة واحدة («فرنسا»
      موضوع جديد مشروع؛ لا ندمج فيه القديم تحكمًا).
    - الرسالة التي لا تحمل موضوعًا (صفر رموز موضوعية) ترث استعلام
      آخر رسالة موضوعية للمستخدم في المحادثة نفسها.

    الصدق محفوظ: الوراثة لا تضيف كلمة لم يكتبها المستخدم — كل كلمة
    في الاستعلام الموروث كتبها هو بنفسه في رسالة سابقة.
    """
    current_tokens = _distill_tokens(message)
    if _topical_tokens(current_tokens):
        return {"query": build_search_query(message, limit=limit),
                "inherited": False, "reason": "own_topic"}
    for previous in reversed(list(user_history or [])[-_INHERIT_SCAN_DEPTH:]):
        previous_tokens = _distill_tokens(str(previous or ""))
        if _topical_tokens(previous_tokens):
            return {"query": build_search_query(str(previous), limit=limit),
                    "inherited": True, "reason": "inherited_topic"}
    return {"query": build_search_query(message, limit=limit),
            "inherited": False, "reason": "no_topic"}


#: (W2-T22) كلمات الحثّ/المتابعة — رسالة قصيرة كل رموزها من هذه
#: المجموعة (أو علامات استفهام وحدها) تعني «حاول الآن مجددًا» في
#: سياق محادثة ذات موضوع. لا تُطلق البحث من تلقاء نفسها — فقط مع
#: موضوع موروث من build_contextual_search_query.
_FOLLOWUP_URGE_WORDS = frozenset(normalize_arabic(word) for word in (
    "والان", "الان", "الآن", "جرب", "حاول", "اعد", "كرر", "مجددا",
    "ثانيه", "مره", "ليش", "لماذا", "شنو", "وشو", "ايش", "ايسه",
    "بعدين", "كمان", "وين", "again", "retry", "now", "why",
))


def is_followup_urge(message: str) -> bool:
    """(W2-T22) هل الرسالة حثّ متابعة قصير («؟»، «والان»، «جرب الان»)؟

    الدافع الموثق (conv-15 دور 3): «؟» وحدها (02:28:24) لم تطلق
    بحثًا إطلاقًا (لا research.started — web_used=false) فأجاب النموذج
    من ذاكرة المتابعة المتقادمة أنه «لا يملك إنترنت مباشر» — وهي
    بالضبط الرسالة التي شكا منها المالك. رسالة الحثّ القصيرة في
    محادثة ذات موضوع تُعيد البحث بالموضوع الموروث بدل ذلك.

    الحد الصارم: كل رموز الرسالة (بعد نزع الترقيم) من كلمات الحثّ،
    وبحد أقصى 4 رموز — الرسالة الفعلية الأطول لا تُعد حثًّا أبدًا.
    """
    stripped = re.sub(
        r"[؟?!.…،,؛:\-–—]+", " ",
        normalize_arabic(str(message or "")),
    )
    tokens = [t for t in stripped.split() if t]
    if not tokens:
        return True   # علامة استفهام/تعجب وحدها — «؟»
    if len(tokens) > 4:
        return False  # رسالة فعلية لا حثّ مقتضب
    return all(t in _FOLLOWUP_URGE_WORDS for t in tokens)


def decide_web_mode(message: str, *, setting: str = "auto") -> dict:
    """قرار الويب الكامل (§26) — {search, fetch_urls, reason}.

    setting: "auto" (كاشف النية) | "on" (صريح) | "off" (صريح).

    (RLR-005) سؤال الساعة/التاريخ الصِرف يُوجَّه إلى ساعة النظام
    حصرًا — حتى مع web=on: البحث عن «اليوم» ضجيج موثق لا يحمل
    التاريخ، وإجابة الساعة أدق وأسرع. السبب معلن في reason وليس
    حكمًا صامتًا، والرابط إن وُجد يُجلب كالمعتاد (معلومة حية).
    """
    setting = (setting or "auto").lower()
    if setting == "off":
        return {"search": False, "fetch_urls": [],
                "reason": "off_explicit", "markers": []}
    urls = extract_urls(message)
    if not urls and is_clock_question(message):
        return {"search": False, "fetch_urls": [],
                "reason": "clock_question",
                "markers": ["سؤال تاريخ/وقت — يجيب عنه نظام الساعة"]}
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

    (AES-EXP-04 §6) السلسلة تُنفّذ في منفّذ البحث المخصص بميزانية
    كلية (AES_CHAT_RESEARCH_BUDGET_S، 20ث افتراضيًا): الشبكة
    المتدهورة لا تحتجز خيط المحادثة — عند التجاوز يعلن فشل
    صادق وتكمل الإجابة من الذاكرة مع الإعلان. الخيط المتروك
    خلف التجاوز تقتله مهل الاتصال الفردية نفسها (محدودة دائمًا).
    """
    from research import service as research_service
    from research.providers import ProviderNotReady

    budget = chat_search_budget_s()
    deadline = time.monotonic() + budget
    future = _chat_research_pool().submit(
        research_service.search, sessions, query, deadline=deadline
    )
    try:
        outcome = future.result(timeout=budget)
    except _FutureTimeout:
        # عامل قيد التشغيل لا يُقتل منتصفًا — مهله الفردية تُنهيه؛
        # خيط المحادثة حر الآن والإعلان صادق مفصل.
        future.cancel()
        return {
            "ok": False,
            "error": (
                f"تجاوز بحث الويب الميزانية الزمنية الكلية "
                f"({budget:.0f}ث) قبل أي نتيجة — الشبكة متدهورة أو "
                "المصادر محجوبة؛ أكمل الإجابة من الذاكرة مع هذا "
                "الإعلان الصريح"
            ),
            "providers_tried": [],
            "budget_exceeded": True,
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

    return {
        "ok": True,
        "provider": outcome.get("provider", ""),
        "provider_kind": outcome.get("provider_kind", ""),
        "results": outcome.get("results", [])[:8],
        "attempts": outcome.get("attempts", []),
    }


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
    "build_contextual_search_query",
    "build_search_query",
    "build_sources_context",
    "decide_web_mode",
    "denied_context",
    "detect_web_intent",
    "extract_urls",
    "fetch_for_chat",
    "is_followup_urge",
    "matched_markers",
    "normalize_arabic",
    "search_for_chat",
]
