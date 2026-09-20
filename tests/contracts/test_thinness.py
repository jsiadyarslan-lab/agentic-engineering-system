"""فحص النحافة الدائم — يرسّخ design-principles.md المبدأ 6 في الاختبارات.

السقوف الملتزمة: منسق <800 | موجّه <600 | واجهة JS <2000 | جداول <10.
تجاوز أي سقف = فشل اختبار = إشارة خلل تصميمي، لا «نمو طبيعي».
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
    from core.state import StateTransitionError

    with pytest.raises(StateTransitionError):
        ctx.move_to(PlanState.VERIFIED, actor="system")  # القاعدة الذهبية


def test_run_cycle_requires_all_five_roles():
    """الأمر الثاني فتح run_cycle — الشرط البنيوي: الأدوار الخمسة مسجلة.

    استدعاء بلا أدوار يرفض برسالة تسمي الناقص (تركيب صريح لا اكتشاف
    خافت) — بديل اختبار القفل التأسيسي الذي فتحه الأمر الثاني.
    """
    orch = Orchestrator()
    with pytest.raises(RuntimeError) as excinfo:
        orch.run_cycle("هدف")
    message = str(excinfo.value)
    for role in ("thinker", "reviewer", "implementer", "verifier", "arbiter"):
        assert role in message


#: الوحدات الاثنتا عشرة الخامدة (غلق اعتماديات المنسوخ) — ARCHITECTURE.md §10.
DORMANT_MODULES = (
    "capability", "contract", "domain", "result", "implementation",
    "high_impact", "mission", "objective", "operations",
    "static_analysis", "testing_domain", "write_operations",
)

#: أكواد v2 التي لا يجوز لها استيراد وحدة خامدة (الأمر الثاني: شرط القبول).
V2_CODE_DIRS = ("core", "roles", "api", "router", "persistence", "ui")


def test_dormant_modules_not_imported_by_v2():
    """الوحدات الـ12 الإضافية خامدة — لا استيراد لها من كود v2.

    أي استيراد مستقبلي يجب أن يكون قرارًا معماريًا موثقًا في
    ARCHITECTURE.md §10 يحدّث هذا الاختبار معه — لا نتيجة عرضية.
    """
    violations: list[str] = []
    for code_dir in V2_CODE_DIRS:
        for path in (REPO / "src" / code_dir).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for module in DORMANT_MODULES:
                if f"from contracts.{module}" in text or (
                    f"import contracts.{module}" in text
                ):
                    violations.append(f"{path.relative_to(REPO)} → {module}")
    assert not violations, f"استيراد وحدات خامدة من كود v2: {violations}"


def test_role_registration_composition():
    orch = Orchestrator()
    assert not orch.role_ready(RoleType.THINKER)
    orch.register_role(RoleType.THINKER, object())
    assert orch.role_ready(RoleType.THINKER)
    plan = orch.cycle_plan()
    assert len(plan) == 5 and plan[0]["role"] == "thinker"
