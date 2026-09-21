"""المنسق النحيف — ينسّق لا ينفّذ (ARCHITECTURE.md القسم 2، المبدأ 4).

السقف الدائم: **<800 سطر** (docs/design-principles.md — المبدأ 6).
أي منطق ينفّذ شيئًا يعيش في دور من الأدوار الخمسة أو وحدة متخصصة؛
المنسق يمسك دورة الحالات ويستدعي الأدوار بعقود CONTRACTS.md فقط.

الأمر الثاني — الدورة الكاملة (mock models، تنفيذ حقيقي داخل الركيزة):

    THINKER → plan (DRAFT)
    REVIEWER → approved | revise            (حلقة مراجعة ≤ 3 جولات)
    IMPLEMENTER → artifacts (EXECUTED)      (داخل الركيزة المعزولة)
    VERIFIER → evidenced | not_evidenced    (حلقة إصلاح ≤ 2 محاولة/مهمة)
    ARBITER → حسم الخلافات عند تجاوز الحدود (ADJUDICATED / تصعيد)

القاعدة الذهبية: الانتقال إلى VERIFIED لا يحدث إلا عبر
``user_verifies()`` — بفعل المستخدم وحده (يُفرض في core/state.py).

حواجز الدوران اللانهائي (دفاع متدرج):
1. حلقة المراجعة سقفها MAX_REVIEW_CYCLES (3) ثم المحكَّم.
2. محاولات المهمة سقفها MAX_EXECUTION_ATTEMPTS (2) ثم استنفاد.
3. جولات إعادة التنفيذ بعد الحكم سقفها MAX_EXECUTION_ROUNDS (2).
4. استدعاءات المحكَّم سقفها MAX_ARBITER_CALLS (3) ثم تصعيد قسري.
5. تكرار نفس بصمة الخلاف = ركود (STAGNANT) عند المحكَّم نفسه.
6. جدول الانتقالات المجمّد: الحالات النهائية لا تُغادر أبدًا.

دورة واحدة في كل لحظة (قفل داخلي) — الركيزة والسجلات مصممتان لمسار
واحد؛ الطلب الثاني ينتظر دوره بلا ادعاء تزامن.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from core.events import CycleEventEmitter as _EventEmitter
from core.stop_controller import StopController as _DefaultStop
from core.roles import RoleType
from core.stop_controller import (
    CycleStopSignal,
    asdict_receipt,
    honor_stop,
    load_resume_point,
)
from core.state import PlanState, StateTransitionError, SubVerdict, validate_transition
from roles.arbiter import ArbiterRequest
from roles.implementer import ImplementerRequest, ImplementerStatus
from roles.reviewer import ReviewerRequest, ReviewerVerdict
from roles.thinker import Plan, PlanTask, ThinkerRequest, ThinkerResult
from roles.verifier import VerifierRequest, VerifierVerdict


#: سقوف الدورة — حواجز بنيوية ضد الدوران اللانهائي (ARCHITECTURE.md §3).
MAX_REVIEW_CYCLES = 3          # جولات مراجعة قبل المحكَّم
MAX_EXECUTION_ATTEMPTS = 2     # محاولات (تنفيذ+تحقق) لكل مهمة في الجولة
MAX_EXECUTION_ROUNDS = 2       # الجولة الأولى + جولة إعادة واحدة بحكم المحكَّم
MAX_ARBITER_CALLS = 3          # بعدها تصعيد قسري مهما كان قرار المحكَّم


from core.cycle_types import (  # noqa: F401 — إعادة تصدير للتوافق القائم
    CYCLE,
    CycleContext,
    CycleResult,
    CycleStep,
    TaskOutcome,
    cycle_plan_rows,
)


def _new_cycle_id() -> str:
    return f"cycle-{uuid.uuid4().hex[:12]}"


def _failures_of(outcomes: list, exhausted: list) -> dict:
    """سياق الفشل المنظم (008 §14) — لكل مهمة مستنفدة كتلتها الصادقة."""
    ids = {t_.id for t_ in exhausted}
    fallback = {"class": "INSUFFICIENT_EVIDENCE", "stage": "VERIFICATION",
                "reason": "NOT_EVIDENCED"}
    return {o.task_id: (o.failure or {**fallback, "attempts": o.attempts,
                                      "artifacts": len(o.artifacts)})
            for o in outcomes if o.task_id in ids}


class Orchestrator:
    """المنسق — يمسك دورة الحالات ويستدعي الأدوار بعقودها.

    التركيب (composition): الأدوار تُسجَّل من الخارج (register_role أو
    core.wiring.build_mock_orchestrator) — لا استيراد داخلي لأي تنفيذ.
    """

    _REQUIRED_ROLES = (
        RoleType.THINKER,
        RoleType.REVIEWER,
        RoleType.IMPLEMENTER,
        RoleType.VERIFIER,
        RoleType.ARBITER,
    )

    def __init__(
        self,
        roles: dict[RoleType, Any] | None = None,
        stop_controller: Any | None = None,
    ):
        self._roles: dict[RoleType, Any] = dict(roles or {})
        self._cycles: dict[str, tuple[CycleContext, _EventEmitter]] = {}
        self._cycle_lock = threading.Lock()
        # الأمر 004: متحكم الإيقاف + الدورة النشطة تحت قفل مستقل —
        # طالب الإيقاف لا يحتجز أبدًا خلف قفل الدورة نفسه.
        self._stop = stop_controller if stop_controller is not None else _DefaultStop()
        self._active_lock = threading.Lock()
        self._active_id: str | None = None

    # ------------------------------------------------------------------ #
    # التركيب (composition) — تسجيل الأدوار من الخارج، لا استيراد داخلي
    # ------------------------------------------------------------------ #

    def register_role(self, role: RoleType, implementation: Any) -> None:
        """تسجيل تنفيذ دور — wiring يسجل الأدوار الخمسة."""
        self._roles[role] = implementation

    # ------------------------------------------------------------------ #
    # الدورة الكاملة — الأمر الثاني
    # ------------------------------------------------------------------ #

    def run_cycle(
        self,
        goal: str,
        *,
        context: str = "",
        cycle_id: str | None = None,
        workspace_root: Path | str | None = None,
        on_event: Callable[[dict], None] | None = None,
        resume_from: dict | None = None,
    ) -> CycleResult:
        """تشغيل دورة كاملة: DRAFT → … → EVIDENCED | ESCALATED | FAILED | STOPPED.

        VERIFIED ليست من مخرجات هذه الدالة أبدًا — قرار المستخدم وحده
        عبر :meth:`user_verifies`.
        resume_from (الأمر 004): لقطة إيقاف دورة سابقة — الخطة الموقّعة
        تُحقن فتتخطى مرحلتي التفكير والمراجعة (دورة جديدة لا إحياء).
        """
        missing = [
            role.value for role in self._REQUIRED_ROLES if role not in self._roles
        ]
        if missing:
            raise RuntimeError(
                f"أدوار غير مسجلة — سجّل الخمسة أولًا: {missing}"
            )

        the_id = cycle_id or _new_cycle_id()
        emitter = _EventEmitter(the_id, on_event)
        ctx = CycleContext(goal=goal, cycle_id=the_id)
        with self._cycle_lock:  # دورة واحدة في كل لحظة
            with self._active_lock:
                self._active_id = the_id
            try:
                self._cycles[the_id] = (ctx, emitter)
                return self._run(
                    ctx=ctx,
                    emitter=emitter,
                    context=context,
                    workspace_root=workspace_root,
                    resume_from=resume_from,
                )
            finally:
                with self._active_lock:
                    self._active_id = None

    # ------------------------------------------------------------------ #
    # موافقة المستخدم — القناة الوحيدة إلى VERIFIED (القاعدة الذهبية)
    # ------------------------------------------------------------------ #

    def user_verifies(self, cycle_id: str) -> dict:
        """موافقة المستخدم على النتيجة — يرفضها جدول الانتقالات إلا من
        EVIDENCED أو ADJUDICATED، ويرفضها القاعدة الذهبية لأي فاعل
        غير «user» (وهذه الدالة هي فاعل المستخدم الوحيد)."""
        entry = self._cycles.get(cycle_id)
        if entry is None:
            raise KeyError(f"دورة غير معروفة: {cycle_id}")
        ctx, emitter = entry
        ctx.move_to(PlanState.VERIFIED, actor="user")  # يفرض القاعدة الذهبية
        event = emitter.emit(
            role="user",
            kind="user_verification",
            state=PlanState.VERIFIED.value,
            text="موافقة المستخدم سُجّلت — VERIFIED",
            details={"cycle_id": cycle_id, "final_state": ctx.state.value},
        )
        return {"cycle_id": cycle_id, "state": ctx.state.value, "event": event}

    # ------------------------------------------------------------------ #
    # الأمر 004 — الإيقاف الفوري الآمن
    # ------------------------------------------------------------------ #

    def request_stop(
        self, cycle_id: str, *, by: str = "owner", reason: str = ""
    ) -> dict:
        """طلب إيقاف دورة — يُقبل للدورة النشطة حصرًا (الأمر 004).

        القبول يرفع العلم ذرّيًا فورًا؛ التكريم عند أقرب نقطة تفتيش
        (أقصى الانتظار = استدعاء دور واحد — حدّ معلن لا خفاء).
        """
        with self._active_lock:
            active = self._active_id == cycle_id
        if active:
            receipt = self._stop.request_stop(cycle_id, by=by, reason=reason)
            return {
                "accepted": True,
                "status": "STOPPING",
                "receipt": asdict_receipt(receipt),
            }
        entry = self._cycles.get(cycle_id)
        if entry is None:
            return {"accepted": False, "status": "unknown"}
        return {
            "accepted": False,
            "status": "finished",
            "final_state": entry[0].state.value,
        }

    def cycle_status(self, cycle_id: str) -> dict | None:
        """حالة دورة للعرض — التشغيل والخطة وإيصال الإيقاف (004)."""
        entry = self._cycles.get(cycle_id)
        if entry is None:
            return None
        ctx = entry[0]
        with self._active_lock:
            running = self._active_id == cycle_id
        receipt = self._stop.receipt(cycle_id)
        return {
            "cycle_id": cycle_id,
            "state": ctx.state.value,
            "running": running,
            "stop_requested": receipt is not None,
            "stop_receipt": asdict_receipt(receipt),
        }

    # ------------------------------------------------------------------ #
    # أدوات تنسيق عامة (تخدم البنية والاختبارات والتوثيق)
    # ------------------------------------------------------------------ #

    @staticmethod
    def cycle_plan() -> list[dict[str, str]]:
        """خريطة الدورة للعرض والتوثيق — بلا تنفيذ."""
        return cycle_plan_rows()

    def role_ready(self, role: RoleType) -> bool:
        """هل دور مسجل؟ — فحص تركيبي للبنية."""
        return role in self._roles

    # ================================================================== #
    # الدورة الداخلية — بنية واحدة، مخارج موثقة، لا تنفيذ هنا
    # ================================================================== #

    def _run(
        self,
        *,
        ctx: CycleContext,
        emitter: _EventEmitter,
        context: str,
        workspace_root: Path | str | None,
        resume_from: dict | None = None,
    ) -> CycleResult:
        started = time.monotonic()
        state_history: list[str] = [ctx.state.value]
        arbiter_decisions: list[str] = []

        # ---- متغيرات الحصيلة (تُملأ عبر المراحل) ----
        plan: Plan | None = None
        outcomes: list[TaskOutcome] = []
        review_cycles = 0
        sub_verdict: SubVerdict | None = None
        issues: list[str] = []
        resumed_from_id = ""
        seeded_evidenced: set[str] = set()

        # جذر مساحة العمل من البداية (004): لقطة الإيقاف لها بيت دائمًا.
        root = (
            Path(workspace_root)
            if workspace_root
            else Path("runtime") / "cycles" / emitter.cycle_id
        )
        root.mkdir(parents=True, exist_ok=True)

        def stopping(at_step: str) -> None:
            """نقطة تفتيش الإيقاف (004) — ترفع الإشارة إن طُلب الطلب."""
            if self._stop.is_stopped(ctx.cycle_id):
                raise CycleStopSignal(at_step)

        # فساد لقطة الاستئناف يُرفض فورًا — خطأ مدخل لا فشل دورة (004)
        resume_point = load_resume_point(resume_from) if resume_from else None

        def move(to_state: PlanState, actor: str) -> None:
            from_state = ctx.state
            ctx.move_to(to_state, actor=actor)
            state_history.append(to_state.value)
            emitter.emit(
                role="coordinator",
                kind="state_change",
                state=to_state.value,
                text=f"{from_state.value} → {to_state.value} (بقرار {actor})",
                details={"from": from_state.value, "to": to_state.value, "actor": actor},
            )

        def finish() -> CycleResult:
            result = CycleResult(
                goal=ctx.goal,
                cycle_id=emitter.cycle_id,
                final_state=ctx.state,
                sub_verdict=sub_verdict,
                plan=plan,
                tasks=outcomes,
                review_cycles=review_cycles,
                arbiter_decisions=list(arbiter_decisions),
                state_history=state_history,
                events=emitter.events,
                duration_ms=int((time.monotonic() - started) * 1000),
                context=ctx,
                resumed_from=resumed_from_id,
            )
            can_verify = result.final_state in (
                PlanState.EVIDENCED,
                PlanState.ADJUDICATED,
            )
            summary = {
                "final_state": result.final_state.value,
                "sub_verdict": sub_verdict.value if sub_verdict else None,
                "tasks": [
                    {
                        "task_id": t.task_id,
                        "attempts": t.attempts,
                        "evidenced": t.evidenced,
                        "execution_failed": t.execution_failed,
                        "artifacts": t.artifacts,
                    }
                    for t in outcomes
                ],
                "review_cycles": review_cycles,
                "arbiter_decisions": list(arbiter_decisions),
                "can_verify": can_verify,
                "duration_ms": result.duration_ms,
            }
            if result.final_state is PlanState.STOPPED:
                done_text = "أُوقفت الدورة بأمر — الحالة النهائية: STOPPED."
            elif can_verify:
                done_text = (
                    "اكتملت الدورة — الحالة النهائية: "
                    f"{result.final_state.value}. موافقتك مطلوبة لبلوغ VERIFIED."
                )
            else:
                done_text = (
                    f"اكتملت الدورة — الحالة النهائية: {result.final_state.value}."
                )
            summary["resumed_from"] = resumed_from_id
            emitter.emit(
                role="coordinator",
                kind="cycle_done",
                state=result.final_state.value,
                text=done_text,
                details=summary,
            )
            return result

        def adjudicate(conflict_type: str, parties: list[str],
                      evidences: list[str], failure_context: dict | None = None):
            """استدعاء المحكَّم بسقف صلب — بعده تصعيد قسري بلا حكم."""
            nonlocal sub_verdict
            stopping("before_arbiter")
            if len(arbiter_decisions) >= MAX_ARBITER_CALLS:
                decision = "escalate_to_human"
                emitter.emit(
                    role="arbiter",
                    kind="arbiter_decision",
                    state=PlanState.ESCALATED_TO_HUMAN.value,
                    text=(
                        f"تجاوز سقف استدعاءات المحكَّم ({MAX_ARBITER_CALLS}) — "
                        "تصعيد قسري"
                    ),
                    details={
                        "conflict_type": conflict_type,
                        "decision": decision,
                        "rationale": "السقف البنيوي للاستدعاءات",
                        "escalation_to_human": True,
                        "max_retries_remaining": 0,
                        "forced": True,
                    },
                )
            else:
                t0 = time.monotonic()
                verdict = self._roles[RoleType.ARBITER].run(
                    ArbiterRequest(
                        conflict_type=conflict_type,
                        parties=parties,
                        evidences=evidences,
                        history=list(arbiter_decisions) + list(ctx.history),
                        failure_context=failure_context or {},
                    )
                )
                emitter.emit(
                    role="arbiter",
                    kind="arbiter_decision",
                    state=PlanState.ADJUDICATED.value,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    text=f"القرار: {verdict.decision} — {verdict.rationale}",
                    details={
                        "conflict_type": conflict_type,
                        "decision": verdict.decision,
                        "rationale": verdict.rationale,
                        "escalation_to_human": verdict.escalation_to_human,
                        "max_retries_remaining": verdict.max_retries_remaining,
                    },
                )
                decision = verdict.decision
                if verdict.sub_verdict is not None:
                    sub_verdict = verdict.sub_verdict
            arbiter_decisions.append(f"{conflict_type}:{decision}")
            return decision

        try:
            emitter.emit(
                role="user",
                kind="goal",
                text=ctx.goal,
                details={"context": context, "cycle_id": emitter.cycle_id},
            )
            stopping("start")

            # ===== الاستئناف (الأمر 004): حقن اللقطة قبل أي مرحلة =====
            if resume_point is not None:
                point = resume_point
                resumed_from_id = point.stopped_cycle_id
                ctx.evidence_refs.extend(point.evidence_refs)
                ctx.artifacts.extend(point.artifacts)
                if point.plan_signed:
                    plan = ThinkerResult(
                        plan=Plan.model_validate(point.plan_dump)
                    )
                    outcomes = [TaskOutcome(**o) for o in point.outcomes]
                    seeded_evidenced = {
                        o.task_id for o in outcomes if o.evidenced
                    }
                    review_cycles = point.review_cycles
                    ctx.state = PlanState.APPROVED  # نقطة الاستئناف
                    state_history = [PlanState.APPROVED.value]
                    emitter.emit(
                        role="coordinator",
                        kind="cycle.resumed",
                        state=PlanState.APPROVED.value,
                        text=(
                            f"استئناف من لقطة {point.stopped_cycle_id} — "
                            "الخطة الموقّعة محقونة والمرحلتان 1 تُتخطيان"
                        ),
                        details={
                            "from_cycle_id": point.stopped_cycle_id,
                            "seeded_outcomes": len(point.outcomes),
                            "seeded_evidenced": sorted(seeded_evidenced),
                        },
                    )
                else:
                    issues = list(point.review_issues)
                    context = (
                        context + " | " if context else ""
                    ) + (
                        f"استئناف دورة موقوفة ({point.stopped_cycle_id}) "
                        f"أُوقفت عند {point.state_at_stop}"
                    )

            # ================= مرحلة 1: التفكير والمراجعة =================
            if plan is None:  # دورة مستأنفة بخطة موقّعة تتخطى المرحلة
                while True:
                    t0 = time.monotonic()
                    plan = self._roles[RoleType.THINKER].run(
                        ThinkerRequest(
                            goal=ctx.goal,
                            context=context,
                            previous_reviews=issues,
                        )
                    )
                    emitter.emit(
                        role="thinker",
                        kind="plan_revised" if issues else "plan",
                        state=PlanState.DRAFT.value,
                        duration_ms=int((time.monotonic() - t0) * 1000),
                        text=(
                            f"عدّلت الخطة وفق ملاحظات المراجعة — "
                            f"{len(plan.plan.tasks)} مهام"
                            if issues
                            else f"أنتجت خطة بـ {len(plan.plan.tasks)} مهام "
                            f"ومخاطر {len(plan.plan.risks)} وافتراضات "
                            f"{len(plan.plan.assumptions)}"
                        ),
                        details={
                            "plan": plan.model_dump(),
                            "review_round": review_cycles + 1,
                        },
                    )

                    move(PlanState.UNDER_REVIEW, actor="system")
                    review_cycles += 1
                    stopping("after_thinker")
                    t1 = time.monotonic()
                    review = self._roles[RoleType.REVIEWER].run(
                        ReviewerRequest(plan=plan.plan, previous_gaps=issues)
                    )
                    emitter.emit(
                        role="reviewer",
                        kind="review_verdict",
                        state=PlanState.UNDER_REVIEW.value,
                        duration_ms=int((time.monotonic() - t1) * 1000),
                        text=(
                            "verdict: approved "
                            f"(الجودة {review.score:.1f}/10، التحسن "
                            f"{review.evolution_score:.1f}/10)"
                            if review.verdict is ReviewerVerdict.APPROVED
                            else "verdict: revise — الملاحظات: "
                            + "؛ ".join(i[:70] for i in review.issues[:3])
                        ),
                        details={
                            "verdict": review.verdict.value,
                            "issues": review.issues,
                            "required_changes": review.required_changes,
                            "score": review.score,
                            "evolution_score": review.evolution_score,
                            "review_round": review_cycles,
                        },
                    )

                    if review.verdict is ReviewerVerdict.APPROVED:
                        move(PlanState.APPROVED, actor="reviewer")
                        break

                    issues = list(review.issues) + list(review.required_changes)

                    if review_cycles >= MAX_REVIEW_CYCLES:
                        # خصام مراجعة: 3 جولات بلا اتفاق → المحكَّم
                        decision = adjudicate(
                            "review_deadlock", ["thinker", "reviewer"], issues)
                        if "retry" in decision:
                            move(PlanState.DRAFT, actor="arbiter")
                            continue
                        move(PlanState.ESCALATED_TO_HUMAN, actor="arbiter")
                        return finish()

                    move(PlanState.DRAFT, actor="reviewer")

            # ============ مرحلة 2: التنفيذ والتحقق (لكل مهمة) ============
            move(PlanState.EXECUTING, actor="system")
            stopping("before_execution")
            exhausted: list[PlanTask] = []
            round_no = 0
            while True:
                round_no += 1
                targets = (
                    [
                        t
                        for t in plan.plan.tasks
                        if t.id not in seeded_evidenced
                    ]
                    if round_no == 1
                    else list(exhausted)
                )
                exhausted = []
                for task in targets:
                    stopping("before_task:" + task.id)
                    outcome = self._run_task_attempts(
                        emitter, task=task, root=root, round_no=round_no,
                        stopping=stopping,
                    )
                    outcomes = [
                        o for o in outcomes if o.task_id != outcome.task_id
                    ] + [outcome]
                    if not outcome.evidenced:
                        exhausted.append(task)

                # فشل تنفيذي صريح (الركيزة رفضت/انهارت في المحاولة الأخيرة)
                # — لا خلاف بين دورين يحتكم؛ إعلان فشل صادق
                if any(o.execution_failed for o in outcomes):
                    move(PlanState.FAILED, actor="implementer")
                    return finish()

                move(PlanState.EXECUTED, actor="implementer")
                move(PlanState.VERIFYING, actor="system")
                stopping("before_rollup")

                # التحقق الكلي: كل معايير كل المهام مقابل كل الأدلة
                all_criteria = [
                    criterion
                    for task in plan.plan.tasks
                    for criterion in task.acceptance_criteria
                ]
                all_artifacts: list[str] = []
                for outcome in outcomes:
                    all_artifacts += outcome.artifacts
                t2 = time.monotonic()
                rollup = self._roles[RoleType.VERIFIER].run(
                    VerifierRequest(
                        task_acceptance_criteria=all_criteria,
                        artifacts=list(dict.fromkeys(all_artifacts)),
                        evidence_refs=list(ctx.evidence_refs),
                    )
                )
                evidenced = rollup.verdict is VerifierVerdict.EVIDENCED
                emitter.emit(
                    role="verifier",
                    kind="verification_rollup",
                    state=(
                        PlanState.EVIDENCED.value
                        if evidenced
                        else SubVerdict.NOT_EVIDENCED.value
                    ),
                    duration_ms=int((time.monotonic() - t2) * 1000),
                    text=(
                        f"الأدلة الكلية تطابق معايير المهام كلها "
                        f"(ثقة {int(rollup.confidence * 100)}%)"
                        if evidenced
                        else "الأدلة الكلية ناقصة: "
                        + "؛ ".join(m[:70] for m in rollup.missing_evidence[:3])
                    ),
                    details={
                        "verdict": rollup.verdict.value,
                        "checks_performed": rollup.checks_performed,
                        "missing_evidence": rollup.missing_evidence,
                        "confidence": rollup.confidence,
                    },
                )
                if evidenced:
                    move(PlanState.EVIDENCED, actor="verifier")
                    return finish()

                # نُفِّذت مهام دون أدلة كافية → خلاف منفذ×مراجع → المحكَّم
                move(PlanState.ADJUDICATED, actor="verifier")
                decision = adjudicate(
                    "execution_exhausted", ["implementer", "verifier"],
                    rollup.missing_evidence,
                    failure_context=_failures_of(outcomes, exhausted))
                if (
                    "retry" in decision
                    and exhausted
                    and round_no < MAX_EXECUTION_ROUNDS
                ):
                    # إعادة التنفيذ قرار المحكَّم وحده — يفرضها جدول
                    # الانتقالات (ADJUDICATED → EXECUTING بفاعل arbiter)
                    move(PlanState.EXECUTING, actor="arbiter")
                    continue
                move(PlanState.ESCALATED_TO_HUMAN, actor="arbiter")
                return finish()

        except CycleStopSignal as stop:  # الأمر 004 — إيقاف مُكرَّم لا فشل
            honor_stop(
                ctx=ctx,
                emitter=emitter,
                move=move,
                root=root,
                plan=plan,
                outcomes=outcomes,
                review_cycles=review_cycles,
                issues=issues,
                signal=stop,
                receipt=self._stop.receipt(ctx.cycle_id),
            )
            return finish()
        except Exception as error:  # noqa: BLE001 — انقطاع صادق لا انهيار صامت
            emitter.emit(
                role="coordinator",
                kind="cycle_error",
                state=ctx.state.value,
                text=f"الدورة انقطعت بخطأ غير متوقع: {error}",
                details={"error": str(error), "state": ctx.state.value},
            )
            try:
                move(PlanState.ESCALATED_TO_HUMAN, actor="system")
            except StateTransitionError:
                pass  # كانت حالة نهائية أصلًا
            return finish()

    # ------------------------------------------------------------------ #
    # محاولات المهمة الواحدة: تنفيذ → تحقق → (إصلاح) — ≤ MAX_EXECUTION_ATTEMPTS
    # ------------------------------------------------------------------ #

    def _run_task_attempts(
        self,
        emitter: _EventEmitter,
        *,
        task: PlanTask,
        root: Path,
        round_no: int,
        stopping: Callable[[str], None],
    ) -> TaskOutcome:
        outcome = TaskOutcome(task_id=task.id)
        previous: list[str] = []

        for attempt in range(1, MAX_EXECUTION_ATTEMPTS + 1):
            stopping(f"before_attempt:{attempt}:{task.id}")
            t0 = time.monotonic()
            implementation = self._roles[RoleType.IMPLEMENTER].run(
                ImplementerRequest(
                    task=task,
                    tools_available=["python"],
                    sandbox_root=str(root),
                    previous_attempts=list(previous),
                )
            )
            duration = int((time.monotonic() - t0) * 1000)
            outcome.attempts = attempt
            names = [Path(a).name for a in implementation.artifacts]
            emitter.emit(
                role="implementer",
                kind="task_execution",
                state=PlanState.EXECUTED.value,
                duration_ms=duration,
                text=(
                    f"نفّذت {task.id} داخل الركيزة (محاولة {attempt}) — "
                    f"الأدلة: {', '.join(names) if names else 'لا شيء'}"
                    if implementation.status is ImplementerStatus.EXECUTED
                    else f"فشل تنفيذ {task.id} (محاولة {attempt}): "
                    + implementation.stderr_truncated[:120]
                ),
                details={
                    "task_id": task.id,
                    "attempt": attempt,
                    "round": round_no,
                    "status": implementation.status.value,
                    "artifacts": implementation.artifacts,
                    "evidence_refs": implementation.evidence_refs[:8],
                    "stdout": implementation.stdout_truncated,
                    "stderr": implementation.stderr_truncated,
                    # الفشل المنظم (008 §18) + جودة الأدلة (§19)
                    "failure": implementation.failure or None,
                    "evidence_quality": (
                        "NO_EVIDENCE" if (
                            implementation.status is not ImplementerStatus.EXECUTED
                            and not implementation.artifacts
                            and not implementation.evidence_refs) else None),
                },
            )
            if implementation.status is not ImplementerStatus.EXECUTED:
                outcome.execution_failed = True
                outcome.failure = implementation.failure
                previous.append(
                    f"محاولة {attempt}: فشل تنفيذي — "
                    f"{implementation.stderr_truncated[:100]}"
                )
                continue
            outcome.execution_failed = False
            stopping(f"after_execution:{task.id}")
            outcome.artifacts = list(
                dict.fromkeys(outcome.artifacts + implementation.artifacts)
            )

            t1 = time.monotonic()
            verdict = self._roles[RoleType.VERIFIER].run(
                VerifierRequest(
                    task_acceptance_criteria=task.acceptance_criteria,
                    artifacts=implementation.artifacts,
                    evidence_refs=implementation.evidence_refs,
                )
            )
            v_duration = int((time.monotonic() - t1) * 1000)
            evidenced = verdict.verdict is VerifierVerdict.EVIDENCED
            emitter.emit(
                role="verifier",
                kind="task_verification",
                state=(
                    PlanState.EVIDENCED.value
                    if evidenced
                    else SubVerdict.NOT_EVIDENCED.value
                ),
                duration_ms=v_duration,
                text=(
                    f"evidenced — معايير {task.id} مستوفاة "
                    f"(ثقة {int(verdict.confidence * 100)}%)"
                    if evidenced
                    else f"not_evidenced ({task.id}) — الناقص: "
                    + "؛ ".join(m[:60] for m in verdict.missing_evidence[:2])
                ),
                details={
                    "task_id": task.id,
                    "attempt": attempt,
                    "verdict": verdict.verdict.value,
                    "checks_performed": verdict.checks_performed,
                    "missing_evidence": verdict.missing_evidence,
                    "confidence": verdict.confidence,
                },
            )
            if evidenced:
                outcome.evidenced = True
                return outcome
            previous.append(
                f"محاولة {attempt}: not_evidenced — "
                + "؛ ".join(verdict.missing_evidence)[:120]
            )

        return outcome