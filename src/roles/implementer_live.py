"""المنفذ الحي (الأمر السادس §2+§3+§4) — LLM يقود أدوات القائمة البيضاء.

مسار المهمة الواحدة (استدعاءان حيان فقط — ميزانية منضبطة):
1. chat_live الأول: خطة استدعاءات أدوات JSON (web_search/fetch_page).
2. تنفيذ كل استدعاء عبر roles.tools.run_tool (قائمة بيضاء + sha256
   + أحداث فورية) — أي أداة خارج البيضاء = فشل خطوة صريح.
3. chat_live الثاني: كتابة التقرير العربي Markdown من المادة المجلوبة
   (قيد الصفحة الواحدة في البرومبت).
4. write_file للتقرير ثم generate_pdf_arabic وverify_pdf_pages
   (داخل الركيزة) — الناتج أدلة بمراجع sha256.

فشل أي خطوة = ImplementerStatus.FAILED برسالة صريحة — لا ترقيع
ولا إعادة مفتوحة (المحكَّم يملك قرار الإعادة).
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path

from roles.implementer import (
    ImplementerRequest,
    ImplementerResult,
    ImplementerStatus,
)
from core.stop_controller import CycleStopSignal
from roles.live import LiveRoleBase, RoleSystemFault, load_prompt
from roles.recovery import run_with_recovery
from roles.tool_failures import ToolError, ToolFailure
from roles.tools import (
    DATA_TOOLS,
    MAX_SEARCH_RESULTS,
    TOOLS_MANIFEST,
    ToolContext,
    run_tool,
)
from router.model_router import ChatMessage

_TRUNCATE = 400
_PDF_HINT = re.compile(r"\.pdf\b", re.IGNORECASE)

#: (AES-LIVE-FACTORY-E2E-001 المرحلة 6) أسماء ملفات التسليم الصريحة —
#: نمط البناء: حين تصرّح المهمة بملفات (html/css/js/…) يبنيها المنفذ
#: فعلياً بدل اختزالها في تقرير. ملفات التقارير (md/txt) وحدها لا
#: تفعّل النمط — مسار التقارير الأصلي يبقى كما هو حرفياً.
_FILENAME_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])([A-Za-z0-9_][A-Za-z0-9_.-]*"
    r"\.(?:html|htm|css|js|mjs|json|svg|py|ts))(?![A-Za-z0-9.-])"
)

#: (RLR-001 §4d) مسارات مجلدات مصرّح بها في نص المهمة — مثل
#: "pages/، assets/css/، scripts/" — تُنشأ فعلياً بملفات .keep
#: كي تكون أدلة وجود المجلدات بصمات حقيقية لا نص الشرح.
_DIR_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])((?:[A-Za-z0-9_][A-Za-z0-9_.-]*/)+)"
)

#: (RLR-001 §4d-2) رموز مسارات كاملة — ملفات بمجلداتها
#: (src/styles/base.css) ومجلدات بلا شرطة نهائية (src/pages, ...)
#: — علة خطوة 218: المنتقي الأول يمنع ما يسبقه / فلا يرى الملف
#: المساريّ ولا المجلد المفصول بفاصلة.
_PATH_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])((?:[A-Za-z0-9_][A-Za-z0-9_.-]*/)+"
    r"[A-Za-z0-9_][A-Za-z0-9_.-]*)"
)
_BUILD_EXTS = ("html", "htm", "css", "js", "mjs", "json", "svg", "py", "ts")


def _safe_rel(p: str) -> str:
    """تطبيع مسار نسبي آمن داخل المنحة — None عند أي هروب."""
    p = p.strip().strip("/")
    if not p or p.startswith(".") or ".." in p or "\\" in p or len(p) > 200:
        return ""
    return p
_REPORT_SUFFIXES = (".md", ".txt")

_BUILD_SYSTEM_PROMPT = """أنت المنفذ البنّاء في نظام هندسي عربي ذاتي.
مهمتك: كتابة ملفات تسليم حقيقية كاملة المحتوى داخل مساحة العمل.

عقد الرد حرفيًا — JSON واحد صالح فقط، بلا أي نص خارجه:
{"files": [{"path": "<اسم ملف مسطح>", "content": "<المحتوى الكامل نصًا>"}],
 "verify": [{"tool": "<أداة من القائمة البيضاء>", "args": {<وسائط الأداة>}}]}

