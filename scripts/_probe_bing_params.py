"""مسبار: هل تُصلح معاملات السوق/اللغة جودة نتائج Bing؟ (013.5 §L)."""

from __future__ import annotations

import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research import providers as rp  # noqa: E402

VARIANTS = {
    "plain": "https://www.bing.com/search?q={q}&count=10",
    "mkt_en": "https://www.bing.com/search?q={q}&count=10&mkt=en-US&setlang=en",
    "form_setmkt": ("https://www.bing.com/search?q={q}&count=10"
                    "&form=QBLH&setmkt=en-US&setlang=en&cc=US"),
}

QUERIES = [
    "ما هي احدث نماذج كلاود؟",
    "أحدث نماذج Claude",
    "Claude latest models",
    "Anthropic Claude models list",
]

for name, template in VARIANTS.items():
    print(f"\n===== {name} =====")
    for q in QUERIES:
        url = template.format(q=urllib.parse.quote(q))
        req = urllib.request.Request(url, headers=dict(rp._BROWSER_HEADERS))
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                page = resp.read().decode("utf-8", "replace")
        except Exception as error:  # noqa: BLE001
            print(f"  {q!r} ERROR {error}")
            continue
        blocks = re.findall(r'<li class="b_algo".*?</li>', page, re.S)
        titles = []
        for block in blocks[:5]:
            head = re.search(r"<h2[^>]*>(.*?)</h2>", block, re.S)
            titles.append(rp._tag(head.group(1))[:45] if head else "?")
        hosts = []
        for block in blocks[:5]:
            link = re.search(r'<h2[^>]*><a[^>]+href="([^"]+)"', block, re.S)
            if not link:
                continue
            href = rp.html_lib.unescape(link.group(1))
            if "bing.com/ck/" in href:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                enc = qs.get("u", [""])[0]
                if enc.startswith("a1"):
                    import base64
                    pad = enc[2:] + "=" * (-len(enc[2:]) % 4)
                    try:
                        href = base64.urlsafe_b64decode(pad).decode(
                            "utf-8", "replace")
                    except Exception:  # noqa: BLE001
                        pass
            hosts.append(urllib.parse.urlparse(href).netloc)
        print(f"  {q!r} -> {titles}")
        print(f"      hosts: {hosts}")
