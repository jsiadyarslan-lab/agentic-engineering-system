"""عقد حل مساحة عمل التنفيذ (الأمر 013.3 §7) — المصدر الوحيد لكل مطلق عملية.

الجذر الذي عالجه هذا الموديول (التشخيص الحرفي 013.3 §1):

    POST /api/execution/environments/{id}/test-run
        ↓
    backend.run_code(code, workspace=Path(tmp)/"ws", …)   ← الدليل «ws»
        ↓                                                    لم يُنشأ قط
    LocalProcessBackend._run → subprocess.run(cwd=str(workspace))
        ↓
    Windows CreateProcess(cwd غير موجود) → [WinError 267]
        ↓
    "FAILED_TO_START: [WinError 267] The directory name is invalid"

القواعد الجوهرية (§2+§3+§4+§6):

1. لا يُمرَّر مسار Linux (‎/workspace، ‎/work، ‎/tmp، ‎/home/…) كـ cwd
   لعملية Windows أبدًا — يُرفض قبل CreateProcess لا بعده (LINUX_PATH_ON_WINDOWS).
2. كل مطلق عملية يستهلك نتيجة ``resolve_execution_workspace`` حصرًا:
   لا يبني cwd بنفسه، ولا «يأمل» أن الدليل موجود.
3. التسلسل الإلزامي (§6): SELECT RUNTIME ← CREATE WORKSPACE ← VERIFY
   ← START WORKER — لا «START WORKER ثم رجاء أن cwd موجود».
4. حدود التنفيذ الأربعة معلنة: WINDOWS_PROCESS (cwd مسار Windows مطلق
   موجود) / POSIX_PROCESS (مسار POSIX موجود) / WSL_PROCESS (المسار داخل
   WSL يُحل داخل WSL نفسه عبر wslpath — لا تخمين ترجمة) /
   REMOTE_PROCESS (cwd يُحل على المضيف البعيد لدى العامل).
5. WinError 267 وأشباهه ليست «فشل تنفيذ» عامًا بل RUNTIME_WORKSPACE_INVALID
   بتقرير مهيكل (host/runtime/cwd/environment_id/worker_id/execution_mode)
   — ثم إصلاح مساحة عمل واحد وإعادة محاولة واحدة، لا حلقة إعادة (§9+§10).
"""

from __future__ import annotations

import platform as _platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

#: أوضاع التنفيذ الأربعة (§2+§3+§4) — مفردة مقفلة.
EXECUTION_MODES: tuple[str, ...] = (
    "WINDOWS_PROCESS",   # عملية مباشرة على مضيف Windows — cwd مسار Windows
    "POSIX_PROCESS",     # عملية مباشرة على مضيف Linux — cwd مسار POSIX
    "WSL_PROCESS",       # عبر wsl.exe — المسار الفعلي يُحل داخل WSL
    "REMOTE_PROCESS",    # عبر عامل بعيد — cwd يُحل على المضيف البعيد
)

#: رمز فشل مساحة العمل (§9) — تصنيف صريح لا «فشل عام».
RUNTIME_WORKSPACE_INVALID = "RUNTIME_WORKSPACE_INVALID"

#: أسباب رفض/فشل مساحة العمل المسماة حرفيًا (تفاصيل التقرير المهيكل).
WORKSPACE_REASONS: dict[str, str] = {
    "LINUX_PATH_ON_WINDOWS": (
        "مسار بنمط Linux مُرَّر كـ cwd لعملية Windows — مرفوض قبل "
        "CreateProcess (قاعدة 013.3 §2)"
    ),
    "WORKSPACE_NOT_CREATED": "تعذر إنشاء دليل مساحة العمل",
    "WORKSPACE_NOT_DIRECTORY": "المسار موجود لكنه ليس دليلًا",
    "WINDOWS_CWD_INVALID": (
        "cwd غير صالح لدى CreateProcess على Windows "
        "(WinError 267 ERROR_DIRECTORY أو ما يماثله)"
    ),
    "WORKSPACE_MISSING_AT_LAUNCH": (
        "دليل مساحة العمل غير موجود لحظة الإطلاق"
    ),
    "REPAIR_FAILED": (
        "فشل إصلاح مساحة العمل (إنشاء/تحقق) — لا إعادة محاولة أخرى"
    ),
}


