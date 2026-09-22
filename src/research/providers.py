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

    def search(self, query: str, *, timeout: float = SEARCH_TIMEOUT) -> list[dict]:
        attempts: list[dict] = []
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
                return results
            attempts.append({
                "strategy": name, "error": "لا نتائج قابلة للتحليل",
            })
        detail = "؛ ".join(
            f"{a['strategy']}: {a['error']}" for a in attempts
        ) or "لا استراتيجيات"
        raise ProviderNotReady(
            f"ddg: كل الاستراتيجيات فشلت — {detail}",
            reason="RESULTS_NOT_ANALYZABLE",
            details={"query": query[:200], "attempts": attempts},
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

    def search(self, query: str, *, timeout: float = SEARCH_TIMEOUT) -> list[dict]:
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
    "BingSearchProvider",
    "DuckDuckGoSearchProvider",
    "PROBE_QUERY",
    "ProviderNotReady",
    "SEARCH_NOT_READY",
    "SearchProvider",
    "SearxJsonSearchProvider",
    "fetch_page",
    "probe_provider",
]
