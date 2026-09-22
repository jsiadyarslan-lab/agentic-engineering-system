"""أدوات الويب (عقد نحافة الأمر 008 + الأمر 010 §25).

المنطق انتقل إلى طبقة البحث (research/) — البحث عبر مزودين قابلين
للتوفير (ddg/searx/api) لا DDG حصرًا، والجلب بنفس العقد القديم.
هذا الملف واجهة الأدوات: يمرر الاستدعاء ويحافظ على التواقيع.

الموقع: معلن خارج الركيزة (E1 مجمّدة على NetworkMode.NONE).
"""

from __future__ import annotations

from roles.tool_failures import ToolFailure, classify_transport_error  # noqa: F401 — عقد قائم

#: حدود مستحضرة — لا احتجاز ذاكرة.
MAX_SEARCH_RESULTS = 8
MAX_PAGE_BYTES = 400_000
FETCH_TIMEOUT = 20.0

#: ثوابت متاحة لمن يستوردها من هنا (عقد قائم — data_tools)
from research.providers import _USER_AGENT  # noqa: E402,F401 — إعادة تصدير


def web_search(query: str, *, endpoint: str = "", timeout: float = FETCH_TIMEOUT,
               sessions=None) -> list[dict]:
    """بحث عبر طبقة المزودين (010 §25) — أول مزود جاهز يُجيب.

    sessions=None (بلا قاعدة): المزود الافتراضي DDG مباشرة — نفس
    سلوك الأمر 008. مع القاعدة: كل المزودين الممكنين بالترتيب،
    والفشل يعاد مفصلًا لكل مزود (لا «الإنترنت مقطوع»).
    """
    if not query.strip():
        raise ToolFailure(
            "web_search", "استعلام بحث فارغ", failure_class="INPUT_FAILURE",
            reason="INVALID_QUERY", stage="TOOL_START", retryable=False,
        )
    from research import providers as research_providers

    if sessions is None:
        # (013.2) بلا قاعدة: نفس مصفوفة المزودين الحقيقيين — DDG
        # متعدد الاستراتيجيات ثم Bing — لا نقطة html وحيدة كانت تعيد
        # صفحة تحدّ فيتعطل البحث كليًا بلا احتياط
        chain = [
            research_providers.DuckDuckGoSearchProvider(
                endpoint=endpoint or "",
            ),
            research_providers.BingSearchProvider(),
        ]
        last_error: research_providers.ProviderNotReady | None = None
        for provider in chain:
            try:
                return provider.search(query, timeout=timeout)
            except research_providers.ProviderNotReady as error:
                last_error = error
        assert last_error is not None
        # النقل منفصل عن التحليل (إضافة 008 §3 محفوظة): صفحة وصلت
        # بلا مادة = TOOL_FAILURE/RESULTS_NOT_ANALYZABLE، غيره اعتماد.
        analyzable = last_error.reason == "RESULTS_NOT_ANALYZABLE"
        raise ToolFailure(
            "web_search", last_error.detail,
            failure_class="TOOL_FAILURE" if analyzable
            else "DEPENDENCY_FAILURE",
            reason=last_error.reason,
            stage="TOOL_RESULT" if analyzable
            else "PROVIDER_RESOLUTION",
            retryable=False,
            details={
                "provider": "ddg→bing", "query": query[:200],
                "transport": "SUCCESS" if analyzable else "FAILED",
                **last_error.details,
            },
        ) from last_error
    from research import service as research_service

    outcome = research_service.search(sessions, query)
    return outcome["results"]


def fetch_page(url: str, *, timeout: float = FETCH_TIMEOUT,
               max_bytes: int = MAX_PAGE_BYTES) -> str:
    """جلب صفحة واستخلاص نصها — التنفيذ في research.providers."""
    from research.providers import fetch_page as _fetch

    try:
        return _fetch(url, timeout=timeout, max_bytes=max_bytes)
    except ValueError as error:
        raise ToolFailure(
            "fetch_page", str(error),
            failure_class="INPUT_FAILURE" if "غير مدعوم" in str(error)
            else "TOOL_FAILURE",
            reason="INVALID_QUERY" if "غير مدعوم" in str(error)
            else "PAGE_EMPTY",
            stage="TOOL_START" if "غير مدعوم" in str(error)
            else "TOOL_RESULT",
            retryable=False,
            details={"url": url[:200]},
        ) from error
