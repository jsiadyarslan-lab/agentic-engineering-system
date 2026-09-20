"""المفكر (Thinker) — يحوّل الهدف إلى خطة (CONTRACTS.md §1).

التأسيس: عقد فقط. التنفيذ الفعلي (استدعاء النموذج) يأتي في الأمر الثاني.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.state import PlanState


class PlanTask(BaseModel):
    """مهمة واحدة داخل الخطة — بمعايير قبول يفحصها المراجع لاحقًا."""

    id: str = Field(min_length=1, description="معرّف المهمة داخل الخطة")
    description: str = Field(min_length=1, description="وصف المهمة التنفيذي")
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="معايير القبول القابلة للفحص (تُغذّي عقد المراجع)",
    )


class Plan(BaseModel):
    """عقد الخطة — مخرج المفكر الوحيد."""

    tasks: list[PlanTask] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    evidence_required: list[str] = Field(default_factory=list)


class ThinkerRequest(BaseModel):
    """عقد طلب المفكر."""

    goal: str = Field(min_length=1)
    context: str = ""
    constraints: list[str] = Field(default_factory=list)
    previous_reviews: list[str] = Field(default_factory=list)


class ThinkerResult(BaseModel):
    """عقد نتيجة المفكر — الحالة الصادقة: DRAFT."""

    plan: Plan


class Thinker:
    """دور المفكر — هيكل تأسيسي.

    run() تُنفَّذ في الأمر الثاني (المنسق النحيف + أول دورة كاملة).
    """

    HONEST_STATE = PlanState.DRAFT

    def run(self, request: ThinkerRequest) -> ThinkerResult:
        raise NotImplementedError(
            "المفكر يُنفَّذ في الأمر الثاني — هذا أمر تأسيس فقط"
        )
