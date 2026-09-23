"""مسبار: هل تُنقذ صياغة مُقطَّرة + RSS استعلامات العربية؟ (013.5 §L)."""

from __future__ import annotations

import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research import providers as rp  # noqa: E402

HEADERS = dict(rp._BROWSER_HEADERS)

TEMPLATES = {
    "rss": "https://www.bing.com/search?q={q}&format=rss&count=10",
    "rss_ar": ("https://www.bing.com/search?q={q}&format=rss&count=10"
               "&setmkt=ar-SA&setlang=ar&cc=SA"),
    "rss_en": ("https://www.bing.com/search?q={q}&format=rss&count=10"
               "&setmkt=en-US&setlang=en&cc=US"),
}

QUERIES = [
    "ما هي احدث نماذج كلاود؟",
    "احدث نماذج كلاود",
    "أحدث نماذج Claude",
    "نماذج Claude الجديدة",
    "Claude أحدث النماذج",
    "Claude models",
    "Claude newest models",
    "Anthropic Claude model list",
]


def rss_results(page: str) -> list[dict]:
    out = []
    for item in re.findall(r"<item>(.*?)</item>", page, re.S)[:10]:
        title = re.search(r"<title>(.*?)</title>", item, re.S)
        link = re.search(r"<link>(.*?)</link>", item, re.S)
        if title and link:
            out.append({
                "title": rp.html_lib.unescape(rp._tag(title.group(1))).strip(),
                "url": rp.html_lib.unescape(link.group(1)).strip(),
                "snippet": "",
            })
    return out


for name, template in TEMPLATES.items():
    print(f"\n===== {name} =====")
    for query in QUERIES:
        url = template.format(q=urllib.parse.quote(query))
        request = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                page = response.read().decode("utf-8", "replace")
        except Exception as error:  # noqa: BLE001
            print(f"  {query!r}: ERROR {type(error).__name__}")
            continue
        results = rss_results(page)
        report = rp.relevance_report(query, results)
        mark = "OK " if report["relevant"] else "   "
        print(f" {mark} {query!r} n={len(results)} "
              f"cover={len(report['covered'])}/{len(report['tokens'])} "
              f"req={report['required']}")
        for r in results[:3]:
            print(f"        - {r['title'][:58]} | {r['url'][:62]}")
