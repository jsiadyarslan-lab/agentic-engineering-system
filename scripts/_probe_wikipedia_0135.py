"""اختبار حي لمزود ويكيبيديا (§L) — بحث ويب حقيقي بلا مفاتيح."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research.providers import (  # noqa: E402
    WikipediaSearchProvider, filter_relevant, query_tokens, relevance_report,
)

QUERIES = [
    "ما هي أحدث نماذج كلاود؟",
    "ما هو React؟",
    "أحدث إصدارات Python",
    "Claude latest models",
    "quantum computing",
]

provider = WikipediaSearchProvider()
for query in QUERIES:
    print(f"\n=== {query!r}  tokens={query_tokens(query)}")
    try:
        results = provider.search(query)
    except Exception as error:  # noqa: BLE001
        print(f"  NOT_READY: {type(error).__name__}: {str(error)[:400]}")
        continue
    report = relevance_report(query, results)
    strong = filter_relevant(query, results)
    print(f"  OK: {len(results)} نتيجة | relevant={report['relevant']} "
          f"coverage={report.get('coverage')} "
          f"strong={report.get('strong_results')}")
    for item in strong[:3]:
        print(f"   ✓ {item['title']}  <{item['url']}>")
        print(f"     {item['snippet'][:130]}")
    dropped = [r for r in results if r not in strong]
    if dropped:
        print(f"   (أُسقطت {len(dropped)} نتيجة غير ذات صلة: "
              + "; ".join((r.get("title") or "")[:40]
                          for r in dropped[:3]) + ")")
