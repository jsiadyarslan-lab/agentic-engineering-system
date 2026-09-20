"""المنسق النحيف — ينسّق لا ينفّذ (ARCHITECTURE.md القسم 2، المبدأ 4).

السقف الدائم: **<800 سطر** (docs/design-principles.md — المبدأ 6).
أي منطق ينفّذ شيئًا يعيش في دور من الأدوار الخمسة أو وحدة متخصصة؛
المنسق يمسك دورة الحالات ويستدعي الأدوار بعقود CONTRACTS.md فقط.

هذا ملف تأسيسي: يعرّف بنية التنسيق كاملة (دورة الحالات، ترتيب الأدوار،
نقاط التسليم) لكن run_cycle يرفض التنفيذ حتى الأمر الثاني — بلا كود
ميزات كما ينص الأمر التأسيسي.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.roles import RoleType
from core.state import PlanState, SubVerdict, validate_transition


@dataclass
class CycleStep:
    """خطوة تنسيق واحدة: دور + الحالة التي يدخلها + مَن يقرر الخروج."""

    role: RoleType
    enters: PlanState
    # القرار الذي يحدد الوجهة التالية (يُستخرج من عقد نتيجة الدور)
    exit_by: str


#: دورة التنسيق الكاملة — الترتيب المرجعي الوحيد للأدوار.
#: (المرحلة الفعلية تبدأ في الأمر الثاني؛ هذا هو الهيكل الملزم)
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


class Orchestrator:
    """المنسق — يمسك دورة الحالات ويستدعي الأدوار بعقودها.

    في التأسيس: هيكل + قفل تنفيذ صريح. الأمر الثاني يملأ استدعاءات
    الأدوار الفعلية (المفكر/المدقق/المنفذ/المراجع/المحكَّم) بنفس هذه
    البنية — بلا تغيير شكل الدورة.
    """

    def __init__(self, roles: dict[RoleType, Any] | None = None):
        self._roles: dict[RoleType, Any] = dict(roles or {})

    # ------------------------------------------------------------------ #
    # التركيب (composition) — تسجيل الأدوار من الخارج، لا استيراد داخلي
    # ------------------------------------------------------------------ #

    def register_role(self, role: RoleType, implementation: Any) -> None:
        """تسجيل تنفيذ دور — الأمر الثاني يسجل الأدوار الخمسة."""
        self._roles[role] = implementation

    # ------------------------------------------------------------------ #
    # الدورة — هيكل التنسيق الملزم
    # ------------------------------------------------------------------ #

    def run_cycle(self, goal: str) -> CycleContext:
        """تشغيل دورة كاملة: DRAFT → … → VERIFIED|FAILED|ESCALATED.

        ملاحظة تأسيسية: التنفيذ الفعلي مقفول صراحةً حتى الأمر الثاني —
        هذا أمر bootstrap ولا يحمل كود ميزات.
        """
        raise NotImplementedError(
            "run_cycle يُنفَّذ في الأمر الثاني (المنسق النحيف + أول دورة "
            "كاملة بين الأدوار الخمسة) — هذا أمر تأسيس فقط"
        )

    # ------------------------------------------------------------------ #
    # أدوات تنسيق عامة (تعمل الآن — تخدم البنية والاختبارات)
    # ------------------------------------------------------------------ #

    @staticmethod
    def cycle_plan() -> list[dict[str, str]]:
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

    def role_ready(self, role: RoleType) -> bool:
        """هل دور مسجل؟ — فحص تركيبي للبنية."""
        return role in self._roles
