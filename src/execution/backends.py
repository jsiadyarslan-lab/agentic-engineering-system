"""خلفيات التنفيذ (الأمر 010 §16) — абстракция صادقة بلا implementation وهمية.

    ExecutionBackend
    ├── LocalLinuxBackend      ركيزة Linux/x86_64 المحلية (حقيقية — نفس
    │                          الركيزة المثبتة بـ21/21 مسبارًا في E1)
    └── RemoteWorkerBackend    عامل بعيد عبر HTTP (بروتوكول §21 —
                               scripts/execution_worker.py الطرف الآخر)

القاعدة (§16+§20): لا خلفية «دوكرة» ولا «سحابة» غير منفذة؛ الخلفية
تُعلن توفرها من الكود الفعلي، وverify() هو نفسه المسار الذي ينفّذ
به run_code() — فلا انفصال بين ما يُفحص وما يُستعمل (§19).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

#: مهلة HTTP للعامل البعيد (تحقق/تنفيذ محدود)
WORKER_HTTP_TIMEOUT = 240.0


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
    """عقد الخلفية (§16-§17) — describe/verify/run عبر نفس المسار."""

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
# LOCAL — ركيزة Linux/x86_64 المحلية (نفس E1 المعتمدة)
# ------------------------------------------------------------------ #

_LOCAL_PROBE_CODE = (
    "import pathlib\n"
    "p = pathlib.Path('/artifacts/probe.txt')\n"
    "p.write_text('boot-ok', encoding='utf-8')\n"
    "print('exec-ok:', p.read_text(encoding='utf-8'))\n"
)


class LocalLinuxBackend:
    """الركيزة المحلية — نفس substrate المثبت، عبر مدير واحد (§19).

    كل من probe_sandbox و_run_in_substrate يمران من هنا: لا مدير
    منفصل للمسبار وآخر للمنفذ — مصدر واحد للحقيقة.
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

    def describe(self) -> dict:
        import platform
        import sys

        from substrate.local_substrate import substrate_capabilities

        ok, reason = self.available()
        caps = substrate_capabilities()
        return {
            "environment_id": self.environment_id,
            "backend": "LOCAL",
            "os": platform.system(),
            "architecture": platform.machine(),
            "runtime": f"python {sys.version_info.major}.{sys.version_info.minor}",
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
# REMOTE_WORKER — عامل بعيد عبر بروتوكول HTTP حقيقي (§21)
# ------------------------------------------------------------------ #

class RemoteWorkerBackend:
    """خلفية العامل البعيد — العميل في مستوى التحكم.

    الطرف الآخر: scripts/execution_worker.py (عامل حقيقي stdlib-only).
    البروتوكول (§21 v1 — تشغيل متزامن محدود + سجل كامل):

        GET  /health        نبضات: {ok, uptime_s, active_runs}
        GET  /capabilities  وصف البيئة الفعلي من العامل نفسه
        POST /probe         فحوص إقلاع/كتابة/تنفيذ/التقاط لدى العامل
        POST /run           {run_id, code, timeout_s} → سجل التنفيذ
        POST /cancel        {run_id} → إلغاء جارٍ

    stream events في v1: النتيجة سجل واحد يعاد نشره أحداثًا من مستوى
    التحكم (معلن لا مفترض)؛ checkpoint مسؤولية مستوى التحكم.
    """

    backend_kind = "REMOTE_WORKER"

    def __init__(self, endpoint: str, token: str = "",
                 environment_id: str = "remote-worker") -> None:
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.environment_id = environment_id

    def _request(self, method: str, path: str,
                 payload: dict | None = None,
                 timeout: float = WORKER_HTTP_TIMEOUT) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
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
            raise ConnectionError(
                f"العامل رد {error.code}: {body or error.reason}"
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ConnectionError(
                f"تعذر الوصول للعامل {self.endpoint}: {error}"
            ) from error
        except ValueError as error:
            raise ConnectionError(
                f"رد العامل ليس JSON سليمًا: {error}"
            ) from error

    def health(self) -> dict:
        return self._request("GET", "/health", timeout=15.0)

    def describe(self) -> dict:
        try:
            caps = self._request("GET", "/capabilities", timeout=15.0)
        except ConnectionError as error:
            return {
                "environment_id": self.environment_id,
                "backend": "REMOTE_WORKER", "endpoint": self.endpoint,
                "os": "?", "architecture": "?", "runtime": "?",
                "workspace_root": "worker-side",
                "network_policy": "worker-declared",
                "resource_limits": "worker-declared",
                "sandboxed": False, "capabilities": [],
                "available": False, "unavailable_reason": str(error),
            }
        caps["environment_id"] = self.environment_id
        caps["backend"] = "REMOTE_WORKER"
        caps["endpoint"] = self.endpoint
        caps["available"] = True
        return caps

    def verify(self) -> VerifyResult:
        import time

        profile = self.describe()
        if not profile.get("available"):
            return VerifyResult(
                ok=False, status="NOT_READY", checks=[],
                profile=profile, reason=profile.get("unavailable_reason", ""),
            )
        started = time.monotonic()
        try:
            probe = self._request("POST", "/probe", payload={}, timeout=120.0)
        except ConnectionError as error:
            return VerifyResult(
                ok=False, status="NOT_READY", checks=[],
                profile=profile, reason=str(error),
            )
        checks = [
            {
                "name": check.get("name", "?"),
                "ok": bool(check.get("ok")),
                "detail": str(check.get("detail", ""))[:200],
            }
            for check in probe.get("checks", [])
        ]
        ok = bool(probe.get("ok")) and checks and all(c["ok"] for c in checks)
        return VerifyResult(
            ok=ok, status="READY" if ok else "NOT_READY",
            checks=checks, profile=profile,
            reason="" if ok else str(probe.get("reason", "")) or
            "؛ ".join(
                f"{c['name']}: {c['detail']}" for c in checks if not c["ok"]
            ),
        )

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
        except ConnectionError as error:
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
    "ExecutionBackend",
    "ExecutionOutcome",
    "LocalLinuxBackend",
    "RemoteWorkerBackend",
    "VerifyResult",
    "WORKER_HTTP_TIMEOUT",
]
