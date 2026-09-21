"""المُحكَّم (Arbiter) — توقيع v2 المعماري (CONTRACTS.md §5).

يحسم الخلافات، يملك ميزانية إعادة التنفيذ المركزية، يصعّد للبشر،
ويمنع الدوران اللانهائي (تشخيص STAGNANT). لا دور غيره يستهلك ميزانية
الإعادة، ولا استئناف بين الأدوار بعد حسمه.

تنفيذ الأمر الثاني (mock حتمي بمنطق حسم صريح):
- **كشف الركود**: إذا تكرر نفس نوع الخلاف (بصمته في history) فهو ركود
  بالتعريف → `terminate_stagnant` + تصعيد، مهما بقي من الميزانية.
- **خصام المراجعة** (3 دورات بلا اتفاق): ركود تخطيطي → إنهاء وتصعيد.
- **ضمن الميزانية**: `retry_with_constraints` (تُخصم وحدة من ميزانية
  النزاع من نوعه) — فرصة واحدة مقيّدة لا إعادة مفتوحة.
- **الميزانية نفدت**: `escalate_to_human` — البشر يقررون.
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
    #: سياق الفشل المنظم (إضافة 008 §14): لكل مهمة فاشلة كتلة
    #: {class, stage, tool, reason, retryable, queries, artifacts,
    #: evidence} — ليقرر المحكَّم على السبب الحقيقي لا على «فشل» عامة.
    failure_context: dict = Field(default_factory=dict)


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
    """دور المُحكَّم — تنفيذ mock بميزانية مركزية (الأمر الثاني).

    الميزانية تُنفق لكل نوع خلاف على حدة (`_spent`) — دورة جديدة بنزاع
    جديد تبدأ بميزانية كاملة لنوعها؛ وتكرار نفس البصمة يقصُر الطريق إلى
    terminate_stagnant قبل أي حساب ميزانية.
    """

    HONEST_STATE = PlanState.ADJUDICATED

    #: أسباب الاستدعاء التي تعني خصام مراجعة/تخطيط — ركود بالتعريف.
    REVIEW_CONFLICT_MARKERS = ("review", "deadlock", "planning")

    def __init__(self, max_retries: int = 2) -> None:
        self._budget = max_retries
        self._spent: dict[str, int] = {}

    def run(self, request: ArbiterRequest) -> ArbiterResult:
        conflict = request.conflict_type
        prior_same = sum(
            1 for entry in request.history if entry.startswith(f"{conflict}:")
        )

        # 1) تكرار نفس بصمة الخلاف = ركود — يُقصَر الطريق مهما بقِي من ميزانية
        if prior_same >= 1:
            return ArbiterResult(
                decision="terminate_stagnant",
                rationale=(
                    f"الخلاف «{conflict}» حُسم سابقًا وتكرر بنفس البصمة — "
                    "ركود لا خلاف جديد؛ القرار للإنسان"
                ),
                escalation_to_human=True,
                max_retries_remaining=0,
            )

        # 2) خصام مراجعة/تخطيط بعد استنفاد الجولات = ركود تخطيطي بالتعريف
        lowered = conflict.lower()
        if any(marker in lowered for marker in self.REVIEW_CONFLICT_MARKERS):
            return ArbiterResult(
                decision="terminate_stagnant",
                rationale=(
                    "ثلاث جولات مراجعة دون اتفاق بين المفكر والمدقق — "
                    "الخطة لا تتقارب؛ إنهاء وتصعيد"
                ),
                escalation_to_human=True,
                max_retries_remaining=self._budget,
            )

        # 3) ضمن الميزانية → فرصة واحدة مقيّدة (تُخصم من ميزانية هذا النوع)
        spent = self._spent.get(conflict, 0)
        if spent < self._budget:
            self._spent[conflict] = spent + 1
            remaining = self._budget - self._spent[conflict]
            return ArbiterResult(
                decision="retry_with_constraints",
                rationale=(
                    "الأدلة ناقصة لكن الهدف قابل للتحقق — إعادة تنفيذ واحدة "
                    f"بقيود ملزمة (الميزانية المتبقية لهذا النزاع: {remaining})"
                ),
                escalation_to_human=False,
                max_retries_remaining=remaining,
            )

        # 4) الميزانية نفدت — البشر يقررون
        return ArbiterResult(
            decision="escalate_to_human",
            rationale="استُنفدت ميزانية إعادة التنفيذ دون أدلة مثبتة",
            escalation_to_human=True,
            max_retries_remaining=0,
        )