def host_os_detected() -> str:
    """نظام مضيف التحكم الفعلي — من runtime لا من إعداد."""
    return _platform.system() or "Unknown"


def looks_like_posix_absolute(path: str) -> bool:
    """هل النمط مسار POSIX مطلق (‎/…)؟ — على Windows هذا مؤشر مسار Linux.

    لا يتحقق من الوجود؛ نمط فقط. يُستخدم للرفض المبكر قبل أي
    CreateProcess (قاعدة §2): مسار مثل ‎/workspace أو ‎/work أو ‎/tmp
    على مضيف Windows مرفوض حرفيًا.
    """
    text = str(path).strip()
    if not text:
        return False
    if text.startswith("/"):
        return True
    # صيغة MSYS/Cygwin النسبية بادئة محرك: C:/… ليست POSIX
    return False


def is_windows_absolute(path: str) -> bool:
    """مسار Windows مطلق (حرف محرك ‎C:\\… أو UNC ‎\\\\server\\share)."""
    text = str(path).strip()
    if len(text) >= 3 and text[1] == ":" and text[2] in ("\\", "/"):
        return True
    return text.startswith("\\\\")


@dataclass(frozen=True)
class ExecutionWorkspace:
    """نتيجة عقد حل مساحة العمل (§7) — كل مطلق عملية يستهلكها حصرًا.

    الحقول كما في الأمر حرفيًا:

    host_path      مسار على مضيف التحكم ("" للعامل البعيد)
    runtime_path   المسار داخل runtime التنفيذ (قد يختلف عن المضيف:
                   WSL يُترجم عبر wslpath داخل WSL نفسه)
    execution_mode أحد EXECUTION_MODES
    """

    environment_id: str
    execution_mode: str
    host_path: str
    runtime_path: str
    host_os: str = ""
    worker_id: str = ""
    created: bool = False          # أُنشئ الدليل فعليًا في هذا الاستدعاء
    preflight: dict = field(default_factory=dict)  # برهان التحقق قبل الإطلاق

    def to_dict(self) -> dict:
        return {
            "environment_id": self.environment_id,
            "execution_mode": self.execution_mode,
            "host_path": self.host_path,
            "runtime_path": self.runtime_path,
            "host_os": self.host_os,
            "worker_id": self.worker_id,
            "created": self.created,
            "preflight": dict(self.preflight),
        }


class WorkspaceInvalid(Exception):
    """فشل مساحة عمل مُشخَّص (§9) — تقرير مهيكل لا رسالة عامة.

    report يحمل حرفيًا: code/reason/host/runtime/cwd/workspace/
    environment_id/worker_id/execution_mode/winerror/errno/original.
    """

    def __init__(self, report: dict) -> None:
        self.report = {
            "code": RUNTIME_WORKSPACE_INVALID,
            **report,
        }
        super().__init__(self.describe())

    def describe(self) -> str:
        r = self.report
        parts = [
            f"{RUNTIME_WORKSPACE_INVALID} — {r.get('reason_text', '')}",
            f"cwd={r.get('cwd', '')}",
            f"host={r.get('host', '')}",
            f"runtime={r.get('runtime', '')}",
            f"execution_mode={r.get('execution_mode', '')}",
            f"environment_id={r.get('environment_id', '')}",
            f"worker_id={r.get('worker_id', '')}",
        ]
        if r.get("winerror"):
            parts.append(f"winerror={r['winerror']}")
        if r.get("errno"):
            parts.append(f"errno={r['errno']}")
        if r.get("original"):
            parts.append(f"original={str(r['original'])[:160]}")
        return "؛ ".join(p for p in parts if p)