قواعد صارمة:
- اكتب كل ملف تصرح به المهمة كاملاً — لا اختصار ولا placeholders.
- المسارات مسطحة بلا مجلدات (مثل index.html) إلا إذا نصّت المهمة على مسار.
- المحتوى نص خام كامل (HTML/CSS/JS كامل صالح)، لا أسوار كود ولا وصف.
- لا تستخدم أداة شبكية (web_search/fetch_page) في verify — التسليم محلي.
- verify اختيارية: أدوات متصفح للتحقق (browser_navigate ثم browser_screenshot
  بأسماء معنّاة، وbrowser_type للحقول) — بترتيب منطقي بعد الملفات.
- الرد JSON خالص يبدأ بـ{ وينتهي بـ}."""


def _deliverable_names(task_payload: dict) -> list[str]:
    """أسماء ملفات البناء الصريحة في وصف المهمة ومعاييرها.

    تعود بغير فارغة فقط حين تصرّح المهمة بملف تسليم غير تقريري
    (html/css/js/…) — فمهمات التقارير (report.md وحده) تبقى على
    مسارها الأصلي بلا أي تغيير.
    """
    texts = [str(task_payload.get("description") or "")]
    texts += [str(c) for c in task_payload.get("acceptance_criteria") or []]
    texts.append(str(task_payload.get("context_goal") or ""))
    names: list[str] = []
    for text in texts:
        for match in _FILENAME_RE.findall(text):
            clean = match.lstrip("./").strip()
            if not clean or clean.lower().endswith(_REPORT_SUFFIXES):
                continue
            if "/" in clean or clean.startswith("."):
                continue
            if clean not in names:
                names.append(clean)
        # (§4d-2) ملفات بمسارات كاملة: src/styles/base.css — الاسم
        # البسيط وحده لا يلتقطها (lookbehind يمنع ما يسبقه /).
        for match in _PATH_TOKEN_RE.findall(text):
            clean = _safe_rel(match)
            if not clean or clean.lower().endswith(_REPORT_SUFFIXES):
                continue
            ext = clean.rsplit(".", 1)[-1].lower() if "." in clean else ""
            if ext in _BUILD_EXTS and clean not in names:
                names.append(clean)
    return names[:10]


def _parse_build_payload(text: str) -> dict:
    """تحليل عقد البناء — JSON واحد أو فشل قيمة صريح (لحلقة الإعادة)."""
    cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip()).strip()
    if not cleaned.startswith("{"):
        raise ValueError("الرد لا يبدأ بـ{ — JSON خالص مطلوب")
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("الجذر يجب أن يكون كائنًا")
    files = data.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("files قائمة غير فارغة مطلوبة")
    for item in files:
        if not isinstance(item, dict) or not item.get("path") \
                or "content" not in item:
            raise ValueError("كل ملف يحتاج path وcontent")
        if len(str(item.get("content", ""))) > 65536:
            raise ValueError(f"الملف {item.get('path')} يتجاوز 64KB")
    verify = data.get("verify") or []
    if not isinstance(verify, list):
        raise ValueError("verify قائمة إن وُجدت")
    return {"files": files[:12], "verify": verify[:12]}


def _mentions_browser_verification(task_payload: dict) -> bool:
    """خطوة تحقق بأدوات المتصفح (browser_*) — نمط بناء بلا ملفات."""
    text = " ".join(
        [str(task_payload.get("description") or "")]
        + [str(c) for c in task_payload.get("acceptance_criteria") or []]
        + [str(task_payload.get("context_goal") or "")]
    )
    return "browser_" in text


def _declared_dirs(task_payload: dict) -> list[str]:
    """مسارات المجلدات المصرّح بها في نص المهمة (RLR-001 §4d).

    تعود بغير فارغة فقط حين تصرّح المهمة بمجلدات صريحة مثل
    "pages/، assets/css/" — تُنشأ لاحقاً بملفات .keep حقيقية عبر
    write_file في الركيزة، فتصير أدلة «المجلدات موجودة» بصمات
    موثقة لا اجتهاد نصي.
    """
    texts = [str(task_payload.get("description") or "")]
    texts += [str(c) for c in task_payload.get("acceptance_criteria") or []]
    texts.append(str(task_payload.get("context_goal") or ""))
    dirs: list[str] = []

    def _add(candidate: str) -> None:
        clean = _safe_rel(candidate)
        if clean and clean not in dirs and len(dirs) < 12:
            dirs.append(clean)

    for text in texts:
        # (1) مجلدات بشرطة نهائية: pages/، assets/css/
        for match in _DIR_RE.findall(text):
            _add(match)
        # (2) رموز مسارات: src/pages (مجلد بفاصلة) أو والد ملف مساري
        for match in _PATH_TOKEN_RE.findall(text):
            clean = _safe_rel(match)
            if not clean or clean.endswith(".keep"):
                continue
            leaf = clean.rsplit("/", 1)[-1]
            if "." in leaf:
                parent = clean.rsplit("/", 1)[0]
                if parent:
                    _add(parent)
            else:
                _add(clean)
    return dirs[:12]


def _sources_section(markdown: str) -> str:
    """قسم «## المصادر» من التقرير — ما بعده حتى عنوان ## آخر أو النهاية."""
    parts = re.split(r"^##\s+", markdown, flags=re.MULTILINE)
    for part in parts[1:]:
        if part.strip().startswith("المصادر"):
            return part
    return ""


