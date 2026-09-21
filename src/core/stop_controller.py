"""التحكم بالإيقاف الفوري الآمن (الأمر 004) — منسق الدورة والمهمة الحية.

المبادئ:
- **حدود آمنة لا قتل خيوط**: طلب الإيقاف يُقبل فورًا (علم ذرّي)،
  ويُكرَّم عند أقرب نقطة تفتيش بين الخطوات — الاستدعاء الجاري
  (نموذج/أداة) يكتمل ثم يتوقف النظام. أطول انتظار = استدعاء دور
  واحد؛ هذا حدّ معلن لا خفاء.
- **الصدق**: لا إخفاء — إيصال إيقاف باسم الطالب ووقته وسببه، حدث
  ``cycle.stopped`` صريح، وحكم المهمة ``STOPPED`` (ليس HARD STOP
  وليس PASS).
- **حفظ الحالة**: لقطة ``stop_snapshot.json`` في جذر مساحة عمل الدورة
  تحمل كل ما يلزم للاستئناف (الخطة/المخرجات/الملاحظات/الأدلة المرجعية).
- **الاستئناف دورة جديدة**: STOPPED نهائية مجمّدة — الاستئناف يُحقن
  اللقطة في دورة جديدة (خطة موقّعة تُتخطى بها مرحلة التفكير/المراجعة)،
  لا إحياء للدورة الموقوفة.
- **حماية السباقات**: علمٌ تحت قفل، طلبات متزامنة تُدمج في إيصال
  واحد (idempotent)، وفحص الدورة النشطة يرفض الإيقاف لدورة منتهية.

لا يعرف هذا الملف شيئًا عن الأدوار أو الركيزة — المنسق وحده يقرأ
النقاط ويكرم الطلب.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.state import PlanState

#: مخطط اللقطة — أي لقطة قادمة بمخطط آخر تُرفض صراحة (fail-closed).
SNAPSHOT_SCHEMA = "stop-snapshot/1"

#: اسم ملف اللقطة داخل جذر مساحة عمل الدورة/المهمة.
SNAPSHOT_NAME = "stop_snapshot.json"

#: الحالات التي تعني أن الخطة كانت موقّعة عند الإيقاف (تجاوزت المراجعة).
_PLAN_SIGNED_STATES = frozenset(
    {
        "APPROVED",
        "EXECUTING",
        "EXECUTED",
        "VERIFYING",
        "EVIDENCED",
        "ADJUDICATED",
    }
)


class CycleStopSignal(Exception):
    """إشارة إيقاف من نقطة تفتيش — يلتقطها المنسق وحده ويكرمها.

    ليست خطأً: الدورة لا تنتقل إلى FAILED بل إلى STOPPING → STOPPED.
    """

    def __init__(self, at_step: str):
        self.at_step = at_step
        super().__init__(f"طلب إيقاف قُبِل عند الحدّ الآمن: {at_step}")


@dataclass(frozen=True)
class StopReceipt:
    """إيصال طلب الإيقاف — من طلب؟ متى؟ لماذا؟ (سجل تدقيق)."""

    cycle_id: str
    requested_by: str   # "owner" | "coordinator"
    at: str             # ISO-8601 UTC
    reason: str = ""


class StopController:
    """متحكم الإيقاف — علم ذرّي لكل دورة تحت قفل واحد.

    ``request_stop`` idempotent: الطلبات المتزامنة/المتكررة تُرجع
    الإيصال الأول نفسه (لا إيصالان لدورة واحدة).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._receipts: dict[str, StopReceipt] = {}

    def request_stop(
        self,
        cycle_id: str,
        *,
        by: str = "owner",
        reason: str = "",
    ) -> StopReceipt:
        with self._lock:
            existing = self._receipts.get(cycle_id)
            if existing is not None:
                return existing  # idempotent — إيصال واحد مهما تكرر الطلب
            receipt = StopReceipt(
                cycle_id=cycle_id,
                requested_by=by,
                at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                reason=reason,
            )
            self._receipts[cycle_id] = receipt
            return receipt

    def is_stopped(self, cycle_id: str) -> bool:
        with self._lock:
            return cycle_id in self._receipts

    def receipt(self, cycle_id: str) -> StopReceipt | None:
        with self._lock:
            return self._receipts.get(cycle_id)

    def checker_for(self, cycle_id: str) -> Callable[[], bool]:
        """إغلاق جاهز لحقنه في سياق أدوات المنفذ الحي (ToolContext)."""

        def _check() -> bool:
            return self.is_stopped(cycle_id)

        return _check

    def clear(self, cycle_id: str) -> None:
        with self._lock:
            self._receipts.pop(cycle_id, None)


