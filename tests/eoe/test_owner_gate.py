"""§10.8 — test_owner_gate: دور يقترح قيمة في حقل قرار = HARD STOP آلي.

الفرض باختبار آلي لا بتعليمات نصية (§7.2): كل دور — مفكر/مدقق/منفذ/
مراجع/محكَّم — يُفحص تسليمه بنفس الفاحص.
"""
from __future__ import annotations

import pytest

from eoe.owner_gate import OwnerDecisionViolation, OwnerGate

ROLES = ["thinker", "reviewer", "implementer", "verifier", "arbiter"]


@pytest.fixture()
def gate():
    gate = OwnerGate()
    gate.register_decision("D1", "مصير الدروس اليتيمة")
    gate.register_decision("D3", "تصنيف الخطة الغامضة")
    return gate


def test_evidence_bundle_accepted(gate):
    """حزمة أدلة نظيفة تُقبل وتُسجل بانتظار المالك."""
    gate.submit_evidence(
        "D1",
        {"عدد": 1904, "معرفات": [18, 19, 20], "حجم الأثر": "1.2MB"},
        role="implementer",
    )
    bundle = gate.bundle("D1")
    assert bundle.state == "بانتظار المالك"
    assert bundle.evidence["عدد"] == 1904
    assert gate.awaiting == ["D1", "D3"]


@pytest.mark.parametrize("role", ROLES)
def test_any_role_suggesting_value_is_violation(gate, role):
    """كل دور بلا استثناء: مفتاح قرار متسلل = انتهاك يوقف آليًا."""
    with pytest.raises(OwnerDecisionViolation) as excinfo:
        gate.submit_evidence(
            "D3",
            {"عدد": 7, "suggested_choice": "منهارة"},
            role=role,
        )
    assert excinfo.value.decision_id == "D3"
    assert role in str(excinfo.value) or excinfo.value.where


@pytest.mark.parametrize("role", ROLES)
def test_arabic_decision_key_is_violation(gate, role):
    """مفاتيح عربية متسللة (مقترح/اختيار/القرار) = انتهاك كذلك."""
    with pytest.raises(OwnerDecisionViolation):
        gate.submit_evidence("D1", {"القرار": "أرشفة"}, role=role)


def test_recommendation_phrase_in_value_is_violation(gate):
    """صيغة توصية داخل قيمة الدليل («نوصي بـ...») = انتهاك."""
    with pytest.raises(OwnerDecisionViolation):
        gate.submit_evidence(
            "D1", {"تحليل": "العدد 1904 ونوصي بـ الأرشفة"}, role="thinker"
        )


def test_nested_decision_is_violation(gate):
    """القرار المتداخل في قوائم/قواميس عميقة يُكشف أيضًا."""
    with pytest.raises(OwnerDecisionViolation):
        gate.submit_evidence(
            "D3",
            {"خيارات": [{"name": "أ", "recommended": True}]},
            role="arbiter",
        )


def test_violation_recorded_and_owner_channel_only(gate):
    """الانتهاك يُسجل، وموضع القرار لا يملؤه إلا المالك نفسه."""
    with pytest.raises(OwnerDecisionViolation):
        gate.submit_evidence("D1", {"choice": "حذف"}, role="verifier")
    assert len(gate.violations) == 1
    assert "verifier" in gate.violations[0]
    # القناة الوحيدة: المالك يقرر بنفسه
    gate.owner_decided("D1", "أرشفة مع سجل")
    assert gate.bundle("D1").state == "قرر المالك: أرشفة مع سجل"
    assert gate.awaiting == ["D3"]
