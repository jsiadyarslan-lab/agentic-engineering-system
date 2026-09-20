"""المراجع (Verifier) — يطابق النتائج بمعايير القبول (CONTRACTS.md §4).

التأسيس: عقد فقط. التنفيذ الفعلي يأتي في الأمر الثاني.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from core.state import PlanState, SubVerdict


class VerifierVerdict(str, Enum):
    EVIDENCED = "evidenced"
    NOT_EVIDENCED = "not_evidenced"


class VerifierRequest(BaseModel):
    """عقد طلب المراجع."""

    task_acceptance_criteria: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class VerifierResult(BaseModel):
    """عقد نتيجة المراجع — الحالة الصادقة: EVIDENCED.

    not_evidenced ليس فشلًا — نقص أدلة يوثَّق ويُغذّي المُحكَّم
    (SubVerdict.NOT_EVIDENCED).
    """

    verdict: VerifierVerdict
    checks_performed: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @property
    def sub_verdict(self) -> SubVerdict | None:
        """الحكم الفرعي — NOT_EVIDENCED عند قصور الأدلة."""
        if self.verdict is VerifierVerdict.NOT_EVIDENCED:
            return SubVerdict.NOT_EVIDENCED
        return None


class Verifier:
    """دور المراجع — هيكل تأسيسي."""

    HONEST_STATE = PlanState.EVIDENCED

    def run(self, request: VerifierRequest) -> VerifierResult:
        raise NotImplementedError(
            "المراجع يُنفَّذ في الأمر الثاني — هذا أمر تأسيس فقط"
        )
