"""المنفذ (Implementer) — ينفّذ المهمة داخل الركيزة (CONTRACTS.md §3).

تنفيذ الأمر الثاني (mock حتمي لكن **بتنفيذ حقيقي داخل الركيزة المعزولة**):

- يولّد كود بايثون يكتب ملفات نصية داخل `/artifacts` (المخرج الرئيسي
  `<id>-output.txt` دائمًا، وملف سجل التشغيل `<id>-run-log.txt` عند إعادة
  التنفيذ فقط — أي عندما تكون previous_attempts غير فارغة).
- التنفيذ كله عبر مدير الركيزة (`substrate.sandbox.SandboxManager`)
  بالركيزة المحلية: namespaces + seccomp + rlimits + لا شبكة — لا تنفيذ
  على المضيف إطلاقًا (fail-closed: إن تعذّر العزل فالحالة failed بلا
  أي تنفيذ بديل).
- لهذا فإن حكم المراجع اللاحق (not_evidenced في المحاولة الأولى) ينشأ
  من **حالة ملفات حقيقية** — الملف الناقص ناقص فعلًا على القرص؛ لا
  فشلًا مزيفًا يصنعه عدّاد.
"""

from __future__ import annotations

import json
import re
import tempfile
import uuid
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from core.state import PlanState
from roles.thinker import PlanTask


class ImplementerStatus(str, Enum):
    EXECUTED = "executed"
    FAILED = "failed"


class ImplementerRequest(BaseModel):
    """عقد طلب المنفذ — sandbox_root مساحة الركيزة الممنوحة."""

    task: PlanTask
    tools_available: list[str] = Field(default_factory=list)
    sandbox_root: str = ""
    previous_attempts: list[str] = Field(default_factory=list)


class ImplementerResult(BaseModel):
    """عقد نتيجة المنفذ — الحالة الصادقة: EXECUTED.

    نُفِّذت ≠ نجحت: القرار للمراجع ثم للمستخدم. الأدلة مراجع لا محتوى.
    """

    status: ImplementerStatus
    artifacts: list[str] = Field(default_factory=list)
    stdout_truncated: str = ""
    stderr_truncated: str = Field(default="")
    evidence_refs: list[str] = Field(default_factory=list)
    #: كتلة الفشل المنظمة (إضافة 008 §18) — class/stage/tool/reason؛
    #: تصل المحكَّم والواجهة كما هي، لا سلسلة نصية غامضة.
    failure: dict | None = None


class CodeFileSpec(BaseModel):
    """ملف واحد في مهمة برمجية (013.16 §2) — مسار نسبي ومحتوى خام."""

    path: str
    content: str


class CodeMissionFiles(BaseModel):
    """عقد ملفات المهمة البرمجية — ما ينتجه النموذج كتابةً قبل التنفيذ.

    المحتوى ينفَّذ لاحقًا حقيقةً داخل الركيزة (run_python) — فالصحة
    هنا شرط نجاح لا تجميل: كود مكسور = فشل تنفيذي صريح يصل المحكَّم.
    """

    files: list[CodeFileSpec]
    entrypoint: str
    tests_entrypoint: str
    notes: list[str] = Field(default_factory=list)


_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")

#: أقصى طول نصي يُردّ من مخرجات التنفيذ (العقد: مقطوعات لا محتوى كامل).
_TRUNCATE = 400


def _safe(task_id: str) -> str:
    """معرّف مهمة آمن كاسم ملف داخل الركيزة (حروف/أرقام/-/_ حصرًا)."""
    cleaned = _SAFE_ID.sub("-", task_id.strip()) or "task"
    return cleaned[:48]


