"""تعريف الأدوار الخمسة وثوابتها — المرجع الواحد للأسماء والرموز.

كل دور يظهر في الواجهة برمزه ووسمه العربي، ويملك حالة صادقة واحدة
(CONTRACTS.md). إضافة دور أو تعديل رمز يحدث هنا وحدها.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.state import PlanState


class RoleType(str, Enum):
    """الأدوار الخمسة — المُحكَّم توقيع v2 المعماري."""

    THINKER = "thinker"
    REVIEWER = "reviewer"
    IMPLEMENTER = "implementer"
    VERIFIER = "verifier"
    ARBITER = "arbiter"
    COORDINATOR = "coordinator"  # المنسق نفسه (للرسائل النظامية لا للقرارات)


@dataclass(frozen=True)
class RoleMeta:
    """بيانات العرض والسياسة لكل دور."""

    key: RoleType
    name_ar: str
    symbol: str
    honest_state: PlanState | None  # الحالة التي يملكها الدور
    decides_verification: bool = False  # هل يملك أيًّا من طريق VERIFIED؟ (لا أحد أبدًا)


ROLES: dict[RoleType, RoleMeta] = {
    RoleType.THINKER: RoleMeta(
        key=RoleType.THINKER,
        name_ar="المفكر",
        symbol="◆",
        honest_state=PlanState.DRAFT,
    ),
    RoleType.REVIEWER: RoleMeta(
        key=RoleType.REVIEWER,
        name_ar="المدقق",
        symbol="◇",
        honest_state=PlanState.UNDER_REVIEW,
    ),
    RoleType.IMPLEMENTER: RoleMeta(
        key=RoleType.IMPLEMENTER,
        name_ar="المنفذ",
        symbol="▸",
        honest_state=PlanState.EXECUTED,
    ),
    RoleType.VERIFIER: RoleMeta(
        key=RoleType.VERIFIER,
        name_ar="المراجع",
        symbol="✦",
        honest_state=PlanState.EVIDENCED,
    ),
    RoleType.ARBITER: RoleMeta(
        key=RoleType.ARBITER,
        name_ar="المُحكَّم",
        symbol="⚖",
        honest_state=PlanState.ADJUDICATED,
    ),
    RoleType.COORDINATOR: RoleMeta(
        key=RoleType.COORDINATOR,
        name_ar="المنسّق",
        symbol="◉",
        honest_state=None,
    ),
}

#: شارات الحالات الصادقة كما تظهر في الواجهة (CONTRACTS.md).
STATE_BADGES: dict[PlanState, str] = {
    PlanState.DRAFT: "◌ DRAFT",
    PlanState.UNDER_REVIEW: "◌ UNDER_REVIEW",
    PlanState.APPROVED: "◌ APPROVED",
    PlanState.EXECUTING: "◌ EXECUTING",
    PlanState.EXECUTED: "✓ EXECUTED",
    PlanState.VERIFYING: "◌ VERIFYING",
    PlanState.EVIDENCED: "✦ EVIDENCED",
    PlanState.ADJUDICATED: "⚖ ADJUDICATED",
    PlanState.VERIFIED: "✔ VERIFIED",
    PlanState.FAILED: "✕ FAILED",
    PlanState.ESCALATED_TO_HUMAN: "▲ ESCALATED_TO_HUMAN",
    PlanState.STOPPING: "◌ STOPPING",   # الأمر 004 — زوج الإيقاف الآمن
    PlanState.STOPPED: "⏹ STOPPED",
}


def role_meta(role: RoleType) -> RoleMeta:
    """بيانات دور — KeyError مستحيل (الجدول مغلق)."""
    return ROLES[role]
