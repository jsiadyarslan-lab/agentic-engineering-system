"""المدقق (Reviewer) — يراجع الخطة قبل التنفيذ (CONTRACTS.md §2).

التأسيس: عقد فقط. التنفيذ الفعلي يأتي في الأمر الثاني.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from core.state import PlanState
from roles.thinker import Plan


class ReviewerVerdict(str, Enum):
    APPROVED = "approved"
    REVISE = "revise"


class ReviewerRequest(BaseModel):
    """عقد طلب المدقق."""

    plan: Plan
    reviewer_checklist: list[str] = Field(default_factory=list)
    previous_gaps: list[str] = Field(default_factory=list)


class ReviewerResult(BaseModel):
    """عقد نتيجة المدقق — الحالة الصادقة: UNDER_REVIEW.

    score: جودة الخطة 0-10 | evolution_score: تحسّنها عن المراجعات 0-10.
    """

    verdict: ReviewerVerdict
    issues: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
    score: float = Field(ge=0.0, le=10.0)
    evolution_score: float = Field(ge=0.0, le=10.0)


class Reviewer:
    """دور المدقق — هيكل تأسيسي."""

    HONEST_STATE = PlanState.UNDER_REVIEW

    def run(self, request: ReviewerRequest) -> ReviewerResult:
        raise NotImplementedError(
            "المدقق يُنفَّذ في الأمر الثاني — هذا أمر تأسيس فقط"
        )
