"""أنواع دورة التنسيق — تعريفات البيانات المجردة عن سلوك التنسيق.

نُقلت من core/orchestrator.py (الأمر 004) ليظل المنسق تحت سقفه
الدائم (<800 سطر) وهو يستوعب آلية الإيقاف والاستئناف — نقل أنواع
لا تغيير سلوك: التعريفات حرفية كما كانت، والمنسق يعيد تصديرها
للتوافق مع كل الاستيرادات القائمة (الاختبارات والواجهة والتقارير).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.roles import RoleType
from core.state import PlanState, SubVerdict, validate_transition
from roles.thinker import Plan


@dataclass
class CycleStep:
    """خطوة تنسيق واحدة: دور + الحالة التي يدخلها + مَن يقرر الخروج."""

    role: RoleType
    enters: PlanState
    # القرار الذي يحدد الوجهة التالية (يُستخرج من عقد نتيجة الدور)
    exit_by: str


#: دورة التنسيق الكاملة — الترتيب المرجعي الوحيد للأدوار.
CYCLE: tuple[CycleStep, ...] = (
    CycleStep(role=RoleType.THINKER, enters=PlanState.DRAFT, exit_by="plan"),
    CycleStep(role=RoleType.REVIEWER, enters=PlanState.UNDER_REVIEW, exit_by="verdict"),
    CycleStep(
        role=RoleType.IMPLEMENTER, enters=PlanState.EXECUTING, exit_by="status"
    ),
    CycleStep(role=RoleType.VERIFIER, enters=PlanState.VERIFYING, exit_by="verdict"),
    CycleStep(role=RoleType.ARBITER, enters=PlanState.ADJUDICATED, exit_by="decision"),
)


@dataclass
class CycleContext:
    """سياق الدورة الواحدة — كل ما تعرفه الأدوار عن بعضها عبر العقود."""

    goal: str
    cycle_id: str = ""
    state: PlanState = PlanState.DRAFT
    artifacts: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    sub_verdicts: list[SubVerdict] = field(default_factory=list)
    history: list[str] = field(default_factory=list)

    def move_to(self, to_state: PlanState, *, actor: str) -> None:
        """انتقال حالة موثق — يرفض أي مسار خارج جدول الانتقالات."""
        validate_transition(self.state, to_state, actor=actor)
        self.history.append(f"{self.state.value} → {to_state.value} (by {actor})")
        self.state = to_state


@dataclass
class TaskOutcome:
    """حصيلة مهمة واحدة عبر محاولاتها — honest بلا زخرفة."""

    task_id: str
    attempts: int = 0
    evidenced: bool = False
    execution_failed: bool = False
    artifacts: list[str] = field(default_factory=list)


@dataclass
class CycleResult:
    """حصيلة الدورة الكاملة — مرجع الاختبارات والواجهة والتقرير.

    events هو نفس قائمة باثر الأحداث الحية (بالمرجع) — حدث cycle_done
    يُلحق بها بعد البناء فتظهر في النتيجة أيضًا.
    """

    goal: str
    cycle_id: str
    final_state: PlanState
    sub_verdict: SubVerdict | None
    plan: Plan | None
    tasks: list[TaskOutcome]
    review_cycles: int
    arbiter_decisions: list[str]
    state_history: list[str]
    events: list[dict]
    duration_ms: int
    context: CycleContext
    #: الأمر 004: معرف الدورة الموقوفة التي حُقنت لقطتها (وإلا فارغ).
    resumed_from: str = ""


#: أنواع عامة للعرض — دورة التنسيق كخريطة (توافق التوقيع القديم).
def cycle_plan_rows() -> list[dict[str, Any]]:
    """خريطة الدورة للعرض والتوثيق — بلا تنفيذ."""
    return [
        {
            "step": str(i + 1),
            "role": step.role.value,
            "enters": step.enters.value,
            "exit_by": step.exit_by,
        }
        for i, step in enumerate(CYCLE)
    ]
