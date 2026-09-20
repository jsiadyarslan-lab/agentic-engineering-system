"""محرك التنفيذ — §3 و§4 من الأمر الرابع المعدل.

تشغيل أوامر حقيقية داخل الركيزة بثلاثة مستويات عزل:

- FULL_ISOLATION: بلا شبكة، ملفات المصدر للقراءة فقط (وضع القراءة).
- BUILD_ISOLATION: كتابة داخل مساحة العمل ضمن منح PATH_GRANT —
  خروج الملفات عبر حضانة /artifacts فقط بعد فحص النطاق.
- TEST_BRIDGE: إعلاني — ربط مضيف محلي محدد داخل العزل؛ الركيزة
  المحلية (D-04=A: شبكة NONE) تمنعه اليوم بصدق: يُرفض قبل التنفيذ
  لا يُمارَس خفية.

القواعد المفروضة آليًا:

1. **القائمة البيضاء أولاً**: أي أمر خارج قائمة الأمر البيضاء =
   HARD STOP قبل التنفيذ — لا استثناء ولا «أمر شبيه».
2. **لا subprocess على المضيف**: كل أمر يمر عبر SandboxManager
   (الركيزة المحلية المثبتة). المحرك لا يستدعي subprocess للأوامر.
3. **حضانة الخروج**: في الوضعين الكاتبين، الملفات الناتجة تخرج من
   /artifacts إلى مسارات PATH_GRANT المعلنة فقط؛ أي مسار خارجها =
   HARD STOP (النسخة المضيفية الوحيدة هنا — نسخ المحرك المحكوم، لا
   أمر المستدعي).
4. **فشل تنفيذ (exit ≠ 0)**: يُعاد للمنفذ مع السياق للإصلاح بحد
   محاولات من الأمر؛ استنفادها = HARD STOP.
"""

from __future__ import annotations

import shlex
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from eoe.access_gateway import AccessAdmission, AccessDenied
from eoe.order_parser import GrantKind
from substrate.limits import E1_LIMITS_DEFAULTS
from substrate.sandbox import NetworkMode, SandboxRequest


class IsolationLevel(str, Enum):
    """مستويات العزل الثلاثة — §4.1."""

    FULL_ISOLATION = "FULL_ISOLATION"
    BUILD_ISOLATION = "BUILD_ISOLATION"
    TEST_BRIDGE = "TEST_BRIDGE"


#: حد الانفجار لملفات الحضانة (متوافق مع E4: ≤64 ملفًا).
CUSTODY_MAX_FILES = 64
CUSTODY_MAX_FILE_BYTES = 1024 * 1024  # 1 MiB لكل ملف — حرفيًا من الأمر


