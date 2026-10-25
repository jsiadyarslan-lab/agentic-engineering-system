"""أدوات اختبارات الركيزة — بناء المحوّل والطلبات بأمان.

AES-EXP-04 §3.2: البوابة الآن قدرة فعلية مثبتة (المصنع الواحد) لا فرض
معماري — المحوّل المختار قد يكون الركيزة المحلية (x86_64) أو bwrap
(أي معمارية تثبت قدراتها). خارج التوفر: تخطٍ صادق ببيان السبب (لا فشل
صامت ولا نجاح مزيف).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from substrate.factory import (
    make_sandbox_manager,
    substrate_available,
    substrate_failure_reason,
)
from substrate.limits import E1_LIMITS_DEFAULTS, ExecutionLimits
from substrate.sandbox import SandboxRequest, SubstrateAdapter


@pytest.fixture
def adapter() -> SubstrateAdapter:
    if not substrate_available():
        pytest.skip(
            "لا ركيزة عزل متاحة على هذا المضيف — " + substrate_failure_reason()
        )
    manager = make_sandbox_manager()
    substrate = manager.substrate if manager is not None else None
    if substrate is None:  # pragma: no cover — تناقض مع substrate_available
        pytest.skip("لا محوّل ركيزة رغم توفر الاختيار — حالة غير متسقة")
    return substrate


def run_in_sandbox(
    adapter: SubstrateAdapter,
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
