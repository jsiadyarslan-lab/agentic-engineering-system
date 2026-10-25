#!/usr/bin/env python3
"""عامل التنفيذ البعيد (الأمر 010 §21) — الطرف الآخر الحقيقي للبروتوكول.

تشغيله على أي جهاز فيه Python 3.10+ (بلا تبعيات خارجية إطلاقًا):

    python scripts/execution_worker.py --port 8900 --token سر-مشترك

ثم من مستوى التحكم (Agentic Engineering System):

    الإعدادات ← بيئات التنفيذ ← إضافة بيئة
        backend:     REMOTE_WORKER
        endpoint:    http://<هذا-الجهاز>:8900
        token:       سر-مشترك
    ← تحقق (فحوص إقلاع/كتابة/تنفيذ/التقاط حقيقية عبر الشبكة)

وضعا التنفيذ المعلنان بصدق:
1. substrate — إن كان الجهاز Linux/x86_64 والسكربت يعمل من جذر
   المستودع (venv): تنفيذ داخل الركيزة المعزولة (namespaces+seccomp)
   — sandboxed: true.
2. subprocess — ما عدا ذلك: تنفيذ مباشر محدود المهلة في مجلد مؤقت
   — sandboxed: false معلنة؛ /capabilities تذكرها صراحة فلا خداع.

البروتوكول (v1 — تشغيل متزامن محدود + سجل كامل):
    GET  /health        → {ok, uptime_s, active_runs, backend_mode}
    GET  /capabilities  → وصف البيئة الفعلي من هذا العامل
    POST /probe         → فحوص boot/write/execute/capture حقيقية
    POST /run           → {run_id, code, timeout_s} → سجل التنفيذ
    POST /cancel        → {run_id} → إلغاء جارٍ (SIGKILL لمجموعة العملية)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_STARTED_AT = time.monotonic()
_ACTIVE_RUNS: dict[str, dict] = {}
_LOCK = threading.Lock()

#: محاولة تحميل الركيزة (تعمل فقط من جذر المستودع على مضيف تثبت
#: قدراته — AES-EXP-04 §3.3: القرار من المصنع الواحد لا فرض معماري)
_SUBSTRATE_MODE = False
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from substrate.factory import substrate_available  # noqa: E402

    if substrate_available():
        _SUBSTRATE_MODE = True
except Exception:  # noqa: BLE001 — الجهاز بلا ركيزة: وضع معلن لا انهيار
    _SUBSTRATE_MODE = False

_TOKEN = ""


def _describe() -> dict:
    return {
        "backend_id": "execution-worker/1.0",
        "os": platform.system(),
        "architecture": platform.machine(),
        "runtime": (
            f"python {sys.version_info.major}.{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        ),
        "workspace_root": tempfile.gettempdir(),
        "artifacts_root": "/artifacts" if _SUBSTRATE_MODE else "artifacts",
        "network_policy": "unrestricted (worker host network)",
        "resource_limits": (
            "substrate: RLIMIT_AS/NPROC/FSIZE/CPU + watchdog"
            if _SUBSTRATE_MODE else
            "subprocess: wall-clock timeout + output caps"
        ),
        "sandboxed": _SUBSTRATE_MODE,
        "isolation": (
            "linux-namespaces+seccomp" if _SUBSTRATE_MODE
            else "none — declared direct subprocess (honest mode)"
        ),
        "capabilities": [
            "code_execution", "filesystem_write", "artifact_capture",
            "python_runtime",
        ],
        "worker_pid": os.getpid(),
    }


def _run_in_substrate(code: str, timeout_s: float) -> dict:
    from substrate.factory import make_sandbox_manager
    from substrate.limits import E1_LIMITS_DEFAULTS
    from substrate.sandbox import NetworkMode, SandboxRequest

    with tempfile.TemporaryDirectory(prefix="worker-run-") as tmp:
        workspace = Path(tmp) / "ws"
        artifacts = Path(tmp) / "art"
        workspace.mkdir()
        artifacts.mkdir()
        manager = make_sandbox_manager()
        image = next(iter(manager.image_allowlist), None) if manager else None
        if manager is None or image is None:
            return {
                "exit_code": -1, "stdout": "", "stderr": "",
                "termination": "FAILED_TO_START",
                "detail": "لا ركيزة عزل مسجلة — التنفيذ المعزول محجوب",
                "artifacts": [],
                "duration_ms": 0,
            }
        request = SandboxRequest(
            sandbox_id=f"worker-{uuid.uuid4().hex[:8]}",
            image=image,
            command=("python", "-c", code),
            limits=E1_LIMITS_DEFAULTS,
            env_names=frozenset({"PATH"}),
            network=NetworkMode.NONE,
            workspace_root=str(workspace),
            artifacts_dir=str(artifacts),
        )
        started = time.monotonic()
        outcome = manager.execute(request)
        record = outcome.record
        if record is None:
            return {
                "exit_code": -1, "stdout": "", "stderr": "",
                "termination": "FAILED_TO_START",
                "detail": str(outcome.detail or ""), "artifacts": [],
                "duration_ms": int((time.monotonic() - started) * 1000),
            }

        def _read(reference):
            if not reference:
                return ""
            try:
                return Path(reference).read_text(
                    encoding="utf-8", errors="replace"
                )[:400_000]
            except OSError:
                return ""

        files = []
        for path in sorted(artifacts.rglob("*")) if artifacts.is_dir() else []:
            if path.is_file():
                try:
                    files.append({
                        "name": str(path.relative_to(artifacts)),
                        "b64": base64.b64encode(
                            path.read_bytes()
                        ).decode("ascii"),
                    })
                except OSError:
                    continue
        return {
            "exit_code": record.exit_code if record.exit_code is not None else -1,
            "stdout": _read(record.stdout_reference),
            "stderr": _read(record.stderr_reference),
            "termination": record.termination.value,
            "detail": str(outcome.detail or ""),
            "artifacts": files,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }


def _run_in_subprocess(code: str, timeout_s: float, run_id: str) -> dict:
    """وضع معلن صادق: تنفيذ مباشر بلا عزل — يُذكر في كل نتيجة."""
    with tempfile.TemporaryDirectory(prefix="worker-run-") as tmp:
        root = Path(tmp)
        artifacts = root / "artifacts"
        artifacts.mkdir()
        script = root / "run_code.py"
        script.write_text(code, encoding="utf-8")
        started = time.monotonic()
        process = subprocess.Popen(  # noqa: S603 - عامل تنفيذ معلن
            [sys.executable, "-I", str(script)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(root), start_new_session=True,
        )
        with _LOCK:
            _ACTIVE_RUNS[run_id] = {"pid": process.pid, "started": started}
        try:
            stdout, stderr = process.communicate(timeout=timeout_s)
            termination = "COMPLETED"
            detail = "direct subprocess (sandboxed=false — declared)"
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
            stdout, stderr = process.communicate()
            termination = "TIMEOUT"
            detail = f"تجاوز حد الزمن {timeout_s}s — قُتلت مجموعة العملية"
        finally:
            with _LOCK:
                _ACTIVE_RUNS.pop(run_id, None)
        files = []
        for path in sorted(artifacts.rglob("*")):
            if path.is_file():
                try:
                    files.append({
                        "name": str(path.relative_to(artifacts)),
                        "b64": base64.b64encode(
                            path.read_bytes()
                        ).decode("ascii"),
                    })
                except OSError:
                    continue
        return {
            "exit_code": process.returncode if process.returncode is not None else -1,
            "stdout": stdout.decode("utf-8", "replace")[:400_000],
            "stderr": stderr.decode("utf-8", "replace")[:400_000],
            "termination": termination,
            "detail": detail,
            "artifacts": files,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }


_PROBE_CODE = (
    "import pathlib\n"
    "p = pathlib.Path('artifacts/probe.txt')\n"
    "p.parent.mkdir(parents=True, exist_ok=True)\n"
    "p.write_text('boot-ok', encoding='utf-8')\n"
    "print('exec-ok:', p.read_text(encoding='utf-8'))\n"
)

#: اصطلاح الأدلة: داخل الركيزة ‎/artifacts مطلق (نفس اصطلاح الأدوات
#: المحلية)؛ في وضع subprocess المعلن، نسبي من جذر التشغيل.
_PROBE_CODE_SANDBOX = (
    "import pathlib\n"
    "p = pathlib.Path('/artifacts/probe.txt')\n"
    "p.write_text('boot-ok', encoding='utf-8')\n"
    "print('exec-ok:', p.read_text(encoding='utf-8'))\n"
)


def _probe() -> dict:
    started = time.monotonic()
    if _SUBSTRATE_MODE:
        result = _run_in_substrate(_PROBE_CODE_SANDBOX, 60.0)
        artifacts = {a["name"] for a in result["artifacts"]}
        capture_ok = "probe.txt" in artifacts or "exec-ok" in result["stdout"]
        checks = [
            {"name": "boot",
             "ok": result["termination"] != "FAILED_TO_START",
             "detail": result["termination"]},
            {"name": "write+execute",
             "ok": result["termination"] == "COMPLETED"
             and result["exit_code"] == 0,
             "detail": f"exit={result['exit_code']} "
                       f"{result['stderr'][:100]}"},
            {"name": "capture", "ok": capture_ok,
             "detail": result["stdout"][:100]},
        ]
    else:
        # وضع subprocess: نفس الفحوص عبر المسار المعلن
        with tempfile.TemporaryDirectory(prefix="worker-probe-") as tmp:
            root = Path(tmp)
            (root / "artifacts").mkdir()
            code = (
                "import pathlib\n"
                "p = pathlib.Path('artifacts/probe.txt')\n"
                "p.write_text('boot-ok', encoding='utf-8')\n"
                "print('exec-ok:', p.read_text(encoding='utf-8'))\n"
            )
            (root / "code.py").write_text(code, encoding="utf-8")
            started_sub = time.monotonic()
            proc = subprocess.run(  # noqa: S603
                [sys.executable, "-I", str(root / "code.py")],
                capture_output=True, timeout=60, cwd=str(root),
            )
            captured = (root / "artifacts" / "probe.txt").is_file()
            checks = [
                {"name": "boot", "ok": True,
                 "detail": "subprocess mode"},
                {"name": "write+execute",
                 "ok": proc.returncode == 0,
                 "detail": f"exit={proc.returncode}"},
                {"name": "capture", "ok": captured,
                 "detail": proc.stdout.decode('utf-8', 'replace')[:100]},
            ]
        result = {"termination": "COMPLETED" if all(
            c["ok"] for c in checks) else "FAILED"}
    ok = bool(checks) and all(check["ok"] for check in checks)
    return {
        "ok": ok,
        "checks": checks,
        "reason": "" if ok else "؛ ".join(
            f"{c['name']}: {c['detail']}" for c in checks if not c["ok"]
        ),
        "backend_mode": "substrate" if _SUBSTRATE_MODE else "subprocess",
        "latency_ms": int((time.monotonic() - started) * 1000),
    }


class WorkerHandler(BaseHTTPRequestHandler):
    """معالج البروتوكول — توثيق كامل في ملف الرأس."""

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not _TOKEN:
            return True
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {_TOKEN}"

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 8_000_000:
            raise ValueError("جسم الطلب أكبر من الحد (8MB)")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        sys.stderr.write(
            "[worker] %s %s\n" % (self.address_string(), fmt % args)
        )

    def do_GET(self):  # noqa: N802
        if not self._authorized():
            self._send(401, {"error": "توكن غير صالح"})
            return
        if self.path == "/health":
            with _LOCK:
                active = len(_ACTIVE_RUNS)
            self._send(200, {
                "ok": True,
                "uptime_s": int(time.monotonic() - _STARTED_AT),
                "active_runs": active,
                "backend_mode": "substrate" if _SUBSTRATE_MODE else "subprocess",
            })
        elif self.path == "/capabilities":
            self._send(200, _describe())
        else:
            self._send(404, {"error": f"مسار غير معروف: {self.path}"})

    def do_POST(self):  # noqa: N802
        if not self._authorized():
            self._send(401, {"error": "توكن غير صالح"})
            return
        try:
            payload = self._body()
        except ValueError as error:
            self._send(400, {"error": str(error)})
            return
        if self.path == "/probe":
            self._send(200, _probe())
        elif self.path == "/run":
            run_id = str(payload.get("run_id") or uuid.uuid4().hex[:12])
            code = str(payload.get("code") or "")
            if not code.strip():
                self._send(422, {"error": "code مطلوب"})
                return
            timeout_s = min(float(payload.get("timeout_s", 120)), 600)
            if _SUBSTRATE_MODE:
                result = _run_in_substrate(code, timeout_s)
            else:
                result = _run_in_subprocess(code, timeout_s, run_id)
            result["run_id"] = run_id
            result["sandboxed"] = _SUBSTRATE_MODE
            self._send(200, result)
        elif self.path == "/cancel":
            run_id = str(payload.get("run_id") or "")
            with _LOCK:
                active = _ACTIVE_RUNS.pop(run_id, None)
            cancelled = False
            if active and "pid" in active:
                try:
                    os.kill(active["pid"], signal.SIGKILL)
                    cancelled = True
                except (ProcessLookupError, PermissionError):
                    cancelled = False
            self._send(200, {"cancelled": cancelled, "run_id": run_id})
        else:
            self._send(404, {"error": f"مسار غير معروف: {self.path}"})


def main() -> int:
    global _TOKEN  # noqa: PLW0603
    parser = argparse.ArgumentParser(description="عامل التنفيذ البعيد")
    parser.add_argument("--port", type=int, default=8900)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--token", default=os.environ.get(
        "EXECUTION_WORKER_TOKEN", ""))
    args = parser.parse_args()
    _TOKEN = args.token
    mode = "substrate (معزولة)" if _SUBSTRATE_MODE else \
        "subprocess (معلن بلا عزل)"
    print("=" * 62)
    print("عامل التنفيذ البعيد — Agentic Engineering System")
    print(f"الاستماع: http://{args.host}:{args.port}")
    print(f"وضع التنفيذ: {mode}")
    print(f"المنصة: {platform.system()}/{platform.machine()}")
    if not _TOKEN:
        print("تحذير: بلا توكن — استخدم --token للإنتاج")
    print("=" * 62)
    server = ThreadingHTTPServer((args.host, args.port), WorkerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[i] أُوقف العامل")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
