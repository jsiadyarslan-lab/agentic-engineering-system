"""اللقطة القانونية لزمن تشغيل المشروع (013.4 §8) — إسقاط واحد.

WorkflowRuntimeSnapshot هو **المصدر الوحيد** الذي تقرأه الواجهة
لحالة سير العمل: لا مكوّن يشتق الحالة بنفسه من نقاط متفرقة —
كل من يريد «أين المشروع الآن وماذا ينتظر» يقرأ هذه اللقطة:

    project_id · job_id · current_phase/stage/step · status ·
    progress (من أحداث فعلية) · started_at · updated_at ·
    heartbeat_at · elapsed · waiting_for · blocking_reason ·
    active_role/tool/provider · environment · worker ·
    last_event · recent_events · available_actions

التقدم من الحقيقة الدائمة حصرًا (خطوات مكتملة/كلية) — لا نسب
مخترعة ولا مؤقتات جمالية (§50). الأفعال المتاحة مشتقة من الحالة
القانونية — لا زر بلا أمر دائم خلفه (§11).
"""

from __future__ import annotations

from datetime import datetime, timezone

from workflow.models import Project, Execution

_STAGES = [
    ("GOAL", "الهدف"),
    ("PLAN", "الخطة"),
    ("APPROVAL", "الاعتماد"),
    ("PREPARE", "التهيئة"),
    ("EXECUTE", "التنفيذ"),
    ("TEST", "الاختبار"),
    ("REVIEW", "المراجعة"),
    ("AUDIT", "التدقيق"),
    ("DONE", "الاكتمال"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _stage_of(project: dict, plan: dict | None) -> str:
    """المرحلة الكلية (013.4 §19) — من الحالة القانونية وحدها."""
    status = project.get("status", "")
    if status in ("VERIFIED",):
        return "DONE"
    if status == "COMPLETED":
        return "AUDIT"
    if status == "RUNNING":
        return "EXECUTE"
    if status == "PLANNING":
        return "PLAN"
    if status == "AWAITING_OWNER_APPROVAL":
        return "APPROVAL"
    if status in ("READY", "BLOCKED"):
        return "PREPARE" if status == "READY" else "PREPARE"
    if status == "REVISING":
        return "PLAN"
    return "GOAL"


def _waiting_for(sessions, project: dict, job: dict | None) -> dict:
    """«ما الذي ينتظره النظام» (§3) — حرفي من الحالة الدائمة."""
    status = project.get("status", "")
    if status == "PLANNING":
        from workflow import planning_runtime

        view = planning_runtime.session_view(sessions, project["id"])
        if view.get("active"):
            return {
                "kind": "model",
                "label": "استدعاء نموذج التخطيط",
                "detail": view.get("waiting_for") or {},
                "session": view.get("detail") or {},
            }
        return {"kind": "planning", "label": "توليد الخطة"}
    if status == "AWAITING_OWNER_APPROVAL":
        return {"kind": "owner_approval", "label": "اعتماد المالك للخطة"}
    if status == "BLOCKED":
        from workflow import service

        gates = [g for g in service.open_gates(sessions, project["id"])
                 if g["status"] == "PENDING"]
        if gates:
            return {
                "kind": "owner_gate",
                "label": "بوابة مالك",
                "gates": [g["kind"] for g in gates],
            }
        return {"kind": "environment", "label": "توفير بيئة التنفيذ"}
    if status == "PAUSED":
        return {"kind": "paused", "label": "متوقف مؤقتًا — الاستئناف قرارك"}
    if job is not None and str(job.get("status", "")).startswith(
            "WAITING_"):
        return {
            "kind": "job_wait",
            "label": job.get("waiting_kind", ""),
            "detail": job.get("waiting_detail") or {},
        }
    return {"kind": "none", "label": ""}


def _blocking_reason(sessions, project: dict) -> str:
    """سبب الحجب الحرفي (§3) — آخر خطأ أو بوابة، لا نص عام."""
    status = project.get("status", "")
    if status not in ("BLOCKED", "PAUSED", "PLANNING"):
        return ""
    last_error = project.get("last_error") or ""
    if last_error:
        return last_error[:400]
    from workflow import service

    gates = [g for g in service.open_gates(sessions, project["id"])
             if g["status"] == "PENDING"]
    if gates:
        return gates[0].get("reason", "")[:400]
    return ""


def _progress(sessions, project: dict, plan: dict | None) -> dict:
    """تقدم حقيقي (§50) — خطوات مكتملة/خطوة جارية/الكلية + أحداث."""
    from workflow import service

    total = completed = failed = 0
    current_step = None
    if plan is not None:
        for phase in service.list_phases(sessions, project["id"]):
            for step in service.phase_steps(sessions, phase["id"]):
                total += 1
                if step["status"] == "COMPLETED":
                    completed += 1
                elif step["status"] == "FAILED":
                    failed += 1
                if step["id"] == project.get("current_step_id"):
                    current_step = step
    return {
        "steps_total": total,
        "steps_completed": completed,
        "steps_failed": failed,
        "percent": round(100.0 * completed / total, 1) if total else 0.0,
        "current_step": (
            {"id": current_step["id"],
             "objective": current_step["objective"],
             "status": current_step["status"]}
            if current_step else None
        ),
    }


def _active_activity(sessions, project: dict) -> dict:
    """الدور/الأداة/المزود النشط — من آخر الأحداث الفعلية لا تخمين."""
    from workflow import service

    events = service.list_events(sessions, project["id"], limit=30)
    role = tool = provider = ""
    last_event = None
    for event in reversed(events):
        if last_event is None:
            last_event = event
        kind = event.get("kind", "")
        payload = event.get("payload") or {}
        if not role and kind == "ROLE_EXECUTING":
            role = payload.get("role", "")
        if not tool and kind == "TOOL_EXECUTION":
            tool = payload.get("tool", "")
        if not provider and kind in ("MODEL_CALL_STARTED",
                                     "MODEL_CALL_COMPLETED"):
            provider = payload.get("provider", "")
        if role and tool and provider:
            break
    return {"role": role, "tool": tool, "provider": provider,
            "last_event": last_event}


def _available_actions(project: dict, job: dict | None,
                       planning_active: bool) -> list[str]:
    """الأزرار المتاحة (§11) — مشتقة من الحالة القانونية حصرًا.

    لا زر بلا أمر دائم خلفه: كل فعل هنا تقابله نقطة نهاية فعلية.
    """
    status = project.get("status", "")
    actions: list[str] = []
    if status in ("RUNNING", "PLANNING", "REVISING"):
        actions += ["pause", "stop"]
    if status == "PAUSED":
        actions += ["resume", "stop"]
    if status in ("READY", "DRAFT", "AWAITING_OWNER_APPROVAL"):
        actions += ["run"]
    if planning_active:
        actions += ["stop"]
    if status in ("BLOCKED", "PAUSED", "FAILED", "DRAFT") or \
            project.get("last_error"):
        actions += ["retry"]
    actions += ["duplicate", "rename", "history", "archive"]
    if project.get("archived_at"):
        actions = [a for a in actions if a != "archive"] + ["restore"]
    # إزالة التكرار مع حفظ الترتيب
    seen: set[str] = set()
    return [a for a in actions if not (a in seen or seen.add(a))]


def _conversation_id(sessions, project_id: int):
    """(013.5 §I) محادثة المشروع — ربط صريح لا تخمين."""
    try:
        from sqlalchemy import select

        from persistence.models import Conversation

        with sessions() as session:
            row = session.scalars(
                select(Conversation)
                .where(Conversation.project_id == int(project_id))
                .order_by(Conversation.id.asc())
                .limit(1)
            ).first()
            return int(row.id) if row is not None else None
    except Exception:  # noqa: BLE001 — القراءة اختيارية
        return None


def _last_successful_transition(sessions, project_id: int) -> dict | None:
    """(013.5 §I) آخر انتقال ناجح — النجاحات وحدها لا كل الأحداث."""
    from workflow import service

    events = service.list_events(sessions, project_id, limit=60)
    for event in reversed(events):
        kind = str(event.get("kind") or "")
        if kind.endswith(("_FAILED", "_INTERRUPTED")) or \
                kind in ("WORKFLOW_DIAGNOSED", "PLANNING_INVARIANT_HEALED"):
            continue
        if kind.startswith(("PLAN_", "PLANNING_", "OWNER_", "JOB_",
                            "ENVIRONMENT_", "EXECUTION_", "PHASE_", "STEP_",
                            "PREFLIGHT_", "CAPABILITIES_", "EVIDENCE_")):
            return {"kind": kind, "id": event.get("id"),
                    "at": event.get("created_at"),
                    "payload": event.get("payload") or {}}
    return None


def _retry_count(sessions, project_id: int) -> int:
    """(013.5 §I) عدد محاولات التخطيط — من السجل الدائم."""
    try:
        from sqlalchemy import func, select

        from workflow.models import PlanningSession

        with sessions() as session:
            total = session.scalar(
                select(func.count()).select_from(PlanningSession)
                .where(PlanningSession.project_id == int(project_id))
            )
            return int(total or 0)
    except Exception:  # noqa: BLE001
        return 0


def runtime_snapshot(sessions, project_id: int, *,
                     job: dict | None = None) -> dict:
    """اللقطة القانونية (013.4 §8 + 013.5 §I) — مصدر الحقيقة الواحد.

    كل ما تحتاجه الواجهة في نداء واحد. (013.5 §I) أُضيفت الحقول التي
    كانت تنقصها فاضطرت خمسة ملفات واجهة لاشتقاق «حقائق» متفرقة:
    المزود/النموذج/request_id الفعليون، آخر نشاط حقيقي منفصلًا عن
    النبضة، سقف المهلة، عدّاد المحاولات، الهويات (محادثة/تشغيل/
    جلسة تخطيط)، وآخر انتقال ناجح.
    """
    from workflow import planning_runtime
    from workflow import service

    project = service.get_project(sessions, int(project_id))
    if project is None:
        raise KeyError(f"مشروع غير معروف: {project_id}")
    plan = service.latest_plan(sessions, project["id"])
    if job is None:
        try:
            from harness.jobs import JobManager
            from harness.seams import HarnessSeams

            manager = JobManager(HarnessSeams(sessions))
            job = manager.job_for_project(project["id"])
        except Exception:  # noqa: BLE001 — الوظيفة قراءة اختيارية
            job = None

    planning = planning_runtime.session_view(sessions, project["id"])
    planning_detail = planning.get("detail") or {}
    waiting = _waiting_for(sessions, project, job)
    activity = _active_activity(sessions, project)
    started = _parse_iso(project.get("created_at"))
    now = _now()

    # البيئة والعامل — من الحالة القانونية الموحدة (013.2)
    environment: dict = {}
    try:
        from execution import runtime_state as runtime_state_mod

        canonical = runtime_state_mod.canonical_state(
            sessions, project.get("execution_policy")
            or "STRICT_ISOLATED", job=job
        )
        environment = {
            "state": canonical.get("state"),
            "coherent": canonical.get("coherent"),
            "environment_id": canonical.get("environment_id"),
            "worker_id": canonical.get("worker_id"),
            "backend": canonical.get("selected") or {},
        }
    except Exception:  # noqa: BLE001 — البيئة قراءة اختيارية
        pass

    # (013.5 §I) زمن التشغيل: الوظيفة إن وُجدت، وإلا جلسة التخطيط —
    # لا «مضى 17992ث» بلا مرجع حقيقي.
    heartbeat_at = None
    started_at = project.get("created_at")
    elapsed_s = None
    if job is not None:
        heartbeat_at = job.get("heartbeat_at")
        job_started = _parse_iso(job.get("started_at"))
        if job_started is not None:
            started_at = job.get("started_at")
            elapsed_s = round((now - job_started).total_seconds(), 1)
    if elapsed_s is None and planning_detail.get("started_at"):
        session_started = _parse_iso(planning_detail["started_at"])
        if session_started is not None:
            started_at = planning_detail["started_at"]
            heartbeat_at = planning_detail.get("heartbeat_at") or heartbeat_at
            elapsed_s = round((now - session_started).total_seconds(), 1)
    if elapsed_s is None and started is not None:
        elapsed_s = round((now - started).total_seconds(), 1)

    phase_row = _entity(sessions, "phase", project.get("current_phase_id"))
    step_row = _entity(sessions, "step", project.get("current_step_id"))

    from workflow import service as _service

    recent_events = _service.list_events(
        sessions, project["id"], limit=20
    )

    return {
        # ---- الهويات (§I) ----
        "project_id": project["id"],
        "conversation_id": _conversation_id(sessions, project["id"]),
        "run_id": (job or {}).get("id"),
        "planning_session_id": planning_detail.get("id"),
        "name": project["name"],
        "objective": project["objective"],
        "archived_at": project.get("archived_at"),
        # ---- الموضع ----
        "status": project["status"],
        "phase": phase_row,
        "stage": _stage_of(project, plan),
        "stage_labels": {key: label for key, label in _STAGES},
        "step": step_row,
        "current_phase_id": project.get("current_phase_id"),
        "current_step_id": project.get("current_step_id"),
        "plan": (
            {"id": plan["id"], "version": plan["version"],
             "approved": plan["approved_by_owner"],
             "phases": len(plan.get("phases") or [])}
            if plan else None
        ),
        "progress": _progress(sessions, project, plan),
        # ---- الزمن (§I) ----
        "started_at": started_at,
        "updated_at": project.get("updated_at"),
        "elapsed_seconds": elapsed_s,
        "elapsed_s": elapsed_s,
        "heartbeat_at": heartbeat_at,
        "last_meaningful_activity_at": planning_detail.get(
            "last_meaningful_activity_at"),
        "planning_silence_s": planning_detail.get("silence_s"),
        "timeout_at": planning_detail.get("hard_deadline_at"),
        "finished_at": planning_detail.get("finished_at"),
        # ---- المزود/النموذج الفعليان (§B/§I) ----
        "provider": planning_detail.get("provider") or activity["provider"],
        "model": planning_detail.get("model") or "",
        "actual_provider": planning_detail.get("actual_provider") or "",
        "actual_model": planning_detail.get("actual_model") or "",
        "request_id": planning_detail.get("request_id") or "",
        "attempt": planning_detail.get("attempt"),
        "retry_count": _retry_count(sessions, project["id"]),
        # ---- الانتظار والسبب (§3/§J) ----
        "waiting_for": waiting,
        "blocking_reason": _blocking_reason(sessions, project),
        "planning": planning,
        "wait_phase": planning.get("wait_phase"),
        "last_error": project.get("last_error", ""),
        # ---- المزود/النموذج الفعليان (مكرر للتوضيح) ----
        "provider": planning_detail.get("provider") or activity["provider"],
        "model": planning_detail.get("model") or "",
        "actual_provider": planning_detail.get("actual_provider") or "",
        "actual_model": planning_detail.get("actual_model") or "",
        "attempt": planning_detail.get("attempt"),
        "retry_count": _retry_count(sessions, project["id"]),
        # ---- المرحلة والخطوة الحالية ----
        "stage": _stage_of(project, plan),
        "stage_labels": {key: label for key, label in _STAGES},
        "step": step_row,
        "current_phase_id": project.get("current_phase_id"),
        "current_step_id": project.get("current_step_id"),
        # ---- الانتظار والسبب (§3/§J) ----
        "waiting_for": waiting,
        "blocking_reason": _blocking_reason(sessions, project),
        "planning": planning,
        "wait_phase": planning.get("wait_phase"),
        "last_error": project.get("last_error", ""),
        # ---- المزود/النموذج الفعليان (مكرر للتوضيح) ----
        "provider": planning_detail.get("provider") or activity["provider"],
        "model": planning_detail.get("model") or "",
        "actual_provider": planning_detail.get("actual_provider") or "",
        "actual_model": planning_detail.get("actual_model") or "",
        "request_id": planning_detail.get("request_id") or "",
        "attempt": planning_detail.get("attempt"),
        "retry_count": _retry_count(sessions, project["id"]),
        # ---- الانتظار والسبب (§3/§J) ----
        "waiting_for": waiting,
        "blocking_reason": _blocking_reason(sessions, project),
        "planning": planning,
        "wait_phase": planning.get("wait_phase"),
        "last_error": project.get("last_error", ""),
        # ---- التشغيل والبيئة ----
        "job": (
            {"id": job["id"], "status": job.get("status"),
             "waiting_kind": job.get("waiting_kind"),
             "heartbeat_at": job.get("heartbeat_at"),
             "tick_count": job.get("tick_count"),
             "attempt": job.get("attempt")}
            if job else None
        ),
        "activity": {
            "role": activity["role"],
            "tool": activity["tool"],
            "provider": activity["provider"],
        },
        "environment": environment,
        "backend": environment.get("backend") or {},
        "worker": (
            {"id": environment.get("worker_id")}
            if environment.get("worker_id") else None
        ),
        # (013.7 §P14) تنفيذ الأمر الحالي
        "execution": _execution_detail(sessions, project["id"]),
        # ---- الأحداث ----
        "last_event": activity["last_event"],
        "last_successful_transition": _last_successful_transition(
            sessions, project["id"]),
        "recent_events": recent_events[-10:],
        "available_actions": _available_actions(
            project, job, bool(planning.get("active"))
        ),
    }


def _execution_detail(sessions, project_id: int) -> dict | None:
    """(013.7 §P14) تفاصيل تنفيذ الأمر الحالي — للواجهة."""
    from workflow import service
    from workflow.models import Project, Execution

    with sessions() as session:
        project = session.get(Project, int(project_id))
        if project is None:
            return None
        exec_id = project.get("current_execution_id")
        if not exec_id:
            return None
        exec_row = session.get(Execution, int(exec_id))
        if exec_row is None:
            return None
        return {
            "id": exec_row.id,
            "step_id": exec_row.step_id,
            "attempt": exec_row.attempt,
            "status": exec_row.status,
            "command": exec_row.command,
            "command_type": exec_row.command_type,
            "cwd": exec_row.cwd,
            "pid": exec_row.pid,
            "parent_pid": exec_row.parent_pid,
            "command_type": exec_row.command_type,
            "started_at": exec_row.started_at.isoformat() if exec_row.started_at else None,
            "finished_at": exec_row.finished_at.isoformat() if exec_row.finished_at else None,
            "status": exec_row.status,
            "agent_role": exec_row.agent_role,
        }


def _entity(sessions, kind: str, entity_id):
    """صف مرحلة/خطوة بمعرّفه — للعرض الحرفي في اللقطة (§I)."""
    if not entity_id:
        return None
    from workflow import service

    try:
        if kind == "phase":
            return service.get_phase(sessions, int(entity_id))
        return service.get_step(sessions, int(entity_id))
    except Exception:  # noqa: BLE001 — القراءة اختيارية
        return {"id": entity_id}


__all__ = ["runtime_snapshot"]