# ------------------------------------------------------------------ #
# تكريم الإيقاف — الانتقالان + اللقطة + الحدث الصريح
# ------------------------------------------------------------------ #

#: حقول مخرجات المهام التي تدخل اللقطة (TaskOutcome بلا استيراد طبقة الأدوار).
_OUTCOME_KEYS = ("task_id", "attempts", "evidenced", "execution_failed", "artifacts")


def plan_signed_at(state_at_stop: str, has_plan: bool) -> bool:
    """هل كانت الخطة موقّعة عند الإيقاف؟ — يقرر مسار الاستئناف."""
    return has_plan and state_at_stop in _PLAN_SIGNED_STATES


def honor_stop(
    *,
    ctx: Any,
    emitter: Any,
    move: Callable[[Any, str], None],
    root: Path,
    plan: Any,
    outcomes: list[Any],
    review_cycles: int,
    issues: list[str],
    signal: CycleStopSignal,
    receipt: StopReceipt | None,
) -> Path:
    """تكريم طلب الإيقاف عند نقطة تفتيش (الأمر 004).

    الانتقالان الموثقان: ``→ STOPPING (بفعل المالك)`` ثم ``→ STOPPED``،
    بينهما كتابة اللقطة القابلة للاستئناف، وبعدها حدث ``cycle.stopped``
    الصريح بكل بيانات التدقيق — لا إخفاء ولا صمت.
    """
    state_at_stop = ctx.state.value
    move(PlanState.STOPPING, actor="user")
    plan_dump = plan.plan.model_dump() if plan is not None else None
    snapshot = build_stop_snapshot(
        cycle_id=ctx.cycle_id,
        goal=ctx.goal,
        state_at_stop=state_at_stop,
        phase=signal.at_step,
        plan_dump=plan_dump,
        plan_signed=plan_signed_at(state_at_stop, plan_dump is not None),
        outcomes=[{k: getattr(o, k) for k in _OUTCOME_KEYS} for o in outcomes],
        review_cycles=review_cycles,
        review_issues=list(issues),
        evidence_refs=list(ctx.evidence_refs),
        artifacts=list(ctx.artifacts),
        events_count=len(emitter.events),
        receipt=receipt
        or StopReceipt(cycle_id=ctx.cycle_id, requested_by="system", at=""),
    )
    snapshot_path = root / SNAPSHOT_NAME
    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    move(PlanState.STOPPED, actor="system")
    emitter.emit(
        role="coordinator",
        kind="cycle.stopped",
        state=PlanState.STOPPED.value,
        text=(
            f"أُوقفت الدورة بأمر ({snapshot['stopped_by']}) عند "
            f"{signal.at_step} — اللقطة محفوظة: {snapshot_path.name}"
        ),
        details={
            "stopped_by": snapshot["stopped_by"],
            "stopped_at": snapshot["stopped_at"],
            "reason": snapshot["stop_reason"],
            "honored_at_step": signal.at_step,
            "state_at_stop": state_at_stop,
            "snapshot_path": str(snapshot_path),
            "snapshot_sha256": hashlib.sha256(
                snapshot_path.read_bytes()
            ).hexdigest(),
            "resumable": True,
        },
    )
    return snapshot_path


# ------------------------------------------------------------------ #
# لقطة الإيقاف — بناؤها وتحميلها
# ------------------------------------------------------------------ #


@dataclass
class ResumePoint:
    """نقطة استئناف مُصادق عليها من لقطة إيقاف."""

    stopped_cycle_id: str
    goal: str
    plan_signed: bool
    plan_dump: dict | None
    state_at_stop: str = ""
    outcomes: list[dict] = field(default_factory=list)
    review_cycles: int = 0
    review_issues: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    stopped_by: str = ""
    stopped_at: str = ""
    stop_reason: str = ""


