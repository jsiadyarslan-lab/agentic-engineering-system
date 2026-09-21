"""أدوات البيانات (الأمر التنفيذي 003) — منقولة من v1 كحزمة مستقلة.

الأدوات الخمس: http_get_text / http_get_json / page_to_text / fred_csv /
worldbank_indicator — جلب بيانات رسمية للمنفذ الحي (ImplementerLive)
حصرًا، عبر القائمة البيضاء في roles.tools.

النمط المعلن (قرار المالك في الأمر 003): ركيزة E1 مجمّدة على
NetworkMode.NONE — أدوات الشبكة تعمل **خارج** الركيزة في العملية،
وكل حدث ودليل يعلن execution_site: "in_process_declared" صراحة.
البيانات المستلمة تُنزَّل داخل المجلد الممنوح (data/raw + data/normalized)
بمسارات محصورة (_bounded_path) — لا كتابة خلف المنحة أبدًا.

التوثيق (§تكامل): كل استدعاء يعيد sha256 للمحتوى المستلم خامًا؛
الموزّع roles.tools.run_tool يوثقه في حدث tool.call فيلتقطه evidence.json.

الانحرافات الموثقة عن v1 (المصدر backend/services/tools.py):
- صفر تبعيات: urllib/csv/json/html.parser القياسية حصرًا — v1 استخدم
  requests وpandas؛ النقل يعيد التصميم لا الاستنساخ (حد النحافة أولاً).
- إعادة محاولة واحدة على 5xx فقط (كما v1)؛ أخطاء الشبكة تفشل فورًا —
  حلقة المنفذ تتسامح مع الاستدعاء الفاشل الموثق (tool.failed).
- سقف حجم 2MB للاستجابة — التجاوز = ToolError بتوجيه صريح
  (قيّد الدول/السنوات) لا اقتطاع صامت.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from roles.tools import ToolContext, ToolError, _bounded_path, _USER_AGENT

#: الحدود — مهلة v1 نفسها (30ث) وسقف حجم يحمي ذاكرة المهمة.
DATA_FETCH_TIMEOUT = 30.0
MAX_FETCH_BYTES = 2_000_000
SAMPLE_ROWS = 3

FRED_BASE_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
WORLDBANK_BASE_URL = "https://api.worldbank.org/v2"

#: موقع التنفيذ المعلن — ثابت الحزمة كلها (قرار المالك، النمط المعلن).
EXECUTION_SITE = "in_process_declared"


# ------------------------------------------------------------------ #
# جلب خام — إعادة محاولة واحدة على 5xx فقط (سلوك v1 لهذه الأدوات)
# ------------------------------------------------------------------ #

def _fetch(url: str, params: dict | None = None) -> tuple[bytes, str]:
    """جلب بايتات خام مع مهلة 30ث — خطأ صريح ToolError بلا صمت."""
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    if not url.startswith(("http://", "https://")):
        raise ToolError(f"رابط غير مدعوم: {url[:80]}")
    last_error = ""
    for attempt in (1, 2):
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(
                request, timeout=DATA_FETCH_TIMEOUT
            ) as response:
                raw = response.read(MAX_FETCH_BYTES + 1)
            if len(raw) > MAX_FETCH_BYTES:
                raise ToolError(
                    f"الاستجابة تجاوزت {MAX_FETCH_BYTES} بايت — قيّد "
                    "الدول/السنوات أو نطاق التاريخ لتصغيرها"
                )
            ctype = response.headers.get("Content-Type", "")
            return raw, ctype
        except urllib.error.HTTPError as error:
            last_error = f"HTTP {error.code}"
            if error.code >= 500 and attempt == 1:
                continue  # خطأ خادم — إعادة المحاولة الوحيدة
            raise ToolError(f"جلب {url[:80]} فشل: HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise ToolError(f"جلب {url[:80]} فشل: {error.reason}") from error
    raise ToolError(f"جلب {url[:80]} فشل: {last_error}")


def _domain(url: str) -> str:
    host = urllib.parse.urlparse(url).hostname or "local"
    return re.sub(r"[^a-z0-9.-]", "", host)[:40] or "local"


def _tag(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]


def _land(ctx: ToolContext, folder: str, name: str, content: str) -> str:
    """إنزال ملف داخل المنحة (data/<folder>/<name>) — مسار محصور."""
    relative = f"data/{folder}/{name}"
    target = _bounded_path(ctx.grant_root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return relative


def _base_summary(tool: str, url: str, raw: bytes) -> dict:
    return {
        "tool": tool,
        "url": url,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "execution_site": EXECUTION_SITE,
    }


# ------------------------------------------------------------------ #
# 1) http_get_text / 2) http_get_json — جلب خام عام
# ------------------------------------------------------------------ #

def http_get_text(ctx: ToolContext, url: str) -> dict:
    """جلب نص خام (CSV/SDMX/نص) — يُنزَّل خامًا ويعاد ملخص محدود."""
    started = time.monotonic()
    raw, _ctype = _fetch(url)
    text = raw.decode("utf-8", "replace")
    artifact = _land(ctx, "raw", f"text-{_domain(url)}-{_tag(url)}.txt", text)
    return {
        **_base_summary("http_get_text", url, raw),
        "chars": len(text),
        "head": text[:1000],
        "artifact": artifact,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def http_get_json(ctx: ToolContext, url: str) -> dict:
    """جلب JSON — خام يُنزَّل + مخطط بنيوي (بنية الحمولة لا تُخمَّن)."""
    started = time.monotonic()
    raw, _ctype = _fetch(url)
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError as error:
        raise ToolError(f"استجابة {url[:60]} ليست JSON صالحًا: {error}") from error
    artifact = _land(
        ctx, "raw", f"json-{_domain(url)}-{_tag(url)}.json",
        json.dumps(payload, ensure_ascii=False, indent=1),
    )
    if isinstance(payload, list):
        count = len(payload)
        structure = sorted(payload[0]) if payload and isinstance(payload[0], dict) else []
        sample = payload[:SAMPLE_ROWS]
    elif isinstance(payload, dict):
        count = 1
        structure = sorted(payload)[:20]
        # عينة محدودة: القيم السلّمية كما هي والمركّبة بطولها فقط —
        # بنية الحمولة مرئية بلا نقل حمولة كاملة إلى البرومبت.
        sample = {
            key: (
                value if not isinstance(value, (list, dict))
                else f"<{type(value).__name__} len={len(value)}>"
            )
            for key, value in list(payload.items())[:5]
        }
    else:
        count, structure, sample = 1, [], {}
    return {
        **_base_summary("http_get_json", url, raw),
        "count": count,
        "structure": structure,
        "sample": sample,
        "artifact": artifact,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


# ------------------------------------------------------------------ #
# 3) page_to_text — HTML → فقرات (HTMLParser القياسي — منقول من v1)
# ------------------------------------------------------------------ #

_BLOCK_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote",
    "td", "th", "figcaption", "article", "section", "main",
}
_SKIP_TAGS = {
    "script", "style", "noscript", "template", "svg", "iframe", "head",
    "nav", "header", "footer", "aside", "form", "button", "select",
}


class _TextExtractor(HTMLParser):
    """منقول حرفيًا من v1 — فقرات نصية بلا bs4 (المعيار القياسي فقط)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._buf: list[str] = []
        self._skip_depth = 0
        self._in_block = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._in_block += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS and self._in_block:
            self._in_block -= 1
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data.strip():
            self._buf.append(data.strip())

    def _flush(self) -> None:
        if self._buf:
            self.blocks.append(" ".join(self._buf))
            self._buf = []

    def result(self) -> str:
        self._flush()
        seen: set[str] = set()
        out: list[str] = []
        for block in self.blocks:
            if block not in seen and len(block) > 1:
                seen.add(block)
                out.append(block)
        return "\n".join(out)


