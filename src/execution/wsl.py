"""حد تنفيذ WSL2 (الأمر 013.3 §3) — Windows ← wsl.exe ← Linux ← العامل.

القاعدة الحاسمة (بالأمر حرفيًا):

    لا يُطلق عامل Linux عبر Windows CreateProcess بـ cwd بنمط Linux.

حد التنفيذ الصريح المطلوب:

    Windows (مضيف التحكم)
        ↓  wsl.exe  (عملية Windows — cwd مسار Windows صالح أو لا شيء)
    Linux runtime (WSL2)
        ↓  المسار يُحل داخل WSL نفسه (wslpath + تحقق فعلي)
    python scripts/execution_worker.py
        ↓  HTTP
    مستوى التحكم (RemoteWorkerBackend)

كل مسار داخل WSL يُحل **داخل WSL** عبر ``wslpath`` — لا تخمين ترجمة
أبدًا. وقبل إطلاق العامل يُتحقق داخل WSL حرفيًا: pwd، test -d،
python3 --version (§3). الرفض أو الفشل في أي درجة = خطأ مسمّى صادق،
لا READY كاذبة ولا محاولة تشغيل العامل كعملية Windows (§5).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

#: منفذ عامل WSL2 الافتراضي (8900 قد يستخدمه عامل المالك اليدوي).
WSL_WORKER_DEFAULT_PORT = 8901

#: اسم بيئة عامل WSL2 المسجلة في القاعدة.
WSL_ENVIRONMENT_NAME = "wsl2-linux"


def _wsl_runner(
    args: list[str], *, timeout: float = 20.0,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> tuple[int, str]:
    """تشغيل أمر عبر wsl.exe — بلا cwd إطلاقًا (قاعدة §3 الجذرية).

    لا يُمرَّر cwd أبدًا لهذه العملية: أي cwd بنمط Linux لعملية
    Windows هو بالضبط ما أنتج WinError 267؛ ووراثة cwd الخادم
    (مسار Windows صالح) هي السلوك الآمن الوحيد.
    """
    run = runner or subprocess.run
    try:
        proc = run(
            ["wsl.exe", *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return proc.returncode, (proc.stdout or proc.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return -1, str(error)[:200]


def wsl_available(
    *, runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> dict:
    """اكتشاف WSL2 الفعلي (§5: لا افتراض توفر أبدًا).

    الدرجة الوحيدة المقبولة: wsl.exe يعمل ويطلق ``uname -sm`` داخل
    WSL ويعيد Linux/x86_64 (أو aarch64 — يُعلن كما هو).
    """
    import shutil

    detail_steps: dict[str, Any] = {}
    exe = shutil.which("wsl.exe") or shutil.which("wsl")
    detail_steps["wsl_exe"] = bool(exe)
    if not exe:
        return {
            "available": False,
            "reason": "WSL2_UNAVAILABLE",
            "detail": "wsl.exe غير موجود على PATH — لا WSL2 مثبت",
            "steps": detail_steps,
        }

    code, out = _wsl_runner(["-e", "uname", "-sm"], runner=runner)
    detail_steps["uname"] = out[:120]
    if code != 0 or not out.lower().startswith("linux"):
        return {
            "available": False,
            "reason": "WSL2_NO_DISTRO",
            "detail": (
                f"wsl.exe موجود لكن لا توزيعة Linux تعمل: {out[:160]}"
            ),
            "steps": detail_steps,
        }

    parts = out.split()
    os_name, arch = (parts + ["?", "?"])[:2]
    code_py, py_out = _wsl_runner(
        ["-e", "python3", "--version"], runner=runner,
    )
    detail_steps["python3"] = py_out[:80]
    if code_py != 0 or "Python" not in py_out:
        return {
            "available": False,
            "reason": "WSL2_NO_PYTHON3",
            "detail": (
                "توزيعة WSL تعمل لكن python3 غير متاح داخلها: "
                + py_out[:160]
            ),
            "steps": detail_steps,
        }

    return {
        "available": True,
        "reason": "",
        "detail": f"{os_name}/{arch} — {py_out}",
        "os": "Linux",
        "architecture": arch,
        "python": py_out.split()[-1] if py_out else "",
        "steps": detail_steps,
    }


def wsl_resolve_path(
    windows_path: str,
    *, runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> str:
    """ترجمة مسار Windows إلى مسار Linux — داخل WSL نفسه (wslpath).

    لا تُخمَّن الترجمة أبدًا (§3: "Do not guess the translation").
    """
    code, out = _wsl_runner(
        ["-e", "wslpath", "-a", str(windows_path)], runner=runner,
    )
    if code != 0 or not out.startswith("/"):
        raise RuntimeError(
            f"تعذر حل المسار داخل WSL عبر wslpath: {windows_path!r} ← "
            f"exit={code} out={out[:160]}"
        )
    return out.strip()


def wsl_verify_runtime(
    linux_path: str,
    *, runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> dict:
    """التحقق داخل WSL قبل إطلاق العامل (§3 حرفيًا): pwd + test -d +
    python3 --version — على المسار الفعلي داخل WSL."""
    quoted = str(linux_path).replace("'", "'\\''")
    code, out = _wsl_runner(
        ["-e", "sh", "-c",
         f"cd '{quoted}' 2>/dev/null && pwd && test -d . && "
         "python3 --version"],
        runner=runner,
    )
    lines = [line for line in out.splitlines() if line.strip()]
    ok = code == 0 and bool(lines)
    return {
        "ok": ok,
        "pwd_inside_wsl": lines[0] if lines else "",
        "python3": next(
            (line for line in lines if "Python" in line), ""
        ),
        "detail": out[:200] if not ok else "؛ ".join(lines),
    }


def wsl_create_workspace(
    linux_path: str,
    *, runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> dict:
    """إنشاء مساحة العمل داخل WSL (§6) — mkdir -p ثم تحقق بعده."""
    quoted = str(linux_path).replace("'", "'\\''")
    code, out = _wsl_runner(
        ["-e", "sh", "-c",
         f"mkdir -p '{quoted}' && test -d '{quoted}' && echo WORKSPACE_OK"],
        runner=runner,
    )
    ok = code == 0 and "WORKSPACE_OK" in out
    return {
        "ok": ok,
        "runtime_path": str(linux_path),
        "detail": out[:200] if not ok else f"WORKSPACE_OK: {linux_path}",
    }


def launch_wsl_worker(
    *,
    repo_windows_root: Path,
    port: int = WSL_WORKER_DEFAULT_PORT,
    token: str = "",
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    spawner: Callable[..., subprocess.Popen] | None = None,
) -> dict:
    """إطلاق العامل داخل WSL2 عبر حد صريح (§3) — التسلسل الإلزامي:

    resolve repo داخل WSL (wslpath) ← verify داخل WSL (pwd/test -d/
    python3) ← CREATE WORKSPACE داخل WSL ← START WORKER عبر wsl.exe.

    عملية wsl.exe نفسها تُطلق بلا cwd (أو بمسار Windows) — **أبدًا**
    ليس بمسار Linux؛ العامل يدير cwd داخل Linux بنفسه.
    """
    repo_win = str(Path(repo_windows_root).resolve())
    repo_linux = wsl_resolve_path(repo_win, runner=runner)

    verify = wsl_verify_runtime(repo_linux, runner=runner)
    if not verify["ok"]:
        return {
            "ok": False,
            "stage": "VERIFY_WSL_RUNTIME",
            "reason": "WSL_RUNTIME_VERIFY_FAILED",
            "detail": (
                f"التحقق داخل WSL فشل على {repo_linux}: "
                + verify["detail"]
            ),
            "repo_linux": repo_linux,
        }

    workspace_linux = f"{repo_linux}/runtime/wsl-worker"
    workspace = wsl_create_workspace(workspace_linux, runner=runner)
    if not workspace["ok"]:
        return {
            "ok": False,
            "stage": "CREATE_WORKSPACE",
            "reason": "WSL_WORKSPACE_CREATE_FAILED",
            "detail": f"تعذر إنشاء مساحة العمل داخل WSL: "
                      + workspace["detail"],
            "repo_linux": repo_linux,
            "workspace_linux": workspace_linux,
        }

    worker_script = f"{repo_linux}/scripts/execution_worker.py"
    argv = [
        "wsl.exe", "-e", "python3", worker_script,
        "--port", str(port), "--host", "0.0.0.0",
    ]
    if token:
        argv += ["--token", token]

    popen = spawner or subprocess.Popen
    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        # cwd متعمد الغياب: لا مسار Linux لعملية Windows أبدًا (§3)
    }
    if hasattr(subprocess, "DETACHED_PROCESS"):  # مضيف Windows فقط
        popen_kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    process = popen(argv, **popen_kwargs)

    return {
        "ok": True,
        "stage": "WORKER_LAUNCHED",
        "endpoint": f"http://127.0.0.1:{port}",
        "worker_command": argv,
        "worker_pid_windows": process.pid,
        "repo_windows": repo_win,
        "repo_linux": repo_linux,
        "workspace_linux": workspace_linux,
        "verify_inside_wsl": verify,
        "workspace_created": workspace,
        "boundary": "Windows ← wsl.exe ← Linux ← execution_worker.py",
    }


__all__ = [
    "WSL_ENVIRONMENT_NAME",
    "WSL_WORKER_DEFAULT_PORT",
    "launch_wsl_worker",
    "wsl_available",
    "wsl_create_workspace",
    "wsl_resolve_path",
    "wsl_verify_runtime",
]
