"""مشغّل المهمة العامة (الأمر 006 §2) — الدورة الحية لأي هدف مستخدم.

المسار الرئيسي للمهمة في الواجهة: هدف المستخدم يمر بالأدوار الخمسة
الحية، والمنفذ ينفذ أدوات حقيقية، والمراجع يحكم على أدلة ميكانيكية.
لا mock في أي دور، ولا نجاح وهمي أبدًا.

الأمر 008 (+ الإضافة): كل استدعاء أداة يخلف ToolInvocation دائمًا
(نجح أم فشل)؛ الفشل يصل الحكمَ كتلةً منظمة (class/stage/reason)؛
الخلاصة النهائية نص عربي مولَّد من حالة الدورة الفعلية لا قالبًا
ثابتًا (§27)؛ evidence_quality صادقة (artifacts=[] = NO_EVIDENCE §19).

الحكم الصادق:
- PASS إذا وفقط إذا كانت الحالة النهائية EVIDENCED أو ADJUDICATED.
- STOPPED إذا أوقفت (لقطة قابلة للاستئناف مكتوبة).
- غير ذلك HARD STOP بسبب موثق.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core.state import PlanState
from core.stop_controller import SNAPSHOT_NAME, StopController
from roles.live import RoleSystemFault
from roles.tools import ToolContext

TASKS_DIR = Path("runtime") / "tasks"

_VERDICT_TITLES = {
    "PASS": "اكتملت المهمة",
    "STOPPED": "أُوقفت المهمة",
    "HARD STOP": "توقفت المهمة عند حدّ صلب",
}


@dataclass
class TaskResult:
    """حصيلة المهمة العامة — الحكم الصادق والأدلة."""

    verdict: str                      # "PASS" | "HARD STOP" | "STOPPED"
    reason: str
    goal: str
    cycle_id: str = ""
    final_state: str = ""
    workspace: str = ""
    files: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    tool_invocations: list[dict] = field(default_factory=list)
    failure: dict | None = None       # كتلة الفشل المنظمة (008 §18)
    evidence_path: str = ""
    evidence_sha256: str = ""
    duration_ms: int = 0
    state_history: list[str] = field(default_factory=list)
    #: المنسق الحي — يبقى للموافقة اللاحقة (user_verifies).
    orchestrator: Any = None

    def human_summary(self) -> str:
        """خلاصة عربية مولَّدة من حالة الدورة الفعلية (008 §27)."""
        lines = [_VERDICT_TITLES.get(self.verdict, self.verdict) + "."]
        lines.append("")
        lines.append(f"الحالة النهائية: {self.final_state or '—'}")
        if self.failure:
            lines.append(
                f"السبب المباشر: {self.failure.get('tool', '')} — "
                f"{self.failure.get('reason', '')}"
                + (
                    f" (التصنيف: {self.failure.get('class', '')} / "
                    f"المرحلة: {self.failure.get('stage', '')})"
                    if self.failure.get("class") else ""
                )
            )
            attempts = self.failure.get("attempt")
            if attempts:
                lines.append(f"المحاولات: {attempts}")
        done = len(self.tool_invocations)
        succeeded = sum(
            1 for r in self.tool_invocations
            if r.get("status") == "SUCCEEDED"
        )
        lines.append(
            f"ما تم: {done} استدعاء أداة (نجح {succeeded}) · "
            f"{len(self.files)} ملفًا في مساحة العمل"
        )
        if self.verdict != "PASS":
            lines.append(
                "ما لم يتم: "
                + (
                    "المخرجات النهائية غير مكتملة الأدلة"
                    if not self.files else "التوثيق الكامل للنتيجة"
                )
            )
        lines.append(
            "الإجراء التالي: "
            + (
                "يمكن الموافقة على النتيجة"
                if self.verdict == "PASS"
                else "إعادة المحاولة أو مراجعة إعدادات الأدوات/المزودات"
            )
        )
        if self.evidence_path:
            lines.append(f"الأدلة: {self.evidence_path}")
        return "\n".join(lines)


def _emit(on_event: Callable[[dict], None] | None, event: dict) -> None:
    if on_event is not None:
        try:
            on_event(event)
        except Exception:  # noqa: BLE001 — المستقبِل لا يكسر المهمة
            pass


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _role_models_block(role_config: dict | None) -> dict:
    """نماذج الأدوار الفعلية — إثبات التوجيه المستقل (§17)."""
    block: dict[str, dict] = {}
    for key, value in (role_config or {}).items():
        provider = getattr(value, "provider", None)
        model = getattr(value, "model", None)
        if provider and model:
            block[key] = {"provider": provider, "model": model}
    return block


def _persist_tool_invocations(sessions, cycle_id: str,
                              records: list) -> None:
    """سجل الاستدعاءات الدائم (إضافة 008 §2) — فشل الكتابة لا يقتل."""
    if sessions is None or not records:
        return
    try:
        from readiness.models import ToolInvocation  # noqa: PLC0415

        with sessions() as session:
            for record in records:
                data = record.to_dict() if hasattr(record, "to_dict") else dict(record)
                session.add(ToolInvocation(
                    cycle_id=cycle_id,
                    tool_call_id=str(data.get("tool_call_id", ""))[:40],
                    tool=str(data.get("tool", ""))[:40],
                    status=str(data.get("status", "")),
                    transport_status=str(data.get("transport_status", "")),
                    result_status=str(data.get("result_status", "")),
                    failure_class=str(data.get("failure_class", ""))[:32],
                    failure_stage=str(data.get("failure_stage", ""))[:24],
                    failure_reason=str(data.get("failure_reason", ""))[:40],
                    query=str(data.get("query", "")),
                    result_count=int(data.get("result_count", 0) or 0),
                    analyzable=1 if data.get("analyzable") else 0,
                    error=str(data.get("error", "")),
                    retryable=1 if data.get("retryable") else 0,
                    duration_ms=int(data.get("duration_ms", 0) or 0),
                    execution_site=str(data.get("execution_site", ""))[:32],
                    output_sha256=str(data.get("output_sha256", ""))[:64],
                    record_json=json.dumps(data, ensure_ascii=False, default=str),
                ))
            session.commit()
    except Exception:  # noqa: BLE001 — السجل لا يكسر المهمة
        pass


def run_task(
    goal: str,
    *,
    router: Any,
    role_config: dict | None = None,
    workspace: Path | str | None = None,
    on_event: Callable[[dict], None] | None = None,
    cycle_id: str | None = None,
    stop_controller: StopController | None = None,
    resume_from: dict | None = None,
    sessions: Any = None,
    execution_policy: str | None = None,
    stop_cycle_id: str | None = None,
) -> TaskResult:
    """تشغيل المهمة الحية العامة — دورة الأدوار الخمسة بأدوار حية.

    router: موجّه حي (ModelRouter.build_live() — production wiring).
    role_config: اختيار مستقل لكل دور (router.role_config.RoleSelection).
    sessions: جلسة القاعدة لسجل tool_invocations الدائم (اختياري).
    execution_policy (013.1 §13): سياسة تنفيذ المشروع — تصل أدوات
    الخطوات حصرًا؛ STRICT_ISOLATED بلا بيئة معزولة = POLICY_BLOCK
    لا تنفيذ غير معزول بدلًا عنها.
    stop_cycle_id (013.1 §19): مفتاح إشارة الإيقاف على مستوى المشروع
    — المحرك يوقف بمفتاح ``project-{id}`` والمنفذ كان يستمع لمفتاح
    الخطوة ``project-{id}-step-{n}`` فلم يكن الإيقاف داخل الخطوة
    يُكرَّم أبدًا؛ الآن المفتاحان متطابقان عبر هذا المعامل.
    فشل بناء الأدوار أو أي system_fault = HARD STOP صريح بسبب موثق.
    """
    from core.stop_controller import load_resume_point
    from core.wiring import build_live_orchestrator

    if resume_from is not None:
        point = load_resume_point(resume_from)
        goal = point.goal  # هدف اللقطة هو العقد الأصلي

    started = time.monotonic()
    target = Path(workspace) if workspace else TASKS_DIR / (cycle_id or "task")
    target.mkdir(parents=True, exist_ok=True)
    task_events: list[dict] = []

    def sink(event: dict) -> None:
        task_events.append(event)
        _emit(on_event, event)

    sink({
        "kind": "task.start",
        "role": "mission",
        "goal": goal,
        "workspace": str(target),
        "role_models": _role_models_block(role_config),
    })

    ctx = ToolContext(grant_root=target, sessions=sessions,
                      execution_policy=execution_policy)

    def tool_event_sink(event: dict) -> None:
        sink({"role": "implementer", **event})

    ctx.on_event = tool_event_sink

    if stop_controller is not None and (stop_cycle_id or cycle_id):
        ctx.stop_check = stop_controller.checker_for(
            stop_cycle_id or cycle_id
        )

    try:
        orchestrator = build_live_orchestrator(
            router,
            tools_ctx=ctx,
            stop_controller=stop_controller,
            role_config=role_config,
        )
    except RoleSystemFault as fault:
        _persist_tool_invocations(sessions, cycle_id or "", ctx.tool_records)
        return _hard_stop(goal, str(fault), started, target, on_event,
                          tool_records=ctx.tool_records)

    try:
        cycle = orchestrator.run_cycle(
            goal,
            cycle_id=cycle_id,
            workspace_root=target,
            on_event=sink,
            resume_from=resume_from,
        )
    except RoleSystemFault as fault:
        _emit(on_event, {
            "kind": "role.system_fault",
            "role": getattr(fault, "role", "unknown"),
            "text": str(fault),
        })
        _persist_tool_invocations(sessions, cycle_id or "", ctx.tool_records)
        return _hard_stop(goal, str(fault), started, target, on_event,
                          tool_records=ctx.tool_records)
    except Exception as error:  # noqa: BLE001 — فشل صريح موثق
        _emit(on_event, {
            "kind": "role.system_fault",
            "role": "coordinator",
            "text": f"الدورة الحية فشلت: {error}",
        })
        _persist_tool_invocations(sessions, cycle_id or "", ctx.tool_records)
        return _hard_stop(
            goal, f"الدورة الحية فشلت: {error}", started, target, on_event,
            tool_records=ctx.tool_records,
        )

    # ---- سجل الاستدعاءات الدائم + الأدلة الميكانيكية ----
    _persist_tool_invocations(sessions, cycle.cycle_id, ctx.tool_records)
    files = sorted(
        p.name for p in target.iterdir()
        if p.is_file() and p.name != "evidence.json"
    )
    tool_calls = [e for e in task_events if e.get("kind") == "tool.call"]
    tool_records = [
        r.to_dict() if hasattr(r, "to_dict") else dict(r)
        for r in ctx.tool_records
    ]

    stopped = cycle.final_state is PlanState.STOPPED
    stop_block: dict | None = None
    snapshot_path = target / SNAPSHOT_NAME
    if stopped:
        try:
            snap = json.loads(snapshot_path.read_text(encoding="utf-8"))
            stop_block = {
                "stopped_by": snap.get("stopped_by", "غير معروف"),
                "stopped_at": snap.get("stopped_at", ""),
                "reason": snap.get("stop_reason", ""),
                "state_at_stop": snap.get("state_at_stop", ""),
                "phase": snap.get("phase", ""),
                "snapshot_path": str(snapshot_path),
                "snapshot_sha256": _sha256_file(snapshot_path),
            }
        except (OSError, ValueError):
            stop_block = {"snapshot_path": str(snapshot_path), "readable": False}

    # كتلة الفشل المنظمة من نتائج المهام الفاشلة (008 §18-§19)
    failure_block: dict | None = None
    failed_steps = [
        step for step in getattr(cycle, "steps", [])
        if getattr(step, "status", "") == "failed"
    ]
    # (W2-T25) مسار المنسق الحي: نتائج المهام في cycle.tasks — فشل
    # تنفيذي (execution_failed) يحمل كتلة فشل المنفذ (رسالة
    # RoleSystemFault الحرفية ضمن «detail»)؛ غياب هذا المسار كان
    # يبتلع تفاصيل الفشل في «لم تكتمل أدلةً» العامة.
    if not failed_steps:
        failed_outcomes = [
            t for t in getattr(cycle, "tasks", []) or []
            if getattr(t, "execution_failed", False)
        ]
        if failed_outcomes:
            first_outcome = failed_outcomes[0]
            failure_block = (
                getattr(first_outcome, "failure", None)
                or {
                    "class": "INSUFFICIENT_EVIDENCE",
                    "stage": "IMPLEMENTATION",
                    "reason": "EXECUTION_FAILED",
                    "tool": "",
                    "retryable": True,
                }
            )
            failure_block = {
                **failure_block,
                "task_id": getattr(first_outcome, "task_id", ""),
                "attempts": getattr(first_outcome, "attempts", 0),
            }
            failed_steps = [first_outcome]
    if failed_steps:
        first = failed_steps[0]
        failure_block = (
            getattr(first, "failure", None)
            or {
                "class": "INSUFFICIENT_EVIDENCE",
                "stage": "IMPLEMENTATION",
                "reason": "EXECUTION_FAILED",
                "tool": "",
                "retryable": True,
            }
        )
        failure_block = {
            **failure_block,
            "task_id": getattr(first, "task_id", ""),
            "attempts": getattr(first, "attempts", 0),
            "queries": sorted({
                str(r.get("query", "")) for r in tool_records
                if r.get("query") and r.get("tool") == failure_block.get("tool")
            })[:6],
            "artifacts": 0 if not files else len(files),
            "evidence": "NO_EVIDENCE" if not files else "PARTIAL",
        }

    if stopped:
        verdict = "STOPPED"
        reasons = [
            f"أوقفت المهمة بأمر ({stop_block.get('stopped_by', 'غير معروف')}) "
            f"عند {stop_block.get('phase', 'خطوة غير معروفة')}"
        ]
    else:
        reasons = []
        if cycle.final_state not in (PlanState.EVIDENCED, PlanState.ADJUDICATED):
            reasons.append(
                f"الحالة النهائية {cycle.final_state.value} — الدورة لم تكتمل أدلةً"
            )
        if failed_steps:
            reasons.append(
                "مهام فاشلة: " + "، ".join(
                    getattr(step, "task_id", "?") for step in failed_steps
                )
            )
        verdict = "PASS" if not reasons else "HARD STOP"

    evidence: dict[str, Any] = {
        "goal": goal,
        "cycle_id": cycle.cycle_id,
        "final_state": cycle.final_state.value,
        "role_models": _role_models_block(role_config),
        "files": {
            p.name: {"sha256": _sha256_file(p), "bytes": p.stat().st_size}
            for p in sorted(target.iterdir())
            if p.is_file() and p.name != "evidence.json"
        },
        "tool_calls": tool_calls,
        "tool_invocations": tool_records,
        "failure": failure_block,
        "evidence_quality": (
            "NO_EVIDENCE" if not files and not tool_records else "PRESENT"
        ),
        "state_history": cycle.state_history,
        "arbiter_decisions": cycle.arbiter_decisions,
        "resumed_from": cycle.resumed_from,
        "duration_ms": cycle.duration_ms,
        "verdict": verdict,
        "verdict_reasons": reasons,
    }
    if stop_block is not None:
        evidence["stop"] = stop_block
    evidence_path = target / "evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    evidence_sha = _sha256_file(evidence_path)

    result = TaskResult(
        verdict=verdict,
        reason="؛ ".join(reasons) if reasons else "المهمة اكتملت بأدلة كاملة",
        goal=goal,
        cycle_id=cycle.cycle_id,
        final_state=cycle.final_state.value,
        workspace=str(target),
        files=files,
        tool_calls=tool_calls,
        tool_invocations=tool_records,
        failure=failure_block,
        evidence_path=str(evidence_path),
        evidence_sha256=evidence_sha,
        duration_ms=int((time.monotonic() - started) * 1000),
        state_history=list(cycle.state_history),
        orchestrator=orchestrator,
    )
    _emit(on_event, {
        "kind": "task_done",
        "role": "mission",
        "verdict": verdict,
        "text": result.reason,
        "details": {
            "cycle_id": result.cycle_id,
            "final_state": result.final_state,
            "workspace": result.workspace,
            "files_count": len(result.files),
            "tool_calls_count": len(result.tool_calls),
            "tool_invocations_count": len(tool_records),
            "failed_tool_calls": sum(
                1 for r in tool_records if r.get("status") == "FAILED"
            ),
            "recovery_attempts": sum(
                1 for e in task_events if e.get("kind") == "tool.recovery"
            ),
            "failure": failure_block,
            "evidence_quality": evidence["evidence_quality"],
            "human_summary": result.human_summary(),
            "evidence_path": result.evidence_path,
            "evidence_sha256": evidence_sha,
            "verdict_reasons": reasons,
            "duration_ms": result.duration_ms,
            "state_history": result.state_history,
            "stop": stop_block,
        },
    })
    return result


def _hard_stop(
    goal: str,
    reason: str,
    started: float,
    workspace: Path,
    on_event: Callable[[dict], None] | None,
    *,
    tool_records: list | None = None,
) -> TaskResult:
    """توقف صلب صريح — سبب موثق لا ترقيع (ولا دليل مزيف)."""
    records = [
        r.to_dict() if hasattr(r, "to_dict") else dict(r)
        for r in (tool_records or [])
    ]
    sandbox_failure = next(
        (r for r in records if r.get("failure_class") == "SANDBOX_FAILURE"),
        None,
    )
    failure_block = None
    if sandbox_failure is not None:
        failure_block = {
            "class": "SANDBOX_FAILURE",
            "stage": sandbox_failure.get("failure_stage", "STARTUP"),
            "tool": sandbox_failure.get("tool", ""),
            "reason": sandbox_failure.get("failure_reason", ""),
            "retryable": False,
        }
    result = TaskResult(
        verdict="HARD STOP",
        reason=reason,
        goal=goal,
        workspace=str(workspace),
        tool_invocations=records,
        failure=failure_block or {
            "class": "EXECUTOR_FAILURE", "stage": "IMPLEMENTATION",
            "reason": "SYSTEM_FAULT", "retryable": False,
        },
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    _emit(on_event, {
        "kind": "task_done",
        "role": "mission",
        "verdict": "HARD STOP",
        "text": reason,
        "details": {
            "final_state": "HARD STOP",
            "verdict_reasons": [reason],
            "duration_ms": result.duration_ms,
            "workspace": str(workspace),
            "failure": result.failure,
            "tool_invocations_count": len(records),
            "human_summary": result.human_summary(),
        },
    })
    return result
