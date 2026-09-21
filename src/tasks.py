"""مشغّل المهمة العامة (الأمر 006 §2) — الدورة الحية لأي هدف مستخدم.

هذا هو المسار الرئيسي للمهمة في الواجهة: هدف المستخدم يمر بالأدوار
الخمسة الحية باختيارات النموذج المستقلة لكل دور (§3+§4)، والمنفذ
ينفذ أدوات حقيقية (بحث/جلب معلَن + كتابة/PDF داخل الركيزة)، والمراجع
يحكم على أدلة ميكانيكية. لا mock في أي دور، ولا نجاح وهمي أبدًا.

الحكم الصادق (أبسط من المهمة المتخصصة missions.py — هنا عقد عام):
- PASS إذا وفقط إذا كانت الحالة النهائية EVIDENCED أو ADJUDICATED.
- STOPPED إذا أوقفها المالك (لقطة قابلة للاستئناف مكتوبة).
- غير ذلك HARD STOP بسبب موثق (حالة/فشل مهام).

الأدلة evidence.json في مساحة عمل المهمة: كل ملف بـ sha256، وكل
استدعاء أداة موثق، وكل دور بنموذجه الذي استخدمه فعلًا (provider و
model من اختيار المستخدم — إثبات توجيه الأدوار §17).
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
    evidence_path: str = ""
    evidence_sha256: str = ""
    duration_ms: int = 0
    state_history: list[str] = field(default_factory=list)
    #: المنسق الحي — يبقى للموافقة اللاحقة (user_verifies).
    orchestrator: Any = None


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
) -> TaskResult:
    """تشغيل المهمة الحية العامة — دورة الأدوار الخمسة بأدوار حية.

    router: موجّه حي (ModelRouter.build_live() — production wiring).
    role_config: اختيار مستقل لكل دور (router.role_config.RoleSelection).
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

    ctx = ToolContext(grant_root=target)

    def tool_event_sink(event: dict) -> None:
        sink({"role": "implementer", **event})

    ctx.on_event = tool_event_sink

    if stop_controller is not None and cycle_id:
        ctx.stop_check = stop_controller.checker_for(cycle_id)

    try:
        orchestrator = build_live_orchestrator(
            router,
            tools_ctx=ctx,
            stop_controller=stop_controller,
            role_config=role_config,
        )
    except RoleSystemFault as fault:
        return _hard_stop(goal, str(fault), started, target, on_event)

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
        return _hard_stop(goal, str(fault), started, target, on_event)
    except Exception as error:  # noqa: BLE001 — فشل صريح موثق
        _emit(on_event, {
            "kind": "role.system_fault",
            "role": "coordinator",
            "text": f"الدورة الحية فشلت: {error}",
        })
        return _hard_stop(
            goal, f"الدورة الحية فشلت: {error}", started, target, on_event
        )

    # ---- جمع الأدلة الميكانيكية من مساحة العمل ----
    files = sorted(
        p.name for p in target.iterdir()
        if p.is_file() and p.name != "evidence.json"
    )
    tool_calls = [e for e in task_events if e.get("kind") == "tool.call"]

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
        failed_tasks = [
            getattr(step, "task_id", "?")
            for step in getattr(cycle, "steps", [])
            if getattr(step, "status", "") == "failed"
        ]
        if failed_tasks:
            reasons.append("مهام فاشلة: " + "، ".join(failed_tasks))
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
        json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8"
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
) -> TaskResult:
    """توقف صلب صريح — سبب موثق لا ترقيع (ولا دليل مزيف)."""
    result = TaskResult(
        verdict="HARD STOP",
        reason=reason,
        goal=goal,
        workspace=str(workspace),
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
        },
    })
    return result