def build_stop_snapshot(
    *,
    cycle_id: str,
    goal: str,
    state_at_stop: str,
    phase: str,
    plan_dump: dict | None,
    plan_signed: bool,
    outcomes: list[dict],
    review_cycles: int,
    review_issues: list[str],
    evidence_refs: list[str],
    artifacts: list[str],
    events_count: int,
    receipt: StopReceipt,
) -> dict:
    """بناء اللقطة الكاملة — كل ما يلزم للاستئناف والتدقيق."""
    return {
        "schema": SNAPSHOT_SCHEMA,
        "cycle_id": cycle_id,
        "goal": goal,
        "state_at_stop": state_at_stop,
        "phase": phase,
        "plan": plan_dump,
        "plan_signed": plan_signed,
        "outcomes": outcomes,
        "review_cycles": review_cycles,
        "review_issues": review_issues,
        "evidence_refs": evidence_refs,
        "artifacts": artifacts,
        "events_count": events_count,
        "stopped_by": receipt.requested_by,
        "stopped_at": receipt.at,
        "stop_reason": receipt.reason,
    }


def load_resume_point(snapshot: dict) -> ResumePoint:
    """تحميل وتصديق لقطة استئناف — أي نقص/انحراف = رفض صريح.

    fail-closed: مخطط مجهول أو حقول جوهرية فاسدة ترفض بأخطاء
    مسماة، لا استئناف أعمى من لقطة مجهولة الهوية.
    """
    if not isinstance(snapshot, dict):
        raise ValueError("اللقطة ليست كائن JSON")
    schema = snapshot.get("schema")
    if schema != SNAPSHOT_SCHEMA:
        raise ValueError(
            f"مخطط لقطة غير معروف: {schema!r} (المطلوب {SNAPSHOT_SCHEMA})"
        )
    cycle_id = snapshot.get("cycle_id")
    goal = snapshot.get("goal")
    if not isinstance(cycle_id, str) or not cycle_id:
        raise ValueError("اللقطة بلا معرف دورة صالح")
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("اللقطة بلا هدف صالح")
    state_at_stop = str(snapshot.get("state_at_stop", ""))
    plan_dump = snapshot.get("plan")
    if plan_dump is not None and not isinstance(plan_dump, dict):
        raise ValueError("حقل الخطة في اللقطة فاسد")
    signed = bool(snapshot.get("plan_signed")) or (
        state_at_stop in _PLAN_SIGNED_STATES and plan_dump is not None
    )
    return ResumePoint(
        stopped_cycle_id=cycle_id,
        goal=goal,
        plan_signed=signed and plan_dump is not None,
        plan_dump=plan_dump if signed else None,
        state_at_stop=state_at_stop,
        outcomes=list(snapshot.get("outcomes") or []),
        review_cycles=int(snapshot.get("review_cycles") or 0),
        review_issues=[str(i) for i in snapshot.get("review_issues") or []],
        evidence_refs=[str(r) for r in snapshot.get("evidence_refs") or []],
        artifacts=[str(a) for a in snapshot.get("artifacts") or []],
        stopped_by=str(snapshot.get("stopped_by") or ""),
        stopped_at=str(snapshot.get("stopped_at") or ""),
        stop_reason=str(snapshot.get("stop_reason") or ""),
    )


def snapshot_summary(snapshot: dict) -> dict:
    """ملخص اللقطة للعرض — بلا الخطة الكاملة (تُفحص في الملف)."""
    return {
        "cycle_id": snapshot.get("cycle_id"),
        "state_at_stop": snapshot.get("state_at_stop"),
        "phase": snapshot.get("phase"),
        "plan_signed": snapshot.get("plan_signed"),
        "outcomes_count": len(snapshot.get("outcomes") or []),
        "stopped_by": snapshot.get("stopped_by"),
        "stopped_at": snapshot.get("stopped_at"),
        "stop_reason": snapshot.get("stop_reason"),
        "schema": snapshot.get("schema"),
    }


def asdict_receipt(receipt: StopReceipt | None) -> dict | None:
    """إيصال الإيقاف كقاموس JSON — أو None."""
    return asdict(receipt) if receipt is not None else None
