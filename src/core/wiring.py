"""تركيب الدورة الافتراضية — نقطة التجميع الوحيدة للأدوار الخمسة.

منفصلة عن المنسق (الذي يبقى نقّاءً تركيبيًا: لا يستورد تنفيذ دور) وعن
api (طبقة النقل): كل مستدعٍ — الخادم أو الاختبارات — يجمّع الدورة
نفسها أو يستبدل أي دور عبر overrides.
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
