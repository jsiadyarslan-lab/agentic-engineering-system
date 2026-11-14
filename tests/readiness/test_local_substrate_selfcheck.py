"""اختبارات بوابة الركيزة المحلية (AES-FACTORY-RELEASE-READINESS-002 §2).

الجذر الذي أُصلح: كانت بوابة «supported» تفترض وضع seccomp للمضيف
(1 أو 2) — بصمة بيئة الحاوية المنفّذ لا قدرة نواة. على عدّاء GitHub
Actions (seccomp 0، مستخدم namespaces مفعّل) أنتجت سالبًا كاذبًا
فحجبت «local-namespace-substrate» ثم انهار مسبار bwrap (مبني
لسنة aarch64 فقط) → 8 اختبارات فشلت بدفع رمل BLOCKED.

العقد الجديد (مقفل هنا):
- البوابة = مسبار «unshare(CLONE_NEWUSER)» حقيقي في مفسّر جديد
  أحادي الخيط — نفس الظروف التي يعمل بها المُطلِق نفسه.
- وضع seccomp للمضيف يُسجَّل للصدق ولا يبوّت شيئًا (فلتر الرمل
  يُنصَّب داخل الرمل).
- الفشل يبقى fail-closed: مسبار فاشل = غير مدعومة + المحوّل يرفض
  الإنشاء بسبب صادق كامل.
- المسبار الواحد يُخزَّن للمَعمل (عقد التخزين نفسه لمسبار bwrap).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import substrate.local_substrate as ls  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_probe_cache():
    """مسبار نظيف لكل اختبار — ثم إعادة المسبار بعدها مباشرة."""
    ls._USERNS_PROBE_CACHE.clear()
    yield
    ls._USERNS_PROBE_CACHE.clear()
    ls._userns_probe(force=True)


def test_gate_ignores_host_seccomp_mode_zero(monkeypatch):
    """seccomp المضيف = 0 (بصمة عدّاء GitHub) لا يمنع الدعم —
    البوابة الحقيقية هي مسبار userns، لا بصمة البيئة."""
    monkeypatch.setattr(ls, "_seccomp_self_mode", lambda: 0)
    caps = ls.substrate_capabilities()
    assert caps["seccomp_self_mode"] == 0            # يُسجَّل للصدق
    if sys.platform.startswith("linux") and caps["userns_probe"] == "OK":
        assert caps["supported"] is True             # لا سالب كاذب
        assert caps["arch_x86_64_linux"] is True


def test_gate_fail_closed_when_userns_probe_fails(monkeypatch):
    """مسبار userns فاشل = غير مدعومة (fail-closed) + المحوّل يرفض
    الإنشاء بسبب صادق — لا تخفيف أمني للحصول على أخضر."""
    if not ls._SUPPORTED_ARCH:
        pytest.skip("بوابة المحوّل تعمل على linux/x86_64 فقط")
    monkeypatch.setattr(ls, "_userns_probe", lambda **k: (False, "محاكاة: EPERM"))
    caps = ls.substrate_capabilities()
    assert caps["supported"] is False
    assert "محاكاة" in str(caps["userns_probe"])
    with pytest.raises(RuntimeError, match="local substrate unsupported"):
        ls.LocalSubstrateAdapter()


def test_gate_still_requires_sysctl_enabled(monkeypatch):
    """max_user_namespaces=0 (sysctl مقفل) = غير مدعومة ولو نجح
    المسبار المصطنع — الثابت الرخيص لا يُلغى بمسبار مزوَّر."""
    real_probe = ls._userns_probe
    monkeypatch.setattr(ls, "_userns_probe", lambda **k: real_probe(force=True))
    # قراءة حقيقية مقفلة عبر تزوير فتح الملف:
    import builtins
    real_open = builtins.open

    def fake_open(path, *a, **k):
        if str(path) == "/proc/sys/user/max_user_namespaces":
            from io import StringIO
            return StringIO("0\n")
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", fake_open)
    caps = ls.substrate_capabilities()
    assert caps["user_namespaces_enabled"] is False
    assert caps["supported"] is False


def test_probe_is_real_and_cached_once():
    """المسبار إطلاق حقيقي (مفسّر جديد) ويُخزَّن للمَعمل: الاستدعاء
    الثاني لا يعيد الإطلاق (نفس probed_at)."""
    if not sys.platform.startswith("linux"):
        pytest.skip("مسبار userns خاص بـ Linux")
    ok1, _ = ls._userns_probe(force=True)
    assert ok1 is True, "على هذا المضيف (x86_64 + userns) يجب أن ينجح المسبار"
    first_at = ls._USERNS_PROBE_CACHE["probed_at"]
    ok2, _ = ls._userns_probe()
    assert ok2 is True
    assert ls._USERNS_PROBE_CACHE["probed_at"] == first_at


def test_selection_report_carries_probe_verdict():
    """تقرير اختيار الركيزة يحمل حكم المسبار الجديد (وليست البصمة)."""
    from substrate import factory as sf

    sf._SELECTION = None
    try:
        report = sf.substrate_capabilities_report()
        caps = report["capabilities"]
        assert "userns_probe" in caps
        if report["supported"]:
            assert caps["userns_probe"] == "OK"
    finally:
        sf._SELECTION = None
