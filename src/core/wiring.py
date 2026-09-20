"""تركيب الدورة الافتراضية — نقطة التجميع الوحيدة للأدوار الخمسة.

منفصلة عن المنسق (الذي يبقى نقّاءً تركيبيًا: لا يستورد تنفيذ دور) وعن
api (طبقة النقل): كل مستدعٍ — الخادم أو الاختبارات — يجمّع الدورة
نفسها أو يستبدل أي دور عبر overrides.

الأمر السادس يضيف build_live_orchestrator: الأدوار الحية (LLM حقيقي
عبر chat_live — لا mock في أي دور) للمهمة الحية حصرًا؛ الدورة
الافتراضية للخادم تبقى mock حتى يجهز المالك مفتاح مزوده.
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
    """منسق بالأدوار الخمسة (mock الأمر الثاني) — مع إحلالات اختيارية.

    overrides يستبدل أي دور (مثل Reviewer(approve_after=None) لاختبار
    مسار المحكَّم) — بقية الأدوار تبقى التركيبة الافتراضية نفسها.
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
) -> Orchestrator:
    """منسق بالأدوار الخمسة **الحية** (الأمر السادس §2).

    router: ModelRouter.build_live() — نقل urllib حقيقي لكل مزود محلول.
    لا mock هنا إطلاقًا: أي دور يفشل يفشل صراحةً (RoleSystemFault
    يلتقطه مشغّل المهمة ويسجّله system_fault).
    """
    from roles.implementer_live import LiveImplementer
    from roles.live import ArbiterLive, ReviewerLive, ThinkerLive, VerifierLive

    verifier = VerifierLive(router)
    if verifier_facts_builder is not None:
        verifier.facts_builder = verifier_facts_builder

    orchestrator = Orchestrator()
    for role, implementation in {
        RoleType.THINKER: ThinkerLive(router),
        RoleType.REVIEWER: ReviewerLive(router),
        RoleType.IMPLEMENTER: LiveImplementer(router, tools_ctx=tools_ctx),
        RoleType.VERIFIER: verifier,
        RoleType.ARBITER: ArbiterLive(router),
    }.items():
        orchestrator.register_role(role, implementation)
    return orchestrator
