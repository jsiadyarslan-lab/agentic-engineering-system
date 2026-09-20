"""آلة حالات v2 الصادقة — 11 حالة + حُكمان فرعيان.

التصميم (CONTRACTS.md / ARCHITECTURE.md القسمان 3-4):

- لا حالة SUCCESS إطلاقًا. سلسلة المعنى الصادقة:
    EXECUTED (نُفِّذ) ≠ EVIDENCED (أُثبت) ≠ ADJUDICATED (حُسم) ≠ VERIFIED (وافق المستخدم)

- الحالات الإحدى عشرة:
    DRAFT, UNDER_REVIEW, APPROVED, EXECUTING, EXECUTED, VERIFYING,
    EVIDENCED, ADJUDICATED, VERIFIED, FAILED, ESCALATED_TO_HUMAN

- الحكمان الفرعيان (ليسا حالتَي خطة):
    NOT_EVIDENCED — حكم المراجع عند قصور الأدلة (يُغذّي المُحكَّم)
    STAGNANT      — تشخيص المُحكَّم للركود (يُصعّد للبشر)

القاعدة الذهبية المطبقة برمجيًا: الانتقال إلى VERIFIED يشترط
``actor == "user"`` — لا دور ولا المنسق يستطيع منح النظام نجاحه بنفسه.
"""

from __future__ import annotations

from enum import Enum


class PlanState(str, Enum):
    """الحالات الصادقة الإحدى عشرة لدورة العمل."""

    DRAFT = "DRAFT"                        # المفكر أنتج خطة (مسودة)
    UNDER_REVIEW = "UNDER_REVIEW"          # المدقق يراجع
    APPROVED = "APPROVED"                  # المدقق وافق
    EXECUTING = "EXECUTING"                # المنفذ يعمل داخل الركيزة
    EXECUTED = "EXECUTED"                  # التنفيذ اكتمل (ليس نجاحًا)
    VERIFYING = "VERIFYING"                # المراجع يفحص الأدلة
    EVIDENCED = "EVIDENCED"                # الأدلة تطابق المعايير
    ADJUDICATED = "ADJUDICATED"            # المُحكَّم حسم
    VERIFIED = "VERIFIED"                  # المستخدم وافق (وحده)
    FAILED = "FAILED"                      # فشل تنفيذي
    ESCALATED_TO_HUMAN = "ESCALATED_TO_HUMAN"  # تصعيد للبشر


class SubVerdict(str, Enum):
    """حكمان فرعيان يقودان المسار — ليسا حالتَي خطة."""

    NOT_EVIDENCED = "NOT_EVIDENCED"  # المراجع: الأدلة لا تكفي ← المُحكَّم
    STAGNANT = "STAGNANT"            # المُحكَّم: ركود ← تصعيد


#: الحالات النهائية — لا انتقال يخرج منها (إلا قرار بشري موثق لاحقًا).
TERMINAL_STATES: frozenset[PlanState] = frozenset(
    {PlanState.VERIFIED, PlanState.FAILED, PlanState.ESCALATED_TO_HUMAN}
)

#: جدول الانتقالات المسموحة: من → مجموعة «إلى» المسموحة.
TRANSITIONS: dict[PlanState, frozenset[PlanState]] = {
    PlanState.DRAFT: frozenset(
        {PlanState.UNDER_REVIEW, PlanState.ESCALATED_TO_HUMAN}
    ),
    PlanState.UNDER_REVIEW: frozenset(
        {PlanState.APPROVED, PlanState.DRAFT, PlanState.ESCALATED_TO_HUMAN}
    ),
    PlanState.APPROVED: frozenset(
        {PlanState.EXECUTING, PlanState.ESCALATED_TO_HUMAN}
    ),
    PlanState.EXECUTING: frozenset(
        {PlanState.EXECUTED, PlanState.FAILED, PlanState.ESCALATED_TO_HUMAN}
    ),
    PlanState.EXECUTED: frozenset(
        {PlanState.VERIFYING, PlanState.ESCALATED_TO_HUMAN}
    ),
    PlanState.VERIFYING: frozenset(
        {PlanState.EVIDENCED, PlanState.ADJUDICATED, PlanState.ESCALATED_TO_HUMAN}
    ),
    PlanState.EVIDENCED: frozenset(
        {PlanState.ADJUDICATED, PlanState.VERIFIED, PlanState.ESCALATED_TO_HUMAN}
    ),
    PlanState.ADJUDICATED: frozenset(
        {
            PlanState.VERIFIED,
            PlanState.EXECUTING,  # المُحكَّم يقرر إعادة التنفيذ
            PlanState.ESCALATED_TO_HUMAN,
        }
    ),
    PlanState.VERIFIED: frozenset(),
    PlanState.FAILED: frozenset(),
    PlanState.ESCALATED_TO_HUMAN: frozenset(),
}


class StateTransitionError(Exception):
    """انتقال غير مسموح — يُرفض fail-closed مع سبب آلي."""

    def __init__(self, from_state: PlanState, to_state: PlanState, reason: str):
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason
        super().__init__(
            f"انتقال مرفوض: {from_state.value} → {to_state.value} — {reason}"
        )


def validate_transition(
    from_state: PlanState,
    to_state: PlanState,
    *,
    actor: str = "system",
) -> None:
    """التحقق من انتقال واحد — raise StateTransitionError عند الرفض.

    القاعدة الذهبية: VERIFIED لا تُبنى إلا بقرار المستخدم.
    actor: "user" | "arbiter" | "reviewer" | "implementer" | "verifier" | "system"
    """
    if from_state not in PlanState:
        raise StateTransitionError(from_state, to_state, "حالة مصدر غير معروفة")
    if to_state not in PlanState:
        raise StateTransitionError(from_state, to_state, "حالة هدف غير معروفة")
    if from_state in TERMINAL_STATES:
        raise StateTransitionError(
            from_state, to_state, "حالة مصدر نهائية — لا خروج منها"
        )
    if to_state not in TRANSITIONS[from_state]:
        raise StateTransitionError(
            from_state, to_state, "انتقال غير موجود في جدول الانتقالات"
        )
    # القاعدة الذهبية — VERIFIED من المستخدم وحده.
    if to_state is PlanState.VERIFIED and actor != "user":
        raise StateTransitionError(
            from_state,
            to_state,
            "القاعدة الذهبية: لا دور يمنح VERIFIED — القرار للمستخدم وحده",
        )
    # إعادة التنفيذ قرار المُحكَّم وحده.
    if (
        to_state is PlanState.EXECUTING
        and from_state is PlanState.ADJUDICATED
        and actor != "arbiter"
    ):
        raise StateTransitionError(
            from_state,
            to_state,
            "إعادة التنفيذ بعد الحسم قرار المُحكَّم وحده",
        )


def allowed_targets(from_state: PlanState) -> frozenset[PlanState]:
    """الأهداف المسموحة من حالة — للعرض في الواجهة والاختبارات."""
    return TRANSITIONS.get(from_state, frozenset())