def execution_mode_of_environment(environment: dict | None,
                                  *, host_os: str | None = None) -> str:
    """وضع التنفيذ لبيئة مسجلة — القرار البنيوي قبل أي مسار.

    REMOTE_WORKER ← REMOTE_PROCESS (cwd يُحل لدى العامل §4)؛
    LOCAL + sandboxed ← ركيزة Linux/x86_64 (POSIX_PROCESS)؛
    LOCAL + بلا عزل على Windows ← WINDOWS_PROCESS؛ على غيره POSIX_PROCESS.
    """
    host = host_os or host_os_detected()
    if not environment:
        return "WINDOWS_PROCESS" if host == "Windows" else "POSIX_PROCESS"
    backend = str(environment.get("backend", ""))
    if backend == "REMOTE_WORKER":
        return "REMOTE_PROCESS"
    if bool(environment.get("sandboxed")):
        return "POSIX_PROCESS"  # الركيزة المعزولة Linux/x86_64 حصرًا
    return "WINDOWS_PROCESS" if host == "Windows" else "POSIX_PROCESS"


def resolve_execution_workspace(
    environment: dict | None,
    *,
    workspace: Path | str | None,
    artifacts: Path | str | None = None,
    host_os: str | None = None,
    create: bool = True,
    worker_id: str = "",
    runtime_path_override: str = "",
) -> ExecutionWorkspace:
    """حل مساحة العمل الموحد (§7) — إنشاء ثم تحقق قبل أي إطلاق.

    WINDOWS_PROCESS: رفض مسار POSIX أولًا (قبل CreateProcess)، ثم
    إنشاء الدليل إن غاب، ثم التحقق absolute+exists+is_dir.
    POSIX_PROCESS: نفس التسلسل بمسار POSIX.
    REMOTE_PROCESS: لا مسار مضيف — cwd يُدار لدى العامل لكل تشغيل
    (يُبرهن عليه سلم /probe لدى العامل، لا محليًا).
    """
    mode = execution_mode_of_environment(environment, host_os=host_os)
    host = host_os or host_os_detected()
    env_id = str((environment or {}).get("id", "") or "")

    if mode == "REMOTE_PROCESS":
        return ExecutionWorkspace(
            environment_id=env_id, execution_mode=mode,
            host_path="", runtime_path="worker-managed (يُنشأ لكل تشغيل "
            "داخل العامل ويُبرهن عبر /probe)",
            host_os=host, worker_id=worker_id,
            preflight={"note": "cwd resolved on the remote host per run "
                               "(013.3 §4) — لا مسار مضيف محلي"},
        )

    raw = "" if workspace is None else str(workspace)
    if not raw:
        raise WorkspaceInvalid({
            "reason": "WORKSPACE_MISSING_AT_LAUNCH",
            "reason_text": WORKSPACE_REASONS["WORKSPACE_MISSING_AT_LAUNCH"],
            "cwd": "", "host": host, "runtime": "python",
            "environment_id": env_id, "worker_id": worker_id,
            "execution_mode": mode,
        })

    # (§2) الرفض المبكر: مسار بنمط Linux على مضيف Windows — قبل أي
    # CreateProcess. هذا هو بالضبط الجذر الذي أنتج WinError 267.
    if host == "Windows" and looks_like_posix_absolute(raw):
        raise WorkspaceInvalid({
            "reason": "LINUX_PATH_ON_WINDOWS",
            "reason_text": WORKSPACE_REASONS["LINUX_PATH_ON_WINDOWS"],
            "cwd": raw, "host": host, "runtime": "python",
            "environment_id": env_id, "worker_id": worker_id,
            "execution_mode": mode,
        })

    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    created = False
    if create and not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=True)
            created = True
        except OSError as error:
            raise WorkspaceInvalid({
                "reason": "WORKSPACE_NOT_CREATED",
                "reason_text": WORKSPACE_REASONS["WORKSPACE_NOT_CREATED"],
                "cwd": str(path), "host": host, "runtime": "python",
                "environment_id": env_id, "worker_id": worker_id,
                "execution_mode": mode, "errno": error.errno,
                "original": error,
            }) from error
    if not path.exists():
        raise WorkspaceInvalid({
            "reason": "WORKSPACE_NOT_CREATED",
            "reason_text": WORKSPACE_REASONS["WORKSPACE_NOT_CREATED"]
            + f" — {path}",
            "cwd": str(path), "host": host, "runtime": "python",
            "environment_id": env_id, "worker_id": worker_id,
            "execution_mode": mode,
        })
    if not path.is_dir():
        raise WorkspaceInvalid({
            "reason": "WORKSPACE_NOT_DIRECTORY",
            "reason_text": WORKSPACE_REASONS["WORKSPACE_NOT_DIRECTORY"],
            "cwd": str(path), "host": host, "runtime": "python",
            "environment_id": env_id, "worker_id": worker_id,
            "execution_mode": mode,
        })

    # دليل الأدلة إن مُرر: يُنشأ كذلك (نفس عقد الخلفية §6)
    if artifacts is not None and str(artifacts):
        art = Path(str(artifacts))
        if not art.is_absolute():
            art = Path.cwd() / art
        if not art.exists():
            try:
                art.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass  # الأدلة اختيارية للالتقاط؛ فشلها لا يحجب الإطلاق

    runtime_path = runtime_path_override or str(path)
    return ExecutionWorkspace(
        environment_id=env_id, execution_mode=mode,
        host_path=str(path), runtime_path=runtime_path,
        host_os=host, worker_id=worker_id, created=created,
        preflight={
            "cwd_exists": True, "cwd_is_directory": True,
            "absolute": True,
            "verified_at_launch": True,
            "note": "CREATE WORKSPACE → VERIFY → START (013.3 §6)",
        },
    )


