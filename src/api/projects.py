"""نقاط نهاية المشاريع (الأمر 007 §18) — API نحيف حول المحرك الدائم.

لا orchestration هنا: الحلقة الذاتية في workflow/engine.py، والقاعدة
في workflow/service.py — هذه الطبقة نقل وتسجيل وبث فقط.

- POST/GET /api/projects                    إنشاء/قائمة (+ حالة الاسترداد)
- GET    /api/projects/{id}                 التفصيل الكامل (خطة/مراحل/بوابات)
- GET    /api/projects/{id}/plan            الخطة الحالية
- POST   /api/projects/{id}/plan/generate   توليد الخطة (حي)
- POST   /api/projects/{id}/plan/approve    اعتماد/رفض المالك
- POST   /api/projects/{id}/run/stream      تشغيل الحلقة الذاتية — SSE
- POST   /api/projects/{id}/stop            إيقاف بلقطة قابلة للاستئناف
- POST   /api/projects/{id}/resume          استئناف صريح (بعد restart أيضًا)
- POST   /api/projects/{id}/gates/{gid}     حل بوابة مالك
- POST   /api/projects/{id}/verify          التحقق النهائي — المالك وحده
- GET    /api/projects/{id}/phases|steps|executions|evidence|audit|events
"""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from providers_registry import registry
from workflow import service
from workflow.engine import EngineError, ProjectEngine

router = APIRouter(prefix="/api/projects", tags=["projects"])

#: منفّذ المشاريع — مشروع واحد يعمل في كل لحظة (حلقة ذاتية واحدة).
_project_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aes-project")

#: حالة المشروع النشط — بث لحظي فقط؛ الحقيقة الدائمة في القاعدة.
_project_state: dict = {"active": None, "lock": threading.Lock()}

#: خطاف اختبار — يستبدل مصنع المحرك (test wiring صريح، لا يمر منه إنتاج).
_test_engine_factory = None


def _sessions():
    from api import routes  # noqa: PLC0415 — كسول يمنع الدوران

    return routes._sessions


def _build_engine(on_event=None) -> ProjectEngine:
    """محرك الإنتاج — موجّه حي + مخطط حي، لا mock في أي طبقة."""
    if _test_engine_factory is not None:
        return _test_engine_factory(on_event=on_event)

    def router_factory():
        from api.routes import _build_live_router

        return _build_live_router()

    return ProjectEngine(
        _sessions(),
        router_factory=router_factory,
        on_event=on_event,
        role_mappings_provider=lambda: registry.get_mappings(_sessions()),
    )


class ProjectCreateIn(BaseModel):
    """إنشاء مشروع — الاسم والهدف."""

    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=3)


class PlanDecisionIn(BaseModel):
    """قرار المالك على الخطة."""

    approved: bool = True
    feedback: str = Field(default="", max_length=2000)


class GateDecisionIn(BaseModel):
    """حل بوابة مالك."""

    approved: bool
    note: str = Field(default="", max_length=2000)


class ProjectStopIn(BaseModel):
    """طلب إيقاف."""

    reason: str = Field(default="", max_length=500)


