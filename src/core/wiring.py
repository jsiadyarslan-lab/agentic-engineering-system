"""تركيب الدورة — نقطة التجميع الوحيدة للأدوار الخمسة.

منفصلة عن المنسق (الذي يبقى نقّاءً تركيبيًا: لا يستورد تنفيذ دور) وعن
api (طبقة النقل): كل مستدعٍ — الخادم أو الاختبارات — يجمّع الدورة
نفسها أو يستبدل أي دور عبر overrides.

الأمر 006 (فصل التركيب الصريح §12):
- production wiring: build_live_orchestrator حصرًا — مسار الإنتاج
  لا يستدعي build_mock_orchestrator أبدًا (يُرسّخ اختبار حارس في
  tests/api/test_no_mock_in_production.py).
- test wiring: build_mock_orchestrator للأدوار الحتمية في الاختبارات
  فقط — الأدوار mock باقية عمدًا (roles/*.py) للاختبارات deterministic.
"""

from __future__ import annotations

from typing import Any

from core.orchestrator import Orchestrator
from core.roles import RoleType
from roles.arbiter import Arbiter
from roles.implementer import Implementer
from roles.reviewer import Reviewer
from roles.thinker import Thinker
from roles.verifier import Verifier


def build_mock_orchestrator(
    overrides: dict[RoleType, Any] | None = None,
) -> Orchestrator:
    """منسق بالأدوار الخمسة الحتمية — TEST WIRING ONLY (الأمر 006 §12).

    لا يستدعيها مسار الإنتاج أبدًا (اختبار الحارس يمنع العودة للديمو
    بالخطأ). overrides يستبدل أي دور (مثل Reviewer(approve_after=None)
    لاختبار مسار المحكَّم) — بقية الأدوار تبقى التركيبة نفسها.
    """
    roles: dict[RoleType, Any] = {
        RoleType.THINKER: Thinker(),
        RoleType.REVIEWER: Reviewer(),
        RoleType.IMPLEMENTER: Implementer(),
        RoleType.VERIFIER: Verifier(),
        RoleType.ARBITER: Arbiter(),
    }
    if overrides:
        roles.update(overrides)

    orchestrator = Orchestrator()
    for role, implementation in roles.items():
        orchestrator.register_role(role, implementation)
    return orchestrator


def build_live_orchestrator(
    router: Any,
    *,
    tools_ctx: Any = None,
    verifier_facts_builder: Any = None,
    stop_controller: Any = None,
    role_config: dict[str, Any] | None = None,
) -> Orchestrator:
    """منسق بالأدوار الخمسة **الحية** (الأمر السادس §2).

    router: ModelRouter.build_live() — نقل urllib حقيقي لكل مزود محلول.
    لا mock هنا إطلاقًا: أي دور يفشل يفشل صراحةً (RoleSystemFault
    يلتقطه مشغّل المهمة ويسجّله system_fault).
    stop_controller (الأمر 004): متحكم الإيقاف الفوري — يُمرّر للمنسق
    وتُربط نقاط تفتيشه بسياق أدوات المنفذ الحي.
    role_config (الأمر 006 §3+§4): اختيار مستقل لكل دور —
    {role: RoleSelection(provider, model)}؛ الدور بلا اختيار يستخدم
    افتراضات الموجّه المعلنة. لا دور يتلقى مزود دور آخر أبدًا.
    """
    from roles.implementer_live import LiveImplementer
    from roles.live import ArbiterLive, ReviewerLive, ThinkerLive, VerifierLive

    def _pick(role_key: str) -> Any:
        return (role_config or {}).get(role_key)

    verifier = VerifierLive(router, selection=_pick("verifier"))
    if verifier_facts_builder is not None:
        verifier.facts_builder = verifier_facts_builder

    orchestrator = Orchestrator(stop_controller=stop_controller)
    for role, implementation in {
        RoleType.THINKER: ThinkerLive(router, selection=_pick("thinker")),
        RoleType.REVIEWER: ReviewerLive(router, selection=_pick("reviewer")),
        RoleType.IMPLEMENTER: LiveImplementer(
            router, tools_ctx=tools_ctx, selection=_pick("implementer")
        ),
        RoleType.VERIFIER: verifier,
        RoleType.ARBITER: ArbiterLive(router, selection=_pick("arbiter")),
    }.items():
        orchestrator.register_role(role, implementation)
    return orchestrator
