"""خلفيات التنفيذ (الأمر 010 §16 + الأمر 011 §4-§11) — حقيقة تشغيلية.

    ExecutionBackend (عقد موحد §6: probe/workspace/execute/capture/…)
    ├── LocalSandboxBackend   ركيزة Linux/x86_64 المعزولة (namespaces+
    │                         seccomp — نفس المثبتة بـ21/21 مسبارًا في E1)
    ├── LocalProcessBackend   تنفيذ محلي متوافق بلا عزل (معلن صراحة —
    │                         011 §4+§25: Host Windows + no sandbox =
    │                         Platform Compatibility Mode، لا ادعاء عزل)
    └── RemoteWorkerBackend   عامل بعيد عبر HTTP (011 §9-§10: سلم الجاهزية
                              connectivity→auth→heartbeat→env→workspace→
                              execute→artifact قبل READY)

الفصل الجوهري (011 §4): Host Platform ≠ Execution Backend ≠ Isolation —
اسم البيئة من runtime الفعلي (لا ``local-linux`` على مضيف Windows)،
والوصف من جرد حقيقي (runtime_truth) لا من configuration.name.

القاعدة (§16+§20 010): لا خلفية غير منفذة؛ والعملية غير المدعومة
ترفع ``BackendNotSupported`` (NOT_SUPPORTED) — لا نجاح زائف أبدًا.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

#: مهلة HTTP للعامل البعيد (تحقق/تنفيذ محدود)
WORKER_HTTP_TIMEOUT = 240.0


class BackendNotSupported(Exception):
    """عملية غير مدعومة في هذه الخلفية (011 §6) — NOT_SUPPORTED صريح.

    كل خلفية تعلن عملياتها؛ ما لا تدعمه يرفع هذا الاستثناء بسبب
    معلن — لا fake success ولا سكوت.
    """

    def __init__(self, backend: str, operation: str, reason: str = "") -> None:
        super().__init__(
            f"NOT_SUPPORTED: الخلفية {backend} لا تدعم {operation}"
            + (f" — {reason}" if reason else "")
        )
        self.backend = backend
        self.operation = operation


class WorkerHttpError(ConnectionError):
    """رد HTTP بخطأ من العامل البعيد — يفصل 401/403 عن انعدام الوصول.

    ترث ConnectionError (عقد 010): رافعو الأخطاء القدامى يصطادونها كما
    هي، والحقل code/body يفصّلان السبب الحقيقي للسلم (011 §10).
    """

    def __init__(self, code: int, body: str) -> None:
        super().__init__(f"العامل رد {code}: {body}")
        self.code = code
        self.body = body


@dataclass
class ExecutionOutcome:
    """نتيجة تنفيذ كود في بيئة — سجل صادق موحد لكل الخلفيات."""

    environment_id: str
    backend: str
    exit_code: int
    stdout: str
    stderr: str
    termination: str
    detail: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.termination == "COMPLETED" and self.exit_code == 0


@dataclass
class VerifyResult:
    """نتيجة التحقق من بيئة — فحوص حقيقية مسماة لا «نجاح» مجملًا."""

    ok: bool
    status: str  # READY | NOT_READY | UNAVAILABLE
    checks: list[dict]
    profile: dict
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok, "status": self.status, "checks": self.checks,
            "profile": self.profile, "reason": self.reason,
        }


class ExecutionBackend(Protocol):
    """عقد الخلفية (011 §6) — كل عملية معلنة أو مرفوعة NOT_SUPPORTED.

    العمليات الأساسية (describe/verify/run_code) مدعومة في كل الخلفيات
    الحقيقية؛ عمليات مساحة العمل (create_workspace/write_file/read_file)
    حقيقية حيث تُنفَّذ فعلًا، والعملية غير المدعومة ترفع
    BackendNotSupported — لا fake success أبدًا (§6-§7).
    """

    backend_kind: str

    def describe(self) -> dict:
        """وصف البيئة: os/arch/runtime/عزل/شبكة/حدود — من الكود الفعلي."""

    def verify(self) -> VerifyResult:
        """فحوص حقيقية: إقلاع + كتابة + تنفيذ + التقاط مخرجات."""

    def run_code(
        self, code: str, *, workspace: Path, artifacts: Path,
        timeout_s: float = 120.0,
    ) -> ExecutionOutcome:
        """تنفيذ كود فعلي — نفس آلية التحقق حرفيًا."""


# ------------------------------------------------------------------ #
# Runtime Truth (011 §5) — كل معلومة المضيف من runtime الفعلي
# ------------------------------------------------------------------ #

_TRUTH_CACHE: dict[str, Any] = {"at": 0.0, "truth": None}
_TRUTH_TTL_S = 60.0


def _cmd_first_line(args: list[str], timeout: float = 3.0) -> str:
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout
        )
        lines = (proc.stdout or proc.stderr or "").strip().splitlines()
        return lines[0][:160] if lines and proc.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def runtime_truth() -> dict:
    """جرد المضيف الفعلي (011 §5) — لا اعتماد على configuration.name.

    OS/kernel/arch/Python/Node/Git/Shell/container/WSL/Docker/CPU/
    memory/disk — كل قيمة مكتشفة الآن من runtime الحقيقي، مع كاش
    قصير (60ث) كي يبقى الاستدعاء رخيصًا داخل describe/verify.
    """
    import os
    import platform
    import shutil
    import sys
    import time as _time

    now = _time.monotonic()
    if _TRUTH_CACHE["truth"] is not None and now - _TRUTH_CACHE["at"] < _TRUTH_TTL_S:
        return dict(_TRUTH_CACHE["truth"])

    os_name = platform.system()          # Linux | Windows | Darwin
    truth: dict[str, Any] = {
        "os": os_name,
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "kernel": _cmd_first_line(["uname", "-r"]) if os_name == "Linux"
        else platform.release(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}."
                  f"{sys.version_info.micro}",
        "python_executable": sys.executable,
        "git": _cmd_first_line(["git", "--version"]),
        "node": _cmd_first_line(["node", "--version"]),
        "shell": "",
        "container_runtime": "",
        "wsl": False,
        "docker": _cmd_first_line(["docker", "--version"]),
        "cpu_cores": os.cpu_count() or 1,
        "memory": "",
        "disk_free_gb": 0,
        "network": "unknown",
    }

    # القشدة — من البيئة الفعلية لا من افتراض
    truth["shell"] = (
        os.environ.get("SHELL")
        or os.environ.get("COMSPEC", "")
        or ("/bin/sh" if os_name != "Windows" else "cmd.exe")
    )

    # WSL — كشف فعلي من /proc/version (داخل WSL فقط)
    if os_name == "Linux":
        try:
            version_text = Path("/proc/version").read_text(encoding="utf-8")
            truth["wsl"] = "microsoft" in version_text.lower()
        except OSError:
            truth["wsl"] = False

    # الذاكرة — /proc/meminfo على Linux، وإلا غير معروف بلا تخمين
    if os_name == "Linux":
        try:
            for line in Path("/proc/meminfo").read_text(
                    encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    gb = int(line.split()[1]) // (1024 * 1024)
                    truth["memory"] = f"{gb} GB"
                    break
        except (OSError, ValueError, IndexError):
            truth["memory"] = ""
    # Docker كـcontainer runtime داخل الحاوية نفسها
    if shutil.which("docker"):
        truth["container_runtime"] = "docker"
    elif Path("/.dockerenv").exists():
        truth["container_runtime"] = "container (dockerenv)"

    try:
        usage = shutil.disk_usage(os.getcwd())
        truth["disk_free_gb"] = round(usage.free / (1024 ** 3), 1)
    except OSError:
        truth["disk_free_gb"] = 0

    _TRUTH_CACHE["at"] = now
    _TRUTH_CACHE["truth"] = truth
    return dict(truth)


def host_platform_label(truth: dict | None = None) -> str:
    """تسمية المضيف الصادقة (011 §4) — ``Windows/x86_64`` لا «linux»."""
    truth = truth or runtime_truth()
    return f"{truth['os']}/{truth['architecture']}"


def local_environment_name() -> str:
    """اسم البيئة المحلية من OS الفعلي (011 §4) — لا local-linux على Windows."""
    os_name = runtime_truth()["os"].lower()
    return {"linux": "local-linux", "windows": "local-windows",
            "darwin": "local-darwin"}.get(os_name, f"local-{os_name}")


# ------------------------------------------------------------------ #
# LOCAL — ركيزة Linux/x86_64 المحلية (نفس E1 المعتمدة)
# ------------------------------------------------------------------ #

_LOCAL_PROBE_CODE = (
    "import pathlib\n"
    "p = pathlib.Path('/artifacts/probe.txt')\n"
    "p.write_text('boot-ok', encoding='utf-8')\n"
    "print('exec-ok:', p.read_text(encoding='utf-8'))\n"
)


class LocalSandboxBackend:
    """الركيزة المحلية المعزولة — Linux/x86_64 حصرًا (011 §4).

    كل من probe_sandbox و_run_in_substrate يمران من هنا: لا مدير
    منفصل للمسبار وآخر للمنفذ — مصدر واحد للحقيقة (010 §19).
    على مضيف غير Linux: available() صادقة → UNAVAILABLE مع المسار
    الحقيقي (عامل بعيد أو الوضع المتوافق المعلن).
    """

    backend_kind = "LOCAL"

    def __init__(self, environment_id: str = "local-linux") -> None:
        self.environment_id = environment_id

    def _manager(self):
        from substrate.local_substrate import local_sandbox_manager

        return local_sandbox_manager()

    def available(self) -> tuple[bool, str]:
        """هل الركيزة المحلية ممكنة أصلًا على هذه المنصة؟ (§20 صادق)"""
        from substrate.local_substrate import default_local_images

        images = default_local_images()
        if not images:
            return False, (
                "الركيزة المعزولة غير متاحة — تتطلب Linux/x86_64 والفحص "
                "الذاتي للمنصة رفضها. المسار الحقيقي: أضف عاملًا بعيدًا "
                "يعمل على Linux/WSL2 (بيئات التنفيذ ← إضافة بيئة ← "
                "REMOTE_WORKER) ثم تحقق"
            )
        return True, ""

    isolation = "SANDBOXED"
    supported_operations = (
        "probe", "create_workspace", "write_file", "read_file", "execute",
        "capture_stdout", "capture_stderr", "capture_exit_code",
        "collect_artifacts", "cleanup",
    )

    def describe(self) -> dict:
        from substrate.local_substrate import substrate_capabilities

        truth = runtime_truth()
        ok, reason = self.available()
        caps = substrate_capabilities()
        return {
            "environment_id": self.environment_id,
            "backend": "LOCAL",
            "isolation": "SANDBOXED",
            "host_platform": host_platform_label(truth),
            "os": truth["os"],
            "architecture": truth["architecture"],
            "kernel": truth["kernel"],
            "runtime": f"python {truth['python']}",
            "workspace_root": "runtime/sandbox",
            "network_policy": "none (network namespace بلا واجهات)",
            "resource_limits": "RLIMIT_AS/NPROC/FSIZE/CPU/NOFILE + affinity",
            "sandboxed": bool(ok and caps.get("supported")),
            "capabilities": [
                "code_execution", "filesystem_write", "artifact_capture",
                "python_runtime",
            ],
            "available": ok,
            "unavailable_reason": reason if not ok else "",
            "runtime_truth": truth,
            "kernel_features": {
                k: v for k, v in caps.items() if k != "interpreter"
            },
        }

    def verify(self) -> VerifyResult:
        import tempfile
        import time

        import substrate.local_substrate as local_substrate
        from substrate.sandbox import NetworkMode, SandboxRequest, SandboxTermination

        profile = self.describe()
        if not profile["available"]:
            return VerifyResult(
                ok=False, status="UNAVAILABLE", checks=[],
                profile=profile, reason=profile["unavailable_reason"],
            )
        checks: list[dict] = []
        started = time.monotonic()
        try:
            with tempfile.TemporaryDirectory(prefix="env-verify-") as tmp:
                workspace = Path(tmp) / "ws"
                artifacts = Path(tmp) / "art"
                workspace.mkdir()
                artifacts.mkdir()
                outcome = self.run_code(
                    _LOCAL_PROBE_CODE, workspace=workspace,
                    artifacts=artifacts, timeout_s=60.0,
                )
            checks.append({
                "name": "boot", "ok": outcome.termination != "FAILED_TO_START",
                "detail": outcome.termination,
            })
            checks.append({
                "name": "execute",
                "ok": outcome.termination == "COMPLETED"
                and outcome.exit_code == 0,
                "detail": f"exit={outcome.exit_code} {outcome.stderr[:120]}",
            })
            checks.append({
                "name": "capture",
                "ok": "boot-ok" in (outcome.artifacts.get("probe.txt") or "")
                or "exec-ok: boot-ok" in outcome.stdout,
                "detail": outcome.stdout[:120],
            })
        except substrate_local_substrate.SubstrateUnavailable as error:
            return VerifyResult(
                ok=False, status="UNAVAILABLE", checks=checks,
                profile=profile, reason=str(error),
            )
        ok = all(check["ok"] for check in checks)
        return VerifyResult(
            ok=ok, status="READY" if ok else "NOT_READY", checks=checks,
            profile=profile,
            reason="" if ok else "؛ ".join(
                f"{c['name']}: {c['detail']}" for c in checks if not c["ok"]
            ),
        )

    def run_code(
        self, code: str, *, workspace: Path, artifacts: Path,
        timeout_s: float = 120.0,
    ) -> ExecutionOutcome:
        import time
        import uuid as uuid_mod

        from substrate.limits import E1_LIMITS_DEFAULTS
        from substrate.sandbox import NetworkMode, SandboxRequest, SandboxTermination

        ok, reason = self.available()
        if not ok:
            return ExecutionOutcome(
                environment_id=self.environment_id, backend="LOCAL",
                exit_code=-1, stdout="", stderr="",
                termination="FAILED_TO_START", detail=reason,
            )
        manager = self._manager()
        image = next(iter(manager.image_allowlist), None)
        if image is None:
            return ExecutionOutcome(
                environment_id=self.environment_id, backend="LOCAL",
                exit_code=-1, stdout="", stderr="",
                termination="FAILED_TO_START",
                detail="لا صورة تنفيذ في قائمة المدير المسموحة",
            )
        started = time.monotonic()
        request = SandboxRequest(
            sandbox_id=f"tool-{uuid_mod.uuid4().hex[:8]}",  # عقد تسمية قائم (منح/تنظيف)
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
            return ExecutionOutcome(
                environment_id=self.environment_id, backend="LOCAL",
                exit_code=-1, stdout="", stderr="",
                termination="FAILED_TO_START",
                detail=str(outcome.detail or "بلا سجل ركيزة"),
            )
        stdout = _read_text(record.stdout_reference)
        stderr = _read_text(record.stderr_reference)
        captured: dict[str, str] = {}
        if artifacts.is_dir():
            for path in sorted(artifacts.rglob("*")):
                if path.is_file():
                    captured[str(path.relative_to(artifacts))] = _read_text(
                        path, limit=100_000
                    )
        if record.termination is not SandboxTermination.COMPLETED:
            adapter = getattr(manager, "_substrate", None)
            evidence = (
                adapter.execution_evidence(request.sandbox_id)
                if adapter is not None else {}
            )
            return ExecutionOutcome(
                environment_id=self.environment_id, backend="LOCAL",
                exit_code=record.exit_code if record.exit_code is not None else -1,
                stdout=stdout, stderr=stderr,
                termination=record.termination.value,
                detail=str(
                    evidence.get("failure_reason")
                    or outcome.detail or "بلا تفصيل إضافي"
                ),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        return ExecutionOutcome(
            environment_id=self.environment_id, backend="LOCAL",
            exit_code=record.exit_code if record.exit_code is not None else -1,
            stdout=stdout, stderr=stderr, termination="COMPLETED",
            artifacts=captured,
            duration_ms=int((time.monotonic() - started) * 1000),
        )


def _read_text(reference: str | None, *, limit: int = 400_000) -> str:
    if not reference:
        return ""
    try:
        return Path(reference).read_text(
            encoding="utf-8", errors="replace"
        )[:limit]
    except OSError:
        return ""


# ------------------------------------------------------------------ #
# LOCAL COMPATIBLE — تنفيذ محلي بلا عزل، معلن صراحة (011 §4+§25+§26)
# ------------------------------------------------------------------ #

_COMPAT_PROBE_CODE = (
    "import pathlib, sys\n"
    "p = pathlib.Path(sys.argv[1])\n"
    "p.write_text('compat-ok', encoding='utf-8')\n"
    "print('exec-ok:', p.read_text(encoding='utf-8'))\n"
)


class LocalProcessBackend:
    """تنفيذ محلي متوافق بلا عزل (011 §26 COMPATIBLE_LOCAL).

    لا namespaces ولا seccomp ولا منع شبكة — subprocess مباشر على
    المضيف بمهلة فقط، وهذا **معلن في كل وصف وكل نتيجة**: الوضع
    «متوافق» للمهام غير الحساسة حين تسمح سياسة التنفيذ بذلك.
    المهام STRICT_ISOLATED لا تختار هذه الخلفية أبدًا (policy.py).

    جاهزيتها حقيقية كجيرانها: verify() ينفذ فعليًا إقلاعًا وكتابة
    وتنفيذًا والتقاطًا عبر subprocess — READY لا تمنح بلا إثبات.
    """

    backend_kind = "LOCAL"
    isolation = "NONE"

    supported_operations = (
        "probe", "create_workspace", "write_file", "read_file", "execute",
        "capture_stdout", "capture_stderr", "capture_exit_code",
        "collect_artifacts", "cleanup",
    )

    def __init__(self, environment_id: str = "local-compatible") -> None:
        self.environment_id = environment_id

    # ---- عقد مساحة العمل (011 §6) — عمليات ملفات حقيقية محليًا ---- #

    def create_workspace(self, root: Path) -> tuple[Path, Path]:
        """(workspace, artifacts) — إنشاء فعلي."""
        workspace = root / "ws"
        artifacts = root / "art"
        workspace.mkdir(parents=True, exist_ok=True)
        artifacts.mkdir(parents=True, exist_ok=True)
        return workspace, artifacts

    def write_file(self, workspace: Path, name: str, content: str) -> Path:
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def read_file(self, path: Path) -> str:
        return Path(path).read_text(encoding="utf-8", errors="replace")

    def cleanup(self, root: Path) -> None:
        import shutil

        shutil.rmtree(root, ignore_errors=True)

    def cancel(self, run_id: str) -> dict:  # noqa: ARG002 — عقد موحد
        raise BackendNotSupported(
            "LOCAL_PROCESS", "cancel",
            "التنفيذ المتزامن داخل العملية — الإلغاء عبر StopController "
            "على مستوى المهمة لا الخلفية",
        )

    def describe(self) -> dict:
        truth = runtime_truth()
        return {
            "environment_id": self.environment_id,
            "backend": "LOCAL",
            "isolation": "NONE",
            "host_platform": host_platform_label(truth),
            "os": truth["os"],
            "architecture": truth["architecture"],
            "kernel": truth["kernel"],
            "runtime": f"python {truth['python']}",
            "workspace_root": "temp dir لكل تنفيذ",
            "network_policy": "host (بلا عزل — معلن)",
            "resource_limits": "مهلة زمنية فقط — بلا rlimits (معلن)",
            "sandboxed": False,
            "compatibility_mode": True,
            "compatibility_note": (
                "وضع متوافق بلا عزل: مناسب للمهام غير الحساسة حين تسمح "
                "سياسة التنفيذ (COMPATIBLE_LOCAL). لا ادعاء عزل هنا."
            ),
            "capabilities": [
                "code_execution", "filesystem_write", "artifact_capture",
                "python_runtime",
            ],
            "available": True,
            "unavailable_reason": "",
            "runtime_truth": truth,
        }

    def _run(self, code: str, args: list[str], *,
             workspace: Path, timeout_s: float) -> tuple[int, str, str, str]:
        import sys
        import time as _time

        started = _time.monotonic()
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code, *args],
                capture_output=True, text=True, timeout=timeout_s,
                cwd=str(workspace),
            )
            elapsed = int((_time.monotonic() - started) * 1000)
            return (
                proc.returncode, proc.stdout or "", proc.stderr or "",
                f"{elapsed}ms",
            )
        except subprocess.TimeoutExpired as error:
            return (
                -1, (error.stdout or "") if isinstance(error.stdout, str) else "",
                f"TIMEOUT بعد {timeout_s}s — قُتل التنفيذ", "timeout",
            )
        except OSError as error:
            return -1, "", f"FAILED_TO_START: {error}", "startup"

    def verify(self) -> VerifyResult:
        import tempfile
        import time as _time

        profile = self.describe()
        checks: list[dict] = []
        started = _time.monotonic()
        with tempfile.TemporaryDirectory(prefix="env-compat-") as tmp:
            workspace, artifacts = self.create_workspace(Path(tmp))
            exit_code, stdout, stderr, detail = self._run(
                _COMPAT_PROBE_CODE, [str(artifacts / "probe.txt")],
                workspace=workspace, timeout_s=60.0,
            )
            checks.append({
                "name": "boot",
                "ok": "FAILED_TO_START" not in stderr and detail != "startup",
                "detail": detail,
            })
            checks.append({
                "name": "execute",
                "ok": exit_code == 0,
                "detail": f"exit={exit_code} {stderr[:120]}",
            })
            probe_file = artifacts / "probe.txt"
            checks.append({
                "name": "capture",
                "ok": probe_file.exists()
                and probe_file.read_text(encoding="utf-8") == "compat-ok"
                and "exec-ok: compat-ok" in stdout,
                "detail": stdout[:120],
            })
        ok = all(check["ok"] for check in checks)
        return VerifyResult(
            ok=ok, status="READY" if ok else "NOT_READY", checks=checks,
            profile=profile,
            reason="" if ok else "؛ ".join(
                f"{c['name']}: {c['detail']}" for c in checks if not c["ok"]
            ),
        )

    def run_code(
        self, code: str, *, workspace: Path, artifacts: Path,
        timeout_s: float = 120.0,
    ) -> ExecutionOutcome:
        import time as _time

        profile = self.describe()
        started = _time.monotonic()
        exit_code, stdout, stderr, detail = self._run(
            code, [], workspace=workspace, timeout_s=timeout_s,
        )
        captured: dict[str, str] = {}
        if artifacts.is_dir():
            for path in sorted(artifacts.rglob("*")):
                if path.is_file():
                    captured[str(path.relative_to(artifacts))] = _read_text(
                        path, limit=100_000
                    )
        termination = (
            "COMPLETED" if exit_code == 0
            else ("TIMEOUT" if detail == "timeout"
                  else "FAILED_TO_START" if detail == "startup"
                  else "COMPLETED")
        )
        return ExecutionOutcome(
            environment_id=self.environment_id,
            backend="LOCAL",
            exit_code=exit_code, stdout=stdout, stderr=stderr,
            termination=termination,
            detail=(
                f"[COMPATIBLE MODE — بلا عزل، معلن] {detail}"
                if detail else
                "[COMPATIBLE MODE — بلا عزل، معلن] host="
                f"{profile['host_platform']}"
            ),
            artifacts=captured,
            duration_ms=int((_time.monotonic() - started) * 1000),
        )


#: توافق خلفي بالاسم القديم (اختبارات 010 ووثائقها)
LocalLinuxBackend = LocalSandboxBackend


# ------------------------------------------------------------------ #
# REMOTE_WORKER — عامل بعيد عبر بروتوكول HTTP حقيقي (§21)
# ------------------------------------------------------------------ #

class RemoteWorkerBackend:
    """خلفية العامل البعيد — العميل في مستوى التحكم.

    الطرف الآخر: scripts/execution_worker.py (عامل حقيقي stdlib-only).
    البروتوكول (011 §9 — register/heartbeat/capabilities/probe/execute/
    stream/upload artifact/cancel؛ v1: النتيجة سجل واحد يُنشر أحداثًا
    من مستوى التحكم — معلن لا مفترض):

        GET  /health        نبضات: {ok, uptime_s, active_runs}
        GET  /register      تعريف العامل (نفس /capabilities — idempotent)
        GET  /capabilities  وصف البيئة الفعلي من العامل نفسه
        POST /probe         فحوص إقلاع/كتابة/تنفيذ/التقاط لدى العامل
        POST /run           {run_id, code, timeout_s} → سجل التنفيذ
        POST /cancel        {run_id} → إلغاء جارٍ
    """

    backend_kind = "REMOTE_WORKER"
    #: العزل يقرؤه describe() من العامل نفسه (sandboxed المعلن لديه)
    isolation = "WORKER_DECLARED"

    supported_operations = (
        "probe", "execute", "capture_stdout", "capture_stderr",
        "capture_exit_code", "collect_artifacts", "cancel",
    )

    def __init__(self, endpoint: str, token: str = "",
                 environment_id: str = "remote-worker") -> None:
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.environment_id = environment_id

    def _request(self, method: str, path: str,
                 payload: dict | None = None,
                 timeout: float = WORKER_HTTP_TIMEOUT,
                 *, with_auth: bool = True) -> dict:
        headers = {"Content-Type": "application/json"}
        if with_auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.endpoint + path, data=data, method=method, headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = ""
            try:
                body = error.read().decode("utf-8", "replace")[:200]
            except OSError:
                pass
            raise WorkerHttpError(error.code, body or error.reason) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ConnectionError(
                f"تعذر الوصول للعامل {self.endpoint}: {error}"
            ) from error
        except ValueError as error:
            raise ConnectionError(
                f"رد العامل ليس JSON سليمًا: {error}"
            ) from error

    def _request_status(self, method: str, path: str,
                        timeout: float = 15.0) -> tuple[int, str]:
        """(HTTP status, body) — للتفريق بين عدم الوصول ورفض التوكن."""
        try:
            payload = self._request(method, path, timeout=timeout)
            return 200, json.dumps(payload)[:300]
        except WorkerHttpError as error:
            return error.code, error.body
        except ConnectionError as error:
            raise error from error

    def health(self) -> dict:
        return self._request("GET", "/health", timeout=15.0)

    def cancel(self, run_id: str) -> dict:
        """إلغاء تنفيذ جارٍ لدى العامل (011 §6 cancel) — POST /cancel."""
        return self._request("POST", "/cancel", payload={"run_id": run_id})

    def create_workspace(self, root: Path) -> tuple[Path, Path]:  # noqa: ARG002
        raise BackendNotSupported(
            "REMOTE_WORKER", "create_workspace",
            "مساحة العمل لدى العامل — تُدار ضمن /run (البروتوكول v1)",
        )

    def write_file(self, workspace: Path, name: str, content: str) -> Path:  # noqa: ARG002
        raise BackendNotSupported(
            "REMOTE_WORKER", "write_file",
            "كتابة الملفات لدى العامل عبر /run (البروتوكول v1) — "
            "المسار الحقيقي: الكود المُنفَّذ يكتب ملفاته بنفسه",
        )

    def describe(self) -> dict:
        try:
            caps = self._request("GET", "/capabilities", timeout=15.0)
        except (ConnectionError, WorkerHttpError) as error:
            return {
                "environment_id": self.environment_id,
                "backend": "REMOTE_WORKER", "endpoint": self.endpoint,
                "isolation": "REMOTE",
                "host_platform": f"remote ({self.endpoint})",
                "os": "?", "architecture": "?", "runtime": "?",
                "workspace_root": "worker-side",
                "network_policy": "worker-declared",
                "resource_limits": "worker-declared",
                "sandboxed": False, "capabilities": [],
                "available": False, "unavailable_reason": str(error),
            }
        caps["environment_id"] = self.environment_id
        caps["backend"] = "REMOTE_WORKER"
        caps["isolation"] = "REMOTE" if caps.get("sandboxed") else "NONE"
        caps["endpoint"] = self.endpoint
        caps["host_platform"] = (
            f"{caps.get('os', '?')}/{caps.get('architecture', '?')}"
        )
        caps["available"] = True
        return caps

    def verify(self) -> VerifyResult:
        """سلم جاهزية العامل (011 §10) — درجات مسماة، READY آخرها.

        connectivity → authentication → heartbeat → environment_probe →
        workspace_probe → execute_probe → artifact_probe — أي درجة
        تفشل توقف السلم بسببها بالضبط (لا «نجاح» مجملًا ولا READY
        بمجرد التسجيل).
        """
        import time

        checks: list[dict] = []
        started = time.monotonic()

        # 1) connectivity — أي رد HTTP (ولو 401) = العامل موجود
        try:
            status, _body = self._request_status("GET", "/health")
            checks.append({
                "name": "connectivity", "ok": status in (200, 401, 403),
                "detail": f"HTTP {status}",
            })
        except ConnectionError as error:
            checks.append({
                "name": "connectivity", "ok": False,
                "detail": str(error)[:200],
            })
            return VerifyResult(
                ok=False, status="NOT_READY", checks=checks,
                profile=self.describe(),
                reason="connectivity: " + str(error)[:200],
            )

        # 2) authentication — الطلب الموثق يُقبل
        try:
            status, body = self._request_status("GET", "/capabilities")
            checks.append({
                "name": "authentication", "ok": status == 200,
                "detail": f"HTTP {status}" + (
                    " — توكن مرفوض" if status in (401, 403) else ""
                ) if status != 200 else "موثق",
            })
            if status != 200:
                return VerifyResult(
                    ok=False, status="NOT_READY", checks=checks,
                    profile=self.describe(),
                    reason=f"authentication: HTTP {status} — {body[:150]}",
                )
        except ConnectionError as error:
            checks.append({
                "name": "authentication", "ok": False,
                "detail": str(error)[:200],
            })
            return VerifyResult(
                ok=False, status="NOT_READY", checks=checks,
                profile=self.describe(), reason=str(error)[:300],
            )

        # 3) heartbeat — العامل حي لا مجرد مستجيب
        try:
            health = self.health()
            checks.append({
                "name": "heartbeat", "ok": bool(health.get("ok")),
                "detail": (
                    f"uptime={health.get('uptime_s')}s "
                    f"active={health.get('active_runs')}"
                ),
            })
        except (ConnectionError, WorkerHttpError) as error:
            checks.append({
                "name": "heartbeat", "ok": False, "detail": str(error)[:200],
            })
            return VerifyResult(
                ok=False, status="NOT_READY", checks=checks,
                profile=self.describe(),
                reason="heartbeat: " + str(error)[:200],
            )

        # 4) environment_probe — العامل يصف بيئته الفعلية
        profile = self.describe()
        env_ok = (
            profile.get("os") not in (None, "?", "")
            and profile.get("architecture") not in (None, "?", "")
        )
        checks.append({
            "name": "environment_probe", "ok": env_ok,
            "detail": f"{profile.get('os')}/{profile.get('architecture')} "
                      f"runtime={profile.get('runtime', '?')}",
        })

        # 5-7) فحوص العامل الفعلية — إقلاع/تنفيذ/التقاط
        try:
            probe = self._request("POST", "/probe", payload={}, timeout=120.0)
        except (ConnectionError, WorkerHttpError) as error:
            checks.append({
                "name": "execute_probe", "ok": False,
                "detail": str(error)[:200],
            })
            return VerifyResult(
                ok=False, status="NOT_READY", checks=checks,
                profile=profile, reason=str(error)[:300],
            )
        by_name = {str(c.get("name")): c for c in probe.get("checks", [])}
        checks.append({
            "name": "workspace_probe",
            "ok": bool(by_name.get("boot", {}).get("ok")),
            "detail": str(by_name.get("boot", {}).get("detail", "غائب"))[:150],
        })
        checks.append({
            "name": "execute_probe",
            "ok": bool(by_name.get("write+execute", {}).get("ok")),
            "detail": str(
                by_name.get("write+execute", {}).get("detail", "غائب")
            )[:150],
        })
        checks.append({
            "name": "artifact_probe",
            "ok": bool(by_name.get("capture", {}).get("ok")),
            "detail": str(by_name.get("capture", {}).get("detail", "غائب"))
            [:150],
        })

        ok = all(check["ok"] for check in checks)
        reason = "" if ok else "؛ ".join(
            f"{c['name']}: {c['detail']}" for c in checks if not c["ok"]
        )
        result = VerifyResult(
            ok=ok, status="READY" if ok else "NOT_READY",
            checks=checks, profile=profile, reason=reason,
        )
        result.checks_latency_ms = int((time.monotonic() - started) * 1000)  # type: ignore[attr-defined]
        return result

    def run_code(
        self, code: str, *, workspace: Path, artifacts: Path,
        timeout_s: float = 120.0,
    ) -> ExecutionOutcome:
        import base64
        import time
        import uuid as uuid_mod

        run_id = f"run-{uuid_mod.uuid4().hex[:10]}"
        started = time.monotonic()
        try:
            result = self._request("POST", "/run", payload={
                "run_id": run_id, "code": code, "timeout_s": timeout_s,
            })
        except (ConnectionError, WorkerHttpError) as error:
            return ExecutionOutcome(
                environment_id=self.environment_id,
                backend="REMOTE_WORKER", exit_code=-1, stdout="", stderr="",
                termination="FAILED_TO_START", detail=str(error),
            )
        artifacts_out: dict[str, str] = {}
        for item in result.get("artifacts", []):
            name = str(item.get("name", ""))
            if not name:
                continue
            try:
                artifacts_out[name] = base64.b64decode(
                    item.get("b64", "")
                ).decode("utf-8", "replace")
                target = artifacts / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(artifacts_out[name], encoding="utf-8")
            except (ValueError, OSError):
                continue
        return ExecutionOutcome(
            environment_id=self.environment_id, backend="REMOTE_WORKER",
            exit_code=int(result.get("exit_code", -1)),
            stdout=str(result.get("stdout", ""))[:400_000],
            stderr=str(result.get("stderr", ""))[:400_000],
            termination=str(result.get("termination", "UNKNOWN")),
            detail=str(result.get("detail", "")),
            artifacts=artifacts_out,
            duration_ms=int((time.monotonic() - started) * 1000),
        )


__all__ = [
    "BackendNotSupported",
    "ExecutionBackend",
    "ExecutionOutcome",
    "LocalLinuxBackend",
    "LocalProcessBackend",
    "LocalSandboxBackend",
    "RemoteWorkerBackend",
    "VerifyResult",
    "WorkerHttpError",
    "WORKER_HTTP_TIMEOUT",
    "host_platform_label",
    "local_environment_name",
    "runtime_truth",
]
