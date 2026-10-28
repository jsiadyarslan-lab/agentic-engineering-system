"""المنفذ الحي (الأمر السادس §2+§3+§4 + W2-T23) — LLM يقود أدوات القائمة البيضاء.

مسار المهمة الواحدة (ثلاثة استدعاءات حية — ميزانية منضبطة):
1. chat_live الأول: خطة استدعاءات أدوات JSON (web_search/fetch_page).
2. تنفيذ كل استدعاء عبر roles.tools.run_tool (قائمة بيضاء + sha256
   + أحداث فورية) — أي أداة خارج البيضاء = فشل خطوة صريح.
3. (W2-T23) create_files عند وجود ملفات مطلوبة في معايير القبول:
   نداء حي يكتب ملفات المشروع بصيغة ### FILE: (المنطق في
   roles/build_files.py — عقد الرقة) ثم كتابتها عبر write_file داخل
   الركيزة بأدلة sha256 لكل ملف. مهام البحث/التقرير لا تمر هنا إطلاقًا.
4. chat_live الأخير: كتابة التقرير العربي Markdown من المادة المجلوبة
   (وإن وُجدت ملفات منشأة وُثّقها التقرير) — قيد الصفحة الواحدة.
5. write_file للتقرير ثم generate_pdf_arabic وverify_pdf_pages
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
from roles import build_commands, build_files
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
    # (2.5) إنشاء ملفات المشروع (W2-T23) في roles/build_files.py —
    # الاستدعاء الحي والتحليل والفحوص الأمنية هناك؛ الدور هنا نحيل.
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
            # (2.5) إنشاء ملفات المشروع (W2-T23) — قبل التقرير ليشمله:
            # مهمة البناء تُعرف من معاييرها (ملفات مطلوبة غير مخرجات الدور)،
            # والمنطق كله في roles/build_files.py (عقد الرقة 430 سطرًا).
            required_build = build_files.required_build_files(
                request.task.acceptance_criteria, request.task.id,
            )
            created_files: list[tuple[str, str]] = []
            if required_build:
                self._stop_requested(ctx, "implementer.create_files")
                created_files = build_files.create_files_phase(
                    live_call=self._live_call,
                    system_prompt=self._system_prompt,
                    task_payload=task_payload,
                    materials=materials,
                    required_files=required_build,
                    previous_attempts=list(request.previous_attempts or []),
                    role=self.ROLE,
                )
            # (2.7) أوامر البناء الحقيقية (W2-T24) — npm install/build
            # تُنفَّذ فعليًا بأدلة exit_code؛ وفقد node/npm فشل صادق
            # يغذي تصنيف المحرك (BUILD_TOOLING_MISSING → حاجز توفير).
            commands = build_commands.required_build_commands(
                request.task.acceptance_criteria,
            )
            build_outcome = None
            if commands:
                self._stop_requested(ctx, "implementer.build_commands")
                build_outcome = build_commands.run_build_commands_phase(
                    ctx, root, commands,
                    request.task.acceptance_criteria,
                )
                if build_outcome.failed_result is not None:
                    return build_outcome.failed_result
            if (
                not materials["search_results"]
                and not materials["pages"]
                and not materials["data"]
                and not created_files
                and not (build_outcome and build_outcome.results)
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

            # (2) التقرير من المادة المجلوبة — وملفات البناء المنشأة
            # تُمرّر معه (W2-T23) ليوثّق التقرير ما بُني لا ما وُصف فقط.
            self._stop_requested(ctx, "implementer.write_report")
            report_materials = build_files.materials_with_created(
                materials, created_files,
            )
            if build_outcome and build_outcome.results:
                report_materials["build_commands"] = build_outcome.results
            report_md = self._write_report(task_payload, report_materials)

            # (3) الكتابة والـPDF — كلها عبر الأدوات (ركيزة + توثيق)
            artifacts: list[str] = []
            evidence_refs: list[str] = []
            # (3.5) ملفات البناء أولًا (W2-T23) — عبر write_file داخل
            # الركيزة بأدلة sha256 لكل ملف؛ المعايير هي العقد.
            for build_path, build_body in created_files:
                run_tool(
                    "write_file",
                    {"path": build_path, "content": build_body},
                    ctx,
                )
                built = root / build_path
                artifacts.append(str(built))
                evidence_refs.append(
                    f"sha256:{_sha16(built)}:{build_path}"
                )
            for build_artifact in (
                    build_outcome.artifacts if build_outcome else []):
                artifacts.append(str(build_artifact))
                evidence_refs.append(
                    f"sha256:{_sha16(build_artifact)}:"
                    f"{Path(build_artifact).name}"
                )
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

            # (4) ملف المصادر — التجميع والكتابة في roles/build_files.py
            # (W2-T23: استخراج لعقد الرقة 430 سطرًا)؛ الدليل يطابق التقرير.
            src_path = build_files.write_sources_file(ctx, root, report_md)
            if src_path is not None:
                artifacts.append(str(src_path))
                evidence_refs.append(f"sha256:{_sha16(src_path)}:sources.json")

            return ImplementerResult(
                status=ImplementerStatus.EXECUTED,
                artifacts=artifacts,
                stdout_truncated=(
                    f"نفّذت {len(calls)} استدعاء أداة"
                    + (
                        f" وأنشأت {len(created_files)} ملف بناء"
                        if created_files else ""
                    )
                    + (
                        f" و{build_outcome.summary}"
                        if build_outcome and build_outcome.summary else ""
                    )
                    + f" وأنتجت {len(artifacts)} ملفًا"
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
