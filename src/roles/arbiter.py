"""المُحكَّم (Arbiter) — توقيع v2 المعماري (CONTRACTS.md §5).

يحسم الخلافات، يملك ميزانية إعادة التنفيذ المركزية، يصعّد للبشر،
ويمنع الدوران اللانهائي (تشخيص STAGNANT). لا دور غيره يستهلك ميزانية
الإعادة، ولا استئناف بين الأدوار بعد حسمه.

التأسيس: عقد فقط. التنفيذ الفعلي يأتي في الأمر الثاني.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.state import PlanState, SubVerdict


class ArbiterRequest(BaseModel):
    """عقد طلب المُحكَّم — يُستدعى عند التعارض أو الركود."""

    conflict_type: str = Field(min_length=1)
    parties: list[str] = Field(default_factory=list)
    evidences: list[str] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)


class ArbiterResult(BaseModel):
    """عقد نتيجة المُحكَّم — الحالة الصادقة: ADJUDICATED.

    max_retries_remaining: ميزانية إعادة التنفيذ المركزية — عنده وحده.
    """

    decision: str
    rationale: str
    escalation_to_human: bool = False
    max_retries_remaining: int = Field(ge=0)

    @property
    def sub_verdict(self) -> SubVerdict | None:
        """الحكم الفرعي — STAGNANT عند تشخيص الركود (يُصعّد)."""
        if self.escalation_to_human and "stagnant" in self.decision.lower():
            return SubVerdict.STAGNANT
        return None


class Arbiter:
    """دور المُحكَّم — هيكل تأسيسي."""

    HONEST_STATE = PlanState.ADJUDICATED

    def run(self, request: ArbiterRequest) -> ArbiterResult:
        raise NotImplementedError(
            "المُحكَّم يُنفَّذ في الأمر الثاني — هذا أمر تأسيس فقط"
        )
