"""نقاط نهاية بيئات التنفيذ (الأمر 010 §28) — إدارة حقيقية لا عرضًا.

- GET    /api/execution/environments          البيئات المسجلة (بلا أسرار)
- POST   /api/execution/environments          إضافة (LOCAL/REMOTE_WORKER فقط)
- DELETE /api/execution/environments/{id}     حذف (غير الافتراضية)
- POST   /api/execution/environments/{id}/verify   تحقق حقيقي (إقلاع/كتابة/تنفيذ/التقاط)
- POST   /api/execution/environments/{id}/default  تعيين افتراضية
- POST   /api/execution/environments/{id}/test-run اختبار تنفيذ فعلي قصير
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from execution import service

router = APIRouter(prefix="/api/execution", tags=["execution"])


def _sessions():
    from api import routes  # noqa: PLC0415 — كسول يمنع الاستيراد الدائري

    return routes._sessions


class EnvironmentIn(BaseModel):
    """جسم إضافة بيئة — خيارات مدعومة من الكود فعلًا حصرًا (§28)."""

    name: str = Field(min_length=1, max_length=120)
    backend: str = Field(pattern="^(LOCAL|REMOTE_WORKER)$")
    endpoint: str = Field(default="", max_length=300)
    token: str = Field(default="", max_length=400)
    make_default: bool = False


@router.get("/environments")
def environments() -> dict:
    return {
        "environments": service.list_environments(_sessions()),
        "supported_backends": [
            {
                "backend": "LOCAL",
                "description": "ركيزة Linux/x86_64 المحلية — تكشف تلقائيًا",
                "requires": "Linux/x86_64 (أو WSL2 على Windows)",
            },
            {
                "backend": "REMOTE_WORKER",
                "description": "عامل بعيد حقيقي عبر بروتوكول HTTP",
                "requires": "رابط عامل (python scripts/execution_worker.py)",
            },
        ],
        "note": "READY فقط بعد تحقق حقيقي — المسبار والمنفذ من مصدر واحد",
    }


@router.post("/environments")
def add_environment(body: EnvironmentIn) -> dict:
    try:
        environment = service.add_environment(
            _sessions(), name=body.name, backend=body.backend,
            endpoint=body.endpoint, token=body.token,
            make_default=body.make_default,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return environment


@router.delete("/environments/{environment_id}")
def remove_environment(environment_id: int) -> dict:
    try:
        removed = service.delete_environment(_sessions(), environment_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not removed:
        raise HTTPException(status_code=404, detail="بيئة غير معروفة")
    return {"deleted": True}


@router.post("/environments/{environment_id}/verify")
def verify(environment_id: int) -> dict:
    try:
        return service.verify_environment(_sessions(), environment_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail=str(error.args[0] or error)
        ) from error


@router.post("/environments/{environment_id}/default")
def make_default(environment_id: int) -> dict:
    try:
        return service.set_default(_sessions(), environment_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail=str(error.args[0] or error)
        ) from error


@router.post("/environments/{environment_id}/test-run")
def test_run(environment_id: int) -> dict:
    """تنفيذ فعلي قصير في البيئة — إثبات المنفذ لا المسبار وحده (§40)."""
    environment = service._get_environment_full(_sessions(), environment_id)
    if environment is None:
        raise HTTPException(status_code=404, detail="بيئة غير معروفة")
    backend = service.build_backend(environment)
    code = (
        "import platform, sys\n"
        "print('os:', platform.system())\n"
        "print('arch:', platform.machine())\n"
        "print('python:', sys.version_info[:3])\n"
    )
    with tempfile.TemporaryDirectory(prefix="env-test-") as tmp:
        outcome = backend.run_code(
            code, workspace=Path(tmp) / "ws",
            artifacts=Path(tmp) / "art", timeout_s=60.0,
        )
    return {
        "environment": environment["name"],
        "status": environment["status"],
        "ok": outcome.ok,
        "termination": outcome.termination,
        "exit_code": outcome.exit_code,
        "stdout": outcome.stdout[:2000],
        "stderr": outcome.stderr[:500],
        "detail": outcome.detail[:500],
        "duration_ms": outcome.duration_ms,
    }
