"""أدوات اختبارات الركيزة — بناء المحوّل والطلبات بأمان.

الاختبارات السالبة تعمل على Linux/x86_64 فقط (على Windows عبر WSL2) —
وتُتخطى بصدق مع بيان السبب خارجها (لا فشل صامت ولا نجاح مزيف).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from substrate.local_substrate import (
    _SUPPORTED_ARCH,
    LocalSubstrateAdapter,
)
from substrate.limits import E1_LIMITS_DEFAULTS, ExecutionLimits
from substrate.sandbox import SandboxRequest


@pytest.fixture
def adapter() -> LocalSubstrateAdapter:
    if not _SUPPORTED_ARCH:
        pytest.skip("الركيزة تتطلب Linux/x86_64 — على Windows عبر WSL2")
    return LocalSubstrateAdapter()


def run_in_sandbox(
    adapter: LocalSubstrateAdapter,
    tmp_path: Path,
    code: str,
    *,
    sandbox_id: str,
    limits: ExecutionLimits | None = None,
):
    """تشغيل مقطع بايثون داخل الركيزة وإرجاع السجل + مجلد الحجز.

    اصطلاح أكواد الخروج في الاختبارات السالبة:
    0 = حدث الهروب/الخرق (سيئ) | غير الصفر = مُنع (جيد)
    """
    workspace = tmp_path / "ws"
    artifacts = tmp_path / "artifacts"
    workspace.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    image = next(iter(adapter.image_names))
    request = SandboxRequest(
        sandbox_id=sandbox_id,
        image=image,
        command=("python", "-c", code),
        limits=limits or E1_LIMITS_DEFAULTS,
        env_names=frozenset({"PATH"}),
        workspace_root=str(workspace),
        artifacts_dir=str(artifacts),
    )
    record = adapter.execute(request)
    adapter.teardown(sandbox_id)
    return record, artifacts


def read_stdout(record, artifacts: Path | None = None) -> str:
    """قراءة مخرجات التنفيذ من مرجع الحجز (custody) الموثق في السجل.

    الركيزة تحفظ المخرجات باسم stdout-<sandbox_id>.txt داخل مجلد الحجز
    — المرجع الكامل في record.stdout_reference.
    """
    ref = getattr(record, "stdout_reference", "") or ""
    path = Path(ref) if ref else None
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")