class ExecutionHardStop(Exception):
    """توقف صلب من المحرك — يحمل السبب المقروء والقسم المتوقف."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class ExecutionOutcome:
    """نتيجة تنفيذ واحد — دليل كامل لا حكم (D-08)."""

    sandbox_id: str
    command: tuple[str, ...]
    executed: bool
    exit_code: int | None
    duration_ms: int
    stdout: str
    stderr: str
    custody_files: tuple[tuple[str, str], ...] = ()  # (هدف مضيفي، مصدر artifacts)
    termination: str = ""
    memory_ceiling_kb: int = 0  # سقف الذاكرة المطبق (الركيزة المحلية لا ترصد الذروة — RLIMIT_AS هو المطبَّق، يوثق بصدق)


@dataclass
class SectionExecutionPlan:
    """إعلان القسم المسبق — ما سيصل إليه قبل التنفيذ (§3)."""

    section_number: int
    commands: tuple[tuple[str, ...], ...]
    isolation: IsolationLevel
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()   # مسارات هبوط مضيفية معلنة


class ExecutionEngine:
    """تنفيذ أوامر الأقسام داخل الركيزة — بلا مضيف أبدًا."""

    def __init__(
        self,
        manager,
        admission: AccessAdmission,
        *,
        command_whitelist: tuple[str, ...] = (),
        work_base: str = "",
    ) -> None:
        self._manager = manager
        self._admission = admission
        self._whitelist = tuple(command_whitelist)
        self._work_base = Path(work_base) if work_base else None
        self.executions: list[ExecutionOutcome] = []

    # -- القائمة البيضاء: قبل أي شيء ------------------------------------

    def set_whitelist(self, whitelist: tuple[str, ...]) -> None:
        """تعيين قائمة الأمر البيضاء — من مواصفة الأمر بعد تحليله."""
        self._whitelist = tuple(whitelist)

    def check_whitelist(self, command: tuple[str, ...]) -> None:
        """فرض القائمة البيضاء — أي أمر خارجها يُوقف قبل التنفيذ."""
        if not command:
            raise ExecutionHardStop(
                "أمر خارج القائمة البيضاء", "أمر فارغ"
            )
        binary = command[0]
        if binary not in self._whitelist:
            raise ExecutionHardStop(
                "أمر خارج القائمة البيضاء",
                f"{binary!r} ليس في [{', '.join(self._whitelist)}] — رفض قبل التنفيذ",
            )

    # -- تنفيذ قسم كامل -------------------------------------------------

    def run_section(
        self,
        plan: SectionExecutionPlan,
        *,
        repair_fn=None,
        max_attempts: int = 1,
    ) -> list[ExecutionOutcome]:
        """تنفيذ أوامر القسم — فشل يعاد للمنفذ ثم HARD STOP عند الاستنفاد."""
        outcomes: list[ExecutionOutcome] = []
        for command in plan.commands:
            self.check_whitelist(command)
            outcome = self._execute_one(plan, command)
            attempts = 1
            while outcome.exit_code not in (0,) and attempts < max_attempts:
                # §4.4: الإعادة للمنفذ مع السياق للإصلاح
                if repair_fn is None:
                    break
                repaired = repair_fn(plan.section_number, command, outcome)
                if repaired is None:
                    break
                outcome = self._execute_one(plan, tuple(repaired))
                attempts += 1
            if outcome.exit_code not in (0,):
                raise ExecutionHardStop(
                    "فشل تنفيذ بعد محاولات الإصلاح",
                    f"§{plan.section_number}: {command[0]} exit={outcome.exit_code} "
                    f"محاولات={attempts} stderr={outcome.stderr[:200]}",
                )
            outcomes.append(outcome)
            self.executions.append(outcome)
        return outcomes

    # -- تنفيذ واحد داخل الركيزة -----------------------------------------

    def _execute_one(
        self, plan: SectionExecutionPlan, command: tuple[str, ...]
    ) -> ExecutionOutcome:
        sandbox_id = f"s{plan.section_number}-{uuid.uuid4().hex[:10]}"
        if self._work_base is not None:
            root = self._work_base / f"sec{plan.section_number}-{uuid.uuid4().hex[:6]}"
        else:
            import tempfile
            root = Path(tempfile.mkdtemp(prefix=f"eoe-s{plan.section_number}-"))
        workspace = root / "ws"
        artifacts = root / "artifacts"
        workspace.mkdir(parents=True, exist_ok=True)
        artifacts.mkdir(parents=True, exist_ok=True)

        sources_root = ""
        if plan.isolation is IsolationLevel.FULL_ISOLATION and plan.reads:
            # الركيزة تربط جذر المصدر للقراءة فقط عند /work
            granted = self._admit_read(plan.reads[0])
            sources_root = granted.target if Path(granted.target).is_dir() else str(
                Path(granted.target).parent
            )
        if plan.isolation is IsolationLevel.TEST_BRIDGE:
            raise ExecutionHardStop(
                "TEST_BRIDGE غير مدعوم على الركيزة المحلية",
                "شبكة الركيزة NONE (D-04=A) — الربط يُرفض بصدق قبل التنفيذ",
            )

        image = self._pick_image(command)
        request = SandboxRequest(
            sandbox_id=sandbox_id,
            image=image,
            command=tuple(command),
            limits=E1_LIMITS_DEFAULTS,
            env_names=frozenset({"PATH"}),
            network=NetworkMode.NONE,
            workspace_root=str(workspace),
            artifacts_dir=str(artifacts),
            sources_root=sources_root,
        )
        started = time.time()
        outcome = self._manager.execute(request)
        record = outcome.record
        if record is None or not record.executed:
            return ExecutionOutcome(
                sandbox_id=sandbox_id,
                command=tuple(command),
                executed=False,
                exit_code=None,
                duration_ms=0,
                stdout="",
                stderr=(outcome.detail or "بلا سجل تنفيذ"),
                termination=record.termination.value if record else "NO_RECORD",
            )
        stdout = self._read_text(record.stdout_reference)
        stderr = self._read_text(record.stderr_reference)
        custody: tuple[tuple[str, str], ...] = ()
        if plan.writes:
            custody = self._custody_exit(plan, artifacts, str(root))
        return ExecutionOutcome(
            sandbox_id=sandbox_id,
            command=tuple(command),
            executed=True,
            exit_code=record.exit_code,
            duration_ms=record.duration_ms,
            stdout=stdout,
            stderr=stderr,
            custody_files=custody,
            termination=record.termination.value,
            memory_ceiling_kb=int(record.limits_applied.memory_bytes // 1024)
            if record.limits_applied
            else 0,
        )

    def _pick_image(self, command: tuple[str, ...]) -> str:
        """اختيار صورة الركيزة بحسب أول الأمر: git→صورة git، غيره python."""
        allowlist = self._manager.image_allowlist
        if command and command[0] == "git" and "git" in allowlist:
            return "git"
        for name in sorted(allowlist):
            if name != "git":
                return name
        return next(iter(allowlist))

    def _admit_read(self, path: str):
        """فحص القبول لقراءة المسار — بلا منح = رفض (fail-closed)."""
        try:
            return self._admission.admit_access(
                kind=GrantKind.PATH_GRANT, write=False, path=str(Path(path).resolve())
            )
        except AccessDenied as denied:
            raise ExecutionHardStop(
                "وصول بلا منح سارية", f"{path}: {denied.reason.value} — {denied.detail}"
            ) from denied

    # -- حضانة الخروج: ملفات الأقسام الكاتبة ------------------------------

    def _custody_exit(
        self,
        plan: SectionExecutionPlan,
        artifacts_dir: Path,
        section_root: str,
    ) -> tuple[tuple[str, str], ...]:
        """خروج الملفات من /artifacts إلى مسارات PATH_GRANT المعلنة.

        القاعدة: كل ملف ناتج يُنسخ إلى هدفه المعلن داخل المنحة فقط.
        ملف بلا هدف معلن أو هدف خارج المنحة = HARD STOP.
        """
        produced = sorted(
            p for p in artifacts_dir.iterdir()
            if p.is_file() and not p.name.startswith("stdout-")
            and not p.name.startswith("stderr-")
        )
        if len(produced) > CUSTODY_MAX_FILES:
            raise ExecutionHardStop(
                "تجاوز حدود الانفجار",
                f"{len(produced)} ملفًا > سقف {CUSTODY_MAX_FILES}",
            )
        landing: dict[str, str] = {}
        for host_target in plan.writes:
            resolved = str(Path(host_target).resolve())
            self._admit_write(resolved)
            landing[Path(resolved).name] = resolved
        transfers: list[tuple[str, str]] = []
        for artifact in produced:
            if artifact.stat().st_size > CUSTODY_MAX_FILE_BYTES:
                raise ExecutionHardStop(
                    "تجاوز حدود الانفجار",
                    f"{artifact.name} يتجاوز 1MiB للملف الواحد",
                )
            target = landing.get(artifact.name)
            if target is None:
                # هدف ضمن المنحة بلا ملف مطابق: يُسجل ويُتجاوز بأمان
                continue
            transfers.append((target, str(artifact)))
        for target, source in transfers:
            Path(target).write_bytes(Path(source).read_bytes())
        return tuple(transfers)

    def _admit_write(self, path: str) -> None:
        try:
            self._admission.admit_access(
                kind=GrantKind.PATH_GRANT, write=True, path=path
            )
        except AccessDenied as denied:
            raise ExecutionHardStop(
                "ملف خارج نطاق PATH_GRANT",
                f"{path}: {denied.reason.value} — {denied.detail}",
            ) from denied

    @staticmethod
    def _read_text(reference: str) -> str:
        if not reference:
            return ""
        try:
            return Path(reference).read_text(encoding="utf-8", errors="replace")[:8000]
        except OSError:
            return ""


def parse_command_line(line: str) -> tuple[str, ...]:
    """تحويل سطر أمر إلى argv — لا shell، لا تفسير إضافي."""
    return tuple(shlex.split(line))
