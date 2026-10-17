"""اختبار تكاملي للركيزة (الأمر 006 §11) — manager حقيقي + تنفيذ حقيقي.

على Linux/x86_64 (بيئة CI هذه): يُنشأ المدير بالصور الافتراضية ويُطلب
تنفيذ فعلي فينجح COMPLETED. وعبر مسار الأدوات: write_file يعمل داخل
الركيزة وفشل البدء يظهر بسببه الكامل لا برسالة خام.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from substrate.local_substrate import (  # noqa: E402
    _SUPPORTED_ARCH,
    default_local_images,
    local_git_image,
    local_sandbox_manager,
)

pytestmark = pytest.mark.skipif(
    not _SUPPORTED_ARCH,
    reason="الركيزة تتطلب Linux/x86_64 — على Windows عبر WSL2",
)


def test_manager_builds_and_executes_for_real(tmp_path):
    """بناء manager بالصور الافتراضية + طلب تنفيذ حقيقي يكتمل.

    (013.17-R1 §5) بنية الصور تُتحقق وحدويًا على أي مضيف Linux، أما
    التنفيذ الحي فيُسجل SKIPPED — NOT RUN بالسبب المحدد إن رفض فحص
    القدرات الفعلي المضيف (لا خطأ ولا نجاح مزيف)."""
    from substrate.limits import E1_LIMITS_DEFAULTS
    from substrate.local_substrate import substrate_capabilities
    from substrate.sandbox import NetworkMode, SandboxRequest, SandboxTermination

    images = default_local_images()
    assert images, "على Linux/x86_64 يجب أن توجد صورة افتراضية واحدة+"
    for name, image in images.items():
        # §11: كل صورة باسم ومفسّر مطلق وأسماء مستعارة وجذور صالحة
        assert image.name == name
        assert image.interpreter.startswith("/")
        assert image.entrypoint_aliases
        assert all(r.startswith("/") for r in image.read_only_roots)

    git = local_git_image()
    assert git.interpreter == "/usr/bin/git"

    caps = substrate_capabilities()
    if not caps.get("supported"):
        pytest.skip(
            "SKIPPED — NOT RUN: تنفيذ حي داخل الركيزة يتطلب مضيفًا يجتاز "
            "فحص القدرات الفعلي؛ هنا: "
            + "; ".join(f"{k}={caps.get(k)}" for k in (
                "seccomp_self_mode", "user_namespaces_enabled"))
            + " — لا محاكاة ولا تخفيض معيار")

    manager = local_sandbox_manager(images={**images, "git": git})
    image_name = next(iter(images))
    request = SandboxRequest(
        sandbox_id="order006-integration-1",
        image=image_name,
        command=("python", "-c", "print('inside-substrate-ok')"),
        limits=E1_LIMITS_DEFAULTS,
        env_names=frozenset({"PATH"}),
        network=NetworkMode.NONE,
        workspace_root=str(tmp_path / "ws"),
        artifacts_dir=str(tmp_path / "art"),
    )
    outcome = manager.execute(request)
    assert outcome.outcome.value == "EXECUTED"
    assert outcome.record.termination is SandboxTermination.COMPLETED
    assert outcome.record.exit_code == 0
    stdout = Path(outcome.record.stdout_reference).read_text(
        encoding="utf-8", errors="replace"
    )
    assert "inside-substrate-ok" in stdout


def test_write_file_tool_executes_inside_substrate(tmp_path):
    """مسار الأدوات: write_file يعمل داخل الركيزة — الملف يُكتب فعلًا.

    (013.17-R1 §5) تنفيذ حي: SKIPPED — NOT RUN بالسبب المحدد عندما
    يرفض فحص القدرات الفعلي المضيف (الاختبارات الوحدوية تظل تعمل)."""
    from substrate.local_substrate import substrate_capabilities

    caps = substrate_capabilities()
    if not caps.get("supported"):
        pytest.skip(
            "SKIPPED — NOT RUN: مسار الأدوات داخل الركيزة يتطلب مضيفًا "
            "يجتاز فحص القدرات الفعلي؛ هنا: "
            + "; ".join(f"{k}={caps.get(k)}" for k in (
                "seccomp_self_mode", "user_namespaces_enabled"))
            + " — لا محاكاة")
    from roles.tools import ToolContext, write_file

    ctx = ToolContext(grant_root=tmp_path)
    result = write_file(ctx, "evidence_note.txt", "محتوى مكتوب داخل الركيزة")
    assert "evidence_note.txt" in result
    written = tmp_path / "evidence_note.txt"
    assert written.is_file()
    assert "داخل الركيزة" in written.read_text(encoding="utf-8")


def test_run_in_substrate_failure_carries_honest_reason(tmp_path, monkeypatch):
    """منصة غير مدعومة (محاكاة) = FAILED_TO_START بالسبب الكامل (§11).

    على ويندوز كان هذا مسار ``LocalImage needs a name and absolute
    interpreter`` الخام — الآن: رسالة عربية واضحة تسمي السبب.
    """
    import substrate.local_substrate as ls
    from roles.tools import ToolContext, _run_in_substrate

    monkeypatch.setattr(ls, "_SUPPORTED_ARCH", False)
    assert ls.default_local_images() == {}  # لا صور = لا انفجار خام

    ctx = ToolContext(grant_root=tmp_path)
    code, _stdout, stderr = _run_in_substrate(
        ctx, "print('x')", tmp_path / "ws", tmp_path
    )
    assert code != 0
    assert "FAILED_TO_START" in stderr
    assert "الركيزة المعزولة" in stderr or "linux/x86_64" in stderr, (
        f"سبب غير صادق: {stderr!r}"
    )
