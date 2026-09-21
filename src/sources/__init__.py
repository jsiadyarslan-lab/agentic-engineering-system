"""سجل المصادر الرسمي (الأمر التنفيذي 003) — واجهة قراءة نحيفة.

سجل v1 المنقول: ‎25 مصدرًا رسميًا (بنوك مركزية/منظمات دولية/سلاسل
اقتصادية/أسواق) كل مصدر صف إعدادات لا كود — connector_tool يحدد أداة
الجلب من tools.data_tools. النطاق: الأدوات المنقولة إلى v2 حصرًا؛
مصادر yfinance/rss تُضاف عند نقل حزمتها (راجع docs/migration-plan.md).

الواجهة: load_sources / list_sources / search_sources / suggest_sources
— قراءة صرفة بلا قاعدة بيانات (سجل v2 ثلاثة جداول فقط، والمبدأ 1:
القدرة تظهر داخل المحادثة لا في جداول إدارية مبكرة).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parent / "sources.json"

#: الأدوات الموصولة في v2 — مصدر بأداة أخرى يُرفض عند التحميل (fail-closed).
SUPPORTED_CONNECTORS = frozenset({
    "http_get_text", "http_get_json", "page_to_text",
    "fred_csv", "worldbank_indicator",
})

#: خريطة الكلمات المفتاحية العربية → ملامح المصادر الإنجليزية
#: (السجل أسماؤه إنجليزية والمهام عربية — الجسر ضروري للاقتراح).
_KEYWORD_BRIDGES: dict[str, tuple[str, ...]] = {
    "تضخم": ("cpi", "inflation", "أسعار"),
    "الفائدة": ("interest", "rate", "dgs", "fedfunds", "bank_rate"),
    "فائدة": ("interest", "rate", "dgs", "fedfunds", "bank_rate"),
    "ناتج": ("gdp",),
    "الناتج": ("gdp",),
    "بطالة": ("unemployment", "unrate"),
    "البطالة": ("unemployment", "unrate"),
    "نفط": ("oil", "wti"),
    "الذهب": ("gold",),
    "دولار": ("dollar", "dxy", "usd", "exr"),
    "الصرف": ("exr", "exchange", "fx"),
    "صرف": ("exr", "exchange", "fx"),
    "أسواق": ("market", "exchange"),
    "سوق": ("market", "exchange"),
    "اقتصاد": ("gdp", "economic", "weo", "economy"),
    "الاقتصاد": ("gdp", "economic", "weo", "economy"),
    "بنك": ("bank", "central"),
    "المركزي": ("central",),
    "سندات": ("dgs", "t10y2y", "bonds"),
    "الخوف": ("vix",),
    "تقلب": ("vix",),
    "اليورو": ("ecb", "eur", "exr"),
    "الين": ("boj",),
    "الفرنك": ("snb",),
}

_TOKEN_RE = re.compile(r"[A-Za-z\u0600-\u06FF]{3,}")

_cache: list[dict] | None = None


def load_sources(path: Path | str | None = None) -> list[dict]:
    """تحميل السجل — مصدر بأداة غير منقولة = رفض صريح لا تجاهل."""
    global _cache
    if path is None and _cache is not None:
        return list(_cache)
    data = json.loads(
        Path(path or REGISTRY_PATH).read_text(encoding="utf-8")
    )
    sources = data.get("sources", []) if isinstance(data, dict) else []
    bad = [
        s.get("id", "?") for s in sources
        if s.get("connector_tool") not in SUPPORTED_CONNECTORS
    ]
    if bad:
        raise ValueError(
            f"مصادر بأدوات غير منقولة إلى v2: {bad} "
            f"(المسموح: {sorted(SUPPORTED_CONNECTORS)})"
        )
    loaded = list(sources)
    if path is None:
        _cache = loaded
    return loaded


def list_sources(
    *, category: str | None = None, connector: str | None = None,
    country: str | None = None,
) -> list[dict]:
    """قائمة المصادر — تصفية بالفئة/الأداة/البلد (بحث بالوسم/النوع)."""
    rows = load_sources()
    if category:
        rows = [s for s in rows if category in str(s.get("category", ""))]
    if connector:
        rows = [s for s in rows if s.get("connector_tool") == connector]
    if country:
        rows = [s for s in rows if country in str(s.get("country", ""))]
    return rows


def search_sources(query: str, **filters) -> list[dict]:
    """بحث نصي في المعرف/الاسم/الملاحظات/الفئة + تصفية اختيارية."""
    needle = (query or "").strip().lower()
    rows = list_sources(**filters)
    if not needle:
        return rows
    scored: list[tuple[int, dict]] = []
    for source in rows:
        hay = " ".join(str(source.get(k, "")) for k in
                       ("id", "name", "notes", "category", "country", "url")
                       ).lower()
        score = hay.count(needle)
        if score:
            scored.append((score, source))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("id", ""))))
    return [source for _score, source in scored]


def _call_hint(source: dict) -> str:
    """سطر استدعاء جاهز ينسخه النموذج في خطة الأدوات حرفيًا."""
    tool = str(source.get("connector_tool", ""))
    url = str(source.get("url", ""))
    if tool == "fred_csv":
        match = re.search(r"[?&]id=([A-Za-z0-9]+)", url)
        return f"fred_csv | {match.group(1)}" if match else ""
    if tool == "worldbank_indicator":
        match = re.search(r"/indicator/([A-Za-z0-9_.]+)", url)
        return f"worldbank_indicator | {match.group(1)}" if match else ""
    if tool in ("http_get_text", "http_get_json", "page_to_text"):
        return f"{tool} | {url}"
    return ""


def suggest_sources(task_text: str, *, limit: int = 8) -> list[dict]:
    """اقتراح مصادر رسمية لمهمة — ترتيب بتراكب الكلمات المفتاحية.

    جسر عربي→إنجليزي (أسماء السجل إنجليزية) + مطابقة الرموز الإنجليزية
    مباشرة. صفر تطابقات = قائمة فارغة (لا ضجيج على المهام غير البيانية).
    كل اقتراح يحمل سطر استدعاء جاهزًا (call) — ما يظهر للنموذج حرفي.
    """
    tokens = set(_TOKEN_RE.findall((task_text or "").lower()))
    needles: set[str] = set()
    for token in tokens:
        needles.add(token)
        # الجسر يحتمل السوابق العربية (و/ال/وال/بال…) — المفتاح جزء من
        # الرمز لا مساواة تامة: «والناتج» يلتقي مفتاح «الناتج».
        for key, bridges in _KEYWORD_BRIDGES.items():
            if key in token:
                needles.update(bridge.lower() for bridge in bridges)
    scored: list[tuple[int, dict]] = []
    for source in load_sources():
        hay = " ".join(str(source.get(k, "")) for k in
                       ("id", "name", "notes", "category", "country", "url")
                       ).lower()
        score = sum(1 for needle in needles if needle and needle in hay)
        if score:
            hint = _call_hint(source)
            if hint:
                scored.append((score, source))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("id", ""))))
    out: list[dict] = []
    for _score, source in scored[:limit]:
        row = {
            "id": source.get("id", ""),
            "name": source.get("name", ""),
            "connector_tool": source.get("connector_tool", ""),
            "call": _call_hint(source),
        }
        out.append(row)
    return out
