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
    CodeMissionFiles,
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

#: (013.16 §2) بصمة المهمة البرمجية — وصف المهمة أو معايير قبولها
#: يذكر ملف Python أو بيانات CSV برمجية. كشف حتمي معلن: إن لم يطبع
#: فالمسار التقريري الافتراضي هو الصحيح؛ وإن طبع خطأً فالمدقق يرفض
#: بصراحة ودورة إعادة التخطيط تصحح — لا تخمين خفي.
_CODE_MISSION_HINT = re.compile(
    r"\.py\b|transactions\.csv|python|بايثون", re.IGNORECASE
)


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

    # ------------------------------------------------------------------ #
    # 0) المهمة البرمجية (013.16 §2) — كتابة ← تشغيل ← اختبار
    # ------------------------------------------------------------------ #

    @classmethod
    def _is_code_mission(cls, request: ImplementerRequest) -> bool:
        """كشف حتمي معلن: المهمة برمجية إن ذكر وصفها/معاييرها كودًا."""
        text = " ".join(
            [request.task.description, *request.task.acceptance_criteria]
        )
        return bool(_CODE_MISSION_HINT.search(text))

    def _run_code_mission(
        self,
        task_payload: dict,
        ctx: ToolContext,
        root: Path,
        previous_attempts: list[str],
    ) -> ImplementerResult:
        """مسار المهمة البرمجية — ثلاث مراحل كلها عبر الأدوات الموثقة.

        1. النموذج يكتب الملفات (أداة/بيانات/اختبارات) بعقد صارم.
        2. write_file لكل ملف داخل الركيزة (سجل sha256 لكل كتابة).
        3. run_python للأداة ثم للاختبارات — المخرجات الفعلية وحدها
           تحدد النتيجة: فشل التشغيل أو فشل الاختبارات = فشل تنفيذي
           مفصل يصل المحكّم؛ لا نص نموذج يُدّعى مخرجًا أبدًا.
        """
        self._stop_requested(ctx, "implementer.plan_code")
        payload = dict(task_payload)
        payload["previous_attempts"] = list(previous_attempts[-3:])
        spec = self._validated_completion(
            payload, CodeMissionFiles,
            system_prompt=load_prompt("implementer_code"),
        )

        written: list[str] = []
        for spec_file in spec.files[:12]:
            self._stop_requested(ctx, "implementer.write_code")
            run_tool(
                "write_file",
                {"path": spec_file.path, "content": spec_file.content},
                ctx,
            )
            written.append(spec_file.path)

        self._stop_requested(ctx, "implementer.run_code")
        run_out = run_tool("run_python", {"path": spec.entrypoint}, ctx)
        self._stop_requested(ctx, "implementer.run_tests")
        tests_out = run_tool(
            "run_python", {"path": spec.tests_entrypoint}, ctx,
        )

        # الأدلة: كل ملف فعلي في مجلد المهمة (مكتوب أو منتج) ببصمة
        artifacts: list[str] = []
        evidence_refs: list[str] = []
        for produced in sorted(p for p in root.iterdir()
                               if p.is_file() and p.name != "sources.json"):
            artifacts.append(str(produced))
            evidence_refs.append(
                f"sha256:{_sha16(produced)}:{produced.name}"
            )
        evidence_refs.append(
            f"run:exit={run_out['exit_code']}:{spec.entrypoint}"
        )
        evidence_refs.append(
            f"run:exit={tests_out['exit_code']}:{spec.tests_entrypoint}"
        )
        evidence_refs.append(
            "run:stdout:" + run_out["stdout"][:300].replace("\n", " ⏎ ")
        )
        evidence_refs.append(
            "tests:stdout:" + tests_out["stdout"][:300].replace("\n", " ⏎ ")
        )

        tool_ok = run_out["exit_code"] == 0
        tests_ok = tests_out["exit_code"] == 0
        if not (tool_ok and tests_ok):
            failed_run = run_out if not tool_ok else tests_out
            failed_path = (
                spec.entrypoint if not tool_ok else spec.tests_entrypoint
            )
            return ImplementerResult(
                status=ImplementerStatus.FAILED,
                artifacts=artifacts,
                evidence_refs=evidence_refs,
                stderr_truncated=(
                    f"تنفيذ برمجي فشل: {failed_path} خرج "
                    f"{failed_run['exit_code']} — "
                    + failed_run["stderr"][:200]
                )[:_TRUNCATE],
                failure={
                    "class": "CODE_RUN_FAILURE",
                    "stage": "TOOL_RESULT",
                    "tool": "run_python",
                    "reason": (
                        "ENTRYPOINT_NONZERO" if not tool_ok
                        else "TESTS_NONZERO"
                    ),
                    "retryable": True,
                    "entrypoint": spec.entrypoint,
                    "tests_entrypoint": spec.tests_entrypoint,
                    "entry_exit": run_out["exit_code"],
                    "tests_exit": tests_out["exit_code"],
                    "stderr_head": failed_run["stderr"][:200],
                    "files_written": written,
                },
            )
        return ImplementerResult(
            status=ImplementerStatus.EXECUTED,
            artifacts=artifacts,
            stdout_truncated=(
                f"كُتب {len(written)} ملفًا ونُفّذت داخل الركيزة: "
                f"الأداة خرجت {run_out['exit_code']} والاختبارات "
                f"خرجت {tests_out['exit_code']}"
            )[:_TRUNCATE],
            evidence_refs=evidence_refs,
        )

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
            # (013.16 §2) المهمة البرمجية: النموذج يكتب الأداة وبياناتها
            # واختباراتها، ثم تُنفّذ فعليًا داخل الركيزة (write_file ←
            # run_python ×2) — المخرج من البرنامج لا من النموذج.
            if self._is_code_mission(request):
                return self._run_code_mission(
                    task_payload, ctx, root, request.previous_attempts,
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
            return ImplementerResult(
                status=ImplementerStatus.FAILED,
                stderr_truncated=f"المنفذ الحي فشل: {error}"[:_TRUNCATE],
            )
