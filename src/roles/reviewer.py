"""المدقق (Reviewer) — يراجع الخطة قبل التنفيذ (CONTRACTS.md §2).

تنفيذ الأمر الثاني (mock حتمي، لا استدعاء LLM بعد):
- يستنتج رقم جولة المراجعة من محتوى الخطة نفسها (عدّ علامات «عولجت
  مراجعة» في الافتراضات التي يتركها المفكر) — لا عدّاد داخلي، وبالتالي
  لا تتلوث الحالة بين الدورات ولا يتغير سلوكه بتكرار الاستخدام.
- الجولة الأولى: verdict = revise (لاختبار حلقة المراجعة) مع ملاحظات
  وتغييرات مطلوبة محددة. الجولات التالية: approved.
- approve_after=None يعني «لا يوافق أبدًا» — لإثبات مسار المحكَّم عند
  خصام المراجعة (اختبار التكامل الرابع).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from core.state import PlanState
from roles.thinker import Plan, REVIEW_ADDRESSED_MARK


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


def review_round_of(plan: Plan) -> int:
    """رقم جولة المراجعة الحالية — 1 للخطة الجديدة، +1 لكل مراجعة عولجت."""
    addressed = sum(
        1 for assumption in plan.assumptions
        if assumption.startswith(REVIEW_ADDRESSED_MARK)
    )
    return addressed + 1


class Reviewer:
    """دور المدقق — تنفيذ mock عديم الحالة (الأمر الثاني)."""

    HONEST_STATE = PlanState.UNDER_REVIEW

    def __init__(self, approve_after: int | None = 1) -> None:
        """:param approve_after: كم جولة revise قبل الموافقة؛ None = لا يوافق أبدًا."""
        self._approve_after = approve_after

    def run(self, request: ReviewerRequest) -> ReviewerResult:
        plan = request.plan
        review_round = review_round_of(plan)

        still_revising = (
            self._approve_after is None
            or review_round <= self._approve_after
        )
        if still_revising:
            return ReviewerResult(
                verdict=ReviewerVerdict.REVISE,
                issues=[
                    "الخطة لا توثّق كيف يُنتَج سجل التنفيذ لكل مهمة",
                    "معايير القبول تفتقر إلى ملف سجل تشغيل صريح لكل مهمة",
                ],
                required_changes=[
                    "إضافة <معرّف-المهمة>-run-log.txt إلى معايير قبول كل مهمة",
                    "توثيق ملاحظات المراجعة في افتراضات الخطة (قابلية التتبع)",
                ],
                score=5.5,
                evolution_score=min(10.0, 3.5 + review_round),
            )

        return ReviewerResult(
            verdict=ReviewerVerdict.APPROVED,
            issues=[],
            required_changes=[],
            score=min(10.0, 8.0 + 0.5 * (review_round - 1)),
            evolution_score=min(10.0, 6.0 + review_round),
        )
