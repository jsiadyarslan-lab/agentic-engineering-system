"""تشخيص رد Bing الخام: هل يستجيب للاستعلام أصلًا؟ (013.5 §L)."""

from __future__ import annotations

import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research import providers as rp  # noqa: E402

query = "Claude latest models"
url = ("https://www.bing.com/search?q=" + urllib.parse.quote(query)
       + "&count=10")
req = urllib.request.Request(url, headers=dict(rp._BROWSER_HEADERS))
with urllib.request.urlopen(req, timeout=20) as resp:
    print("status:", resp.status)
    print("final url:", resp.geturl())
    print("content-type:", resp.headers.get("content-type"))
    page = resp.read().decode("utf-8", "replace")

print("bytes:", len(page))
print("title:", re.search(r"<title>(.*?)</title>", page, re.S).group(1)[:120])
print("has query echoed:", query.lower() in page.lower())
print("b_algo count:", len(re.findall(r'<li class="b_algo"', page)))
for marker in ("b_no", "no results", "sb_count", "b_results",
               "captcha", "unusual traffic", "Anmelden", "Redirecting"):
    print(f"  marker {marker!r}:", marker.lower() in page.lower())

# أول ثلاثة عناوين في الصفحة كما تعاد
for block in re.findall(r'<li class="b_algo".*?</li>', page, re.S)[:3]:
    h = re.search(r"<h2[^>]*>(.*?)</h2>", block, re.S)
    print("  head:", rp._tag(h.group(1))[:100] if h else None)

out = ROOT / "runtime" / "_bing_raw.html"
out.write_text(page, encoding="utf-8")
print("saved:", out)