def repair_workspace(
    environment: dict | None,
    *,
    workspace: Path | str,
    host_os: str | None = None,
    worker_id: str = "",
) -> ExecutionWorkspace:
    """إصلاح مساحة عمل (§10): DIAGNOSE ← REPAIR ← VERIFY — مرة واحدة.

    يُستدعى بعد فشل إطلاق مصنف RUNTIME_WORKSPACE_INVALID فقط؛ الفشل
    هنا نهائي (REPAIR_FAILED) — لا إعادة محاولة ثالثة أبدًا.
    """
    try:
        return resolve_execution_workspace(
            environment, workspace=workspace, host_os=host_os,
            create=True, worker_id=worker_id,
        )
    except WorkspaceInvalid as error:
        report = dict(error.report)
        # السبب الأصلي يبقى مرئيًا: فشل الإصلاح لا يمحو التشخيص
        report["repair_of"] = report.get("reason", "")
        report["reason"] = "REPAIR_FAILED"
        report["reason_text"] = (
            WORKSPACE_REASONS["REPAIR_FAILED"]
            + f" — {report.get('reason_text', '')}"
        )
        raise WorkspaceInvalid(report) from error


def classify_process_oserror(
    error: OSError, *, cwd: str,
    environment_id: str = "", worker_id: str = "",
    execution_mode: str = "", host_os: str | None = None,
) -> dict | None:
    """تصنيف OSError الإطلاقي (§9) — WinError 267 ليس «فشل تنفيذ» عامًا.

    يعيد تقرير RUNTIME_WORKSPACE_INVALID مهيكلًا حين يكون الخطأ في cwd
    (ERROR_DIRECTORY=267 على Windows، ENOTDIR/ENOENT على cwd في POSIX)،
    أو None إن كان الخطأ من عائلة أخرى (تنفيذي غير قابل للتشخيص هنا).
    """
    host = host_os or host_os_detected()
    winerror = getattr(error, "winerror", None)
    errno = getattr(error, "errno", None)
    text = str(error)

    is_cwd_error = False
    reason = ""
    if winerror == 267:  # ERROR_DIRECTORY — cwd غير صالح لدى CreateProcess
        is_cwd_error = True
        reason = "WINDOWS_CWD_INVALID"
    elif isinstance(error, NotADirectoryError):
        is_cwd_error = True
        reason = "WORKSPACE_NOT_DIRECTORY"
    elif isinstance(error, FileNotFoundError) and cwd:
        # ENOENT: إن كان المسار الغائب هو cwd نفسه (أو أحدآبه) فهو فشل
        # مساحة عمل؛ إن كان الملف التنفيذي فليس مساحة عمل (WinError 2
        # للتنفيذي يفترض أن يُحل قبلها عبر sys.executable المطلق).
        target = str(getattr(error, "filename", "") or "")
        if not target or target == cwd or cwd.startswith(target):
            is_cwd_error = True
            reason = "WORKSPACE_MISSING_AT_LAUNCH"
    elif errno in (20, 2) and cwd and (
        "directory" in text.lower() or "no such file" in text.lower()
    ):
        is_cwd_error = True
        reason = "WORKSPACE_MISSING_AT_LAUNCH"

    if not is_cwd_error:
        return None
    return {
        "code": RUNTIME_WORKSPACE_INVALID,
        "reason": reason,
        "reason_text": WORKSPACE_REASONS.get(reason, reason),
        "cwd": cwd,
        "host": host,
        "runtime": "python",
        "execution_mode": execution_mode,
        "environment_id": environment_id,
        "worker_id": worker_id,
        "winerror": winerror,
        "errno": errno,
        "original": text[:200],
    }


