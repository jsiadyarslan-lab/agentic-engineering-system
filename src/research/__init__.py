"""حزمة البحث (الأمر 010 §23-§26) — طبقة ResearchProvider حقيقية.

    Research
    ├── SearchProvider   ddg / searx / api — كل واحد تنفيذ فعلي
    ├── FetchProvider    جلب الصفحات (fetch_page)
    ├── PageParser       استخلاص النص (داخل fetch_page)
    └── SourceEvidence   المصادر في سجل الاستدعاءات (tool_invocations)

المخطط لا يتزوج DDG (§25) — كل البحث يمر عبر service.search().
"""

from __future__ import annotations

from research import providers

__all__ = ["providers"]
