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


def test_stop_controller_under_380_lines():
    """الأمر 004: وحدة الإيقاف الكاملة (متحكم + لقطة + تكريم) بسقفها."""
    assert _count_lines("src/core/stop_controller.py") < 380


def test_cycle_events_under_120_lines():
    """الأمر 004: باثر الأحداث منقول من المنسق — وحدة نحيلة نقية."""
    assert _count_lines("src/core/events.py") < 120


def test_cycle_types_under_140_lines():
    """الأمر 004: أنواع الدورة (سياق/نتيجة/خطوات) منقولة من المنسق."""
    assert _count_lines("src/core/cycle_types.py") < 140


def test_model_router_under_600_lines():
    assert _count_lines("src/router/model_router.py") < 600


def test_rate_limiter_under_300_lines():
    """الأمر الثالث: الحزم المنقولة لها سقوفها الملتزمة (ARCHITECTURE §12)."""
    assert _count_lines("src/router/rate_limiter.py") < 300


def test_failover_chain_under_250_lines():
    assert _count_lines("src/router/failover_chain.py") < 250


def test_cooling_loop_under_250_lines():
    assert _count_lines("src/router/cooling_loop.py") < 250


def test_eoe_engine_under_600_lines():
    """الأمر الرابع: منطق EOE كله في وحداته — المنسق لا يتضخم."""
    assert _count_lines("src/eoe/eoe_engine.py") < 600


def test_push_engine_under_500_lines():
    """الأمر الرابع: محرك الدفع — أخطر وحدة، سقفها الخاص."""
    assert _count_lines("src/eoe/push_engine.py") < 500


def test_eoe_units_under_400_lines():
    """الأمر الرابع: بقية وحدات EOE نحيفة (محلل/بوابة/تنفيذ/بوابة مالك)."""
    for unit in (
        "src/eoe/order_parser.py",
        "src/eoe/access_gateway.py",
        "src/eoe/execution_engine.py",
        "src/eoe/proofs.py",
        "src/eoe/owner_gate.py",
        "src/eoe/report_builder.py",
    ):
        assert _count_lines(unit) < 400, unit


def test_data_tools_under_420_lines():
    """الأمر 003: حزمة أدوات البيانات لها سقفها المرسّخ (كحزم الأمر 3)."""
    assert _count_lines("src/tools/data_tools.py") < 420


def test_sources_registry_under_220_lines():
    """الأمر 003: واجهة سجل المصادر قراءة صرفة — سقف مضغوط."""
    assert _count_lines("src/sources/__init__.py") < 220


def test_roles_tools_under_620_lines():
    """الأمر 003: الموزّع كبر بتسجيل خمس أدوات — سقف جديد يراقبه."""
    assert _count_lines("src/roles/tools.py") < 620


def test_implementer_live_under_430_lines():
    """الأمر 003: المنفذ الحي كبر ببروتوكول أدوات البيانات — سقف يراقبه."""
    assert _count_lines("src/roles/implementer_live.py") < 430


def test_ui_js_under_2000_lines():
    """يعمل حتى بعد كتابة الواجهة — ملف app.js سقفه 2000."""
    path = REPO / "src/ui/app.js"
    if not path.exists():
        return  # يُنشأ في خطوة الواجهة نفسها
    assert _count_lines("src/ui/app.js") < 2000


def test_styles_css_under_1200_lines():
    """الأمر 005: ملف التنسيقات له سقفه — التصميم كثيف القيمة لا منتفخ."""
    assert _count_lines("src/ui/styles.css") < 1200


def test_tables_per_family_documented():
    """(الأمر 007) العائلات الثلاث بأعدادها الموثقة — قرار معماري معلن.

    السقف القديم (<10) وصف منتج المحادثة وحده؛ الأمر 007 جعل القاعدة
    مصدر الحقيقة الدائم لحالة المشروع (§9) ولمزودي الخدمة (007.1 §15)
    — فالعائلات الثلاث بأعداد مقفلة، وأي جدول جديد قرار يحدّث هذا
    الاختبار معه.
    """
    from persistence.models import TABLE_COUNT_TOTAL
    from providers_registry import models as provider_models
    from workflow.models import WORKFLOW_TABLES

    assert TABLE_COUNT == 3  # المنتج اليومي: محادثات/رسائل/أحداث أدوار
    assert len(WORKFLOW_TABLES) == 11  # Project/Plan/Phase/Step/Execution/
    # Evidence/Audit/Retry/Checkpoint/OwnerGate/ProjectEvent
    provider_tables = {
        t for t in provider_models.Base.metadata.tables
        if t in ("providers", "provider_configurations", "role_provider_mappings")
    }
    assert len(provider_tables) == 3
    assert TABLE_COUNT_TOTAL == 17


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