def _read_bounded(path: str, limit: int = _TRUNCATE) -> str:
    """قراءة مرجع مخرجات إن وُجد — مقطوعة كما يفرض العقد."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text if len(text) <= limit else text[:limit] + " …"


class Implementer:
    """دور المنفذ — تنفيذ حقيقي داخل الركيزة المعزولة (الأمر الثاني)."""

    HONEST_STATE = PlanState.EXECUTED

    def __init__(self) -> None:
        # المدير يُبنى كسولًا عند أول تنفيذ — تسجيل الركيزة المحلية فعلًا.
        self._manager = None

    # ------------------------------------------------------------------ #
    # الركيزة — عبر المدير حصرًا (لا استدعاء مباشر للمحوّل)
    # ------------------------------------------------------------------ #

    def _sandbox_manager(self):
        if self._manager is None:
            from substrate.local_substrate import local_sandbox_manager

            self._manager = local_sandbox_manager()
        return self._manager

    # ------------------------------------------------------------------ #
    # التنفيذ
    # ------------------------------------------------------------------ #

    def run(self, request: ImplementerRequest) -> ImplementerResult:
        try:
            return self._run(request)
        except Exception as error:  # noqa: BLE001 — fail-closed بلا تنفيذ مضيف
            return ImplementerResult(
                status=ImplementerStatus.FAILED,
                stderr_truncated=f"فشل المنفذ قبل التنفيذ: {error}"[:_TRUNCATE],
            )

    def _run(self, request: ImplementerRequest) -> ImplementerResult:
        task = request.task
        task_file_id = _safe(task.id)
        attempt_no = len(request.previous_attempts) + 1

        # مساحة العمل الممنوحة: ws (مساحة مؤقتة) + artifacts (حجز الأدلة)
        root = Path(request.sandbox_root) if request.sandbox_root else Path(
            tempfile.mkdtemp(prefix="v2-cycle-")
        )
        workspace = root / "ws"
        artifacts_dir = root / "artifacts"
        workspace.mkdir(parents=True, exist_ok=True)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # الملفات المطلوبة: الناتج الرئيسي دائمًا؛ سجل التشغيل عند إعادة
        # التنفيذ فقط (previous_attempts غير فارغة) — هذا ما يجعل حلقة
        # الإصلاح تنشأ من حالة ملفات حقيقية لا من حكم مزيف.
        primary = f"{task_file_id}-output.txt"
        run_log = f"{task_file_id}-run-log.txt"
        files: dict[str, str] = {
            primary: (
                f"task: {task.id}\n"
                f"description: {task.description}\n"
                f"attempt: {attempt_no}\n"
            )
        }
        if request.previous_attempts:
            files[run_log] = (
                "سجل التنفيذ:\n"
                + "\n".join(request.previous_attempts[-6:])
                + "\n"
            )

        # كود الركيزة: كتابة الملفات داخل /artifacts (مسار الحجز الوحيد)
        payload = json.dumps(files, ensure_ascii=False)
        code = (
            "import json\n"
            f"files = json.loads({payload!r})\n"
            "for name, content in files.items():\n"
            "    with open('/artifacts/' + name, 'w', encoding='utf-8') as handle:\n"
            "        handle.write(content)\n"
            "print('wrote: ' + ', '.join(sorted(files)))\n"
        )

        manager = self._sandbox_manager()
        image = next(iter(manager.image_allowlist))
        from substrate.limits import E1_LIMITS_DEFAULTS
        from substrate.sandbox import NetworkMode, SandboxRequest

        sandbox_id = f"{task_file_id}-a{attempt_no}-{uuid.uuid4().hex[:8]}"
        sandbox_request = SandboxRequest(
            sandbox_id=sandbox_id,
            image=image,
            command=("python", "-c", code),
            limits=E1_LIMITS_DEFAULTS,
            env_names=frozenset({"PATH"}),
            network=NetworkMode.NONE,
            workspace_root=str(workspace),
            artifacts_dir=str(artifacts_dir),
        )
        outcome = manager.execute(sandbox_request)
        record = outcome.record

        if outcome.outcome.value != "EXECUTED" or record is None:
            detail = outcome.detail or (
                record.termination.value if record else "بلا سجل"
            )
            return ImplementerResult(
                status=ImplementerStatus.FAILED,
                stderr_truncated=f"الركيزة رفضت/فشلت: {detail}"[:_TRUNCATE],
            )
        if record.exit_code not in (0, None):
            return ImplementerResult(
                status=ImplementerStatus.FAILED,
                stdout_truncated=_read_bounded(record.stdout_reference),
                stderr_truncated=_read_bounded(record.stderr_reference),
                evidence_refs=[record.stdout_reference, record.stderr_reference],
            )

        # الأدلة: الملفات التي كتبها كودنا فعلًا (من حجز الركيزة بالهاش)
        wanted = {primary, run_log}
        custody = [entry for entry in record.artifacts if entry.path in wanted]
        artifacts = [
            str(artifacts_dir / entry.path)
            for entry in sorted(custody, key=lambda e: e.path)
        ]
        evidence_refs = [
            f"sha256:{entry.sha256[:16]}:{entry.path}" for entry in custody
        ]
        evidence_refs.append(record.stdout_reference)

        return ImplementerResult(
            status=ImplementerStatus.EXECUTED,
            artifacts=artifacts,
            stdout_truncated=_read_bounded(record.stdout_reference),
            stderr_truncated=_read_bounded(record.stderr_reference),
            evidence_refs=[ref for ref in evidence_refs if ref],
        )