def page_to_text(ctx: ToolContext, url: str) -> dict:
    """صفحة HTML → نص فقرات — يُنزَّل .txt + أول 300 كلمة للملخص."""
    started = time.monotonic()
    raw, ctype = _fetch(url)
    if "text/html" not in ctype and "</" not in raw.decode("utf-8", "replace")[:2000]:
        raise ToolError(f"{url[:60]} ليست صفحة HTML (Content-Type: {ctype})")
    extractor = _TextExtractor()
    extractor.feed(raw.decode("utf-8", "replace"))
    text = extractor.result()
    if not text.strip():
        raise ToolError(
            f"الصفحة شبه فارغة بعد الاستخلاص (تعتمد JavaScript غالبًا): {url[:60]}"
        )
    artifact = _land(ctx, "normalized", f"page-{_domain(url)}-{_tag(url)}.txt", text)
    words = text.split()
    return {
        **_base_summary("page_to_text", url, raw),
        "words": len(words),
        "paragraphs": len(text.splitlines()),
        "first_300_words": " ".join(words[:300]),
        "artifact": artifact,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


# ------------------------------------------------------------------ #
# 4) fred_csv — سلسلة FRED العامة بلا مفتاح (تطبيع بلا pandas)
# ------------------------------------------------------------------ #

def fred_csv(
    ctx: ToolContext, series_id: str,
    start: str | None = None, end: str | None = None,
    base_url: str | None = None,
) -> dict:
    """سلسلة FRED → CSV مطبّع date/value — إجبار رقمي (درس v1: منع
    كارثة str/str) عبر float() لا pandas (صفر تبعيات — انحراف موثق).

    base_url يُحل داخليًا من ثابت الوحدة (لا قيمة افتراضية مقيّدة وقت
    التعريف — حتى تبقى قابلة للتحويل في الاختبارات بلا شبكة).
    """
    started = time.monotonic()
    if base_url is None:
        base_url = FRED_BASE_URL
    series_id = (series_id or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,20}", series_id):
        raise ToolError(f"معرف سلسلة FRED غير صالح: {series_id!r}")
    params: dict[str, str] = {"id": series_id}
    if start:
        params["cosd"] = start
    if end:
        params["coed"] = end
    raw, ctype = _fetch(base_url, params)
    if "text/html" in ctype:
        raise ToolError(f"FRED لم يجد السلسلة {series_id} — تحقق من المعرف")
    text = raw.decode("utf-8", "replace")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration as error:
        raise ToolError(f"استجابة FRED فارغة للسلسلة {series_id}") from error
    if len(header) < 2:
        raise ToolError(f"أعمدة FRED غير متوقعة: {header}")
    rows: list[list[str]] = []
    for record in reader:
        if len(record) >= 2:
            rows.append([record[0].strip(), record[1].strip()])
    normalized_rows: list[tuple[str, float | None]] = []
    for date_str, value_str in rows:
        try:
            value = round(float(value_str), 6) if value_str not in (".", "") else None
        except ValueError:
            value = None
        normalized_rows.append((date_str, value))
    if not normalized_rows:
        raise ToolError(f"السلسلة {series_id} أعادت صفر صفوف — تحقق من المعرف")
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["date", "value"])
    writer.writerows(normalized_rows)
    normalized = out.getvalue()
    raw_rel = _land(ctx, "raw", f"fred-{series_id}.csv", text)
    norm_rel = _land(ctx, "normalized", f"fred-{series_id}.csv", normalized)
    sample = (
        normalized_rows[:SAMPLE_ROWS] + normalized_rows[-SAMPLE_ROWS:]
        if len(normalized_rows) > SAMPLE_ROWS * 2 else normalized_rows
    )
    return {
        **_base_summary("fred_csv", f"fred:{series_id}", raw),
        "series_id": series_id,
        "rows": len(normalized_rows),
        "columns": ["date", "value"],
        "sample_rows": [list(row) for row in sample],
        "artifacts": {"raw": raw_rel, "normalized": norm_rel},
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


# ------------------------------------------------------------------ #
# 5) worldbank_indicator — API البنك الدولي العام (JSON بلا مفتاح)
# ------------------------------------------------------------------ #

def worldbank_indicator(
    ctx: ToolContext, indicator: str, countries: str = "all",
    dates: str | None = None, base_url: str | None = None,
) -> dict:
    """مؤشر البنك الدولي → CSV مطبّع country/iso3/year/value/indicator.

    قيّد countries (مثل SA;US;DE) وdates (مثل 2020:2024) — الاستجابة
    بلا تقييد قد تتجاوز سقف 2MB وترفض صراحة. base_url يُحل داخليًا
    من ثابت الوحدة (قابل للتحويل في الاختبارات بلا شبكة).
    """
    started = time.monotonic()
    if base_url is None:
        base_url = WORLDBANK_BASE_URL
    indicator = (indicator or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.]{3,40}", indicator):
        raise ToolError(f"رمز مؤشر غير صالح: {indicator!r}")
    countries = (countries or "all").strip() or "all"
    path = f"/country/{countries}/indicator/{indicator}"
    params: dict[str, str] = {"format": "json", "per_page": "20000"}
    if dates:
        params["date"] = dates
    raw, _ctype = _fetch(base_url.rstrip("/") + path, params)
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError as error:
        raise ToolError(f"استجابة البنك الدولي ليست JSON: {error}") from error
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise ToolError(f"استجابة البنك الدولي غير متوقعة للمؤشر {indicator}")
    rows: list[list] = []
    for item in payload[1]:
        value = item.get("value")
        try:
            value = round(float(value), 4) if value is not None else None
        except (TypeError, ValueError):
            value = None
        rows.append([
            (item.get("country") or {}).get("value", ""),
            item.get("countryiso3code", ""),
            str(item.get("date", "")),
            value,
            ((item.get("indicator") or {}).get("id") or indicator),
        ])
    rows.sort(key=lambda row: (row[0], row[2]))
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["country", "iso3", "year", "value", "indicator"])
    writer.writerows(rows)
    normalized = out.getvalue()
    raw_rel = _land(
        ctx, "raw", f"wb-{indicator}-{_tag(countries)}.json",
        json.dumps(payload, ensure_ascii=False),
    )
    norm_rel = _land(
        ctx, "normalized", f"wb-{indicator}-{_tag(countries)}.csv", normalized
    )
    return {
        **_base_summary("worldbank_indicator", f"worldbank:{indicator}", raw),
        "indicator": indicator,
        "countries": countries,
        "rows": len(rows),
        "columns": ["country", "iso3", "year", "value", "indicator"],
        "sample_rows": rows[:SAMPLE_ROWS] + rows[-SAMPLE_ROWS:] if len(rows) > SAMPLE_ROWS * 2 else rows,
        "artifacts": {"raw": raw_rel, "normalized": norm_rel},
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
