"""فحص النحافة الدائم — يرسّخ design-principles.md المبدأ 6 في الاختبارات.

السقوف الملتزمة: منسق <800 | موجّه <600 | واجهة JS <2000 | جداول <10.
تجاوز أي سقف = فشل اختبار = إشارة خلل تصميمي، لا «نمو طبيعي».
"""

from __future__ import annotations

from pathlib import Path

from core.orchestrator import CYCLE, CycleContext, Orchestrator
from core.roles import RoleType
from core.state import PlanState
from persistence.models import TABLE_COUNT


REPO = Path(__file__).resolve().parents[2]


def _count_lines(rel: str) -> int:
    return len((REPO / rel).read_text(encoding="utf-8").splitlines())


def test_orchestrator_under_800_lines():
    assert _count_lines("src/core/orchestrator.py") < 800


def test_model_router_under_600_lines():
    assert _count_lines("src/router/model_router.py") < 600


def test_ui_js_under_2000_lines():
    """يعمل حتى بعد كتابة الواجهة — ملف app.js سقفه 2000."""
    path = REPO / "src/ui/app.js"
    if not path.exists():
        return  # يُنشأ في خطوة الواجهة نفسها
    assert _count_lines("src/ui/app.js") < 2000


def test_tables_under_10():
    assert TABLE_COUNT < 10


def test_cycle_structure_is_the_five_roles_in_order():
    """دورة التنسيق: الأدوار الخمسة بالترتيب الملزم."""
    assert [s.role for s in CYCLE] == [
        RoleType.THINKER,
        RoleType.REVIEWER,
        RoleType.IMPLEMENTER,
        RoleType.VERIFIER,
        RoleType.ARBITER,
    ]


def test_cycle_context_moves_only_via_transition_table():
    ctx = CycleContext(goal="g")
    ctx.move_to(PlanState.UNDER_REVIEW, actor="system")
    assert ctx.state is PlanState.UNDER_REVIEW
    import pytest

    from core.state import StateTransitionError

    with pytest.raises(StateTransitionError):
        ctx.move_to(PlanState.VERIFIED, actor="system")  # القاعدة الذهبية


def test_run_cycle_locked_until_order_two():
    import pytest

    orch = Orchestrator()
    with pytest.raises(NotImplementedError):
        orch.run_cycle("هدف")


def test_role_registration_composition():
    orch = Orchestrator()
    assert not orch.role_ready(RoleType.THINKER)
    orch.register_role(RoleType.THINKER, object())
    assert orch.role_ready(RoleType.THINKER)
    plan = orch.cycle_plan()
    assert len(plan) == 5 and plan[0]["role"] == "thinker"
