"""مسبار: أي محرك بلا مفاتيح يعيد نتائج متعلقة فعلًا؟ (013.5 §L).

إصلاح الصدق وحده لا يكفي: البوابة ترفض النتائج العمياء بـ«الفشل
الصادق»، لكن §L يطلب بحثًا حقيقيًا يعمل. هذا مسبار تجريبي لنقاط
نهاية بلا مفاتيح — لا يُدرج أي منها في الإنتاج قبل أن يثبت.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research import providers as rp  # noqa: E402

UA = rp._USER_AGENT
HEADERS = dict(rp._BROWSER_HEADERS)

CANDIDATES = {
    "bing_rss": "https://www.bing.com/search?q={q}&format=rss&count=10",
    "bing_rss_mkt": "https://www.bing.com/search?format=rss&q={q}&count=10"
                    "&setmkt=en-US&setlang=en&cc=US",
    "mojeek": "https://www.mojeek.com/search?q={q}",
    "ddg_lite_get": "https://lite.duckduckgo.com/lite/?q={q}",
    "ddg_html_get": "https://html.duckduckgo.com/html/?q={q}",
    "ddg_lite_post": "https://lite.duckduckgo.com/lite/",
    "brave": "https://search.brave.com/search?q={q}",
    "startpage": "https://www.startpage.com/sp/search?query={q}",
    "ecosia": "https://www.ecosia.org/search?q={q}",
    "searx_be": "https://searx.be/search?q={q}&format=json",
    "searxng_site": "https://searxng.site/search?q={q}&format=json",
    "marginalia": "https://search.marginalia.nu/search?query={q}",
}

QUERIES = ["Claude latest models", "أحدث نماذج Claude"]


def _get(url: str, data: bytes | None = None, timeout: float = 20.0):
    request = urllib.request.Request(url, data=data, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8", "replace")


def _links_from_rss(page: str) -> list[dict]:
    out = []
    for item in re.findall(r"<item>(.*?)</item>", page, re.S)[:10]:
        title = re.search(r"<title>(.*?)</title>", item, re.S)
        link = re.search(r"<link>(.*?)</link>", item, re.S)
        desc = re.search(r"<description>(.*?)</description>", item, re.S)
        if title and link:
            out.append({
                "title": rp.html_lib.unescape(rp._tag(title.group(1))).strip(),
                "url": rp.html_lib.unescape(link.group(1)).strip(),
                "snippet": rp.html_lib.unescape(
                    rp._tag(desc.group(1))).strip()[:200]
                if desc else "",
            })
    return out


def _links_from_html(page: str) -> list[dict]:
    """استخراج عام: كل <a> بعنوان ونص — للمقارنة الأولية فقط."""
    out = []
    for match in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                             page, re.S):
        url = rp.html_lib.unescape(match.group(1))
        title = rp.html_lib.unescape(rp._tag(match.group(2))).strip()
        if len(title) < 8 or "bing.com" in url or "duckduckgo" in url:
            continue
        out.append({"title": title[:90], "url": url[:110], "snippet": ""})
        if len(out) >= 8:
            break
    return out


for name, template in CANDIDATES.items():
    print(f"\n===== {name} =====")
    for query in QUERIES:
        try:
            if name == "ddg_lite_post":
                body = urllib.parse.urlencode({"q": query}).encode()
                status, page = _get(template, data=body)
            else:
                status, page = _get(template.format(q=urllib.parse.quote(query)))
        except Exception as error:  # noqa: BLE001
            print(f"  {query!r}: ERROR {type(error).__name__}: {str(error)[:90]}")
            continue
        if page.lstrip().startswith("{") or page.lstrip().startswith("["):
            try:
                data = json.loads(page)
                results = [
                    {"title": r.get("title", ""), "url": r.get("url", ""),
                     "snippet": r.get("content", "")}
                    for r in (data.get("results") or [])[:8]
                ]
                kind = "json"
            except ValueError:
                results, kind = [], "json-bad"
        elif "<rss" in page[:400] or "<item>" in page:
            results, kind = _links_from_rss(page), "rss"
        else:
            results, kind = _links_from_html(page), "html"
        report = rp.relevance_report(query, results)
        verdict = "RELEVANT" if report["relevant"] else "irrelevant"
        print(f"  {query!r}: http={status} parse={kind} n={len(results)} "
              f"cover={len(report['covered'])}/{len(report['tokens'])} "
              f"req={report['required']} -> {verdict}")
        for r in results[:4]:
            print(f"      - {r['title'][:60]} | {r['url'][:70]}")
