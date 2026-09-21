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
from roles.tools import (
    DATA_TOOLS,
    MAX_SEARCH_RESULTS,
    TOOLS_MANIFEST,
    ToolContext,
    ToolError,
    run_tool,
)
from router.model_router import ChatMessage

_TRUNCATE = 400
_PDF_HINT = re.compile(r"\.pdf\b", re.IGNORECASE)


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

    def __init__(self, router, tools_ctx: ToolContext | None = None):
        super().__init__(router)
        self._ctx = tools_ctx

    def _stop_requested(self, ctx: ToolContext, at_step: str) -> None:
        """نقطة تفتيش إيقاف (الأمر 004) — إشارة تُرفع ولا تُبتلع هنا."""
        check = getattr(ctx, "stop_check", None)
        if check is not None and check():
            raise CycleStopSignal(at_step)

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
            text = self._router.chat_live(messages)["text"]
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
        text = self._router.chat_live(messages)["text"]
        # تنظيف أسوار الكود إن أضافها النموذج رغم التعليمات
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip()).strip()
        if len(text) < 200:
            raise RoleSystemFault(
                self.ROLE, f"التقرير قصير بلا مبرر ({len(text)} حرفًا)"
            )
        return text

    # ------------------------------------------------------------------ #
    # التنفيذ الكامل
    # ------------------------------------------------------------------ #

    def run(self, request: ImplementerRequest) -> ImplementerResult:
        task_payload = {
            "id": request.task.id,
            "description": request.task.description,
            "acceptance_criteria": request.task.acceptance_criteria,
            "attempt": len(request.previous_attempts) + 1,
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
            # (1) خطة الأدوات ← تنفيذها (كل استدعاء موثق داخل run_tool).
            # فشل أداة بيضاء (رابط يحجب الروبوتات مثلًا) يُسجّل حدثًا
            # ويُتجاوز — المادة تُجمع مما نجح؛ الفشل الكامل فقط عند
            # انعدام أي مادة (لا ترقيع: الإخفاق موثق في الأدلة).
            self._stop_requested(ctx, "implementer.plan_tools")
            calls = self._plan_tool_calls(task_payload)
            materials: dict[str, list] = {
                "search_results": [], "pages": [], "data": [],
            }
            failed_calls: list[str] = []
            for call in calls[:8]:  # سقف صلب فوق تعليمات البرومبت
                self._stop_requested(ctx, "implementer.tool_loop")
                name = str(call.get("tool", ""))
                args = dict(call.get("args", {}) or {})
                try:
                    value = run_tool(name, args, ctx)
                except ToolError as error:
                    failed_calls.append(f"{name}: {error}")
                    ctx.emit({
                        "kind": "tool.failed",
                        "role": "implementer",
                        "tool": name,
                        "error": str(error)[:200],
                    })
                    continue
                if name == "web_search":
                    materials["search_results"].extend(
                        value[:MAX_SEARCH_RESULTS]
                    )
                elif name == "fetch_page":
                    materials["pages"].append(
                        {"chars": len(value), "text": value[:6000]}
                    )
                elif name in DATA_TOOLS:
                    # الأمر 003: ملخص محدود من مادة البيانات للتقرير —
                    # الخام الكامل في data/ داخل الأدلة، لا في البرومبت.
                    materials["data"].append({
                        key: value.get(key)
                        for key in ("tool", "series_id", "indicator", "url",
                                    "rows", "count", "chars", "words",
                                    "structure", "sample_rows", "first_300_words")
                        if key in value
                    })
            if (
                not materials["search_results"]
                and not materials["pages"]
                and not materials["data"]
            ):
                return ImplementerResult(
                    status=ImplementerStatus.FAILED,
                    stderr_truncated=(
                        "كل استدعاءات الأدوات فشلت — لا مادة: "
                        + "؛ ".join(failed_calls[:3])
                    )[:_TRUNCATE],
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
            return ImplementerResult(
                status=ImplementerStatus.FAILED,
                stderr_truncated=f"المنفذ الحي فشل: {error}"[:_TRUNCATE],
            )
