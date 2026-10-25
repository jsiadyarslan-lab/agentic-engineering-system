"""اختبار تكاملي للركيزة (الأمر 006 §11 + AES-EXP-04 §3) — تنفيذ حقيقي.

على مضيف تثبت الركيزة قدراتها (x86_64 محليًا أو bwrap على أي معمارية):
يُنشأ المدير بالصور الافتراضية ويُطلب تنفيذ فعلي فينجح COMPLETED. وعبر
مسار الأدوات: write_file يعمل داخل الركيزة وفشل البدء يظهر بسببه الكامل
لا برسالة خام. محاكاة عدم التوفر تستهدف المصنع (المصدر الواحد للحقيقة).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from substrate.factory import (  # noqa: E402
    default_sandbox_images,
    make_sandbox_manager,
    sandbox_git_image,
    substrate_available,
    substrate_failure_reason,
)

pytestmark = pytest.mark.skipif(
    not substrate_available(),
    reason=(
        "لا ركيزة عزل متاحة على هذا المضيف — " + substrate_failure_reason()
    ),
)


def test_manager_builds_and_executes_for_real(tmp_path):
    """بناء manager بالصور الافتراضية + طلب تنفيذ حقيقي يكتمل."""
    from substrate.limits import E1_LIMITS_DEFAULTS
    from substrate.sandbox import NetworkMode, SandboxRequest, SandboxTermination

    images = default_sandbox_images()
    assert images, "على مضيف ركيزة مثبتة يجب أن توجد صورة افتراضية واحدة+"
    for name, image in images.items():
        # §11: كل صورة باسم ومفسّر مطلق وأسماء مستعارة وجذور صالحة
        assert image.name == name
        assert image.interpreter.startswith("/")
        assert image.entrypoint_aliases
        assert all(r.startswith("/") for r in image.read_only_roots)

    git = sandbox_git_image()
    assert git.interpreter == "/usr/bin/git"

    manager = make_sandbox_manager(images={**images, "git": git})
    assert manager is not None
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
    """مسار الأدوات: write_file يعمل داخل الركيزة — الملف يُكتب فعلًا."""
    from roles.tools import ToolContext, write_file

    ctx = ToolContext(grant_root=tmp_path)
    result = write_file(ctx, "evidence_note.txt", "محتوى مكتوب داخل الركيزة")
    assert "evidence_note.txt" in result
    written = tmp_path / "evidence_note.txt"
    assert written.is_file()
    assert "داخل الركيزة" in written.read_text(encoding="utf-8")


def test_run_in_substrate_failure_carries_honest_reason(tmp_path, monkeypatch):
    """لا ركيزة على المضيف (محاكاة على مستوى المصنع) = فشل صادق مسمى.

    AES-EXP-04: مصدر حقيقة عدم التوفر أصبح substrate.factory — المحاكاة
    تُحقن هناك، والفشل يظهر FAILED_TO_START بسبب عربي كامل لا رسالة خام.
    """
    import substrate.factory as sf
    from roles.tools import ToolContext, _run_in_substrate

    monkeypatch.setattr(sf, "substrate_available", lambda *a, **k: False)
    monkeypatch.setattr(
        sf, "substrate_failure_reason",
        lambda *a, **k: "الركيزة المعزولة غير متاحة — محاكاة اختبار (لا bwrap ولا ركيزة محلية)",
    )

    ctx = ToolContext(grant_root=tmp_path)
    code, _stdout, stderr = _run_in_substrate(
        ctx, "print('x')", tmp_path / "ws", tmp_path
    )
    assert code != 0
    assert "FAILED_TO_START" in stderr
    assert "الركيزة المعزولة" in stderr or "linux/x86_64" in stderr or "bwrap" in stderr, (
        f"سبب غير صادق: {stderr!r}"
    )