def _sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


class LiveImplementer(LiveRoleBase):
    """المنفذ الحي — أدوات مضمّنة يقودها النموذج عبر عقد JSON صارم."""

    PROMPT_NAME = "implementer"
    ROLE = "implementer"

    def __init__(self, router, tools_ctx: ToolContext | None = None,
                 selection=None):
        super().__init__(router, selection=selection)
        self._ctx = tools_ctx

    def _stop_requested(self, ctx: ToolContext, at_step: str) -> None:
        """نقطة تفتيش إيقاف (الأمر 004) — إشارة تُرفع ولا تُبتلع هنا."""
        check = getattr(ctx, "stop_check", None)
        if check is not None and check():
            raise CycleStopSignal(at_step)

    def _live_call_streamed(self, messages: list[ChatMessage]) -> dict:
        """استدعاء متدفق (المرحلة 6هـ) — نفس نمط المخطط حرفياً.

        البث يجعل بايتات الرد تصل لحظياً فلا تقتل مهلة القراءة (90ث
        افتراضياً) توليد ملف كبير (مثبت حياً: style.css تجاوز السقف
        × 3 محاولات نقل ≈ 4 دقائق ثم فشل الدورة — مشروع 12).
        فشل «لا بث لهذا المزود» يتراجع بصراحة للمسار الكامل؛ فشل
        النقل نفسه يُرفع ولا يُبتلع.
        """
        if hasattr(self._router, "chat_live_stream"):
            chunks: list[str] = []

            def _on_delta(piece: str) -> None:
                chunks.append(piece)

            try:
                return self._router.chat_live_stream(
                    messages, on_delta=_on_delta,
                    **self._selection_kwargs(),
                )
            except Exception as error:  # noqa: BLE001 — تراجع صريح
                from router.model_router import ProviderCallError

                text = str(error)
                if isinstance(error, ProviderCallError) and (
                    "بث" in text or "stream" in text.lower()
                ):
                    pass  # لا بث لهذا المزود — المسار الكامل بصراحة
                else:
                    raise
        return self._live_call(messages)

    def _selection_kwargs(self) -> dict:
        if self._selection is None:
            return {}
        return {
            "provider_id": self._selection.transport_key(),
            "model": self._selection.model,
        }

    # ------------------------------------------------------------------ #
    # 1) خطة الأدوات — بروتوكول سطر لكل استدعاء (لا JSON: أقواس LLM
    #    الناقصة علة معروفة؛ لكل أداة ويب وسيطة واحدة فيكفي السطر)
    #    مع إعادة محاولة واحدة عند فشل التحليل (§2.3)
    #    الأمر 003: أدوات البيانات الخمس تنضم — ثلاث برابط واحد،
    #    واثنتان (fred_csv/worldbank_indicator) بوسيطة أساسية +
    #    أزواج مفتاح=قيمة اختيارية (start/end/countries/dates).
    # ------------------------------------------------------------------ #

    _LINE_TOOLS = {
        "web_search": "query",
        "fetch_page": "url",
        "http_get_text": "url",
        "http_get_json": "url",
        "page_to_text": "url",
    }
    #: وسيطة أساسية + أزواج مفتاح=قيمة اختيارية بعد فراغ (fail-closed:
    #: أي جزء بلا «=» بعد الوسيطة الأساسية = سطر غير صالح).
    _KV_LINE_TOOLS = {"fred_csv": "series_id", "worldbank_indicator": "indicator"}
    _KV_ALLOWED_KEYS = {
        "fred_csv": {"start", "end"},
        "worldbank_indicator": {"countries", "dates"},
    }
    _STRIP_ARG_CHARS = "`'\""  # أسوار الكود وعلامات الاقتباس المحيطة

    def _parse_tool_lines(self, text: str) -> list[dict]:
        calls: list[dict] = []
        for raw_line in text.strip().splitlines():
            line = raw_line.strip().lstrip("-*•0123456789. ").strip()
            if not line or "|" not in line:
                continue
            name, _, arg = line.partition("|")
            name = name.strip()
            arg = arg.strip().strip(self._STRIP_ARG_CHARS)
            if not arg:
                raise ValueError(f"سطر أداة غير صالح: {raw_line[:80]}")
            if name in self._LINE_TOOLS:
                calls.append(
                    {"tool": name, "args": {self._LINE_TOOLS[name]: arg}}
                )
            elif name in self._KV_LINE_TOOLS:
                parts = arg.split()
                primary = parts[0]
                args = {self._KV_LINE_TOOLS[name]: primary}
                for token in parts[1:]:
                    if "=" not in token:
                        raise ValueError(
                            f"جزء بلا مفتاح=قيمة في سطر {name}: {token[:40]}"
                        )
                    key, _, val = token.partition("=")
                    if key not in self._KV_ALLOWED_KEYS[name]:
                        raise ValueError(
                            f"مفتاح غير مسموح {key} لأداة {name} "
                            f"(المسموح: {sorted(self._KV_ALLOWED_KEYS[name])})"
                        )
                    args[key] = val
                calls.append({"tool": name, "args": args})
            else:
                raise ValueError(f"سطر أداة غير صالح: {raw_line[:80]}")
        if not calls:
            raise ValueError("لا أسطر استدعاء صالحة في الرد")
        return calls

    def _plan_tool_calls(self, task_payload: dict) -> list[dict]:
        from sources import suggest_sources

        payload = {
            "phase": "plan_tools",
            "task": task_payload,
            "tools": [t for t in TOOLS_MANIFEST
                      if t["tool"] in self._LINE_TOOLS
                      or t["tool"] in self._KV_LINE_TOOLS],
            #: الأمر 003: مصادر رسمية مقترحة بأسطر استدعاء جاهزة —
            #: يختارها النموذج عند ملاءمتها للموضوع (لا فرض).
            "official_sources": suggest_sources(
                task_payload.get("description", ""), limit=8
            ),
        }
        messages = [
            ChatMessage(role="system", content=self._system_prompt),
            ChatMessage(
                role="user", content=json.dumps(payload, ensure_ascii=False)
            ),
        ]
        last_error: Exception | None = None
        for _attempt in (1, 2):
            text = self._live_call(messages)["text"]
            try:
                return self._parse_tool_lines(text)
            except ValueError as error:
                last_error = error
                messages = messages + [
                    ChatMessage(role="assistant", content=text[:1500]),
                    ChatMessage(
                        role="user",
                        content=(
                            f"صيغة غير صالحة ({error}) — أعد أسطر "
                            "الاستدعاء فقط بالصيغة: أداة | وسيطة"
                        ),
                    ),
                ]
        raise RoleSystemFault(
            self.ROLE, f"خطة الأدوات فشلت بعد إعادة واحدة: {last_error}"
        )

    # ------------------------------------------------------------------ #
    # 2) كتابة التقرير — نص Markdown خام (عقد محتوى لا JSON)
    # ------------------------------------------------------------------ #

    def _write_report(self, task_payload: dict, materials: dict) -> str:
        payload = {
            "phase": "write_report",
            "task": task_payload,
            "materials": materials,
        }
        messages = [
            ChatMessage(role="system", content=self._system_prompt),
            ChatMessage(
                role="user",
                content=json.dumps(payload, ensure_ascii=False)[:24000],
            ),
        ]
        text = self._live_call(messages)["text"]
        # تنظيف أسوار الكود إن أضافها النموذج رغم التعليمات
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip()).strip()
        if len(text) < 200:
            raise RoleSystemFault(
                self.ROLE, f"التقرير قصير بلا مبرر ({len(text)} حرفًا)"
            )
        return text

    # ------------------------------------------------------------------ #
    # (AES-LIVE-FACTORY-E2E-001 المرحلة 6) البناء — ملفات تسليم حقيقية
    # ------------------------------------------------------------------ #

    def _build_one_file(self, task_payload: dict, name: str,
                        done: list[str]) -> dict:
        """استدعاء LLM واحد لملف واحد — محتوى نص خام لا JSON.

        (المرحلة 6و) محتوى الكود داخل JSON أثبت فشله متكرراً (style.css:
        أقواس واقتباسات تكسر الترميز مرتين ثم فشل الدورة — مشروع 13)،
        ومسار التقارير الأصلي لا يعاني هذا لأن محتواه نص خام. هنا نفس
        العقد: الاسم من حلقة المنفذ حصراً، والرد نص الملف كاملاً بلا
        أسوار وبلا شرح — أول سطر هو أول الملف.
        """
        payload = {
            "phase": "write_one_file_raw",
            "file": name,
            "files_done": done,
            "task": task_payload,
            "note": "أعد محتوى هذا الملف وحده نصاً خاماً كاملاً: بلا "
                    "أسوار كود، بلا عنوان، بلا أي شرح قبله أو بعده. "
                    "الملفات السابقة مكتوبة فعلاً — لا تعدها.",
        }
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "أنت المنفذ البنّاء في نظام هندسي عربي ذاتي. مهمتك "
                    "كتابة ملف تسليم واحد كامل. ردك هو محتوى الملف "
                    "حرفياً — أول سطر من ردك هو أول سطر في الملف وآخر "
                    "سطر آخره. لا تكتب أسوار كود (```) ولا تعليقات "
                    "ميتا ولا أي نص خارج الملف. الملفات السابقة جاهزة "
                    "فعلاً — اكتب الملف المطلوب وحده متسقاً معها."
                ),
            ),
            ChatMessage(
                role="user",
                content=json.dumps(payload, ensure_ascii=False)[:24000],
            ),
        ]
        last_error: Exception | None = None
        for _attempt in (1, 2):
            text = self._live_call_streamed(messages)["text"]
            cleaned = re.sub(
                r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip()
            ).strip()
            if len(cleaned) < 50:
                last_error = ValueError(
                    f"المحتوى قصير بلا مبرر ({len(cleaned)} حرفاً)")
            elif cleaned.lstrip().startswith("{") and '"path"' in \
                    cleaned[:200]:
                last_error = ValueError(
                    "رد JSON — المطلوب محتوى خام لا JSON")
            else:
                return {"path": name, "content": cleaned}
            messages = messages + [
                ChatMessage(role="assistant", content=text[:1500]),
                ChatMessage(
                    role="user",
                    content=(
                        f"الرد خالف العقد ({last_error}) — أعد محتوى "
                        f"الملف {name} نصاً خاماً كاملاً فقط."
                    ),
                ),
            ]
        raise RoleSystemFault(
            self.ROLE, f"بناء {name} فشل بعد إعادة واحدة: {last_error}"
        )

    def _preview_entry(self, root) -> str:
        """رابط معاينة هذا المشروع مشتقاً من مساحة العمل الفعلية.

        مساحة الخطوة runtime/projects/{pid}/steps/{sid} — الرقم
        المؤكد حرفياً من المسار، لا اجتهاد نموذج.
        """
        try:
            parts = Path(root).resolve().parts
        except (TypeError, ValueError):
            return ""
        for i, part in enumerate(parts):
            if (part == "projects" and i + 1 < len(parts)
                    and parts[i + 1].isdigit()):
                return ("http://127.0.0.1:8011/api/projects/"
                        + parts[i + 1] + "/preview/index.html")
        return ""

    def _plan_verify_calls(self, task_payload: dict,
                           root: Path = None) -> list[dict]:
        """استدعاء واحد لخطة أدوات التحقق (متصفح غالباً) — JSON صارم.

        فشل التحليل = لا خطة تحقق (لا اصطناع فشل؛ الأدلة للملفات).
        رابط المعاينة يُشتق ميكانيكياً من مساحة العمل الفعلية ويُمرر
        للنموذج حرفياً — لا اختراع أرقام (مثبت حياً: مشروع 15 استخدم
        النموذج auto و{{project_id}} ففشلت كل التنقلات).
        """
        preview = self._preview_entry(root) if root is not None else ""
        payload = {
            "phase": "plan_verify",
            "task": task_payload,
            "preview_url": preview,
            "note": "خطط أدوات التحقق فقط. رابط المعاينة الحقيقي "
                    "للمشروع معطى في preview_url أعلاه — استخدمه حرفياً "
                    "كما هو في browser_navigate (لا تخترع رقماً ولا "
                    "مساراً نسبياً)، واشتق منه روابط الصفحات الأخرى "
                    "باستبدال index.html باسم الصفحة.",
        }
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "أنت مخطط تحقق في نظام هندسي عربي ذاتي. أعد JSON "
                    "واحدًا صالحًا حصرًا بالصيغة: "
                    '{"verify": [{"tool": "browser_navigate", '
                    '"args": {"url": "..."}}]} — أدوات القائمة البيضاء '
                    "فقط بترتيب منطقي. لا نص خارج JSON."
                ),
            ),
            ChatMessage(
                role="user",
                content=json.dumps(payload, ensure_ascii=False)[:20000],
            ),
        ]
        text = self._live_call_streamed(messages)["text"]
        try:
            data = json.loads(
                re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip())
            )
            verify = data.get("verify") or []
            if not isinstance(verify, list):
                raise ValueError("verify")
            return [
                {"tool": str(v.get("tool", "")),
                 "args": dict(v.get("args") or {})}
                for v in verify[:12] if v.get("tool")
            ]
        except (ValueError, TypeError):
            return []

    def _run_build_mode(self, request, task_payload: dict, ctx,
                        root: Path, build_names: list[str],
                        build_dirs: list[str] | None = None
                        ) -> "ImplementerResult":
        """نمط البناء (AES-LIVE-FACTORY-E2E-001 المرحلة 6).

        استدعاء واحد لكل ملف (قصير تحت عتبة نبضة الوظيفة) ← كتابة
        كل ملف عبر write_file في الركيزة (أحداث + نسخ فروق) ← استدعاء
        خطة تحقق واحد ← أدوات verify (متصفح غالباً) بأخطائها المعلنة
        لا إسقاطها ← أدلة بصمة لكل ملف ولقطة.
        """
        from roles.implementer import (
            ImplementerResult as _Result,
            ImplementerStatus as _Status,
        )

        artifacts: list[str] = []
        evidence_refs: list[str] = []
        try:
            done: list[str] = []
            # (RLR-001 §4d) المجلدات المصرّح بها أولاً — .keep في كل
            # مجلد عبر write_file (الركيزة تنشئ الأب تلقائياً) بأدلة
            # بصمة حقيقية لشرط «المجلدات موجودة».
            for dir_path in (build_dirs or []):
                self._stop_requested(ctx, "implementer.build_dir")
                keep = f"{dir_path}/.keep"
                run_tool(
                    "write_file",
                    {"path": keep, "content": ""},
                    ctx,
                )
                written = root / keep
                artifacts.append(str(written))
                evidence_refs.append(f"sha256:{_sha16(written)}:{keep}")
            for name in build_names:
                self._stop_requested(ctx, "implementer.build_file")
                item = self._build_one_file(task_payload, name, done)
                path = str(item["path"]).strip()
                run_tool(
                    "write_file",
                    {"path": path, "content": str(item["content"])},
                    ctx,
                )
                written = root / path
                artifacts.append(str(written))
                evidence_refs.append(f"sha256:{_sha16(written)}:{path}")
                done.append(path)

            # خطة التحقق (متصفح غالباً): استدعاء واحد قصير.
            self._stop_requested(ctx, "implementer.build_verify_plan")
            verify = self._plan_verify_calls(task_payload, root)

            # أدوات التحقق: كل واحدة توثق حدثها الدائم؛ الفاشلة تُسجل
            # رسالة في الأدلة ولا تخفي — الحكم النهائي للمحقق على
            # الملفات، ولقطات النجاح تُرفق كأدلة.
            verify_notes: list[str] = []
            for step in verify:
                self._stop_requested(ctx, "implementer.build_verify")
                tool = str(step.get("tool", "")).strip()
                args = dict(step.get("args") or {})
                if not tool:
                    continue
                try:
                    result = run_tool(tool, args, ctx)
                    shot = (result or {}).get("file") if isinstance(
                        result, dict) else None
                    if shot:
                        artifacts.append(str(shot))
                        evidence_refs.append(
                            f"shot:{_sha16(Path(shot))}:"
                            f"{Path(shot).name}")
                except (ToolFailure, ToolError) as failure:
                    verify_notes.append(
                        f"فشل {tool}: {str(failure)[:120]}")
                except Exception as error:  # noqa: BLE001 — يوثق لا يخفي
                    verify_notes.append(
                        f"فشل {tool}: {str(error)[:120]}")

            stdout = (
                f"بنيت {len(done)} ملفاً و{len(build_dirs or [])} مجلداً "
                f"(المصرّح بها: {', '.join(build_names)}"
                + (f"؛ مجلدات: {', '.join(build_dirs or [])}"
                   if build_dirs else "")
                + f") ونفذت {len(verify)} أداة تحقق"
            )
            if verify_notes:
                stdout += " — ملاحظات: " + "; ".join(verify_notes)[:200]
            return _Result(
                status=_Status.EXECUTED,
                artifacts=artifacts,
                stdout_truncated=stdout[:_TRUNCATE],
                evidence_refs=evidence_refs,
            )
        except RoleSystemFault as fault:
            return _Result(
                status=_Status.FAILED,
                stderr_truncated=str(fault)[:_TRUNCATE],
                artifacts=artifacts,
                evidence_refs=evidence_refs,
            )
        except CycleStopSignal:
            raise
        except Exception as error:  # noqa: BLE001 — فشل صريح موثق
            from router.model_router import ProviderCallError

            if isinstance(error, ProviderCallError) and \
                    getattr(error, "is_transient", False):
                # (RLR-001 §1) عطل مزود عابر — يُرفع مصنّفًا لا يتحول
                # إلى فشل منفذ زائف (الحكم للمحرك صاحب البوابة).
                raise
            return _Result(
                status=_Status.FAILED,
                stderr_truncated=f"المنفذ البنّاء فشل: {error}"[:_TRUNCATE],
                artifacts=artifacts,
                evidence_refs=evidence_refs,
            )

    # ------------------------------------------------------------------ #
    # التنفيذ الكامل
    # ------------------------------------------------------------------ #

    def run(self, request: ImplementerRequest) -> ImplementerResult:
        task_payload = {
            "id": request.task.id,
            "description": request.task.description,
            "acceptance_criteria": request.task.acceptance_criteria,
            "attempt": len(request.previous_attempts) + 1,
            # (المرحلة 6ز) هدف الخطوة الكامل — مصدر الحقيقة للتسليم
            "context_goal": request.context_goal or "",
        }
        root = (
            Path(request.sandbox_root)
            if request.sandbox_root
            else Path(tempfile.mkdtemp(prefix="v2-live-"))
        )
        root.mkdir(parents=True, exist_ok=True)
        ctx = self._ctx or ToolContext(grant_root=root)
        ctx.grant_root = root

        try:
            # (AES-LIVE-FACTORY-E2E-001 المرحلة 6) نمط البناء: مهمة تصرّح
            # بملفات تسليم (html/css/js/…) تُنفَّذ بملفات حقيقية عبر
            # write_file في الركيزة — الأدلة بصمة لكل ملف + لقطات
            # المتصفح من verify كأدلة مرفقة. مسار التقارير الأصلي
            # (لا ملفات صريحة) لا يمس هذا الفرع إطلاقًا.
            build_names = _deliverable_names(task_payload)
            build_dirs = _declared_dirs(task_payload)
            if build_names or build_dirs or \
                    _mentions_browser_verification(task_payload):
                return self._run_build_mode(
                    request, task_payload, ctx, root, build_names,
                    build_dirs=build_dirs,
                )

            # (1) خطة الأدوات ← تنفيذها بتعافٍ مصنَّف (إضافة 008 §8-§12):
            # لا إعادة عمياء — فشل عابر يعاد، ولا مادة يعاد باستراتيجية
            # مختلفة (استعلام مراجَع أو أداة بديلة مسجلة)، والمصادقة/
            # السياسة لا تعاد. كل قرار يبث حدثًا حيًا ويسجل في الأدلة.
            self._stop_requested(ctx, "implementer.plan_tools")
            calls = self._plan_tool_calls(task_payload)
            materials: dict[str, list] = {
                "search_results": [], "pages": [], "data": [],
            }
            attempt = len(request.previous_attempts) + 1
            attempted_queries: list[str] = []
            failed_calls: list[dict] = []
            available_urls: list[str] = [
                str(a.get("url", "")) for a in calls if a.get("args", {}).get("url")
            ]

            for call in calls[:8]:  # سقف صلب فوق تعليمات البرومبت
                self._stop_requested(ctx, "implementer.tool_loop")
                run_with_recovery(
                    ctx,
                    str(call.get("tool", "")),
                    dict(call.get("args", {}) or {}),
                    attempt=attempt,
                    attempted_queries=attempted_queries,
                    available_urls=available_urls,
                    materials=materials,
                    failed_calls=failed_calls,
                    max_results=MAX_SEARCH_RESULTS,
                )
            if (
                not materials["search_results"]
                and not materials["pages"]
                and not materials["data"]
            ):
                # فشل مادة مصنَّف (§18): TOOL_FAILURE/tool/queries/attempts
                # — لا «كل استدعاءات الأدوات فشلت» الغامضة.
                primary = failed_calls[0] if failed_calls else {}
                return ImplementerResult(
                    status=ImplementerStatus.FAILED,
                    stderr_truncated=(
                        "لا مادة قابلة للتحليل وصلت المنفذ — "
                        + (primary.get("message") or "بلا فشل أداة مسجل")
                        + f" ({len(failed_calls)} فشل مصنَّف)"
                    )[:_TRUNCATE],
                    failure={
                        "class": "TOOL_FAILURE",
                        "stage": primary.get("stage", "TOOL_RESULT"),
                        "tool": primary.get("tool", ""),
                        "reason": primary.get(
                            "reason", "NO_ANALYZABLE_MATERIAL"
                        ),
                        "retryable": primary.get("retryable", True),
                        "attempt": attempt,
                        "max_attempts": 2,
                        "queries": attempted_queries[:6],
                        "failures": failed_calls[:6],
                        "artifacts": 0,
                    },
                )

            # (2) التقرير من المادة المجلوبة
            self._stop_requested(ctx, "implementer.write_report")
            report_md = self._write_report(task_payload, materials)

            # (3) الكتابة والـPDF — كلها عبر الأدوات (ركيزة + توثيق)
            artifacts: list[str] = []
            evidence_refs: list[str] = []
            md_name = f"{request.task.id}-report.md"
            run_tool("write_file", {"path": md_name, "content": report_md}, ctx)
            md_path = root / md_name
            artifacts.append(str(md_path))
            evidence_refs.append(f"sha256:{_sha16(md_path)}:{md_name}")

            wants_pdf = (
                any(
                    _PDF_HINT.search(criterion)
                    for criterion in request.task.acceptance_criteria
                )
                or bool(ctx.search_results)  # مهمة مصادر ⇒ تقرير PDF مطلوب
            )
            if wants_pdf:
                pdf_name = f"{request.task.id}-report.pdf"
                run_tool(
                    "generate_pdf_arabic",
                    {"md_path": md_name, "out_path": pdf_name},
                    ctx,
                )
                pdf_path = root / pdf_name
                artifacts.append(str(pdf_path))
                evidence_refs.append(f"sha256:{_sha16(pdf_path)}:{pdf_name}")
                pages = run_tool("verify_pdf_pages", {"path": pdf_name}, ctx)
                if pages > 1:
                    # §4.3: أي PDF > 1 صفحة = فشل المهمة بصراحة
                    return ImplementerResult(
                        status=ImplementerStatus.FAILED,
                        stderr_truncated=(
                            f"الـPDF تجاوز صفحة واحدة (pages={pages}) — "
                            "فشل صريح بلا ترقيع"
                        )[:_TRUNCATE],
                        artifacts=artifacts,
                        evidence_refs=evidence_refs,
                    )
                evidence_refs.append(f"pdf_pages:{pages}:{pdf_name}")

            # (4) ملف المصادر — المصادر الفعلية المذكورة في قسم
            # «## المصادر» بالتقرير (اختيار النموذج الموثق)؛ وعند نقصها
            # تُستكمل من نتائج البحث الفريدة — الدليل يطابق التقرير.
            report_urls = re.findall(
                r"https?://[^\s\)\]]+", _sources_section(report_md)
            )
            title_by_url = {
                item.get("url", ""): item.get("title", "")
                for item in ctx.search_results
            }

            def _title_of(url: str) -> str:
                """عنوان المصدر: من نتائج البحث إن طابق، وإلا نص سطره."""
                if url in title_by_url and title_by_url[url]:
                    return title_by_url[url]
                for line in _sources_section(report_md).splitlines():
                    if url in line:
                        head = line.split(url)[0]
                        head = head.lstrip("-*• ").strip(" \u2014-:|")
                        return head.strip()[:120]
                return ""

            seen: set[str] = set()
            sources: list[dict] = []
            for url in report_urls:
                clean = url.rstrip(".,;")
                if clean not in seen:
                    seen.add(clean)
                    sources.append(
                        {"title": _title_of(clean), "url": clean}
                    )
            if len(sources) < 5:
                for item in [*ctx.search_results, *ctx.data_urls]:
                    url = item.get("url", "")
                    if url and url not in seen:
                        seen.add(url)
                        sources.append(
                            {"title": item.get("title", ""), "url": url}
                        )
                    if len(sources) >= 8:
                        break
            if sources:
                run_tool(
                    "write_file",
                    {
                        "path": "sources.json",
                        "content": json.dumps(
                            sources, ensure_ascii=False, indent=1
                        ),
                    },
                    ctx,
                )
                src_path = root / "sources.json"
                artifacts.append(str(src_path))
                evidence_refs.append(f"sha256:{_sha16(src_path)}:sources.json")

            return ImplementerResult(
                status=ImplementerStatus.EXECUTED,
                artifacts=artifacts,
                stdout_truncated=(
                    f"نفّذت {len(calls)} استدعاء أداة وأنتجت "
                    f"{len(artifacts)} ملفًا"
                )[:_TRUNCATE],
                evidence_refs=evidence_refs,
            )
        except RoleSystemFault as fault:
            return ImplementerResult(
                status=ImplementerStatus.FAILED,
                stderr_truncated=str(fault)[:_TRUNCATE],
            )
        except CycleStopSignal:
            raise  # الأمر 004: إشارة إيقاف — تُكرّم عند المنسق لا تُبتلع
        except Exception as error:  # noqa: BLE001 — فشل صريح موثق
            from router.model_router import ProviderCallError

            if isinstance(error, ProviderCallError) and \
                    getattr(error, "is_transient", False):
                # (RLR-001 §1) عطل مزود عابر — يُرفع مصنّفًا لا يبتلع.
                raise
            return ImplementerResult(
                status=ImplementerStatus.FAILED,
                stderr_truncated=f"المنفذ الحي فشل: {error}"[:_TRUNCATE],
            )
