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

#: مؤشرات البحث العربية — رسالة تطلب معلومات حديثة/خارجية.
_AR_INTENT = (
    "ابحث", "بحث عن", "ابحثي", "بحث", "ما آخر", "آخر أخبار", "أخبار",
    "ما أحدث", "أحدث", "اليوم", "الآن حاليًا", "حاليًا", "متاح الآن",
    "ما الجديد", "الجديد في", "كم سعر", "سعر", "من هو", "ما هي أحدث",
    "تطورات", "آخر تطورات", "مباشر", "على الإنترنت", "من النت",
    "من الانترنت", "روابط", "مصادر", "مصدر",
)

#: مؤشرات البحث الإنجليزية.
_EN_INTENT = (
    "search", "search for", "find the latest", "latest", "news",
    "recent", "today", "current", "what's new", "look up", "google",
    "browse the web", "find information", "up to date", "2025", "2026",
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
    """هل تحتاج الرسالة بحثًا؟ (§26) — حتمي: عربي/إنجليزي، لا LLM.

    auto الافتراضية: مؤشر صريح أو سؤال معاصر. الصادق: القرار قابل
    للتفسير (الكلمات المطابقة تسجل في القرار) والمستخدم يملك
    التجاوز الصريح من الواجهة (🌐 on/off).
    """
    text = (message or "").strip()
    if not text:
        return False
    lowered = text.lower()
    for marker in _NO_SEARCH:
        if marker in lowered:
            return False
    for marker in _AR_INTENT:
        if marker in text:
            return True
    for marker in _EN_INTENT:
        if marker in lowered:
            return True
    return False


def decide_web_mode(message: str, *, setting: str = "auto") -> dict:
    """قرار الويب الكامل (§26) — {search, fetch_urls, reason}.

    setting: "auto" (كاشف النية) | "on" (صريح) | "off" (صريح).
    """
    setting = (setting or "auto").lower()
    if setting == "off":
        return {"search": False, "fetch_urls": [],
                "reason": "off_explicit"}
    urls = extract_urls(message)
    if setting == "on":
        return {"search": True, "fetch_urls": urls,
                "reason": "on_explicit"}
    wants_search = detect_web_intent(message)
    # رابط وحده = جلب (fetch) لا بالضرورة بحثًا؛ مؤشر + رابط = الاثنان
    return {
        "search": wants_search,
        "fetch_urls": urls,
        "reason": "auto_detected" if wants_search or urls
        else "auto_not_needed",
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


__all__ = [
    "build_sources_context",
    "decide_web_mode",
    "detect_web_intent",
    "extract_urls",
    "fetch_for_chat",
    "search_for_chat",
]
