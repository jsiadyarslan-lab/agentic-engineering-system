"""اختبارات اختيار الركيزة (المصنع) — عقد §3.3 موحد ومثبت (AES-EXP-04).

المصنع هو المصدر الواحد للحقيقة: على x86_64 الركيزة المحلية أولاً،
وعلى أي معمارية أخرى بقدرات bwrap مثبتة → bwrap، وإلا None (كل طلب
BLOCKED بسبب صادق — لا رجوع للتنفيذ على المضيف أبدًا). المحاكاة هنا
تتحكم في قدرات المضيف عبر monkeypatch لاختبار منطق الاختيار نفسه.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import substrate.factory as factory  # noqa: E402
from substrate.factory import (  # noqa: E402
    KIND_BWRAP,
    KIND_LOCAL,
    make_sandbox_manager,
    select_substrate,
)
from substrate.sandbox import (  # noqa: E402
    SandboxManager,
    SandboxOutcomeKind,
    SandboxRejectionReason,
    SandboxRequest,
)


@pytest.fixture(autouse=True)
def _fresh_selection(monkeypatch):
    """اختيار جديد لكل اختبار (المصنع يخزن القرار في متغير وحدة)."""
    monkeypatch.setattr(factory, "_SELECTION", None)
    yield


@pytest.fixture(autouse=True)
def _is_linux_true(monkeypatch):
    monkeypatch.setattr(factory, "_is_linux", lambda: True)


def test_selection_prefers_local_on_x86_64(monkeypatch):
    """x86_64 + ركيزة محلية سليمة → الركيزة المحلية (الشواهد الأقدم)."""
    monkeypatch.setattr(factory, "_machine", lambda: "x86_64")
    import substrate.local_substrate as ls

    monkeypatch.setattr(
        ls, "substrate_capabilities",
        lambda *a, **k: {"supported": True, "arch_x86_64_linux": True},
    )
    selection = select_substrate()
    assert selection["kind"] is KIND_LOCAL
    assert selection["reason"] == ""


def test_selection_falls_back_to_bwrap_on_other_arch(monkeypatch):
    """aarch64 + bwrap مثبت → محوّل bwrap (لا فرض معماري غير مبرر)."""
    monkeypatch.setattr(factory, "_machine", lambda: "aarch64")
    import substrate.bwrap_substrate as bs

    monkeypatch.setattr(
        bs, "bwrap_capabilities",
        lambda *a, **k: {"supported": True, "bwrap_version": "0.6.3"},
    )
    selection = select_substrate()
    assert selection["kind"] is KIND_BWRAP
    assert selection["reason"] == ""


def test_selection_none_without_any_substrate(monkeypatch):
    """لا محلية ولا bwrap → None مع سبب صادق يسمي الحالتين معًا."""
    monkeypatch.setattr(factory, "_machine", lambda: "aarch64")
    import substrate.bwrap_substrate as bs

    monkeypatch.setattr(
        bs, "bwrap_capabilities",
        lambda *a, **k: {
            "supported": False,
            "reason": "bubblewrap غير مثبت — الحزمة المطلوبة: bubblewrap",
        },
    )
    selection = select_substrate()
    assert selection["kind"] is None
    reason = selection["reason"]
    assert "x86_64" in reason
    assert "bubblewrap" in reason


def test_no_substrate_manager_is_none_and_blocked(monkeypatch):
    """بلا ركيزة: make_sandbox_manager → None وكل طلب BLOCKED صادق."""
    monkeypatch.setattr(factory, "_machine", lambda: "aarch64")
    import substrate.bwrap_substrate as bs

    monkeypatch.setattr(
        bs, "bwrap_capabilities",
        lambda *a, **k: {"supported": False, "reason": "bwrap غير متاح"},
    )
    assert make_sandbox_manager() is None
    # مدير بلا محوّل (عقد المستهلكين) يرد كل طلب BLOCKED لا استثناء
    manager = SandboxManager()
    from substrate.limits import E1_LIMITS_DEFAULTS

    request = SandboxRequest(
        sandbox_id="blocked-1",
        image="whatever",
        command=("python", "-c", "print('x')"),
        limits=E1_LIMITS_DEFAULTS,
    )
    outcome = manager.execute(request)
    assert outcome.outcome is SandboxOutcomeKind.BLOCKED
    assert outcome.reason is SandboxRejectionReason.SUBSTRATE_UNAVAILABLE
    assert "fail-closed" in outcome.detail


def test_bwrap_manager_executes_for_real(monkeypatch, tmp_path):
    """على مضيف bwrap: المدير المبني يسمح بصوره وينفذ حقيقيًا (شرطي)."""
    monkeypatch.setattr(factory, "_machine", lambda: "aarch64")
    selection = select_substrate()
    if selection["kind"] is not KIND_BWRAP:
        pytest.skip("هذا المضيف لا يختار bwrap — الاختبار شرطي على الاختيار")
    manager = make_sandbox_manager()
    assert manager is not None
    assert manager.substrate_registered
    images = manager.image_allowlist
    assert images, "مدير bwrap بلا صور مسموحة — عقد التسجيل مكسور"
    from substrate.limits import E1_LIMITS_DEFAULTS
    from substrate.sandbox import NetworkMode, SandboxTermination

    request = SandboxRequest(
        sandbox_id="factory-bw-1",
        image=next(iter(images)),
        command=("python", "-c", "print('factory-bwrap-ok')"),
        limits=E1_LIMITS_DEFAULTS,
        env_names=frozenset({"PATH"}),
        network=NetworkMode.NONE,
        workspace_root=str(tmp_path / "ws"),
        artifacts_dir=str(tmp_path / "art"),
    )
    outcome = manager.execute(request)
    assert outcome.outcome is SandboxOutcomeKind.EXECUTED
    assert outcome.record.termination is SandboxTermination.COMPLETED
