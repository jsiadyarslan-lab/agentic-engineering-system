"""مسبار صياغة الاستعلام: أي استعلام يعطي نتائج متعلقة فعلًا؟ (013.5 §L).

الملاحظة الحيّة: البحث يعمل لكن النتائج غير متعلقة — إرسال الجملة
الاستفهامية الخام إلى Bing يعيد صفحات عن «أنواع ما في اللغة العربية».
هذا مسبار تجريبي (ليس اختبار وحدة) لاختيار صياغة صادقة.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research import providers as rp  # noqa: E402

queries = [
    "ما هي احدث نماذج كلاود؟",
    "أحدث نماذج Claude",
    "احدث نماذج كلاود",
    "Claude latest models",
    "Anthropic Claude newest models 2026",
    "احدث نماذج الذكاء الاصطناعي Claude",
]

provider = rp.BingSearchProvider(endpoint="https://www.bing.com/search")
for q in queries:
    try:
        results = provider.search(q)
    except Exception as error:  # noqa: BLE001
        print(f"\n### {q!r}\n  ERROR {type(error).__name__}: {error}")
        continue
    print(f"\n### {q!r}  ({len(results)})")
    for r in results[:6]:
        title = (r.get("title") or "")[:70]
        url = (r.get("url") or "")[:80]
        print(f"  - {title} | {url}")
