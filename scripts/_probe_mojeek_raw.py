"""مسبار Mojeek الخام — فهرس حقيقي صديق للأتمتة (013.5 §L)."""

from __future__ import annotations

import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research import providers as rp  # noqa: E402

QUERIES = ["Claude latest models", "أحدث نماذج Claude", "ma hi ahdath namadhij claude"]

for query in QUERIES:
    url = "https://www.mojeek.com/search?q=" + urllib.parse.quote(query)
    request = urllib.request.Request(url, headers=dict(rp._BROWSER_HEADERS))
    print(f"\n===== {query!r} =====")
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            page = response.read().decode("utf-8", "replace")
    except Exception as error:  # noqa: BLE001
        print("  ERROR", error)
        continue
    print("  bytes:", len(page))
    print("  title:", re.search(r"<title>(.*?)</title>", page, re.S).group(1)[:90])
    for marker in ("results-standard", "class=\"results", "<ul class=\"results",
                   "no results", "captcha", "blocked"):
        print(f"    {marker!r}:", marker in page)
    # كل <a> مع كلاس
    anchors = re.findall(r'<a[^>]*class="([^"]*)"[^>]*href="(https?://[^"]+)"',
                         page)
    print("  anchors with class:", len(anchors))
    seen = 0
    for cls, href in anchors:
        if "mojeek" in href:
            continue
        print(f"    class={cls[:30]!r} {href[:80]}")
        seen += 1
        if seen >= 8:
            break
    if seen == 0:
        for match in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                                 page, re.S):
            href = match.group(1)
            title = rp._tag(match.group(2)).strip()
            if "mojeek" in href:
                continue
            print(f"    href={href[:70]} title={title[:50]!r}")
            seen += 1
            if seen >= 8:
                break
