"""المفكر (Thinker) — يحوّل الهدف إلى خطة (CONTRACTS.md §1).

تنفيذ الأمر الثاني (mock حتمي، لا استدعاء LLM بعد):
- ينتج خطة ثابتة من الهدف: ثلاث مهام (تحليل/تنفيذ/تحقق) بمعايير قبول
  قابلة للفحص الميكانيكي (أسماء ملفات نصية).
- في دورات المراجعة اللاحقة (previous_reviews غير فارغة) يعدّل الخطة:
  توثيق الملاحظات في الافتراضات بعلامة «عولجت مراجعة: …» — هذه العلامات
  هي ما يستنتج منه المدقق رقم الجولة (بلا عدّاد داخلي ولا حالة تُلوَّث
  بين الدورات).
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


#: علامة الافتراض التي توثّق معالجة مراجعة — يقرؤها المدقق لاستنتاج رقم الجولة.
REVIEW_ADDRESSED_MARK = "عولجت مراجعة"


class Thinker:
    """دور المفكر — تنفيذ mock حتمي (الأمر الثاني).

    الخطة مشتقة من الهدف فقط (ثابتة المعالم): 3 مهام، معايير كل مهمة
    ملفان نصيان `<id>-output.txt` و`<id>-run-log.txt` — الاتفاقية نفسها
    التي يبني عليها المنفذ كوده داخل الركيزة والمراجع فحوصه.
    """

    HONEST_STATE = PlanState.DRAFT

    def run(self, request: ThinkerRequest) -> ThinkerResult:
        goal = request.goal.strip()
        revised = bool(request.previous_reviews)

        def _task(number: int, title: str) -> PlanTask:
            task_id = f"T{number}"
            description = f"{title} — الهدف: {goal}"
            if revised:
                description += " (منقّحة وفق ملاحظات المراجعة)"
            return PlanTask(
                id=task_id,
                description=description,
                acceptance_criteria=[
                    f"الملف {task_id}-output.txt موجود ضمن الأدلة",
                    f"الملف {task_id}-run-log.txt موجود ضمن الأدلة",
                ],
            )

        assumptions = [
            "الهدف قابل للتحقيق بالأدوات المتاحة داخل الركيزة",
            "معايير القبول قابلة للفحص الميكانيكي (أسماء ملفات)",
        ]
        if request.previous_reviews:
            # علامة واحدة لكل جولة مراجعة (لا لكل ملاحظة) — ليطابق عدّ
            # المدقق عدد الجولات الفعلي لا عدد الملاحظات.
            notes = " | ".join(
                note.strip()[:80] for note in request.previous_reviews[:4]
            )
            assumptions.append(f"{REVIEW_ADDRESSED_MARK}: {notes}")

        risks = [
            "مصدر البيانات قد يكون ناقصًا أو متأخرًا",
            "بيئة التنفيذ قد تفرض حدودًا غير متوقعة (rlimits/لا شبكة)",
        ]
        if revised:
            risks.append("الخطة عادت من المراجعة — خطر الانحراف عن الهدف الأصلي")

        return ThinkerResult(
            plan=Plan(
                tasks=[
                    _task(1, "تحليل الهدف وتوثيق المتطلبات"),
                    _task(2, "تنفيذ العمل الأساسي وإنتاج المخرج"),
                    _task(3, "التحقق من المخرجات وتوثيق الأدلة"),
                ],
                risks=risks,
                assumptions=assumptions,
                evidence_required=[
                    "مسار كل ملف أُنتج داخل الركيزة (مرجع لا محتوى)",
                    "مرجع stdout/stderr لكل تنفيذ",
                ],
            )
        )
