"""أدوات المنفذ المضمّنة (الأمر السادس §3+§4) — قائمة بيضاء مغلقة.

القاعدة: القائمة البيضاء أدوات معروفة حصرًا؛ أي استدعاء أداة أخرى
= فشل خطوة صريح (ToolError) لا تجاهل.

مواقع التنفيذ (مبدأ v2: معزول أو معلن):
- أدوات الملفات وPDF (write_file/read_file/generate_pdf_arabic/
  verify_pdf_pages): داخل الركيزة المعزولة (namespaces+seccomp،
  بلا شبكة) عبر SandboxManager نفسه الذي يستخدمه المنفذ mock.
- أدوات الويب (web_search/fetch_page): الركيزة E1 مجمّدة على
  NetworkMode.NONE (لا واجهات شبكة داخل العزل إطلاقًا) — تُنفَّذ
  في العملية مع **إعلان صريح** في كل حدث ودليل (execution_site:
  "in_process_declared") — لا تدهور صامت.

كل استدعاء أداة يوثَّق: الاسم، ملخص الوسائط، sha256 للمخرج، الموقع،
المدة (§3.3) — عبر مستقبِل أحداث يزوّده المستدعي.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

#: القائمة البيضاء (§3.2): 4 أساس + أداتا PDF (§4) + أدوات البيانات
#: الخمس (الأمر 003 — تنفيذها في tools/data_tools.py، استدعاء المنفذ
#: الحي حصرًا، نمط معلن خارج الركيزة بقرار المالك).
TOOL_WHITELIST: tuple[str, ...] = (
    "web_search",
    "fetch_page",
    "write_file",
    "read_file",
    "generate_pdf_arabic",
    "verify_pdf_pages",
    "http_get_text",
    "http_get_json",
    "page_to_text",
    "fred_csv",
    "worldbank_indicator",
)

#: أدوات البيانات الخمس (الأمر 003) — تنفيذ معلن خارج الركيزة دائمًا.
DATA_TOOLS: frozenset[str] = frozenset({
    "http_get_text", "http_get_json", "page_to_text",
    "fred_csv", "worldbank_indicator",
})

#: حدّ مستحضَر من نتائج البحث/الصفحات — لا احتجاز ذاكرة.
MAX_SEARCH_RESULTS = 8
MAX_PAGE_BYTES = 400_000
FETCH_TIMEOUT = 20.0

#: خط IBM Plex Arabic المضمّن مع المستودع (§4.1) — يُحمَّل مرة واحدة.
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
PDF_FONT_PATH = ASSETS_DIR / "fonts" / "IBMPlexSansArabic-Regular.ttf"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class ToolError(RuntimeError):
    """فشل خطوة أداة — استدعاء خارج القائمة البيضاء أو تنفيذ فشل."""


@dataclass
class ToolContext:
    """سياق تنفيذ الأدوات — المجلد الممنوح + مستقبِل الأحداث."""

    grant_root: Path
    on_event: Callable[[dict], None] | None = None
    #: آخر نتائج البحث (لتغذية المراجع بعدد المصادر).
    search_results: list[dict] = field(default_factory=list)
    fetched_urls: list[str] = field(default_factory=list)
    #: مصادر البيانات الرسمية المجلوبة (الأمر 003) — تُغذّي sources.json
    #: مثل نتائج البحث: رابط + عنوان.
    data_urls: list[dict] = field(default_factory=list)
    #: الأمر 004: فحص طلب الإيقاف بين خطوات المنفذ الحي — إغلاق اختياري
    #: يرفع CycleStopSignal عند نقطة آمنة (لا يقتل استدعاءً جاريًا).
    stop_check: Callable[[], bool] | None = None

    def emit(self, event: dict) -> None:
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:  # noqa: BLE001 — المستقبِل لا يكسر الأداة
                pass


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _bounded_path(grant_root: Path, relative: str) -> Path:
    """مسار داخل المنحة حصرًا — خروج عنها = رفض (لا ../ ولا مطلق)."""
    candidate = (grant_root / relative).resolve()
    grant = grant_root.resolve()
    if grant != candidate and grant not in candidate.parents:
        raise ToolError(f"المسار خارج المجلد الممنوح: {relative}")
    return candidate


# ------------------------------------------------------------------ #
# أدوات الويب — معلنة خارج الركيزة (E1: NetworkMode.NONE مجمّد)
# ------------------------------------------------------------------ #

_RESULT_LINK = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_RESULT_SNIPPET = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.DOTALL
)
_TAG = re.compile(r"<[^>]+>")


def _ddg_redirect_url(raw: str) -> str:
    """فك روابط توجيه DuckDuckGo (//duckduckgo.com/l/?uddg=…)."""
    try:
        if "uddg=" in raw:
            query = urllib.parse.urlparse(raw).query
            value = urllib.parse.parse_qs(query).get("uddg", [""])[0]
            return urllib.parse.unquote(value) if value else raw
    except ValueError:
        pass
    return raw


def web_search(query: str, *, endpoint: str = "https://html.duckduckgo.com/html/",
               timeout: float = FETCH_TIMEOUT) -> list[dict]:
    """بحث ويب عبر DuckDuckGo HTML — POST بصيغة نموذج، بلا مفاتيح (§3.1).

    GET محجوب في بعض الشبكات (منها شبكة هذه الحاوية) — POST مجرَّب
    ويعمل؛ urllib فقط، صفر تبعيات.
    """
    if not query.strip():
        raise ToolError("استعلام بحث فارغ")
    body = urllib.parse.urlencode({"q": query}).encode("utf-8")
    request = urllib.request.Request(
        endpoint, data=body, method="POST",
        headers={"User-Agent": _USER_AGENT,
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            page = response.read().decode("utf-8", "replace")
    except Exception as error:  # noqa: BLE001 — خطأ شبكة واحد صريح
        raise ToolError(f"فشل البحث ({query[:60]}): {error}") from error

    results: list[dict] = []
    links = _RESULT_LINK.findall(page)
    snippets = [s for s in _RESULT_SNIPPET.findall(page)]
    for index, (raw_url, title_html) in enumerate(links[:MAX_SEARCH_RESULTS]):
        title = html_lib.unescape(_TAG.sub("", title_html)).strip()
        url = _ddg_redirect_url(html_lib.unescape(raw_url))
        snippet = ""
        if index < len(snippets):
            snippet = html_lib.unescape(
                _TAG.sub("", snippets[index])
            ).strip()[:300]
        if title and url.startswith("http"):
            results.append({"title": title, "url": url, "snippet": snippet})
    if not results:
        raise ToolError(f"البحث لم يُعد نتائج قابلة للتحليل ({query[:60]})")
    return results


def fetch_page(url: str, *, timeout: float = FETCH_TIMEOUT,
               max_bytes: int = MAX_PAGE_BYTES) -> str:
    """جلب صفحة واستخلاص نصها الخام — urllib، مهلة 20ث (§3.1)."""
    if not url.startswith(("http://", "https://")):
        raise ToolError(f"رابط غير مدعوم: {url[:80]}")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
    except Exception as error:  # noqa: BLE001
        raise ToolError(f"فشل جلب {url[:80]}: {error}") from error
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
    text = raw.decode("utf-8", "replace")
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.I)
    text = _TAG.sub(" ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 120:
        raise ToolError(f"الصفحة شبه فارغة بعد الاستخلاص: {url[:80]}")
    return text


# ------------------------------------------------------------------ #
# أدوات الملفات — داخل الركيزة المعزولة (لا شبكة)
# ------------------------------------------------------------------ #

def _run_in_substrate(ctx: ToolContext, code: str, workspace: Path,
                      artifacts: Path) -> tuple[int, str, str]:
    """تنفيذ كود داخل الركيزة — نفس مسار المنفذ mock (SandboxManager)."""
    from substrate.limits import E1_LIMITS_DEFAULTS
    from substrate.local_substrate import local_sandbox_manager
    from substrate.sandbox import NetworkMode, SandboxRequest
    import uuid as uuid_mod

    manager = local_sandbox_manager()
    image = next(iter(manager.image_allowlist))
    sandbox_id = f"tool-{uuid_mod.uuid4().hex[:8]}"
    request = SandboxRequest(
        sandbox_id=sandbox_id,
        image=image,
        command=("python", "-c", code),
        limits=E1_LIMITS_DEFAULTS,
        env_names=frozenset({"PATH"}),
        network=NetworkMode.NONE,
        workspace_root=str(workspace),
        artifacts_dir=str(artifacts),
    )
    outcome = manager.execute(request)
    record = outcome.record
    if record is None:
        return -1, "", str(outcome.detail or "بلا سجل ركيزة")
    stdout = ""
    stderr = ""
    try:
        stdout = Path(record.stdout_reference).read_text(encoding="utf-8", errors="replace") if record.stdout_reference else ""
    except OSError:
        pass
    try:
        stderr = Path(record.stderr_reference).read_text(encoding="utf-8", errors="replace") if record.stderr_reference else ""
    except OSError:
        pass
    return record.exit_code if record.exit_code is not None else -1, stdout, stderr


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    """كتابة ملف داخل المجلد الممنوح فقط — داخل الركيزة (§3.1)."""
    target = _bounded_path(ctx.grant_root, path)
    workspace = ctx.grant_root / "_ws"
    artifacts = ctx.grant_root
    workspace.mkdir(parents=True, exist_ok=True)
    code = (
        "import json\n"
        f"payload = json.loads({json.dumps({'path': path, 'content': content}, ensure_ascii=False)!r})\n"
        "import pathlib\n"
        "target = pathlib.Path('/artifacts') / payload['path']\n"
        "target.parent.mkdir(parents=True, exist_ok=True)\n"
        "target.write_text(payload['content'], encoding='utf-8')\n"
        "print('wrote', len(payload['content']), 'chars to', payload['path'])\n"
    )
    exit_code, stdout, stderr = _run_in_substrate(ctx, code, workspace, artifacts)
    if exit_code != 0:
        raise ToolError(f"فشل كتابة {path} داخل الركيزة: {stderr[:200]}")
    return str(target)


def read_file(ctx: ToolContext, path: str) -> str:
    """قراءة ملف من المجلد الممنوح فقط — داخل الركيزة (§3.1)."""
    _bounded_path(ctx.grant_root, path)  # رفض خارج المنحة قبل أي تنفيذ
    workspace = ctx.grant_root / "_ws"
    artifacts = ctx.grant_root
    workspace.mkdir(parents=True, exist_ok=True)
    code = (
        "import json, pathlib\n"
        f"payload = json.loads({json.dumps({'path': path})!r})\n"
        "target = pathlib.Path('/artifacts') / payload['path']\n"
        "data = target.read_text(encoding='utf-8')\n"
        "print(json.dumps({'len': len(data), 'head': data[:2000]}))\n"
    )
    exit_code, stdout, stderr = _run_in_substrate(ctx, code, workspace, artifacts)
    if exit_code != 0:
        raise ToolError(f"فشل قراءة {path} داخل الركيزة: {stderr[:200]}")
    try:
        return json.loads(stdout.strip().splitlines()[-1])["head"]
    except (ValueError, KeyError, IndexError) as error:
        raise ToolError(f"مخرج قراءة غير مفهوم لـ {path}: {error}") from error


#: كود توليد PDF العربي — يعمل داخل الركيزة وفي العملية على السواء
#: (root_expr يحدد جذر الأدلة: ‎'/artifacts' داخل الركيزة و'.' في العملية).
#: بادئان حتميان: تخطيط عادي؛ فإن تجاوز صفحة واحدة أعاد البناء
#: مضغوطًا (أسطر أضيق + مصادر 9pt) — ضغط تخطيط لا مساس بالمحتوى؛
#: وبعد البادئين يظل >1 صفحة = يُترك للفشل الصريح (§4.3).
def _pdf_code(md_rel: str, out_rel: str, font_path: str,
              root_expr: str = "pathlib.Path('/artifacts')") -> str:
    return (
        "import json, pathlib, re\n"
        "import arabic_reshaper\n"
        "from bidi.algorithm import get_display\n"
        "from pypdf import PdfReader\n"
        "from reportlab.lib.pagesizes import A4\n"
        "from reportlab.lib.enums import TA_RIGHT\n"
        "from reportlab.lib.styles import ParagraphStyle\n"
        "from reportlab.pdfbase import pdfmetrics\n"
        "from reportlab.pdfbase.ttfonts import TTFont\n"
        "from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer\n"
        f"payload = json.loads({json.dumps({'md': md_rel, 'out': out_rel, 'font': font_path})!r})\n"
        f"root = {root_expr}\n"
        "md = (root / payload['md']).read_text(encoding='utf-8')\n"
        "font = pathlib.Path(payload['font'])\n"
        "pdfmetrics.registerFont(TTFont('PlexArabic', str(font)))\n"
        "def ar(t):\n"
        "    return get_display(arabic_reshaper.reshape(str(t)))\n"
        "def build(compact):\n"
        "    lead = 15 if compact else 17\n"
        "    src_size = 9 if compact else 10\n"
        "    title = ParagraphStyle('t', fontName='PlexArabic', fontSize=16 if compact else 17, leading=22 if compact else 26, alignment=TA_RIGHT)\n"
        "    body = ParagraphStyle('b', fontName='PlexArabic', fontSize=11, leading=lead, alignment=TA_RIGHT)\n"
        "    h2 = ParagraphStyle('h', fontName='PlexArabic', fontSize=12.5 if compact else 13, leading=17 if compact else 20, alignment=TA_RIGHT)\n"
        "    small = ParagraphStyle('s', fontName='PlexArabic', fontSize=src_size, leading=src_size + 3, alignment=TA_RIGHT)\n"
        "    story = []\n"
        "    in_sources = False\n"
        "    for block in md.splitlines():\n"
        "        line = block.strip()\n"
        "        if not line:\n"
        "            continue\n"
        "        if line.startswith('# '):\n"
        "            story.append(Paragraph(ar(line[2:]), title)); story.append(Spacer(1, 7 if compact else 10))\n"
        "        elif line.startswith('## '):\n"
        "            head = line[3:]\n"
        "            in_sources = head.startswith('\\u0627\\u0644\\u0645\\u0635\\u0627\\u062f\\u0631')\n"
        "            story.append(Spacer(1, 3 if compact else 6)); story.append(Paragraph(ar(head), h2))\n"
        "        elif line.startswith('- '):\n"
        "            story.append(Paragraph(ar('\\u2022 ' + line[2:]), small if in_sources else body))\n"
        "        else:\n"
        "            story.append(Paragraph(ar(line), small if in_sources else body))\n"
        "    doc = SimpleDocTemplate(str(root / payload['out']), pagesize=A4,\n"
        "        rightMargin=57, leftMargin=57, topMargin=57, bottomMargin=57)\n"  # 2سم ≈ 57pt
        "    doc.build(story)\n"
        "build(False)\n"
        "if len(PdfReader(str(root / payload['out'])).pages) > 1:\n"
        "    build(True)\n"
        "print('pdf_written pages=' + str(len(PdfReader(str(root / payload['out'])).pages)))\n"
    )


def generate_pdf_arabic(ctx: ToolContext, md_path: str, out_path: str) -> str:
    """توليد PDF عربي RTL A4 — reportlab+reshaper+bidi وخط IBM Plex
    Arabic المضمّن — داخل الركيزة؛ وإن رفضت الركيزة الاستيراد فتنفيذ
    معلَن في العملية (execution_site في الحدث والدليل)."""
    _bounded_path(ctx.grant_root, md_path)
    target = _bounded_path(ctx.grant_root, out_path)
    if not PDF_FONT_PATH.is_file():
        raise ToolError(f"خط IBM Plex Arabic مفقود: {PDF_FONT_PATH}")
    workspace = ctx.grant_root / "_ws"
    fonts_dir = workspace / "_fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    font_copy = fonts_dir / PDF_FONT_PATH.name
    if not font_copy.is_file():
        font_copy.write_bytes(PDF_FONT_PATH.read_bytes())
    code = _pdf_code(md_path, out_path, "/ws/_fonts/" + PDF_FONT_PATH.name)
    exit_code, _out, stderr = _run_in_substrate(ctx, code, workspace, ctx.grant_root)
    site = "substrate"
    if exit_code != 0:
        # إعلان صريح: الركيزة رفضت (استيراد مكتبة مثلًا) — تنفيذ في
        # العملية بنفس الكود بجذر مؤقت ثم نسخ الناتج إلى المنحة؛
        # الحدث والدليل يوثقان الموقعين.
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            (fake_root / md_path).parent.mkdir(parents=True, exist_ok=True)
            (fake_root / md_path).write_text(
                (ctx.grant_root / md_path).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (fake_root / out_path).parent.mkdir(parents=True, exist_ok=True)
            proc = subprocess.run(
                [sys.executable, "-c",
                 _pdf_code(md_path, out_path, str(PDF_FONT_PATH),
                           root_expr="pathlib.Path('.')")],
                capture_output=True, text=True, timeout=120,
                cwd=str(fake_root),
            )
            if proc.returncode == 0 and (fake_root / out_path).is_file():
                target.write_bytes((fake_root / out_path).read_bytes())
        if not target.is_file():
            raise ToolError(
                "فشل توليد PDF (الركيزة: "
                f"{stderr[-150:]} / العملية: {proc.stderr[-150:]})"
            )
        site = "in_process_declared"
    if not target.is_file():
        raise ToolError(f"PDF لم يُكتب إلى {out_path}")
    return str(target) + f"#{site}"


def verify_pdf_pages(ctx: ToolContext, path: str) -> int:
    """عدّ صفحات PDF عبر pypdf — داخل الركيزة؛ وعند تعذر الاستيراد
    داخلها: عدّ معلَن في العملية (execution_site في الحدث)."""
    _bounded_path(ctx.grant_root, path)
    workspace = ctx.grant_root / "_ws"
    workspace.mkdir(parents=True, exist_ok=True)
    code = (
        "import json, pathlib\n"
        "from pypdf import PdfReader\n"
        f"payload = json.loads({json.dumps({'path': path})!r})\n"
        "reader = PdfReader(str(pathlib.Path('/artifacts') / payload['path']))\n"
        "print(json.dumps({'pages': len(reader.pages)}))\n"
    )
    exit_code, stdout, stderr = _run_in_substrate(ctx, code, workspace, ctx.grant_root)
    if exit_code != 0:
        try:
            from pypdf import PdfReader as _Reader

            pages = len(_Reader(str(_bounded_path(ctx.grant_root, path))).pages)
        except Exception as error:  # noqa: BLE001
            raise ToolError(f"فشل عدّ صفحات {path}: {stderr[:200]} / {error}") from error
        ctx.emit({
            "kind": "tool.site_declared",
            "role": "implementer",
            "tool": "verify_pdf_pages",
            "execution_site": "in_process_declared",
            "reason": "الركيزة رفضت الاستيراد — عدّ في العملية معلنًا",
        })
        return pages
    try:
        return int(json.loads(stdout.strip().splitlines()[-1])["pages"])
    except (ValueError, KeyError, IndexError) as error:
        raise ToolError(f"مخرج عدّ صفحات غير مفهوم: {error}") from error


# ------------------------------------------------------------------ #
# المنفذ الموحد — القائمة البيضاء + التوثيق (§3.2+§3.3)
# ------------------------------------------------------------------ #

def run_tool(name: str, args: dict, ctx: ToolContext) -> Any:
    """تنفيذ أداة من القائمة البيضاء مع توثيق sha256 — غيرها = فشل خطوة."""
    if name not in TOOL_WHITELIST:
        raise ToolError(
            f"أداة خارج القائمة البيضاء: '{name}' (المسموح: {list(TOOL_WHITELIST)})"
        )
    started = time.monotonic()
    site = (
        "in_process_declared"
        if name in ("web_search", "fetch_page") or name in DATA_TOOLS
        else "substrate"
    )
    try:
        if name == "web_search":
            value = web_search(**args)
            ctx.search_results.extend(value)
            digest = _sha256_text(json.dumps(value, ensure_ascii=False))
        elif name == "fetch_page":
            url = str(args.get("url", ""))
            value = fetch_page(**args)
            ctx.fetched_urls.append(url)
            digest = _sha256_text(value)
        elif name == "write_file":
            value = write_file(ctx, str(args.get("path", "")), str(args.get("content", "")))
            digest = _sha256_text(str(args.get("content", "")))
        elif name == "read_file":
            value = read_file(ctx, str(args.get("path", "")))
            digest = _sha256_text(str(value))
        elif name == "generate_pdf_arabic":
            value = generate_pdf_arabic(
                ctx, str(args.get("md_path", "")), str(args.get("out_path", ""))
            )
            digest = hashlib.sha256(Path(value.split("#")[0]).read_bytes()).hexdigest()
            if "#" in value:
                site = value.split("#", 1)[1]
                value = value.split("#", 1)[0]
        elif name == "verify_pdf_pages":
            value = verify_pdf_pages(ctx, str(args.get("path", "")))
            digest = _sha256_text(f"pages={value}")
        elif name in DATA_TOOLS:
            # الأمر 003: أدوات البيانات — استيراد مؤجل (حزمة tools
            # تستورد roles.tools فالاستيراد المبكر دائري).
            from tools import data_tools

            if name == "http_get_text":
                value = data_tools.http_get_text(ctx, str(args.get("url", "")))
                ctx.data_urls.append({
                    "url": value["url"],
                    "title": value.get("artifact", ""),
                })
            elif name == "http_get_json":
                value = data_tools.http_get_json(ctx, str(args.get("url", "")))
                ctx.data_urls.append({
                    "url": value["url"],
                    "title": value.get("artifact", ""),
                })
            elif name == "page_to_text":
                value = data_tools.page_to_text(ctx, str(args.get("url", "")))
                ctx.data_urls.append({
                    "url": value["url"],
                    "title": value.get("artifact", ""),
                })
            elif name == "fred_csv":
                value = data_tools.fred_csv(
                    ctx, str(args.get("series_id", "")),
                    start=args.get("start") or None,
                    end=args.get("end") or None,
                )
                ctx.data_urls.append({
                    "url": f"https://fred.stlouisfed.org/data/{value['series_id']}",
                    "title": f"FRED — سلسلة {value['series_id']}",
                })
            else:  # worldbank_indicator
                value = data_tools.worldbank_indicator(
                    ctx, str(args.get("indicator", "")),
                    countries=str(args.get("countries", "all")),
                    dates=args.get("dates") or None,
                )
                ctx.data_urls.append({
                    "url": (
                        "https://data.worldbank.org/indicator/"
                        f"{value['indicator']}"
                    ),
                    "title": f"البنك الدولي — مؤشر {value['indicator']}",
                })
            #: sha256 للمحتوى المستلم خامًا — عقد الأمر 003 للتكامل.
            digest = str(value["sha256"])
        else:  # pragma: no cover — القائمة مغلقة أعلاه
            raise ToolError(f"أداة غير منفذة: {name}")
    except ToolError:
        raise
    except Exception as error:  # noqa: BLE001 — فشل خطوة صريح موثق
        raise ToolError(f"الأداة {name} فشلت: {error}") from error

    duration_ms = int((time.monotonic() - started) * 1000)
    summary: Any
    if name == "web_search":
        summary = {"results": len(value), "first": value[0]["title"][:80] if value else ""}
    elif name == "fetch_page":
        summary = {"chars": len(value)}
    elif name == "verify_pdf_pages":
        summary = {"pages": value}
    elif name in DATA_TOOLS:
        summary = {
            key: value.get(key)
            for key in ("series_id", "indicator", "rows", "count",
                        "chars", "words", "artifact")
            if key in value
        }
    else:
        summary = {"path": str(value)}
    ctx.emit({
        "kind": "tool.call",
        "role": "implementer",
        "tool": name,
        "args_summary": summary,
        "output_sha256": digest,
        "execution_site": site,
        "duration_ms": duration_ms,
    })
    return value


#: وصف الأدوات للنموذج — يُدمج في برومبت المنفذ الحي.
TOOLS_MANIFEST: list[dict] = [
    {"tool": "web_search", "args": {"query": "نص الاستعلام"},
     "desc": "بحث ويب (DuckDuckGo) — يعيد عناوين وروابط ومقتطفات"},
    {"tool": "fetch_page", "args": {"url": "https://…"},
     "desc": "جلب صفحة واستخلاص نصها"},
    {"tool": "write_file", "args": {"path": "report.md", "content": "…"},
     "desc": "كتابة ملف داخل المجلد الممنوح (داخل الركيزة)"},
    {"tool": "read_file", "args": {"path": "report.md"},
     "desc": "قراءة ملف من المجلد الممنوح (داخل الركيزة)"},
    {"tool": "generate_pdf_arabic",
     "args": {"md_path": "report.md", "out_path": "report.pdf"},
     "desc": "توليد PDF عربي RTL بحجم A4 من ملف Markdown (داخل الركيزة)"},
    {"tool": "verify_pdf_pages", "args": {"path": "report.pdf"},
     "desc": "عدّ صفحات ملف PDF (داخل الركيزة)"},
    {"tool": "http_get_text", "args": {"url": "https://…/data.csv"},
     "desc": "جلب نص/CSV خام من رابط (معلن خارج الركيزة)"},
    {"tool": "http_get_json", "args": {"url": "https://…/api.json"},
     "desc": "جلب JSON من واجهة عامة (معلن خارج الركيزة)"},
    {"tool": "page_to_text", "args": {"url": "https://…/page"},
     "desc": "صفحة HTML → نص فقرات منسق (معلن خارج الركيزة)"},
    {"tool": "fred_csv", "args": {"series_id": "DGS10"},
     "desc": "سلسلة FRED رسمية بلا مفتاح — مثل DGS10/CPIAUCSL (معلن)"},
    {"tool": "worldbank_indicator",
     "args": {"indicator": "FP.CPI.TOTL.ZG", "countries": "SA;US", "dates": "2020:2024"},
     "desc": "مؤشر البنك الدولي — قيّد countries وdates (معلن)"},
]