#: كود اختبار العملية المصغّر (§8) — بنفس حد التنفيذ: يطبع cwd ويكتب
#: ويقرأ ويحذف ملفًا. المخرج PROBE-JSON قابل للتحقق آليًا.
PREFLIGHT_PROCESS_CODE = (
    "import json, os, pathlib, sys\n"
    "p = pathlib.Path('preflight-0133.txt')\n"
    "p.write_text('ok', encoding='utf-8')\n"
    "read_back = p.read_text(encoding='utf-8') == 'ok'\n"
    "p.unlink()\n"
    "print('PREFLIGHT-JSON:' + json.dumps({\n"
    "    'cwd': os.getcwd(),\n"
    "    'write_read_delete': read_back and not p.exists(),\n"
    "    'python': sys.version_info[:3],\n"
    "}))\n"
)


def preflight_process_test(
    *, cwd: Path, timeout_s: float = 30.0,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    """اختبار عملية مصغّر قبل العامل الحقيقي (§8) — بنفس حد التنفيذ.

    للحدود المحلية (WINDOWS_PROCESS/POSIX_PROCESS): عملية python حقيقية
    بـ cwd المسؤول، تكتب وتقرأ وتحذف ملفًا وتطبع cwd. لحدود WSL/REMOTE:
    يديره طبقة WSL (wsl_verify_runtime) وسلم العامل (/probe) — لا هنا.
    """
    import sys

    try:
        proc = runner(
            [sys.executable, "-c", PREFLIGHT_PROCESS_CODE],
            capture_output=True, text=True, timeout=timeout_s,
            cwd=str(cwd),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "error": str(error)[:200], "cwd": str(cwd)}

    report: dict[str, Any] = {}
    for line in (proc.stdout or "").splitlines():
        if line.startswith("PREFLIGHT-JSON:"):
            try:
                import json

                report = json.loads(line[len("PREFLIGHT-JSON:"):])
            except ValueError:
                report = {}
            break
    ok = (
        proc.returncode == 0
        and bool(report.get("write_read_delete"))
        and bool(report.get("cwd"))
    )
    return {
        "ok": ok,
        "exit_code": proc.returncode,
        "cwd": report.get("cwd", ""),
        "write_read_delete": bool(report.get("write_read_delete")),
        "python": list(report.get("python", [])),
        "stderr": (proc.stderr or "")[:200],
        "command": [sys.executable, "-c", "<preflight-0133>"],
    }


__all__ = [
    "EXECUTION_MODES",
    "ExecutionWorkspace",
    "RUNTIME_WORKSPACE_INVALID",
    "WORKSPACE_REASONS",
    "WorkspaceInvalid",
    "classify_process_oserror",
    "execution_mode_of_environment",
    "host_os_detected",
    "is_windows_absolute",
    "looks_like_posix_absolute",
    "preflight_process_test",
    "repair_workspace",
    "resolve_execution_workspace",
]
