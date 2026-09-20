"""بوابة قرار المالك — §7 من الأمر الرابع المعدل (و§4 من الأصل).

الأقسام المعلَّمة قرارات مالك تُنتج **حزم أدلة فقط**: أرقامًا وحقائق
يفرضها الواقع، بلا خيار مرشح ولا قيمة مقترحة ولا ترجيح.

الفرض آلي لا نصي: ``submit_evidence`` يفحص كل حزمة قادمة من أي دور
(مفكر/مدقق/منفذ/مراجع/محكَّم) بحثًا عن قرار متسلل:

- مفتاح يدل على قرار (suggested / recommended / choice / preferred /
  اختيار / مقترح / موصى / قرار) — سواء بالعربية أو الإنجليزية؛
- قيمة في حزمة أدلة قرار تجاوز الوصف إلى الأمر («ينبغي»، «الأفضل»،
  «أقترح») في موقع القرار.

أي تسلل = ``OwnerDecisionViolation`` → HARD STOP آلي في المحرك.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


#: مفاتيح قرار ممنوعة في حزم الأدلة (تُفحص في مفاتيح JSON وقيمه).
_DECISION_KEY_MARKERS = (
    "suggested", "recommended", "choice", "preferred", "proposal",
    "decision", "verdict", "pick",
    "مقترح", "مقترحة", "اختيار", "موصى", "القرار", "ترجيح",
)
#: صيغ لغوية تدل على قيمة مقترحة داخل نص الدليل.
_DECISION_PHRASES = (
    "أقترح", "نقترح", "ينبغي", "الأفضل", "نوصي", "نوصي بـ",
    "we suggest", "we recommend", "should be", "the best option",
)

_DECISION_KEY_RE = re.compile(
    "|".join(re.escape(marker) for marker in _DECISION_KEY_MARKERS), re.IGNORECASE
)
_DECISION_PHRASE_RE = re.compile(
    "|".join(re.escape(phrase) for phrase in _DECISION_PHRASES), re.IGNORECASE
)


class OwnerDecisionViolation(Exception):
    """قرار صدر من النظام في موضع قرار مالك — HARD STOP آلي."""

    def __init__(self, decision_id: str, where: str) -> None:
        super().__init__(
            f"قرار مالك من النظام في {decision_id} (موضع: {where}) — HARD STOP"
        )
        self.decision_id = decision_id
        self.where = where


@dataclass
class DecisionBundle:
    """حزمة أدلة قرار واحد — أدلة فقط، الحالة بانتظار المالك."""

    decision_id: str
    question: str
    evidence: dict = field(default_factory=dict)
    state: str = "بانتظار المالك"   # الحالة الوحيدة التي تخرج من البوابة

    def as_record(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "question": self.question,
            "evidence": self.evidence,
            "state": self.state,
        }


def _scan_value(value, path: str, decision_id: str) -> None:
    """مسح قيمة JSON بحثًا عن قرار متسلل — تعمق في القواميس والقوائم."""
    if isinstance(value, dict):
        for key, inner in value.items():
            location = f"{path}.{key}"
            if _DECISION_KEY_RE.search(str(key)):
                raise OwnerDecisionViolation(decision_id, f"مفتاح {location}")
            _scan_value(inner, location, decision_id)
    elif isinstance(value, (list, tuple)):
        for index, inner in enumerate(value):
            _scan_value(inner, f"{path}[{index}]", decision_id)
    elif isinstance(value, str):
        if _DECISION_PHRASE_RE.search(value):
            raise OwnerDecisionViolation(decision_id, f"قيمة {path}")


class OwnerGate:
    """البوابة — تسجل القرارات وتفحص الحزم وتحفظ حالة الانتظار."""

    def __init__(self) -> None:
        self._bundles: dict[str, DecisionBundle] = {}
        self.awaiting: list[str] = []
        self.violations: list[str] = []

    def register_decision(self, decision_id: str, question: str) -> None:
        if decision_id in self._bundles:
            raise ValueError(f"قرار مكرر: {decision_id}")
        self._bundles[decision_id] = DecisionBundle(
            decision_id=decision_id, question=question
        )
        self.awaiting.append(decision_id)

    def submit_evidence(
        self, decision_id: str, evidence: dict, *, role: str = "system"
    ) -> DecisionBundle:
        """تسليم حزمة أدلة من دور — الفحص الآلي قبل القبول.

        أي دور — مفكر/مدقق/منفذ/مراجع/محكَّم — يمر من هنا؛ الفحص
        واحد للجميع ولا استثناء لأحد.
        """
        if decision_id not in self._bundles:
            raise ValueError(f"قرار غير مسجل: {decision_id}")
        try:
            _scan_value(evidence, "evidence", decision_id)
        except OwnerDecisionViolation:
            self.violations.append(
                f"{decision_id} بواسطة {role}"
            )
            raise
        bundle = self._bundles[decision_id]
        bundle.evidence.update(evidence)
        return bundle

    def bundle(self, decision_id: str) -> DecisionBundle | None:
        return self._bundles.get(decision_id)

    def all_bundles(self) -> tuple[DecisionBundle, ...]:
        return tuple(self._bundles.values())

    def owner_decided(self, decision_id: str, decision: str) -> None:
        """قرار المالك نفسه — القناة الوحيدة لملء موضع القرار."""
        bundle = self._bundles.get(decision_id)
        if bundle is None:
            raise ValueError(f"قرار غير مسجل: {decision_id}")
        bundle.state = f"قرر المالك: {decision}"
        if decision_id in self.awaiting:
            self.awaiting.remove(decision_id)