def _http(error: Exception) -> HTTPException:
    if isinstance(error, EngineError):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, KeyError):
        return HTTPException(status_code=404, detail=str(error.args[0] or error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=422, detail=str(error))
    return HTTPException(status_code=500, detail=str(error))


def _project_or_404(project_id: int) -> dict:
    project = service.get_project(_sessions(), project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"مشروع غير معروف: {project_id}")
    return project


@router.post("", status_code=201)
def create_project(body: ProjectCreateIn) -> dict:
    """إنشاء مشروع DRAFT — هدف دائم بحالة صادقة (§3)."""
    try:
        return _build_engine().create_project(body.name, body.objective)
    except Exception as error:  # noqa: BLE001 — خطأ صريح لا انهيار
        raise _http(error) from error


@router.get("")
def list_projects() -> dict:
    """قائمة المشاريع + تقييم الاسترداد للمشاريع غير النهائية (§19)."""
    projects = service.list_projects(_sessions())
    unfinished = [
        p for p in projects
        if p["status"] in ("RUNNING", "REVISING", "BLOCKED", "PAUSED")
    ]
    recovery = []
    for project in unfinished:
        checkpoint = service.latest_checkpoint(_sessions(), project["id"])
        gates = service.open_gates(_sessions(), project["id"])
        recovery.append({
            "project_id": project["id"],
            "status": project["status"],
            "checkpoint": checkpoint["id"] if checkpoint else None,
            "open_gates": [g["kind"] for g in gates],
            "resumable": project["status"] == "PAUSED" and not gates,
        })
    return {"projects": projects, "recovery": recovery,
            "active_run": _active_run_id()}


def _active_run_id() -> int | None:
    with _project_state["lock"]:
        active = _project_state.get("active")
        if active is not None and not active["done"].is_set():
            return active["project_id"]
    return None


@router.get("/{project_id}")
def project_detail(project_id: int) -> dict:
    """التفصيل الكامل — الخطة والمراحل والخطوات والبوابات والأحداث."""
    project = _project_or_404(project_id)
    plan = service.latest_plan(_sessions(), project_id)
    phases = service.list_phases(_sessions(), project_id)
    gates = service.list_gates(_sessions(), project_id)
    events = service.list_events(_sessions(), project_id, limit=30)
    executions = service.list_executions(_sessions(), project_id, limit=20)
    return {
        **project,
        "plan": plan,
        "phases": phases,
        "gates": gates,
        "events": events,
        "executions": executions,
        "active_run": _active_run_id() == project_id,
    }


@router.get("/{project_id}/plan")
def project_plan(project_id: int) -> dict:
    _project_or_404(project_id)
    plan = service.latest_plan(_sessions(), project_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="لا خطة بعد — ولّدها أولًا")
    return plan


@router.post("/{project_id}/plan/generate")
def generate_plan(project_id: int) -> dict:
    """توليد Master Plan — استدعاء LLM حي بعقد صارم (§4، لا خطة ملفقة)."""
    _project_or_404(project_id)
    try:
        return _build_engine().generate_plan(project_id)
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.post("/{project_id}/plan/approve")
def approve_plan(project_id: int, body: PlanDecisionIn) -> dict:
    """قرار المالك — اعتماد يفعّل الخطة، ورفض يعيد التوليد (§14)."""
    _project_or_404(project_id)
    try:
        return _build_engine().approve_plan(
            project_id, approved=body.approved, feedback=body.feedback
        )
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.post("/{project_id}/run/stream")
async def run_project(project_id: int) -> StreamingResponse:
    """تشغيل الحلقة الذاتية — بث SSE لكل انتقال مهم (§10+§17).

    كل tick يحمل حالته من القاعدة ويكتب إليها — انقطاع البث أو crash
    لا يفقد شيئًا: الاستئناف من آخر checkpoint بلا إعادة تعريف.
    """
    _project_or_404(project_id)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    done_event = threading.Event()

    with _project_state["lock"]:
        active = _project_state.get("active")
        if active is not None and not active["done"].is_set():
            raise HTTPException(
                status_code=409,
                detail=f"مشروع آخر يعمل حاليًا (#{active['project_id']}) — "
                "الحلقة الذاتية واحدة في كل لحظة",
            )
        _project_state["active"] = {
            "project_id": project_id, "done": done_event,
        }

    def on_event(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def run_in_thread() -> None:
        try:
            engine = _build_engine(on_event=on_event)
            project = service.get_project(_sessions(), project_id)
            if project is None:
                raise EngineError(f"مشروع غير معروف: {project_id}")
            if project["status"] == "PAUSED" and not project["stop_requested"]:
                # استئناف ضمني للموقوف بلقطة — إلا إن كان الإيقاف مطلوبًا
                # حديثًا: العلم يُكرَّم في أول نبضة ولا يُمسح أبدًا بصمت
                engine.resume(project_id)
            outcome = engine.run(project_id)
            loop.call_soon_threadsafe(queue.put_nowait, {
                "project_id": project_id, "kind": "run.done",
                "payload": outcome,
            })
        except Exception as error:  # noqa: BLE001 — بث الخطأ لا موته
            loop.call_soon_threadsafe(queue.put_nowait, {
                "project_id": project_id, "kind": "run.error",
                "payload": {"error": str(error)},
            })
        finally:
            # الخيط مالك تسجيل النشاط — لا دورة حياة SSE (درس السباق
            # الموثق: انقطاع العميل لا يعني توقف المحرك، فالمزامنة ممنوعة)
            done_event.set()
            loop.call_soon_threadsafe(queue.put_nowait, None)
            with _project_state["lock"]:
                if (_project_state.get("active") or {}).get(
                    "project_id"
                ) == project_id:
                    _project_state["active"] = None

    loop.run_in_executor(_project_executor, run_in_thread)

    async def generate():
        try:
            yield "data: " + json.dumps({
                "project_id": project_id, "kind": "run.start",
                "payload": {"status": "RUNNING"},
            }, ensure_ascii=False) + "\n\n"
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield "data: " + json.dumps(
                    event, ensure_ascii=False
                ) + "\n\n"
        finally:
            # انقطاع العميل لا يوقف المحرك — يكمل ويكتب كل شيء في
            # القاعدة؛ وتسجيل النشاط يُمسح من خيط المحرك وحده
            pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{project_id}/stop")
def stop_project(project_id: int, body: ProjectStopIn) -> dict:
    """إيقاف المشروع — علم ذرّي يُكرَّم عند أقرب checkpoint (§9)."""
    _project_or_404(project_id)
    try:
        return _build_engine().request_stop(project_id, body.reason)
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.post("/{project_id}/resume")
def resume_project(project_id: int) -> dict:
    """استئناف صريح — يعمل بعد restart من checkpoint الدائم (§9+§19)."""
    _project_or_404(project_id)
    try:
        return _build_engine().resume(project_id)
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.post("/{project_id}/gates/{gate_id}")
def resolve_gate(project_id: int, gate_id: int, body: GateDecisionIn) -> dict:
    """حل بوابة مالك — لكل نوع أثره (§14)."""
    _project_or_404(project_id)
    try:
        return _build_engine().resolve_gate(
            project_id, gate_id, approved=body.approved
        )
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.post("/{project_id}/verify")
def verify_project(project_id: int) -> dict:
    """التحقق النهائي — VERIFIED قرار المالك وحده (§16)."""
    _project_or_404(project_id)
    try:
        return _build_engine().verify(project_id)
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.get("/{project_id}/phases")
def project_phases(project_id: int) -> dict:
    _project_or_404(project_id)
    return {"phases": service.list_phases(_sessions(), project_id)}


@router.get("/{project_id}/steps")
def project_steps(project_id: int) -> dict:
    _project_or_404(project_id)
    steps = []
    for phase in service.list_phases(_sessions(), project_id):
        for step in service.phase_steps(_sessions(), phase["id"]):
            steps.append({"phase_id": phase["id"],
                          "phase_title": phase["title"], **step})
    return {"steps": steps}


@router.get("/{project_id}/executions")
def project_executions(project_id: int) -> dict:
    _project_or_404(project_id)
    return {"executions": service.list_executions(_sessions(), project_id)}


@router.get("/{project_id}/evidence")
def project_evidence(project_id: int) -> dict:
    _project_or_404(project_id)
    return {"evidence": service.list_evidence(_sessions(), project_id)}


@router.get("/{project_id}/audit")
def project_audit(project_id: int) -> dict:
    _project_or_404(project_id)
    return {"audits": service.list_audits(_sessions(), project_id)}


@router.get("/{project_id}/events")
def project_events(project_id: int, limit: int = 100) -> dict:
    _project_or_404(project_id)
    return {"events": service.list_events(
        _sessions(), project_id, limit=min(limit, 500)
    )}


def run_startup_recovery(sessions) -> list[dict]:
    """استرداد الإقلاع (§19) — اكتشاف وتقييم فقط، لا تنفيذ عشوائي."""
    return ProjectEngine(sessions, router_factory=lambda: None) \
        .assess_recovery()
