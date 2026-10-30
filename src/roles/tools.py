"""أدوات المنفذ المضمّنة (الأمر السادس §3+§4) — قائمة بيضاء مغلقة.

القاعدة: القائمة البيضاء أدوات معروفة حصرًا؛ أي استدعاء أداة أخرى
= فشل خطوة صريح (ToolError) لا تجاهل.

الأمر 008 (إضافة تشخيص فشل الأدوات): كل استدعاء يمر بتصنيف صادق —
- tool.started يبث قبل التنفيذ (الواجهة الحية §12)؛
- النجاح يميّز transport_status عن result_status (§5: HTTP 200 ليست
  نجاح أداة)؛
- الفشل ToolFailure مصنَّف (class/stage/reason/retryable §1+§17) —
  «لا نتائج» غير «نتائج غير قابلة للتحليل» غير «خطأ مزود» (§3)؛
- سجل استدعاء دائم لكل محاولة (ToolCallRecord §2) يصل الأدلة
  والمحكَّم والواجهة.

مواقع التنفيذ (مبدأ v2: معزول أو معلن):
- أدوات الملفات وPDF: داخل الركيزة المعزولة (namespaces+seccomp).
- أدوات الويب والبيانات: في العملية مع إعلان صريح (execution_site).
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid as _uuid
from pathlib import Path
from typing import Any

from roles.pdf_tools import build_pdf_code
from roles.tool_manifest import TOOLS_MANIFEST  # noqa: F401 — إعادة تصدير
from roles.tool_failures import (
    ToolCallRecord,
    ToolError,
    ToolFailure,
    classify_sandbox_failure,
)
from roles.web_tools import (
    MAX_PAGE_BYTES,  # noqa: F401 — إعادة تصدير العقد القديم
    MAX_SEARCH_RESULTS,  # noqa: F401
    FETCH_TIMEOUT,  # noqa: F401
    _USER_AGENT,  # noqa: F401 — data_tools يستورده من هنا
    fetch_page,
    web_search,
)

#: القائمة البيضاء (§3.2): 4 أساس + أداتا PDF + أدوات البيانات الخمس
#: + أدوات المتصفح السبع (013 §13) — متصفح حي بأنشطة مسجلة.
#: (W2-T24) run_build_command: أوامر بناء حقيقية (npm...) — تنفيذ
#: في العملية معلن (تحتاج شبكة+HOME كأدوات الويب) بأدلة exit_code.
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
    "run_build_command",
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_extract",
    "browser_screenshot",
    "browser_download",
    "browser_wait",
)

#: أدوات المتصفح (013 §13) — تنفيذ معلن داخل عملية المتصفح دائمًا.
BROWSER_TOOLS: frozenset[str] = frozenset({
    "browser_navigate", "browser_click", "browser_type",
    "browser_extract", "browser_screenshot", "browser_download",
    "browser_wait",
})

#: أدوات البيانات الخمس (الأمر 003) — تنفيذ معلن خارج الركيزة دائمًا.
DATA_TOOLS: frozenset[str] = frozenset({
    "http_get_text", "http_get_json", "page_to_text",
    "fred_csv", "worldbank_indicator",
})

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
PDF_FONT_PATH = ASSETS_DIR / "fonts" / "IBMPlexSansArabic-Regular.ttf"


class ToolContext:
    """سياق تنفيذ الأدوات — المجلد الممنوح + مستقبِل الأحداث + السجلات."""

    grant_root: Path
    on_event = None
    search_results: list
    fetched_urls: list
    data_urls: list
    stop_check = None
    #: سجلات الاستدعاء الدائمة (إضافة 008 §2) — تصب في evidence.json
    #: وفي جدول tool_invocations عبر tasks.run_task.
    tool_records: list[ToolCallRecord]
    #: (013.1 §13) سياسة تنفيذ المشروع — STRICT_ISOLATED تجعل أدوات
    #: الملفات/العملية تمر بالبيئة الموافقة حصرًا؛ غيابها = حجب
    #: معلن (POLICY_BLOCK) لا تنفيذ غير معزول بدلًا عنها.
    execution_policy = None

    def __init__(self, grant_root: Path, on_event=None, search_results=None,
                 fetched_urls=None, data_urls=None, stop_check=None,
                 tool_records=None, sessions=None, execution_policy=None):
        self.grant_root = grant_root
        self.on_event = on_event
        self.search_results = search_results if search_results is not None else []
        self.fetched_urls = fetched_urls if fetched_urls is not None else []
        self.data_urls = data_urls if data_urls is not None else []
        self.stop_check = stop_check
        self.tool_records = tool_records if tool_records is not None else []
        # (الأمر 010 §19) جلسة القاعدة للتنفيذ الموحد عبر بيئة التنفيذ
        # المختارة — المسبار والمنفذ من resolve_executor() نفسه.
        self.sessions = sessions
        self.execution_policy = execution_policy

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
        raise ToolFailure(
            "filesystem", f"المسار خارج المجلد الممنوح: {relative}",
            failure_class="POLICY_BLOCK", reason="PATH_OUTSIDE_GRANT",
            stage="TOOL_START", retryable=False,
        )
    return candidate


# ------------------------------------------------------------------ #
# أدوات الملفات — داخل الركيزة المعزولة (لا شبكة)
# ------------------------------------------------------------------ #

def _run_in_substrate(ctx: ToolContext, code: str, workspace: Path,
                      artifacts: Path) -> tuple[int, str, str]:
    """تنفيذ كود عبر بيئة التنفيذ الموحدة (006 §11 + 010 §19 + 013.1 §13).

    المصدر الوحيد: execution.service.run_code_unified — نفس الخلفية
    التي يمر بها مسبار sandbox، فلا «مسبار READY ومنفذ UNAVAILABLE»
    بلا تفسير. سياسة المشروع (ctx.execution_policy) تجعل الاختيار
    موافقًا لها حصرًا: STRICT بلا بيئة معزولة = POLICY_BLOCK صادق
    لا تنفيذ غير معزول بدلًا عنها. فشل البدء يظهر بسببه الكامل.
    """
    from execution.service import run_code_unified

    outcome = run_code_unified(
        getattr(ctx, "sessions", None), code,
        workspace=workspace, artifacts=artifacts,
        policy=getattr(ctx, "execution_policy", None),
    )
    if outcome.termination == "POLICY_BLOCK":
        # (013.1 §13) حجب سياسة صريح — غير قابل لإعادة المحاولة
        # داخل نفس الخطوة؛ رفعه يتم بتوفير بيئة موافقة ثم إعادة فحص.
        raise ToolFailure(
            "execution", outcome.detail,
            failure_class="POLICY_BLOCK", reason="NO_POLICY_ENVIRONMENT",
            stage="TOOL_START", retryable=False,
            details={"policy": getattr(ctx, "execution_policy", None)},
        )
    stderr = outcome.stderr
    if outcome.termination != "COMPLETED":
        stderr = f"{outcome.termination}: {outcome.detail}"
    return outcome.exit_code, outcome.stdout, stderr


def _substrate_failure(tool: str, path: str, stderr: str) -> ToolFailure:
    """فشل داخل الركيزة → تصنيف صادق (SANDBOX/DEPENDENCY §16+§23)."""
    classified = classify_sandbox_failure(tool, stderr)
    if classified is not None:
        return classified
    return ToolFailure(
        tool,
        f"فشل {tool} ({path}) داخل الركيزة: {stderr[:200]}",
        failure_class="DEPENDENCY_FAILURE", reason="OUTPUT_UNPARSEABLE",
        stage="TOOL_EXECUTION", retryable=True,
        details={"path": path[:120], "stderr_head": stderr[:200]},
    )


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
        raise _substrate_failure("write_file", path, stderr)
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
        raise _substrate_failure("read_file", path, stderr)
    try:
        return json.loads(stdout.strip().splitlines()[-1])["head"]
    except (ValueError, KeyError, IndexError) as error:
        raise ToolFailure(
            "read_file", f"مخرج قراءة غير مفهوم لـ {path}: {error}",
            failure_class="VALIDATION_FAILURE", reason="OUTPUT_UNPARSEABLE",
            stage="TOOL_RESULT", retryable=True,
        ) from error


def substrate_font_ref(font_name: str) -> str:
    """مسار الخط داخل الركيزة (W2-T25) — WORK_MOUNT هو ربط مساحة
    العمل الحقيقي (/work قراءةً) لا /ws الاتفاقية القديمة الميتة
    (قياس 460: bwrap قبل التنفيذ فانكشف المسار الزور وTTFError
    فشل دورة كاملة كانت تُغطّى سابقًا برفض الركيزة والاحتياطي)."""
    from substrate.local_substrate import WORK_MOUNT

    return f"{WORK_MOUNT}/_fonts/{font_name}"


def generate_pdf_arabic(ctx: ToolContext, md_path: str, out_path: str) -> str:
    """توليد PDF عربي RTL A4 — داخل الركيزة؛ وعند رفض الاستيراد تنفيذ
    معلن في العملية (execution_site في الحدث والدليل)."""
    _bounded_path(ctx.grant_root, md_path)
    target = _bounded_path(ctx.grant_root, out_path)
    if not PDF_FONT_PATH.is_file():
        raise ToolFailure(
            "generate_pdf_arabic", f"خط IBM Plex Arabic مفقود: {PDF_FONT_PATH}",
            failure_class="DEPENDENCY_FAILURE", reason="NO_EXECUTION_IMAGE",
            stage="TOOL_START", retryable=False,
        )
    workspace = ctx.grant_root / "_ws"
    fonts_dir = workspace / "_fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    font_copy = fonts_dir / PDF_FONT_PATH.name
    if not font_copy.is_file():
        font_copy.write_bytes(PDF_FONT_PATH.read_bytes())
    code = build_pdf_code(
        md_path, out_path, substrate_font_ref(PDF_FONT_PATH.name))
    exit_code, _out, stderr = _run_in_substrate(ctx, code, workspace, ctx.grant_root)
    site = "substrate"
    if exit_code != 0:
        # إعلان صريح: الركيزة رفضت (استيراد مكتبة مثلًا) — تنفيذ في
        # العملية بنفس الكود بجذر مؤقت ثم نسخ الناتج إلى المنحة.
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
                 build_pdf_code(md_path, out_path, str(PDF_FONT_PATH),
                                root_expr="pathlib.Path('.')")],
                capture_output=True, text=True, timeout=120,
                cwd=str(fake_root),
            )
            if proc.returncode == 0 and (fake_root / out_path).is_file():
                target.write_bytes((fake_root / out_path).read_bytes())
        if not target.is_file():
            raise ToolFailure(
                "generate_pdf_arabic",
                "فشل توليد PDF (الركيزة: "
                f"{stderr[-150:]} / العملية: {proc.stderr[-150:]})",
                failure_class="DEPENDENCY_FAILURE", reason="OUTPUT_UNPARSEABLE",
                stage="TOOL_EXECUTION", retryable=True,
            )
        site = "in_process_declared"
    if not target.is_file():
        raise ToolFailure(
            "generate_pdf_arabic", f"PDF لم يُكتب إلى {out_path}",
            failure_class="TOOL_FAILURE", reason="OUTPUT_UNPARSEABLE",
            stage="TOOL_RESULT", retryable=False,
        )
    return str(target) + f"#{site}"


# ------------------------------------------------------------------ #
# أوامر البناء الحقيقية (W2-T24) — التنفيذ في roles/build_tool.py
# (أمر 008: توزيع الأنحاف — مثل web_tools/pdf_tools)؛ هنا الاستيراد
# والعقد فقط: الأداة بيضاء، معلنة in_process (شبكة+HOME كأدوات الويب).
# ------------------------------------------------------------------ #

from roles.build_tool import (  # noqa: F401 — إعادة تصدير العقد
    BUILD_COMMAND_WHITELIST,
    resolve_build_tool,
    run_build_command,
)

def verify_pdf_pages(ctx: ToolContext, path: str) -> int:
    """عدّ صفحات PDF عبر pypdf — داخل الركيزة أو معلنًا في العملية."""
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
            raise ToolFailure(
                "verify_pdf_pages",
                f"فشل عدّ صفحات {path}: {stderr[:200]} / {error}",
                failure_class="DEPENDENCY_FAILURE", reason="OUTPUT_UNPARSEABLE",
                stage="TOOL_EXECUTION", retryable=True,
            ) from error
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
        raise ToolFailure(
            "verify_pdf_pages", f"مخرج عدّ صفحات غير مفهوم: {error}",
            failure_class="VALIDATION_FAILURE", reason="OUTPUT_UNPARSEABLE",
            stage="TOOL_RESULT", retryable=True,
        ) from error


# ------------------------------------------------------------------ #
# المنفذ الموحد — القائمة البيضاء + التوثيق + التصنيف (008 §2-§5)
# ------------------------------------------------------------------ #

#: حقول الوسائط الآمنة للعرض — لا أسرار أبدًا (استعلام/رابط/مسار/أمر).
_QUERY_FIELDS = ("query", "url", "path", "series_id", "indicator",
                 "md_path", "out_path", "command")


def _record_of(name: str, args: dict, attempt: int) -> ToolCallRecord:
    query = next(
        (str(args.get(f)) for f in _QUERY_FIELDS if args.get(f)), ""
    )
    return ToolCallRecord(
        tool_call_id=f"tc-{_uuid.uuid4().hex[:10]}",
        tool=name, started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        query=query,
        request_summary={"attempt": attempt, "args_keys": sorted(args)},
    )


def _metrics_count(record: ToolCallRecord) -> None:
    """مراقبة (009 §32) — عدادات فعلية لكل استدعاء حقيقي."""
    try:
        from readiness import metrics  # noqa: PLC0415 — كسول

        metrics.count_tool_call(
            record.duration_ms, record.status == "SUCCEEDED",
            failure_class=record.failure_class,
            failure_stage=record.failure_stage,
        )
    except Exception:  # noqa: BLE001 — المراقبة لا تكسر الأداة
        pass


def _finish_success(ctx: ToolContext, record: ToolCallRecord, value: Any,
                    digest: str, site: str, summary: dict, *,
                    result_count: int = 0, analyzable: bool = True) -> None:
    record.status = "SUCCEEDED"
    record.transport_status = "SUCCESS"
    record.result_status = "USABLE" if analyzable else "NOT_USABLE"
    record.result_count = result_count
    record.analyzable = analyzable
    record.completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record.output_sha256 = digest
    record.execution_site = site
    record.result_summary = summary
    ctx.tool_records.append(record)
    _metrics_count(record)
    ctx.emit({
        "kind": "tool.call",
        "role": "implementer",
        "tool": record.tool,
        "args_summary": summary,
        "output_sha256": digest,
        "execution_site": site,
        "duration_ms": record.duration_ms,
        "tool_call_id": record.tool_call_id,
        "attempt": record.request_summary.get("attempt", 1),
        "transport_status": "SUCCESS",
        "result_status": record.result_status,
        "result_count": result_count,
        "query": record.query,
    })


def _finish_failure(ctx: ToolContext, record: ToolCallRecord,
                    failure: ToolFailure, site: str) -> None:
    record.status = "FAILED"
    transport_failed = failure.failure_class in (
        "NETWORK_FAILURE", "TIMEOUT", "PROVIDER_FAILURE", "AUTH_FAILURE",
    )
    record.transport_status = "FAILED" if transport_failed else "SUCCESS"
    record.result_status = "NOT_USABLE"
    record.failure_class = failure.failure_class
    record.failure_stage = failure.stage
    record.failure_reason = failure.reason
    record.error = str(failure)
    record.retryable = failure.retryable
    record.completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record.execution_site = site
    ctx.tool_records.append(record)
    _metrics_count(record)
    ctx.emit({
        "kind": "tool.failed",
        "role": "implementer",
        "tool": record.tool,
        "error": str(failure)[:300],
        "human": failure.human_summary(),
        "failure_class": failure.failure_class,
        "failure_stage": failure.stage,
        "failure_reason": failure.reason,
        "retryable": failure.retryable,
        "needs_strategy_change": failure.needs_strategy_change,
        "query": record.query,
        "attempt": record.request_summary.get("attempt", 1),
        "transport_status": record.transport_status,
        "tool_call_id": record.tool_call_id,
        "duration_ms": record.duration_ms,
        "execution_site": site,
        "details": failure.details,
    })


def run_tool(name: str, args: dict, ctx: ToolContext,
             *, attempt: int = 1) -> Any:
    """تنفيذ أداة بيضاء مع توثيق وتصنيف — غيرها = فشل مصنَّف صريح."""
    started = time.monotonic()
    if name not in TOOL_WHITELIST:
        # مخالفة السياسة تخلف سجلًا دائمًا كذلك (§2 كل استدعاء)
        record = _record_of(name, args, attempt)
        failure = ToolFailure(
            name,
            f"أداة خارج القائمة البيضاء: '{name}' (المسموح: {list(TOOL_WHITELIST)})",
            failure_class="POLICY_BLOCK", reason="TOOL_NOT_WHITELISTED",
            stage="TOOL_START", retryable=False,
        )
        _finish_failure(ctx, record, failure, "none")
        raise failure
    site = (
        "in_process_declared"
        if name in ("web_search", "fetch_page") or name in DATA_TOOLS
        or name in BROWSER_TOOLS or name == "run_build_command"
        else "substrate"
    )
    record = _record_of(name, args, attempt)
    ctx.emit({
        "kind": "tool.started",
        "role": "implementer",
        "tool": name,
        "query": record.query,
        "attempt": attempt,
        "execution_site": site,
        "tool_call_id": record.tool_call_id,
    })

    def finalize(record: ToolCallRecord) -> None:
        record.duration_ms = int((time.monotonic() - started) * 1000)

    try:
        if name == "web_search":
            value = web_search(**args, sessions=getattr(ctx, "sessions", None))
            ctx.search_results.extend(value)
            digest = _sha256_text(json.dumps(value, ensure_ascii=False))
            finalize(record)
            _finish_success(ctx, record, value, digest, site,
                            {"results": len(value),
                             "first": value[0]["title"][:80] if value else ""},
                            result_count=len(value))
        elif name == "fetch_page":
            url = str(args.get("url", ""))
            value = fetch_page(**args)
            ctx.fetched_urls.append(url)
            digest = _sha256_text(value)
            finalize(record)
            _finish_success(ctx, record, value, digest, site,
                            {"chars": len(value)}, result_count=1)
        elif name == "write_file":
            value = write_file(ctx, str(args.get("path", "")),
                               str(args.get("content", "")))
            digest = _sha256_text(str(args.get("content", "")))
            finalize(record)
            _finish_success(ctx, record, value, digest, site,
                            {"path": str(value)})
        elif name == "read_file":
            value = read_file(ctx, str(args.get("path", "")))
            digest = _sha256_text(str(value))
            finalize(record)
            _finish_success(ctx, record, value, digest, site,
                            {"chars": len(str(value))})
        elif name == "generate_pdf_arabic":
            value = generate_pdf_arabic(
                ctx, str(args.get("md_path", "")), str(args.get("out_path", ""))
            )
            digest = hashlib.sha256(
                Path(value.split("#")[0]).read_bytes()
            ).hexdigest()
            if "#" in value:
                site = value.split("#", 1)[1]
                value = value.split("#", 1)[0]
            finalize(record)
            _finish_success(ctx, record, value, digest, site,
                            {"path": str(value)})
        elif name == "verify_pdf_pages":
            value = verify_pdf_pages(ctx, str(args.get("path", "")))
            digest = _sha256_text(f"pages={value}")
            finalize(record)
            _finish_success(ctx, record, value, digest, site,
                            {"pages": value})
        elif name == "run_build_command":
            value = run_build_command(
                ctx, str(args.get("command", "")),
                timeout_s=float(args.get("timeout_s", 0) or 0),
            )
            digest = _sha256_text(json.dumps(value, ensure_ascii=False))
            finalize(record)
            _finish_success(ctx, record, value, digest, site,
                            {"command": str(args.get("command", "")),
                             "exit_code": value.get("exit_code")},
                            result_count=1)
        elif name in DATA_TOOLS:
            from tools import data_tools

            if name == "http_get_text":
                value = data_tools.http_get_text(ctx, str(args.get("url", "")))
                ctx.data_urls.append({"url": value["url"],
                                      "title": value.get("artifact", "")})
            elif name == "http_get_json":
                value = data_tools.http_get_json(ctx, str(args.get("url", "")))
                ctx.data_urls.append({"url": value["url"],
                                      "title": value.get("artifact", "")})
            elif name == "page_to_text":
                value = data_tools.page_to_text(ctx, str(args.get("url", "")))
                ctx.data_urls.append({"url": value["url"],
                                      "title": value.get("artifact", "")})
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
                    "url": ("https://data.worldbank.org/indicator/"
                            f"{value['indicator']}"),
                    "title": f"البنك الدولي — مؤشر {value['indicator']}",
                })
            digest = str(value["sha256"])
            finalize(record)
            summary = {
                key: value.get(key)
                for key in ("series_id", "indicator", "rows", "count",
                            "chars", "words", "artifact")
                if key in value
            }
            _finish_success(ctx, record, value, digest, site, summary,
                            result_count=int(value.get("count", 1) or 1))
        elif name in BROWSER_TOOLS:
            # (013 §13+§28) متصفح حي — توزيع موحد في browser_tools
            from roles import browser_tools

            value = browser_tools.run_browser_tool(name, args, ctx)
            digest = str(value.get("sha256")
                         or _sha256_text(json.dumps(value,
                                                    ensure_ascii=False)))
            finalize(record)
            summary = {
                key: value.get(key)
                for key in ("url", "title", "chars", "count",
                            "bytes", "file", "clicked", "typed_chars")
                if key in value
            }
            _finish_success(ctx, record, value, digest, site, summary,
                            result_count=1)
        else:  # pragma: no cover — القائمة مغلقة أعلاه
            raise ToolFailure(name, f"أداة غير منفذة: {name}",
                              failure_class="INPUT_FAILURE",
                              reason="TOOL_NOT_WHITELISTED",
                              stage="TOOL_START", retryable=False)
    except ToolFailure as failure:
        finalize(record)
        _finish_failure(ctx, record, failure, site)
        raise
    except ToolError as error:  # أنواع قديمة متبقية — تُصنَّف لا تُبتلع
        finalize(record)
        wrapped = ToolFailure(
            name, str(error), failure_class="EXECUTOR_FAILURE",
            reason="UNKNOWN", stage="TOOL_EXECUTION", retryable=False,
        )
        _finish_failure(ctx, record, wrapped, site)
        raise wrapped from error
    except Exception as error:  # noqa: BLE001 — فشل مصنَّف موثق
        finalize(record)
        wrapped = ToolFailure(
            name, f"الأداة {name} فشلت: {error}",
            failure_class="UNKNOWN_FAILURE", reason="UNKNOWN",
            stage="TOOL_EXECUTION", retryable=False,
        )
        _finish_failure(ctx, record, wrapped, site)
        raise wrapped from error
    return value
