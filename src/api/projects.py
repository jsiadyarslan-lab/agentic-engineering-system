"""نقاط نهاية المشاريع (الأمر 007 §18 + 013 §1-§7) — API نحيف حول
المحرك الدائم ومُطلق سير العمل.

لا orchestration هنا: الحلقة الذاتية في workflow/engine.py، والقاعدة
في workflow/service.py، والإطلاق الخلفي في workflow/runner.py — هذه
الطبقة نقل وتسجيل وبث فقط.

(013 §3) الاعتماد أمر إلى سير العمل: POST /plan/approve لا يكتب
صف قاعدة وينتهي — يطلق الحلقة خلفيًا عبر runner.launch والبث يحمل
كل ما يحدث: PREFLIGHT ← JOB ← PHASE/STEP/ROLES ← EVIDENCE.

- POST/GET /api/projects                    إنشاء/قائمة (+ حالة الاسترداد)
- GET    /api/projects/{id}                 التفصيل الكامل (خطة/مراحل/بوابات)
- GET    /api/projects/{id}/state           لقطة مصالحة كاملة (013 §6)
- GET    /api/projects/{id}/plan            الخطة الحالية
- POST   /api/projects/{id}/plan/generate   توليد الخطة (حي)
- POST   /api/projects/{id}/plan/approve    اعتماد/رفض المالك ← إطلاق (013)
- POST   /api/projects/{id}/run/stream      تشغيل/إرفاق — بث SSE (013 §42)
- POST   /api/projects/{id}/stop            إيقاف بلقطة قابلة للاستئناف
- POST   /api/projects/{id}/resume          استئناف صريح ← إطلاق (013)
- POST   /api/projects/{id}/gates/{gid}     حل بوابة مالك (idempotent)
- POST   /api/projects/{id}/preflight       إعادة الفحص ← إطلاق عند النجاح
- POST   /api/projects/{id}/execution-policy سياسة التنفيذ (011 §26)
- POST   /api/projects/{id}/verify          التحقق النهائي — المالك وحده
- GET    /api/projects/{id}/phases|steps|executions|evidence|audit|events
- GET    /api/projects/events               تيار أحداث عام — SSE حي
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from providers_registry import registry
from workflow import gates as gate_machine
from workflow import service
from workflow import runner as workflow_runner
from workflow.engine import EngineError, ProjectEngine


def _harness_manager(on_event=None, *, engine=None):
    """مدير وظائف فوق درز الـharness — (012-E) ربط بسيط لا منطق."""
    from harness.jobs import JobManager
    from harness.seams import HarnessSeams

    return JobManager(
        HarnessSeams(_sessions()), engine=engine, on_event=on_event,
    )

router = APIRouter(prefix="/api/projects", tags=["projects"])

#: حالة المشروع النشط — بث لحظي فقط؛ الحقيقة الدائمة في القاعدة.
#: (013) المصدر الوحيد الآن workflow/runner — لا مسار موازٍ أبدًا.
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


def _live_broadcast_on_event(event: dict) -> None:
    """بث لحظي لأحداث المحرك على تيار المشاريع (013.4 §1).

    الأحداث الدائمة كتبها المحرك/جلسة التخطيط قبلنا — هذا غلاف النشر
    اللحظي فقط: نفس عقد الـrunner (event_id موحّد + عزل القاعدة).
    """
    from core.live_bus import BUS, normalize_event

    BUS.publish(normalize_event({
        "project_id": event.get("project_id"),
        "kind": event.get("kind", ""),
        "payload": event.get("payload", {}),
        "event_id": int(event.get("event_id") or 0),
        "stream": "projects",
        "db": workflow_runner.sessions_db_key(_sessions()),
    }))


class ProjectCreateIn(BaseModel):
    """إنشاء مشروع — الاسم والهدف (+ سياسة التنفيذ 011 §26)."""

    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=3)
    execution_policy: str = Field(
        default="STRICT_ISOLATED",
        pattern="^(STRICT_ISOLATED|COMPATIBLE_LOCAL)$",
    )


class PlanDecisionIn(BaseModel):
    """قرار المالك على الخطة."""

    approved: bool = True
    feedback: str = Field(default="", max_length=2000)


class GateDecisionIn(BaseModel):
    """حل بوابة مالك."""

    approved: bool
    note: str = Field(default="", max_length=2000)


class ProjectStopIn(BaseModel):
    """طلب إيقاف — مؤقت (افتراضي) أو نهائي دائم (013.4 §12)."""

    reason: str = Field(default="", max_length=500)
    final: bool = False


class ExecutionPolicyIn(BaseModel):
    """سياسة التنفيذ (011 §26) — قرار مالك صريح."""

    policy: str = Field(pattern="^(STRICT_ISOLATED|COMPATIBLE_LOCAL)$")


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


def _execution_gate(project: dict, plan: dict | None) -> dict:
    """حالة بوابة التنفيذ المشتقة (011 §1+§3) — مفصولة عن قرار البوابة.

    المشتق من: اعتماد الخطة + آخر فحص مسبق (PREFLIGHT_* حدث دائم) —
    لا «البوابة ليست مفتوحة» أبدًا: OPEN أو APPROVED_BUT_BLOCKED
    مع السبب والمطلوب وإجراء المالك نصًا.
    """
    plan_approved = None
    if plan is not None:
        plan_approved = bool(plan.get("approved_by_owner"))
    verdict = None
    blocked_reason = required_env = owner_action = ""
    # الأحدث أولًا: list_events تعيد تصاعديًا — نقرأ عكسيًا كي نأخذ
    # آخر فحص لا أوله (الحالة الحقيقية الآن)
    for event in reversed(service.list_events(
            _sessions(), project["id"], limit=50)):
        payload = event.get("payload") or {}
        if event["kind"] == "PREFLIGHT_PASS":
            verdict = "PASS"
            break
        if event["kind"] in ("PREFLIGHT_BLOCKED", "PREFLIGHT_RECHECKED"):
            # RECHECKED يحمل الحكم نفسه بعد إعادة الفحص (011 §19)
            event_verdict = payload.get("verdict")
            if event["kind"] == "PREFLIGHT_RECHECKED" \
                    and event_verdict != "BLOCKED":
                continue
            verdict = event_verdict or "BLOCKED"
            if verdict != "BLOCKED":
                break
            blocked_caps = payload.get("blocked") or []
            reasons = [
                f"{b.get('capability_id')}: {b.get('reason', '')[:120]}"
                for b in blocked_caps if b.get("capability_id") != "llm"
            ] or ["لا توجد بيئة تنفيذ متوافقة وجاهزة."]
            blocked_reason = "؛ ".join(reasons)
            required_env = next(
                (b.get("required_environment") for b in blocked_caps
                 if b.get("required_environment")), "",
            )
            owner_action = next(
                (b.get("owner_action") for b in blocked_caps
                 if b.get("owner_action")), "",
            )
            break
    if project["status"] == "RUNNING":
        verdict = "PASS"   # التنفيذ الجاري برهان على الفتح
    return gate_machine.plan_execution_state(
        plan_approved=plan_approved, preflight_verdict=verdict,
        blocked_reason=blocked_reason,
        required_environment=required_env, owner_action=owner_action,
    )


@router.post("", status_code=201)
def create_project(body: ProjectCreateIn) -> dict:
    """إنشاء مشروع DRAFT — هدف دائم بحالة صادقة (§3)."""
    try:
        return _build_engine().create_project(
            body.name, body.objective,
            execution_policy=body.execution_policy,
        )
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
        decision_gates = [g for g in gates if g["status"] == "PENDING"]
        recovery.append({
            "project_id": project["id"],
            "status": project["status"],
            "checkpoint": checkpoint["id"] if checkpoint else None,
            "open_gates": [g["kind"] for g in gates],
            # (011 §19) بوابات التوفير لا تمنع الاستئناف — إعادة الفحص
            # تكفي؛ القرار وحده (PENDING) يمنع
            "resumable": project["status"] in ("PAUSED", "BLOCKED")
            and not decision_gates,
        })
    return {"projects": projects, "recovery": recovery,
            "active_run": _active_run_id()}


def _active_run_id() -> int | None:
    """المشروع النشط الآن — من مُطلق سير العمل (013: مصدر واحد)."""
    active = workflow_runner.active_run(_sessions())
    return active["project_id"] if active else None


def _environment_eligibility(environment: dict, policy: str) -> dict:
    """(013.7 §P1/P2) نموذج الحالة الصريح — استبدال الثلاثي القديم.

    الحالات المتسلسلة:
        NOT_CONFIGURED → DETECTED/REGISTERED → ONLINE → HEALTHY → ELIGIBLE → READY
        أو يتوقف عند: NOT_READY / UNAVAILABLE / NOT_CONFIGURED

    هذا يحل محل الثلاثي القديم (discovered/healthy/eligible) بنموذج صريح
    متسلسل يعكس دورة حياة البيئة الحقيقية.
    """
    from execution import service as execution_service
    from execution import policy as execution_policy

    env_state = execution_service.compute_environment_state(environment, policy)
    status = env_state["state"]
    eligible = env_state["eligible"]
    ineligible_reason = env_state.get("ineligible_reason", "")
    health_state = env_state.get("health_state", status)

    # وسم عرض صريح — يُمنع على الواجهة أن تقول «جاهزة» حين state != READY
    if status == "READY":
        label = "صالحة لهذه المهمة"
    elif status == "ELIGIBLE":
        label = "سليمة — غير صالحة لهذه المهمة"
    elif status in ("HEALTHY", "ONLINE"):
        label = "مكتشفة وسليمة — قيد التأهيل"
    elif status == "NOT_CONFIGURED":
        label = "غير مهيأة — تسجيل عامل بعيد مطلوب"
    elif status == "DETECTED":
        label = "مكتشفة — لم تُتحقق بعد"
    elif status == "NOT_READY":
        label = "مكتشفة — لم تجتز الفحص"
    elif status == "UNAVAILABLE":
        label = "غير متاحة على هذا المضيف"
    else:
        label = "حالة غير معروفة"

    return {
        "state": status,
        "health_state": health_state,
        "eligible": eligible,
        "ineligible_reason": ineligible_reason,
        "eligibility_label": label,
        "discovered": status not in ("NOT_CONFIGURED", "UNAVAILABLE"),
        "healthy": health_state in ("HEALTHY", "ELIGIBLE", "READY"),
    }


#: (013.6 §4) ذاكرة مؤقتة لخيارات الركائز — الفحص يستدعي wsl.exe فعليًا
#: (وقد يستغرق ثواني)، ونقطة حالة المشروع تُقرأ بالاستطلاع؛ بلا ذاكرة
#: هنا يدفع كل استطلاع كلفة إقلاع عملية. الصلاحية قصيرة (30ث) لأن
#: القدرة تتغيّر بفعل المالك (يثبّت Docker/يفعّل WSL2) فيجب ألا تعلق.
_SUBSTRATE_CACHE: dict = {"at": 0.0, "options": []}
_SUBSTRATE_TTL_SECONDS = 30.0


def _substrate_options() -> list[dict]:
    """(013.6 §4) مسارات التوفير الحقيقية المتاحة على هذا المضيف.

    القاعدة: لا يُعرض خيار إلا إذا كانت قدرته موجودة فعلًا. عرض زر
    «شغّل WSL2» على جهاز بلا WSL2 هو وعد كاذب — وهو ما يرفضه الأمر.
    """
    import time as _time

    now = _time.monotonic()
    if _SUBSTRATE_CACHE["options"] and (
        now - _SUBSTRATE_CACHE["at"] < _SUBSTRATE_TTL_SECONDS
    ):
        return _SUBSTRATE_CACHE["options"]
    options: list[dict] = []
    try:
        from execution import wsl as wsl_mod

        detection = wsl_mod.wsl_available()
        # (013.7 §P3) حالة صريحة بدلاً من boolean available
        if detection.get("available"):
            state = "READY"
        elif detection.get("reason") == "WSL2_NO_DISTRO":
            state = "DETECTED_BUT_NO_DISTRO"
        elif detection.get("reason") == "WSL2_NO_PYTHON3":
            state = "DETECTED_NO_PYTHON3"
        else:
            state = "NOT_CONFIGURED"
        options.append({
            "id": "wsl2",
            "label": "تشغيل WSL2",
            "state": state,
            "reason": ("WSL2 يعمل ويشغّل python3" if state == "READY"
                       else "wsl.exe موجود لكن لا توزيعة Linux تعمل" if state == "DETECTED_BUT_NO_DISTRO"
                       else "التوزيعة تعمل لكن python3 غير متاح" if state == "DETECTED_NO_PYTHON3"
                       else "WSL2 غير مثبّت على هذا المضيف"),
            "detail": str(detection.get("detail", ""))[:600],
            "action": "" if state == "READY" else "wsl --install ثم إعادة الفحص",
        })
    except Exception as error:  # noqa: BLE001 — الفحص لا يكسر الاستجابة
        options.append({
            "id": "wsl2", "label": "تشغيل WSL2", "state": "NOT_CONFIGURED",
            "reason": f"تعذّر فحص WSL2: {str(error)[:120]}", "detail": "",
            "action": "",
        })
    try:
        from execution.backends import runtime_truth

        container = (runtime_truth().get("container_runtime") or "").strip()
        state = "READY" if container else "NOT_CONFIGURED"
        options.append({
            "id": "docker",
            "label": "استخدام Docker",
            "state": state,
            "reason": (
                f"ركيزة الحاويات: {container}" if container
                else "لا Docker ولا Podman على هذا المضيف"
            ),
            "detail": f"container_runtime={container or '—'}",
            "action": "" if container else "ثبّت Docker Desktop ثم أعد الفحص",
        })
    except Exception as error:  # noqa: BLE001
        options.append({
            "id": "docker", "label": "استخدام Docker", "state": "NOT_CONFIGURED",
            "reason": f"تعذّر فحص الحاويات: {str(error)[:120]}", "detail": "",
            "action": "",
        })
    # (013.7 §P1) عامل بعيد — حالات صريحة
    options.append({
        "id": "remote_worker",
        "label": "تسجيل عامل Linux",
        "state": "NOT_CONFIGURED",
        "reason": "لا عامل مسجل — يلزم مضيف Linux/WSL2 يشغّل python scripts/execution_worker.py",
        "detail": "نقطة النهاية + توكن العامل يُدخلان من الإعدادات",
        "action": "شغّل العامل على Linux ثم سجّل رابطه وتوكنه",
    })
    _SUBSTRATE_CACHE["at"] = now
    _SUBSTRATE_CACHE["options"] = options
    return options


def _environment_block(project: dict, *, job: dict | None = None) -> dict:
    """كتلة بيئة التنفيذ (013.1 §10+§18 + 013.2 §1-§3) — من الحالة
    القانونية الواحدة حصرًا.

    (013.2 §1) لا اشتقاق هنا إطلاقًا: كل حقول العرض (state/coherent/
    required/actual/missing/evidence) تُقرأ من runtime_state.canonical_state
    — نفس القراءة التي يقرأها سكربت القبول ونقطة runtime-state — فاستحال
    «الواجهة تقول غير جاهزة والتقرير يقول READY»: الجميع يقرأ مصدرًا
    واحدًا. المطلوب (REQUIRED) والفعلي (ACTUAL) مفصولان حرفيًا (§2).
    """
    from execution import policy as execution_policy
    from execution import runtime_state as runtime_state_mod
    from execution import service as execution_service
    from execution.backends import runtime_truth

    policy = project.get("execution_policy") or "STRICT_ISOLATED"
    canonical = runtime_state_mod.canonical_state(
        _sessions(), policy, job=job
    )
    truth = runtime_truth()
    host = {
        "platform": f"{truth.get('os', '')} {truth.get('architecture', '')}".strip(),
        "os": truth.get("os", ""),
        "arch": truth.get("architecture", ""),
        "container_runtime": truth.get("container_runtime", ""),
        "cores": truth.get("cpu_cores", 0),
        "memory": truth.get("memory", ""),
    }
    selected = execution_service.select_environment(_sessions(), policy=policy)
    block: dict = {
        "policy": policy,
        "policy_label": execution_policy.POLICY_LABELS.get(policy, policy),
        "host": host,
        "selected": canonical.get("selected"),
        "satisfies_policy": selected is not None,
        "requirement": execution_policy.requirement_text(policy),
        "environments": [
            {
                **{k: e.get(k) for k in ("id", "name", "backend", "status",
                                         "isolation", "sandboxed",
                                         "is_default")},
                # (013.6 §1) ثلاث حالات منفصلة لكل بيئة — الواجهة ممنوعة
                # من اشتقاق «جاهزة» بنفسها من status.
                **_environment_eligibility(e, policy),
            }
            for e in execution_service.list_environments(_sessions())
        ],
        # (013.6 §4) مسارات التوفير الحقيقية — الواجهة تعرض المتاح فقط
        "substrate_options": _substrate_options(),
        # (013.2 §1+§3) الحالة القانونية — الواجهة تعرض هذه حصرًا
        "runtime_state": {
            "state": canonical["state"],
            "coherent": canonical["coherent"],
            "required": canonical["required"],
            "actual": canonical["actual"],
            "selected": canonical.get("selected"),
            "missing": canonical["missing"],
            "evidence": canonical["evidence"],
            "environment_id": canonical["environment_id"],
            "worker_id": canonical["worker_id"],
            "progress": canonical["progress"],
            "provisioning_record": canonical.get("provisioning_record"),
        },
    }
    if selected is None:
        block["owner_action"] = execution_service\
            .owner_action_for_missing_environment(_sessions(), policy)
    try:
        from execution import provisioner

        block["heartbeat"] = provisioner.last_heartbeat()
    except Exception:  # noqa: BLE001 — النبضة قراءة اختيارية
        block["heartbeat"] = {}
    return block


@router.get("/events/stream")
async def projects_events_stream(request: Request,
                                 after_id: int = 0) -> StreamingResponse:
    """تيار أحداث عام (011 §21 + 013 §5) — حي فوريًا لا استطلاعًا فقط.

    (013 §5) عقد البث الكامل:
    - **id: <event_id>** لكل حدث — المتصفح يرسل Last-Event-ID تلقائيًا
      عند إعادة الاتصال فتُستكمل الفائتة من الدائمة بلا تكرار.
    - **بث فوري** عبر الناقل (الاشتراك قبل القراءة — لا فجوة سباق)
      + **استطلاع الدائمة** (1.0ث) شبكة أمان لكل ما لا يمر بالناقل.
    - **keepalive** كل ~15ث — صحة الاتصال وقطع الوسائط الصامت.
    - الترتيب بمعرف رتيب؛ المكرر يُسقط بالمقارنة مع آخر مرسل.
    """
    from core.live_bus import BUS

    header_after = request.headers.get("last-event-id", "")
    try:
        start_after = int(header_after) if header_after else int(after_id)
    except ValueError:
        start_after = int(after_id)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sub_id = BUS.subscribe("projects", loop, queue)
    state = {"last_id": start_after}

    def _sse(event: dict) -> str:
        event_id = int(event.get("id") or event.get("event_id") or 0)
        if event_id:
            state["last_id"] = max(state["last_id"], event_id)
            return ("id: " + str(event_id) + "\n"
                    + "data: " + json.dumps(event, ensure_ascii=False)
                    + "\n\n")
        return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    async def generate():
        try:
            yield "data: " + json.dumps(
                {"kind": "stream.start", "last_id": state["last_id"]},
                ensure_ascii=False,
            ) + "\n\n"
            idle_ticks = 0
            while True:
                # 1) الحي من الناقل أولًا — لحظة النشر
                pushed = False
                while not queue.empty():
                    try:
                        event = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    pushed = True
                    if not isinstance(event, dict):
                        continue
                    if str(event.get("stream") or "") not in ("projects", ""):
                        continue
                    event_db_id = int(event.get("event_id") or 0)
                    if event_db_id and event_db_id <= state["last_id"]:
                        continue
                    yield _sse({
                        "id": event_db_id or None,
                        "project_id": event.get("project_id"),
                        "kind": event.get("kind", ""),
                        "payload": (event.get("details") or {}).get(
                            "payload") if isinstance(
                                event.get("details"), dict
                            ) else event.get("payload", {}),
                        "created_at": event.get("timestamp", ""),
                    })
                # 2) الدائمة بعد آخر مرسل — شبكة الأمان الكاملة
                events = service.list_recent_events(
                    _sessions(), state["last_id"], limit=100
                )
                for event in events:
                    pushed = True
                    yield _sse(event)
                if pushed:
                    idle_ticks = 0
                    continue
                idle_ticks += 1
                if idle_ticks % 15 == 14:  # كل ~15ث — صحة الاتصال
                    yield ": keepalive\n\n"
                await asyncio.sleep(1.0)
        finally:
            BUS.unsubscribe(sub_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/active")
def active_runs() -> dict:
    """التشغيلات النشطة (013.4 §9+§32) — مؤشرات الشريط الجانبي.

    كل مشروع غير نهائي مع لقطة تحكم مصغرة: الحالة/المرحلة/الوظيفة/
    الانتظار — من اللقطة القانونية (§8) لا اشتقاقًا موازيًا.
    """
    from workflow.snapshot import runtime_snapshot

    projects = service.list_projects(_sessions())
    active_project_ids = [p["id"] for p in projects
                          if p["status"] not in
                          ("VERIFIED", "COMPLETED", "STOPPED", "ESCALATED")]
    runs: list[dict] = []
    for pid in active_project_ids:
        try:
            snap = runtime_snapshot(_sessions(), pid)
        except Exception:  # noqa: BLE001 — مشروع فاسد لا يكسر القائمة
            continue
        if snap["status"] in ("DRAFT", "AWAITING_OWNER_APPROVAL") \
                and snap["job"] is None \
                and not snap["planning"].get("active"):
            continue   # ليس تشغيلًا — مسودة تنتظر قرارًا
        runs.append({
            "project_id": pid,
            "name": snap["name"],
            "status": snap["status"],
            "stage": snap["stage"],
            "waiting_for": snap["waiting_for"],
            "job": snap["job"],
            "planning_active": bool(snap["planning"].get("active")),
            "heartbeat_at": snap["heartbeat_at"],
            "elapsed_s": snap["elapsed_s"],
            "progress": snap["progress"],
        })
    return {"runs": runs, "active_run": _active_run_id()}


@router.get("/archived/list")
def archived_list() -> dict:
    """المشاريع المؤرشفة (013.4 §45) — قائمة الاسترجاع."""
    return {"projects": service.archived_projects(_sessions())}


@router.get("/{project_id}")
def project_detail(project_id: int) -> dict:
    """التفصيل الكامل — الخطة والمراحل والخطوات والبوابات والأحداث."""
    project = _project_or_404(project_id)
    plan = service.latest_plan(_sessions(), project_id)
    phases = service.list_phases(_sessions(), project_id)
    gates = service.list_gates(_sessions(), project_id)
    events = service.list_events(_sessions(), project_id, limit=30)
    executions = service.list_executions(_sessions(), project_id, limit=20)
    # (012-E) الوظيفة الدائمة للمشروع — أحدث صف مهما كانت حالته
    try:
        job = _harness_manager().job_for_project(project_id)
    except Exception:  # noqa: BLE001
        job = None
    return {
        **project,
        "plan": plan,
        "phases": phases,
        "gates": gates,
        "events": events,
        "executions": executions,
        "execution_gate": _execution_gate(project, plan),
        "active_run": _active_run_id() == project_id,
        "job": job,
    }


@router.get("/{project_id}/state")
def project_state_snapshot(project_id: int) -> dict:
    """لقطة مصالحة كاملة (013 §6) — إعادة بناء الواجهة من هنا ثم
    متابعة التيار.

    initial snapshot + event stream: كل ما تحتاجه الواجهة لبناء
    نفسها (مشروع/خطة/بوابات/مراحل/وظيفة/خط زمن/سلسلة قبول/معايير)
    في نداء واحد — مع last_event_id للاشتراك بعده مباشرة.
    """
    project = _project_or_404(project_id)
    plan = service.latest_plan(_sessions(), project_id)
    phases = service.list_phases(_sessions(), project_id)
    gates = service.list_gates(_sessions(), project_id)
    events = service.list_events(_sessions(), project_id, limit=200)
    executions = service.list_executions(_sessions(), project_id, limit=20)
    evidence = service.list_evidence(_sessions(), project_id)
    audits = service.list_audits(_sessions(), project_id)
    try:
        job = _harness_manager().job_for_project(project_id)
    except Exception:  # noqa: BLE001
        job = None
    timeline = {}
    chain = {}
    try:
        from harness import projections

        timeline = projections.project_timeline(events)
        chain = projections.acceptance_chain(events)
    except Exception:  # noqa: BLE001 — الإسقاط قراءة لا يمنع اللقطة
        pass
    criteria: list[dict] = []
    try:
        from workflow import acceptance

        criteria = acceptance.criteria_view(_sessions(), project_id)
    except Exception:  # noqa: BLE001 — المعايير قراءة اختيارية
        pass
    active = workflow_runner.active_run(_sessions())
    return {
        **project,
        "plan": plan,
        "phases": phases,
        "gates": gates,
        "events": events[-60:],
        "executions": executions,
        "evidence": evidence,
        "audits": audits,
        "execution_gate": _execution_gate(project, plan),
        "job": job,
        "environment": _environment_block(project, job=job),
        "timeline": timeline,
        "chain": chain,
        "acceptance_criteria": criteria,
        "active_run": (
            {"project_id": active["project_id"], "job_id": active["job_id"]}
            if active else None
        ),
        "last_event_id": events[-1]["id"] if events else 0,
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
    """أمر توليد الخطة (013.4 §1-§3) — خلفي محدود لا طلبًا حاجزًا.

    يعيد فورًا {started, session}: المزود/النموذج/request_id/الإيجار.
    كل التطور يصل عبر تيار الأحداث (PLANNING_STARTED ←
    PLAN_GENERATING ← MODEL_CALL_* ← PLAN_CREATED|PLANNING_FAILED)
    — لا «Planning…» صامتة أبدًا، والفشل مصنّف حرفيًا.
    """
    project = _project_or_404(project_id)
    try:
        result = _build_engine(
            on_event=_live_broadcast_on_event
        ).start_plan_generation(
            project_id, reason="أمر صريح من الواجهة"
        )
        return {**result, "project": service.get_project(
            _sessions(), project["id"]
        )}
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


def _launch_after_decision(project_id: int, reason: str) -> dict:
    """إطلاق الحلقة بعد قرار مالك (013 §3) — أمر لا صف قاعدة.

    فشل الإطلاق لا يفشل القرار (القرار دائم وقائم)؛ يعيد وصفًا
    صادقًا {launched, reason, job_id?} يصل الواجهة فورًا، وكل ما
    يحدث لاحقًا يصل عبر تيار الأحداث الحي.

    (013) المصنع يُلتقط وقتَ الطلب لا داخل الخيط الخلفي — بيئة
    الاختبار قد تُستبدل قبل أن يبني الخيط محركه؛ الإنتاج لا يتغير.
    """

    def engine_factory(on_event=None):
        factory = _test_engine_factory  # مقرودة قبل الإغلاق أدناه
        if factory is not None:
            return factory(on_event=on_event)

        def router_factory():
            from api.routes import _build_live_router

            return _build_live_router()

        return ProjectEngine(
            _sessions(),
            router_factory=router_factory,
            on_event=on_event,
            role_mappings_provider=lambda: registry.get_mappings(
                _sessions()
            ),
        )

    try:
        return workflow_runner.launch(
            project_id, engine_factory=engine_factory,
            sessions=_sessions(), reason=reason,
        )
    except workflow_runner.RunConflict as conflict:
        return {"launched": False, "reason": "conflict",
                "detail": str(conflict)}
    except Exception as error:  # noqa: BLE001 — إعلان لا انهيار
        return {"launched": False, "reason": "error",
                "detail": str(error)[:300]}


@router.post("/{project_id}/plan/approve")
def approve_plan(project_id: int, body: PlanDecisionIn) -> dict:
    """قرار المالك — اعتماد يفعّل الخطة **ويطلق الحلقة فورًا** (013 §3).

    الرفض يعيد التوليد بتغذية راجعة (خطة v جديدة تنتظر اعتمادًا).
    الإطلاق خلفي: النتيجة فورية والسلسلة كاملة (PREFLIGHT ← JOB ←
    EXECUTION ← EVIDENCE) تصل عبر تيار الأحداث بلا refresh.
    """
    _project_or_404(project_id)
    try:
        result = _build_engine().approve_plan(
            project_id, approved=body.approved, feedback=body.feedback
        )
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error
    launch: dict = {"launched": False, "reason": "not_requested"}
    if body.approved:
        launch = _launch_after_decision(
            project_id, "اعتماد الخطة — أمر المالك"
        )
    return {**result, "launch": launch}


@router.post("/{project_id}/run/stream")
async def run_project(project_id: int,
                      request: Request) -> StreamingResponse:
    """تشغيل الحلقة الذاتية أو الإرفاق بتشغيل جارٍ — بث SSE (013 §42).

    الإطلاق عبر workflow/runner (single-flight عملية-wide): مشروع
    آخر يعمل = 409؛ نفس المشروع يعمل = إرفاق بالبث القائم (reconnect
    بلا فقد). كل tick يحمل حالته من القاعدة ويكتب إليها — انقطاع
    البث أو crash لا يفقد شيئًا: الاستئناف من آخر checkpoint.

    ?after=<event_id>: استهلاك الأحداث الدائمة بعد معرف — إعادة
    الإرفاق تُكمل من حيث توقفت لا من الصفر (replay صادق).
    """
    _project_or_404(project_id)
    # (013 §42) غياب ?after = من البداية (تاريخ المشروع كاملًا)؛
    # وجوده = استكمال بعد معرف — إعادة الإرفاق بلا فقد ولا تكرار.
    raw_after = request.query_params.get("after", None)
    try:
        after = int(raw_after) if raw_after is not None else -1
    except ValueError:
        after = -1

    db_key = workflow_runner.sessions_db_key(_sessions())
    active = workflow_runner.active_run(_sessions())
    if active is not None and active["project_id"] != project_id:
        raise HTTPException(
            status_code=409,
            detail=f"مشروع آخر يعمل حاليًا (#{active['project_id']}) — "
            "الحلقة الذاتية واحدة في كل لحظة",
        )
    launch = _launch_after_decision(project_id, "تشغيل صريح من الواجهة")

    from core.live_bus import BUS

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sub_id = BUS.subscribe("projects", loop, queue)

    async def generate():
        # (013.7 §P17) الحصول على conversation_id للمشروع
        conversation_id = None
        project = _project_or_404(project_id)
        if project.get("conversation_id"):
            conversation_id = project["conversation_id"]

        try:
            yield "data: " + json.dumps({
                "project_id": project_id, "kind": "run.start",
                "payload": {"status": "RUNNING", "launch": launch},
            }, ensure_ascii=False) + "\n\n"
            last_event_id = max(after, 0) if after > 0 else 0
            # البث من البداية أو الاستكمال بعد معرف — أحداث الدائمة
            # الفائتة أولًا (بلا تكرار)، ثم الحي عبر الناقل
            if after != 0:
                for event in service.list_events(
                        _sessions(), project_id, limit=500):
                    if (event.get("id") or 0) > last_event_id:
                        last_event_id = event["id"]
                        # (013.7 §P17) إضافة conversation_id إلى أحداث المشروع
                        event = {**event, "conversation_id": conversation_id}
                        yield "id: " + str(event["id"]) + "\n" \
                              + "data: " + json.dumps(
                                    {**event, "payload": event.get(
                                        "payload", {})},
                                    ensure_ascii=False,
                                ) + "\n\n"
            idle_ticks = 0
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=0.5
                    )
                    idle_ticks = 0
                except asyncio.TimeoutError:
                    idle_ticks += 1
                    active = workflow_runner.active_run(_sessions())
                    if active is None or active["project_id"] != project_id:
                        yield "data: " + json.dumps({
                            "project_id": project_id, "kind": "run.done",
                            "payload": {"job_id": launch.get("job_id")},
                            "conversation_id": conversation_id,
                        }, ensure_ascii=False) + "\n\n"
                        return
                    if idle_ticks % 30 == 29:  # كل ~15ث — صحة الاتصال
                        yield ": keepalive\n\n"
                    continue
                if event.get("project_id") != project_id:
                    continue
                event_db_key = str(event.get("db") or "")
                if event_db_key and event_db_key != db_key:
                    continue  # بث بيئة أخرى — لا تسريب
                event_db_id = int(event.get("event_id") or 0)
                if event_db_id and event_db_id <= last_event_id:
                    continue  # مكرر (سباق الأرشيف/الحي)
                if event_db_id:
                    last_event_id = event_db_id
                kind = event.get("kind", "")
                details = event.get("details") or {}
                payload = (details.get("payload")
                           if isinstance(details, dict) else None) \
                    or event.get("payload") or {}
                yield "data: " + json.dumps({
                        "project_id": project_id, "kind": kind,
                        "payload": payload,
                        "event_id": event_db_id,
                        "conversation_id": conversation_id,
                    }, ensure_ascii=False) + "\n\n"
                if kind == "run.error":
                    yield "data: " + json.dumps({
                        "project_id": project_id, "kind": "run.done",
                        "payload": {"error": True},
                        "conversation_id": conversation_id,
                    }, ensure_ascii=False) + "\n\n"
                    return
        finally:
            # انقطاع العميل لا يوقف المحرك — يكمل ويكتب كل شيء في
            # القاعدة؛ والاشتراك يُلغى هنا حصرًا (صاحبه هذا المولد)
            BUS.unsubscribe(sub_id)
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{project_id}/stop")
def stop_project(project_id: int, body: ProjectStopIn) -> dict:
    """إيقاف المشروع (013.4 §12) — نهائي دائم أو مؤقت بلقطة.

    final=true: OWNER_STOP_REQUESTED ← checkpoint ← STOPPED دائمة
    مع حفظ كل شيء (لا حذف أبدًا) + إغلاق الوظيفة صادقة.
    """
    _project_or_404(project_id)
    try:
        result = _build_engine().request_stop(
            project_id, body.reason, final=body.final
        )
        if body.final:
            try:
                _harness_manager().mark_stopped(project_id)
            except Exception:  # noqa: BLE001 — دفتر الوظيفة لا يمنع الإيقاف
                pass
        return result
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


# ------------------------------------------------------------------ #
# (013.4 §8-§17) مركز التحكم — اللقطة القانونية + الأزرار الحقيقية
# ------------------------------------------------------------------ #

@router.get("/{project_id}/runtime")
def project_runtime(project_id: int) -> dict:
    """اللقطة القانونية لزمن التشغيل (013.4 §8) — الواجهة تقرأ هذه
    حصرًا: لا مكوّن يشتق حالة سير العمل من مصدر آخر."""
    _project_or_404(project_id)
    from workflow.snapshot import runtime_snapshot

    try:
        return runtime_snapshot(_sessions(), project_id)
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.get("/{project_id}/history")
def project_history(project_id: int, before_id: int = 0,
                    limit: int = 100) -> dict:
    """تاريخ المشروع (013.4 §16+§43) — صفحات بمؤشر رجوع.

    خط زمن من الأحداث الدائمة: انتقالات/قرارات/إعادات/فشل/أدلة —
    لا تُغرق الواجهة: صفحة واحدة في كل مرة، والأقدم عند الطلب.
    """
    _project_or_404(project_id)
    page = service.events_page(
        _sessions(), project_id, before_id=before_id, limit=limit
    )
    timeline = {}
    try:
        from harness import projections

        timeline = projections.project_timeline(page["events"])
    except Exception:  # noqa: BLE001 — الإسقاط قراءة لا يمنع الصفحة
        pass
    return {**page, "timeline": timeline}


@router.get("/{project_id}/artifacts")
def project_artifacts(project_id: int) -> dict:
    """مخرجات المشروع (013.4 §47) — ملفات/تقارير/أدلة من كل خطوة.

    من الأدلة الدائمة حصرًا (evidence.files/artifacts) — لا مسح
    قرص عام: ما لم يُثبت لا يُعرض.
    """
    _project_or_404(project_id)
    artifacts: list[dict] = []
    for evidence in service.list_evidence(_sessions(), project_id):
        files = evidence.get("files") or {}
        for name, meta in files.items():
            artifacts.append({
                "name": name,
                "kind": "file",
                "sha256": (meta or {}).get("sha256", ""),
                "bytes": (meta or {}).get("bytes", 0),
                "step_id": evidence.get("step_id"),
                "evidence_id": evidence.get("id"),
                "verdict": evidence.get("verdict", ""),
                "created_at": evidence.get("created_at"),
            })
        for item in evidence.get("artifacts") or []:
            artifacts.append({
                "name": str(item),
                "kind": "artifact",
                "step_id": evidence.get("step_id"),
                "evidence_id": evidence.get("id"),
                "verdict": evidence.get("verdict", ""),
                "created_at": evidence.get("created_at"),
            })
    artifacts.sort(key=lambda a: str(a.get("created_at") or ""),
                   reverse=True)
    return {"artifacts": artifacts}


class PauseIn(BaseModel):
    """إيقاف مؤقت — سبب اختياري مسجل."""

    reason: str = Field(default="", max_length=500)


@router.post("/{project_id}/pause")
def pause_project(project_id: int, body: PauseIn) -> dict:
    """إيقاف مؤقت (013.4 §13) — RUNNING → PAUSING → PAUSED بلقطة."""
    _project_or_404(project_id)
    try:
        result = _build_engine(on_event=_live_broadcast_on_event).pause(
            project_id, body.reason
        )
        return result
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.post("/{project_id}/retry")
def retry_project(project_id: int) -> dict:
    """إعادة المحاولة (013.4 §11) — آخر فشل يحدد الإجراء الصادق."""
    _project_or_404(project_id)
    try:
        result = _build_engine(
            on_event=_live_broadcast_on_event
        ).retry(project_id)
        # إعادة الخطوات/التشغيل تطلق الحلقة فورًا — أمر لا صف قاعدة
        if result.get("retried") in ("steps", "run"):
            launch = _launch_after_decision(
                project_id, "إعادة محاولة من المالك"
            )
            return {**result, "launch": launch}
        return result
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


class DuplicateIn(BaseModel):
    """تكرار مشروع — اسم اختياري للنسخة."""

    name: str = Field(default="", max_length=200)


@router.post("/{project_id}/duplicate", status_code=201)
def duplicate_project(project_id: int, body: DuplicateIn) -> dict:
    """تكرار (013.4 §15) — نسخة جديدة لا تمس الأصل أبدًا."""
    _project_or_404(project_id)
    try:
        return _build_engine().duplicate_project(
            project_id, name=body.name
        )
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.post("/{project_id}/archive")
def archive_project(project_id: int) -> dict:
    """أرشفة (013.4 §17) — دورة حياة، لا حذف بيانات أبدًا."""
    _project_or_404(project_id)
    try:
        return _build_engine().archive_project(project_id)
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.post("/{project_id}/restore")
def restore_project(project_id: int) -> dict:
    """استرجاع من الأرشيف (013.4 §45)."""
    _project_or_404(project_id)
    try:
        return _build_engine().restore_project(project_id)
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


class RenameIn(BaseModel):
    """إعادة تسمية — الاسم الجديد."""

    name: str = Field(min_length=1, max_length=200)


@router.post("/{project_id}/rename")
def rename_project(project_id: int, body: RenameIn) -> dict:
    """إعادة تسمية المشروع (013.4 §11)."""
    _project_or_404(project_id)
    try:
        return _build_engine().rename_project(project_id, body.name)
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.post("/{project_id}/resume")
def resume_project(project_id: int) -> dict:
    """استئناف صريح ← **إطلاق الحلقة فورًا** (013 §34+§38).

    يعمل بعد restart من checkpoint الدائم (§9+§19)؛ الوظيفة غير
    النهائية تعود للطابور في صفها نفسه، والبث يحمل ما يحدث بعدها.
    """
    _project_or_404(project_id)
    try:
        result = _build_engine().resume(project_id)
        # (012-E) الوظيفة غير النهائية تعود للطابور — استمرارية الصف
        try:
            _harness_manager().mark_resumed(project_id)
        except Exception:  # noqa: BLE001 — دفتر الوظيفة لا يمنع الاستئناف
            pass
        launch = _launch_after_decision(project_id, "استئناف صريح من المالك")
        return {**result, "launch": launch}
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.post("/{project_id}/preflight")
def recheck_preflight(project_id: int) -> dict:
    """إعادة الفحص بعد التوفير (011 §19) — النجاح يفتح **ويطلق تلقائيًا**
    (013 §38: بلا إعادة اعتماد وبلا زر تشغيل إضافي)."""
    _project_or_404(project_id)
    try:
        result = _build_engine().recheck_preflight(project_id)
        project = service.get_project(_sessions(), project_id)
        launch: dict = {"launched": False, "reason": "not_requested"}
        if result["verdict"] == "PASS":
            launch = _launch_after_decision(
                project_id, "إعادة فحص ناجحة بعد التوفير — استئناف آلي"
            )
        return {
            "project": project,
            "preflight": {
                "verdict": result["verdict"],
                "summary": result["summary"],
                "matrix": result.get("matrix", []),
                "blocked": result.get("blocked", []),
                "environment": result.get("environment"),
                "policy": result.get("policy"),
            },
            "execution_gate": _execution_gate(
                project, service.latest_plan(_sessions(), project_id)
            ),
            "launch": launch,
        }
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.post("/{project_id}/execution-policy")
def set_execution_policy(project_id: int, body: ExecutionPolicyIn) -> dict:
    """سياسة التنفيذ (011 §26) — STRICT_ISOLATED أو COMPATIBLE_LOCAL."""
    _project_or_404(project_id)
    try:
        return _build_engine().set_execution_policy(project_id, body.policy)
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.post("/{project_id}/gates/{gate_id}")
def resolve_gate(project_id: int, gate_id: int, body: GateDecisionIn) -> dict:
    """حل بوابة مالك — لكل نوع أثره (§14)؛ الفتح يطلق الحلقة (013 §3)."""
    _project_or_404(project_id)
    try:
        outcome = _build_engine().resolve_gate(
            project_id, gate_id, approved=body.approved
        )
        # (012-E) رفض البوابة يوقف المشروع — الوظيفة تغلق صادقة لا
        # تبقى منتظرة لبوابة ماتت
        launch: dict = {"launched": False, "reason": "not_requested"}
        if not body.approved:
            try:
                _harness_manager().mark_stopped(project_id)
            except Exception:  # noqa: BLE001
                pass
        elif outcome.get("kind") in (
            "PROVIDER_ACTION_REQUIRED", "ESCALATION",
        ):
            # قرار المالك عالج العائق — الحلقة تستأنف فورًا (013 §3)
            launch = _launch_after_decision(
                project_id, "حل بوابة مالك — استئناف آلي"
            )
        return {**outcome, "launch": launch}
    except Exception as error:  # noqa: BLE001
        raise _http(error) from error


@router.post("/{project_id}/verify")
def verify_project(project_id: int) -> dict:
    """التحقق النهائي — VERIFIED قرار المالك وحده (§16)."""
    _project_or_404(project_id)
    try:
        result = _build_engine().verify(project_id)
        # (012-E) اكتمال الوظيفة الحقيقي الوحيد: تحقق المالك
        try:
            _harness_manager().mark_verified(project_id)
        except Exception:  # noqa: BLE001 — دفتر الوظيفة لا يمنع التحقق
            pass
        return result
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
    """استرداد الإقلاع (§19 + 012-G) — اكتشاف وتقييم فقط، لا تنفيذ.

    تقييم المشاريع غير النهائية ثم الوظائف الدائمة: ما كان يدور
    عند وفاة العملية يُوسم INTERRUPTED (لا حياة كاذبة) ويعلن هل
    يستأنف — والاستئناف قرار صريح دائمًا.
    """
    assessments = ProjectEngine(sessions, router_factory=lambda: None) \
        .assess_recovery()
    try:
        from harness.jobs import JobManager
        from harness.seams import HarnessSeams

        manager = JobManager(HarnessSeams(sessions))
        assessments = assessments + manager.assess_jobs_recovery()
    except Exception:  # noqa: BLE001 — استرداد الوظائف لا يمنع الإقلاع
        pass
    return assessments
