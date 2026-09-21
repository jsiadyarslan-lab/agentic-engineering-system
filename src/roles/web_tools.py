"""أدوات الويب (مستخرجة من roles/tools.py — عقد نحافة الأمر 008).

web_search/fetch_page بفشل مصنَّف (إضافة 008 §3): النقل (شبكة/مهلة/
مزود) منفصل عن التحليل (صفحة وصلت بلا مادة قابلة للتحليل) — «لا
نتائج» غير «نتائج غير قابلة للتحليل» غير «خطأ مزود».

الموقع: معلن خارج الركيزة (E1 مجمّدة على NetworkMode.NONE).
"""

from __future__ import annotations

import html as html_lib
import re
import urllib.parse
import urllib.request

from roles.tool_failures import ToolFailure, classify_transport_error

#: حدود مستحضرة — لا احتجاز ذاكرة.
MAX_SEARCH_RESULTS = 8
MAX_PAGE_BYTES = 400_000
FETCH_TIMEOUT = 20.0

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_RESULT_LINK = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_RESULT_SNIPPET = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.DOTALL
)
_TAG = re.compile(r"<[^>]+>")


def _ddg_redirect_url(raw: str) -> str:
    """فك روابط توجيه DuckDuckGo (//duckduckgo.com/l/?uddg=…)."""
    try:
        if "uddg=" in raw:
            query = urllib.parse.urlparse(raw).query
            value = urllib.parse.parse_qs(query).get("uddg", [""])[0]
            return urllib.parse.unquote(value) if value else raw
    except ValueError:
        pass
    return raw


def web_search(query: str, *, endpoint: str = "https://html.duckduckgo.com/html/",
               timeout: float = FETCH_TIMEOUT) -> list[dict]:
    """بحث ويب عبر DuckDuckGo HTML — POST بصيغة نموذج، بلا مفاتيح.

    الفشل مصنَّف (§3): classify_transport_error للنقل، وRESULTS_NOT_
    ANALYZABLE عند ورود الصفحة بلا مادة — مع عدادات الاستخلاص.
    """
    if not query.strip():
        raise ToolFailure(
            "web_search", "استعلام بحث فارغ", failure_class="INPUT_FAILURE",
            reason="INVALID_QUERY", stage="TOOL_START", retryable=False,
        )
    body = urllib.parse.urlencode({"q": query}).encode("utf-8")
    request = urllib.request.Request(
        endpoint, data=body, method="POST",
        headers={"User-Agent": _USER_AGENT,
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            page = response.read().decode("utf-8", "replace")
    except Exception as error:  # noqa: BLE001 — تصنيف صريح واحد
        raise classify_transport_error("web_search", error, query=query) \
            from error

    links = _RESULT_LINK.findall(page)
    snippets = [s for s in _RESULT_SNIPPET.findall(page)]
    results: list[dict] = []
    for index, (raw_url, title_html) in enumerate(links[:MAX_SEARCH_RESULTS]):
        title = html_lib.unescape(_TAG.sub("", title_html)).strip()
        url = _ddg_redirect_url(html_lib.unescape(raw_url))
        snippet = ""
        if index < len(snippets):
            snippet = html_lib.unescape(
                _TAG.sub("", snippets[index])
            ).strip()[:300]
        if title and url.startswith("http"):
            results.append({"title": title, "url": url, "snippet": snippet})
    if not results:
        # النقل نجح لكن لا مادة — التمييز الإلزامي (§3+§5).
        raise ToolFailure(
            "web_search",
            f"البحث لم يُعد نتائج قابلة للتحليل ({query[:60]})",
            failure_class="TOOL_FAILURE",
            reason="RESULTS_NOT_ANALYZABLE",
            stage="TOOL_RESULT",
            retryable=False,
            details={
                "query": query[:200], "transport": "SUCCESS",
                "page_chars": len(page), "links_extracted": len(links),
                "snippets_extracted": len(snippets),
            },
        )
    return results


def fetch_page(url: str, *, timeout: float = FETCH_TIMEOUT,
               max_bytes: int = MAX_PAGE_BYTES) -> str:
    """جلب صفحة واستخلاص نصها الخام — فشل مصنَّف (مهلة/شبكة/فراغ)."""
    if not url.startswith(("http://", "https://")):
        raise ToolFailure(
            "fetch_page", f"رابط غير مدعوم: {url[:80]}",
            failure_class="INPUT_FAILURE", reason="INVALID_QUERY",
            stage="TOOL_START", retryable=False,
        )
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
    except Exception as error:  # noqa: BLE001 — تصنيف صريح واحد
        raise classify_transport_error("fetch_page", error, query=url) \
            from error
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
    text = raw.decode("utf-8", "replace")
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.I)
    text = _TAG.sub(" ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 120:
        raise ToolFailure(
            "fetch_page",
            f"الصفحة شبه فارغة بعد الاستخلاص: {url[:80]}",
            failure_class="TOOL_FAILURE", reason="PAGE_EMPTY",
            stage="TOOL_RESULT", retryable=False,
            details={"url": url[:200], "transport": "SUCCESS",
                     "raw_bytes": len(raw), "text_chars": len(text)},
        )
    return text
