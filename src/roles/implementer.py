"""المنفذ (Implementer) — ينفّذ المهمة داخل الركيزة (CONTRACTS.md §3).

التأسيس: عقد فقط. الربط الفعلي بالركيزة يأتي في الأمر الثاني.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from core.state import PlanState
from roles.thinker import PlanTask


class ImplementerStatus(str, Enum):
    EXECUTED = "executed"
    FAILED = "failed"


class ImplementerRequest(BaseModel):
    """عقد طلب المنفذ — sandbox_root مساحة الركيزة الممنوحة."""

    task: PlanTask
    tools_available: list[str] = Field(default_factory=list)
    sandbox_root: str = ""
    previous_attempts: list[str] = Field(default_factory=list)


class ImplementerResult(BaseModel):
    """عقد نتيجة المنفذ — الحالة الصادقة: EXECUTED.

    نُفِّذت ≠ نجحت: القرار للمراجع ثم للمستخدم. الأدلة مراجع لا محتوى.
    """

    status: ImplementerStatus
    artifacts: list[str] = Field(default_factory=list)
    stdout_truncated: str = ""
    stderr_truncated: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class Implementer:
    """دور المنفذ — هيكل تأسيسي."""

    HONEST_STATE = PlanState.EXECUTED

    def run(self, request: ImplementerRequest) -> ImplementerResult:
        raise NotImplementedError(
            "المنفذ يُنفَّذ في الأمر الثاني — هذا أمر تأسيس فقط"
        )
