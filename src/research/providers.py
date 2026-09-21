"""مزودو البحث الحقيقيون (الأمر 010 §25) — البحث قابل للتوفير.

ثلاثة مزودين حقيقيين فقط، لا أكثر ولا أقل — كل واحد بتنفيذه الفعلي:

- DuckDuckGoSearchProvider: بحث DDG HTML بلا مفاتيح (الافتراضي)
- SearxJsonSearchProvider:  مثيل SearXNG برابط يملكه المالك (JSON API)
- ApiSearchProvider:        نقطة نهاية JSON عامة يملكها المالك + مفتاح

المخطط (Planner) لا يتزوج DDG أبدًا (§25): يستدعي research.search()
فتُستخدم أول مزود جاهز — والفشل يعاد بتصنيف مفصل لكل مزود.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Protocol

MAX_SEARCH_RESULTS = 8
SEARCH_TIMEOUT = 15.0
FETCH_TIMEOUT = 20.0
MAX_PAGE_BYTES = 400_000

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

#: فشل مصنَّف موحد — نقل منفصل عن التحليل (إضافة 008 §3)
SEARCH_NOT_READY = "SEARCH_PROVIDER_NOT_READY"


class ProviderNotReady(RuntimeError):
    """المزود غير جاهز — مع تفصيل كل مزود (لا «الإنترنت مقطوع»)."""

    def __init__(self, detail: str, *, reason: str = "PROVIDER_NOT_READY",
                 details: dict | None = None):
        super().__init__(detail)
        self.detail = detail
        self.reason = reason
        self.details = details or {}


class SearchProvider(Protocol):
    """عقد مزود بحث (§25) — search واحد صادق لكل مزود."""

    provider_id: str
    kind: str

    def search(self, query: str, *, timeout: float = SEARCH_TIMEOUT) -> list[dict]:
        """[{title, url, snippet}] — بلا نتائج تحليلية = خطأ مصنّف."""

    def describe(self) -> dict:
        """وصف المزود — بلا أسرار أبدًا."""


def _tag(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


# ------------------------------------------------------------------ #
# DuckDuckGo — HTML بلا مفاتيح
# ------------------------------------------------------------------ #

class DuckDuckGoSearchProvider:
    """بحث DuckDuckGo HTML — POST بصيغة نموذج، بلا مفاتيح."""

    provider_id = "ddg"
    kind = "search_ddg"

    def __init__(self, endpoint: str = "https://html.duckduckgo.com/html/"):
        self.endpoint = endpoint

    def describe(self) -> dict:
        return {
            "provider_id": self.provider_id, "kind": self.kind,
            "name": "DuckDuckGo (HTML)",
            "requires_key": False, "config": {"endpoint": self.endpoint},
        }

    def search(self, query: str, *, timeout: float = SEARCH_TIMEOUT) -> list[dict]:
        body = urllib.parse.urlencode({"q": query}).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint, data=body, method="POST",
            headers={
                "User-Agent": _USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                page = response.read().decode("utf-8", "replace")
        except Exception as error:  # noqa: BLE001 — تصنيف واحد
            raise ProviderNotReady(
                f"ddg: نقل فاشل — {type(error).__name__}: {error}"
            ) from error
        return _ddg_parse(page, query)


_RESULT_LINK = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_RESULT_SNIPPET = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.DOTALL
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
    links = _RESULT_LINK.findall(page)
    snippets = _RESULT_SNIPPET.findall(page)
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
            f"ddg: لا نتائج قابلة للتحليل ({len(links)} روابط خام) "
            f"لاستعلام: {query[:60]}",
            reason="RESULTS_NOT_ANALYZABLE",
            details={"query": query[:200], "transport": "SUCCESS",
                     "page_chars": len(page), "links_extracted": len(links),
                     "snippets_extracted": len(snippets)},
        )
    return results


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

    def search(self, query: str, *, timeout: float = SEARCH_TIMEOUT) -> list[dict]:
        if not self.base_url:
            raise ProviderNotReady(
                "searx: بلا رابط مثيل — عيّن base_url من إعدادات البحث"
            )
        url = (
            f"{self.base_url}/search?q={urllib.parse.quote(query)}"
            "&format=json&language=en"
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
        return results


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

    def search(self, query: str, *, timeout: float = SEARCH_TIMEOUT) -> list[dict]:
        if not self.endpoint:
            raise ProviderNotReady(
                "api: بلا نقطة نهاية — عيّنها من إعدادات البحث"
            )
        body = json.dumps({"query": query, "q": query,
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
        return results


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

def fetch_page(
    url: str, *, timeout: float = FETCH_TIMEOUT,
    max_bytes: int = MAX_PAGE_BYTES,
) -> str:
    """جلب صفحة واستخلاص نصها — نفس عقد web_tools.fetch_page."""
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"رابط غير مدعوم: {url[:80]}")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(max_bytes + 1)
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
    """مسبار مزود واحد — بحث فعلي بنتائج قابلة للتحليل (§24)."""
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
    "DuckDuckGoSearchProvider",
    "PROBE_QUERY",
    "ProviderNotReady",
    "SEARCH_NOT_READY",
    "SearchProvider",
    "SearxJsonSearchProvider",
    "fetch_page",
    "probe_provider",
]
