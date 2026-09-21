"""نقاط النهاية النحيفة — FastAPI (الأمر الثالث: حزم الموجّه + عرضها).

- GET  /                    الواجهة (index.html)
- GET  /health              الحالة الصادقة (بما فيها توفر الركيزة)
- GET  /api/conversations   قائمة المحادثات (عنصر شاغل في هذه المرحلة)
- POST /api/cycle/stream    بث SSE لأحداث الدورة الكاملة لحظة حدوثها —
                            الدورة تعمل في خيط وكل حدث دور يُدفَع إلى
                            الطابور فور انبعاثه، ويُسجَّل في جدول events
- POST /api/cycle/verify    موافقة المستخدم — القناة الوحيدة إلى VERIFIED
- POST /api/router/demo     بث SSE لأحداث الموجّه (الأمر الثالث): الحزم
                            الثلاث الحقيقية بنقل mock وأزمنة مضغوطة
                            معلنة — إثبات عملها لا ادعاء استدعاءات حية
- POST /api/eoe/stream      بث SSE لتنفيذ أمر تنفيذي كامل (الأمر الرابع):
                            المنح والدفع ينتظران موافقة المالك الحية
- POST /api/eoe/approve     موافقة المالك على المنح أو الدفع — القناة
                            الوحيدة لاستمرار التنفيذ (لا موافقة لا فعل)

لا منطق أدوار هنا — الأدوار مجمعَّة في core.wiring والتنسيق كله في
core.orchestrator؛ هذه الطبقة نقل وتسجيل فقط.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.config import settings
from core.state import StateTransitionError
from core.wiring import build_mock_orchestrator
from persistence.database import build_engine, init_db, make_session_factory
from persistence.models import Event
from router.cooling_loop import CoolingLoop
from router.failover_chain import FailoverChain
from router.model_router import ChatMessage, ModelRouter, ProviderCallError
from router.rate_limiter import RateLimiter

logger = logging.getLogger("agent-hub-v2.api")

UI_DIR = Path(__file__).resolve().parents[1] / "ui"

app = FastAPI(title=settings.app_name, version=settings.app_version)


@app.middleware("http")
async def _no_cache_ui(request, call_next):
    """الأمر 005 (درس v1 الموثق): الصفحة والأصول لا تُخزَّن تخزينًا أعمى.

    no-cache يسمح بالتحقق الرخيص (ETag يبقى فعّالًا ← 304) لكنه يمنع
    المتصفح من استخدام نسخة app.js قديمة بعد git pull — السبب الجذري
    الموثق لـ«الواجهة لا تستجيب بعد التحديث» في v1، منقول الآن إلى v2
    مع الروابط المرقّمة في index.html (طبقتا دفاع مستقلتان).
    """
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


_engine = build_engine(settings.db_path)
init_db(_engine)
_sessions = make_session_factory(_engine)

# ثوابت الواجهة: styles.css + app.js + الخطوط المضمنة محليًا
app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

#: الدورة الافتراضية — أدوار mock فوق الركيزة الحقيقية (الأمر الثاني).
_orchestrator = build_mock_orchestrator()

#: منفّذ الدورات — دورة واحدة في كل لحظة (المنسق يقفل داخليًا أيضًا).
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="v2-cycle")

#: منفّذ EOE مخصص — انتظار موافقة المالك (حتى 600ث) لا يحتجز منفّذ
#: الدورة أبدًا، والعكس صحيح (الأمر الرابع).
_eoe_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="v2-eoe")


def _persist_event(event: dict) -> None:
    """كتابة الحدث في جدول events — سجل نشاط كل دور (الأمر الثاني).

    فشل التسجيل لا يقتل الدورة (الحدث محفوظ في ذاكرة النتيجة) لكنه
    يُعلن في السجل — لا ابتلاع صامت.
    """
    try:
        with _sessions() as session:
            session.add(
                Event(
                    cycle_id=event["cycle_id"],
                    seq=event["seq"],
                    role=event["role"],
                    kind=event["kind"],
                    state=event.get("state"),
                    payload=json.dumps(
                        event.get("details", {}), ensure_ascii=False
                    ),
                    duration_ms=event.get("duration_ms", 0),
                )
            )
            session.commit()
    except Exception:  # noqa: BLE001 — يُعلن لا يُبتلع
        logger.warning("تعذّر تسجيل الحدث %s في جدول events", event.get("kind"))


class CycleStartIn(BaseModel):
    """جسم بدء الدورة — الهدف."""

    goal: str = Field(min_length=1)


class CycleVerifyIn(BaseModel):
    """جسم موافقة المستخدم — معرّف الدورة."""

    cycle_id: str = Field(min_length=1)


class CycleStopIn(BaseModel):
    """جسم طلب الإيقاف الفوري (الأمر 004) — الدورة."""

    cycle_id: str = Field(min_length=1)
    reason: str = ""


class CycleResumeIn(BaseModel):
    """جسم استئناف دورة موقوفة (الأمر 004)."""

    cycle_id: str = Field(min_length=1)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    substrate_available = False
    try:
        from substrate.local_substrate import _SUPPORTED_ARCH

        substrate_available = bool(_SUPPORTED_ARCH)
    except Exception:  # noqa: BLE001 — إعلان صادق لا انهيار
        substrate_available = False
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "phase": "mock-cycle+router-packages+eoe",
        "substrate": {
            "available": substrate_available,
            "isolation": "linux-namespaces+seccomp",
            "note": (
                "معزولة على Linux/x86_64 (WSL2 على Windows) — "
                "وإلا وضع متوافق معلن بلا ادعاء عزل"
            ),
        },
    }


@app.get("/api/conversations")
def conversations() -> dict:
    """قائمة المحادثات — عنصر شاغر (السجل الحي في جدول events)."""
    return {"conversations": []}


@app.post("/api/cycle/stream")
async def cycle_stream(body: CycleStartIn) -> StreamingResponse:
    """بث الدورة الكاملة لحظة حدوثها — SSE حقيقي لا رسالة جاهزة.

    الدورة تعمل في خيط المنفّذ؛ كل حدث ينبعث يُدفَع إلى طابور الحدث
    (للبث) ويُسجَّل في قاعدة البيانات. نهاية الخيط إشارة ختام للبث.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    def sink(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)
        _persist_event(event)

    def run_cycle_in_thread() -> None:
        try:
            _orchestrator.run_cycle(body.goal, on_event=sink)
        except Exception as error:  # noqa: BLE001 — بث الخطأ لا موته صامتًا
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "seq": 0,
                    "cycle_id": "",
                    "role": "coordinator",
                    "kind": "cycle_error",
                    "state": None,
                    "text": f"الدورة فشلت قبل البدء: {error}",
                    "duration_ms": 0,
                    "details": {"error": str(error)},
                },
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)  # خاتمة البث

    running = loop.run_in_executor(_executor, run_cycle_in_thread)

    async def generate():
        while True:
            event = await queue.get()
            if event is None:  # خاتمة — الخيط انتهى
                break
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        await running  # رفع أي استثناء متبقٍ (الكل ملتقط أعلاه)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/cycle/verify")
def cycle_verify(body: CycleVerifyIn) -> dict:
    """موافقة المستخدم على نتيجة الدورة — القناة الوحيدة إلى VERIFIED.

    يرفض 404 لدورة غير معروفة و409 لانتقال غير مسموح (مثل طلب الموافقة
    قبل بلوغ EVIDENCED/ADJUDICATED) — جدول الانتقالات والقاعدة الذهبية
    يُفرضان في core/state.py لا هنا.
    """
    try:
        outcome = _orchestrator.user_verifies(body.cycle_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"دورة غير معروفة: {body.cycle_id}"
        )
    except StateTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error))
    # الحدث يُسجَّل مرة واحدة عبر نقطة استقبال الدورة نفسها (sink) —
    # لا يُعاد تسجيله هنا (كان يُكرر الصف قبل هذا التصحيح)
    return {
        "cycle_id": body.cycle_id,
        "state": outcome["state"],
        "badge": "✔ VERIFIED",
        "event": outcome["event"],
    }


# ------------------------------------------------------------------ #
# الأمر 004 — الإيقاف الفوري الآمن للدورة + الاستئناف من اللقطة
# ------------------------------------------------------------------ #

#: معرف الدورة الصالح حصرًا — fail-closed ضد اجتياز المسارات.
_CYCLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _cycle_snapshot_path(cycle_id: str) -> Path:
    return Path("runtime") / "cycles" / cycle_id / "stop_snapshot.json"


@app.post("/api/cycle/stop")
def cycle_stop(body: CycleStopIn) -> dict:
    """طلب إيقاف فوري للدورة — يُقبل فورًا ويُكرَّم عند حدّ آمن.

    القبول يعني: العلم رُفع ذرّيًا والحالة STOPPING؛ التوقف الفعلي
    عند أقرب نقطة تفتيش (أقصى الانتظار = استدعاء دور واحد).
    """
    outcome = _orchestrator.request_stop(
        body.cycle_id, by="owner", reason=body.reason
    )
    if outcome["status"] == "unknown":
        raise HTTPException(
            status_code=404, detail=f"دورة غير معروفة: {body.cycle_id}"
        )
    if not outcome["accepted"]:
        raise HTTPException(
            status_code=409,
            detail=(
                "الدورة ليست قيد التشغيل — حالتها النهائية: "
                f"{outcome.get('final_state', 'منتهية')}"
            ),
        )
    return {
        "cycle_id": body.cycle_id,
        "status": outcome["status"],
        "receipt": outcome["receipt"],
    }


@app.get("/api/cycle/status/{cycle_id}")
def cycle_status(cycle_id: str) -> dict:
    """حالة الدورة لحظة الطلب — الخطة والتشغيل وإيصال الإيقاف."""
    if not _CYCLE_ID_RE.match(cycle_id):
        raise HTTPException(status_code=422, detail="معرف دورة غير صالح")
    status = _orchestrator.cycle_status(cycle_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"دورة غير معروفة: {cycle_id}")
    status["can_resume"] = _cycle_snapshot_path(cycle_id).is_file()
    return status


@app.post("/api/cycle/resume")
async def cycle_resume(body: CycleResumeIn) -> StreamingResponse:
    """استئناف دورة موقوفة من لقطتها — دورة جديدة بث SSE (الأمر 004).

    الخطة الموقّعة تُحقن فتتخطى التفكير والمراجعة، والمهام المثبتة
    لا تُعاد؛ مساحة العمل نفسها تُعاد الاستخدام حتى تبقى الأدلة متصلة.
    """
    from core.stop_controller import load_resume_point

    if not _CYCLE_ID_RE.match(body.cycle_id):
        raise HTTPException(status_code=422, detail="معرف دورة غير صالح")
    path = _cycle_snapshot_path(body.cycle_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="لا لقطة إيقاف لهذه الدورة")
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        load_resume_point(snapshot)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=f"لقطة غير صالحة: {error}")
    goal = str(snapshot.get("goal", ""))
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    def sink(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)
        _persist_event(event)

    def run_resumed_in_thread() -> None:
        try:
            _orchestrator.run_cycle(
                goal,
                workspace_root=path.parent,  # مساحة العمل نفسها — الأدلة متصلة
                on_event=sink,
                resume_from=snapshot,
            )
        except Exception as error:  # noqa: BLE001 — بث الخطأ لا موته صامتًا
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "seq": 0,
                    "cycle_id": "",
                    "role": "coordinator",
                    "kind": "cycle_error",
                    "state": None,
                    "text": f"الاستئناف فشل: {error}",
                    "duration_ms": 0,
                    "details": {"error": str(error)},
                },
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(_executor, run_resumed_in_thread)

    async def generate():
        yield "data: " + json.dumps(
            {
                "seq": 0,
                "cycle_id": "",
                "role": "coordinator",
                "kind": "cycle.resume_requested",
                "state": None,
                "text": f"استئناف الدورة الموقوفة {body.cycle_id} من لقطتها",
                "duration_ms": 0,
                "details": {"from_cycle_id": body.cycle_id},
            },
            ensure_ascii=False,
        ) + "\n\n"
        while True:
            event = await queue.get()
            if event is None:
                break
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------------------ #
# الأمر الثالث — عرض أحداث الموجّه (الحزم الثلاث بنقل mock)
# ------------------------------------------------------------------ #

def _build_demo_router(on_event) -> ModelRouter:
    """موجّه العرض: الحزم الثلاث الحقيقية بأزمنة مضغوطة معلنة.

    الأزمنة هنا للعرض (فاصل 0.7ث، تبريد 0.6←1.2ث، تراجع 0.15ث) —
    القيم الافتراضية الحقيقية (40 طلب/دقيقة، 60←120←240←300، ميزانية
    1800ث) مثبتة في tests/router/ بالساعة والنوم القابلين للحقن.
    """
    limiter = RateLimiter(
        {"rpm": 40, "min_interval": 0.7, "cooldown": 0.4, "concurrency": 1}
    )
    # أطوار العرض مستقلة: كل طور بمزوده وبلا فاصل أدنى إلا طور الحد
    for demo_provider in ("demo-throttled", "demo-primary", "demo-backup"):
        limiter.configure(demo_provider, {"min_interval": 0.0, "cooldown": 0.4})

    chain = FailoverChain(
        ["demo-primary", "demo-backup"],
        {"max_retries": 2, "backoff_base": 0.15},
        on_event=on_event,
    )
    cooling = CoolingLoop(
        {"cooldown_base": 0.6, "cooldown_max": 1.2, "max_waits": 3,
         "budget_seconds": 10},
        on_event=on_event,
    )

    throttled_calls = {"n": 0}

    def free_gateway(model: str, messages) -> str:
        return "رد النموذج من البوابة المجانية (40 طلبًا/دقيقة)"

    def throttled_gateway(model: str, messages) -> str:
        throttled_calls["n"] += 1
        if throttled_calls["n"] <= 2:
            raise ProviderCallError(
                "429 Too Many Requests — حصة الدقيقة مستنفدة",
                code=429,
                is_throttle=True,
            )
        return "رد النموذج بعد الصبر على الاختناق (تبريد ×2)"

    def primary_down(model: str, messages) -> str:
        raise ProviderCallError(
            "503 Service Unavailable — البوابة الأساسية منهارة",
            code=503,
            is_server_error=True,
        )

    def backup_gateway(model: str, messages) -> str:
        return "رد النموذج عبر البوابة الاحتياطية بعد التبدّل"

    return ModelRouter(
        rate_limiter=limiter,
        failover_chain=chain,
        cooling_loop=cooling,
        default_provider="demo-nvidia",
        transports={
            "demo-nvidia": free_gateway,
            "demo-throttled": throttled_gateway,
            "demo-primary": primary_down,
            "demo-backup": backup_gateway,
        },
        on_event=on_event,
    )


@app.post("/api/router/demo")
async def router_demo() -> StreamingResponse:
    """بث حي لأحداث الموجّه: ⏳ حد المعدل ثم 🧊 التبريد ثم 🔄 التبدّل.

    الأدوار الخمسة ما زالت mock خالصة لا تستدعي الموجّه — هذا مسار
    عرض صريح يشغّل الحزم الثلاث المنقولة بنقل mock حقيقي (وليس
    استدعاءات LLM). كل حدث يُسجَّل في جدول events بدور "router".
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    demo_id = f"router-demo-{uuid.uuid4().hex[:8]}"
    seq = {"n": 0}

    def emit(kind: str, details: dict, text: str = "") -> None:
        seq["n"] += 1
        envelope = {
            "seq": seq["n"],
            "cycle_id": demo_id,
            "role": "router",
            "kind": kind,
            "state": None,
            "text": text,
            "duration_ms": 0,
            "details": details,
        }
        loop.call_soon_threadsafe(queue.put_nowait, envelope)
        _persist_event(envelope)

    def sink(event: dict) -> None:
        emit(event.get("kind", "router.event"), event)

    def run_demo() -> None:
        try:
            emit(
                "router.demo.start",
                {"demo_id": demo_id},
            )
            router = _build_demo_router(sink)
            messages = [ChatMessage(role="user", content="اشرح أداء السوق اليوم")]

            emit(
                "router.demo.phase",
                {"phase": "rate_limit",
                 "note": "طور 1 من 3 — حماية مفتاح نفيديا المجاني"},
            )
            router.chat(messages, provider_id="demo-nvidia", model="free-40rpm")
            router.chat(messages, provider_id="demo-nvidia", model="free-40rpm")

            emit(
                "router.demo.phase",
                {"phase": "cooling",
                 "note": "طور 2 من 3 — الصبر عند اختناق 429"},
            )
            router.chat(
                messages, provider_id="demo-throttled", model="free-40rpm"
            )

            emit(
                "router.demo.phase",
                {"phase": "failover",
                 "note": "طور 3 من 3 — المرونة عند انهيار المزود"},
            )
            router.chat(
                messages, provider_id="demo-primary", model="free-40rpm"
            )

            emit(
                "router.demo.done",
                {
                    "demo_id": demo_id,
                    "calls": 4,
                    "note": (
                        "أزمنة العرض مضغوطة (0.7ث/0.6ث/0.15ث) — القيم "
                        "الافتراضية الحقيقية: 40 طلبًا/دقيقة، تبريد "
                        "60←120←240←300ث بميزانية 1800ث، وإعادتان قبل "
                        "التبدّل (كلها مثبتة في tests/router/)"
                    ),
                },
            )
        except Exception as error:  # noqa: BLE001 — بث الخطأ لا موته صامتًا
            emit("router.demo.error", {"error": str(error)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    running = loop.run_in_executor(_executor, run_demo)

    async def generate():
        while True:
            event = await queue.get()
            if event is None:
                break
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        await running

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# =========================================================================
# الأمر الرابع المعدل — محرك الأوامر التنفيذية (EOE)
# =========================================================================


class EoeStartIn(BaseModel):
    """طلب تنفيذ أمر تنفيذي كامل ملصوق من المالك."""

    order_text: str = Field(..., min_length=1)
    working_repo: str = ""


class EoeApproveIn(BaseModel):
    """موافقة المالك — البطاقات الثلاث: منح / دفع."""

    run_id: str
    kind: str  # grants | push
    approved: bool


#: عمليات EOE الجارية — واحدة في كل لحظة (كالدورة).
_eoe_lock = threading.Lock()
_eoe_active: dict | None = None

#: مهلة انتظار موافقة المالك (ثوان) — انقضاؤها = رفض fail-closed.
EOE_APPROVAL_TIMEOUT_S = 600.0


def _eoe_event_shape(run_id: str, seq_box: list, kind: str, payload: dict) -> dict:
    """تشكيل حدث EOE بذيل أحداث الدورة نفسه (يسجل في جدول events)."""
    seq_box[0] += 1
    return {
        "seq": seq_box[0],
        "cycle_id": run_id,
        "role": "eoe",
        "kind": kind,
        "state": "HARD STOP" if kind == "hard_stop.fired" else None,
        "text": payload.get("title", kind),
        "duration_ms": payload.get("duration_ms", 0),
        "details": payload,
    }


def _build_eoe_engine(working_repo: str):
    from eoe.eoe_engine import EoeEngine
    from substrate.local_substrate import (
        default_local_images,
        local_git_image,
        local_sandbox_manager,
    )

    images = {**default_local_images(), "git": local_git_image()}
    manager = local_sandbox_manager(images=images)
    work_base = Path(settings.db_path).parent / "eoe-runs" / uuid.uuid4().hex[:8]
    work_base.mkdir(parents=True, exist_ok=True)
    return EoeEngine(
        manager,
        grantor_key=uuid.uuid4().bytes,   # مفتاح جلسة — لا يخزن
        approval_key=uuid.uuid4().bytes,
        on_event=lambda kind, payload: None,   # يُربط لاحقًا داخل الخيط
        work_base=str(work_base),
        working_repo=working_repo or str(Path(__file__).resolve().parents[2]),
    )


@app.post("/api/eoe/stream")
async def eoe_stream(body: EoeStartIn) -> StreamingResponse:
    """بث تنفيذ أمر تنفيذي كامل — بطاقات الموافقة جزء من البث.

    تدفق الموافقة الحقيقي: المحرك يقترح المنح ← حدث ``grant.requested``
    يُبث ← الخيط ينتظر موافقة المالك (``/api/eoe/approve``) ← التوقيع
    والاستمرار أو الرفض الصريح. الدفع كذلك: ``push.approval_needed`` ←
    انتظار ← موافقة موقعة أحادية الاستخدام أو رفض. لا موافقة = لا فعل.
    """
    global _eoe_active
    with _eoe_lock:
        if (
            _eoe_active is not None
            and not _eoe_active["done"].is_set()
        ):
            raise HTTPException(status_code=409, detail="أمر EOE يعمل بالفعل")

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    run_id = f"eoe-{uuid.uuid4().hex[:10]}"
    seq_box = [0]
    grants_event = threading.Event()
    push_event = threading.Event()
    done_event = threading.Event()
    approval_state: dict = {"grants": None, "push": None}

    def emit(kind: str, payload: dict) -> None:
        event = _eoe_event_shape(run_id, seq_box, kind, payload)
        loop.call_soon_threadsafe(queue.put_nowait, event)
        _persist_event(event)

    engine = _build_eoe_engine(body.working_repo)

    def approve_grants(proposals):
        """انتظار موافقة المالك على المنح — بلا موافقة لا وصول."""
        emit("grant.awaiting_owner", {
            "proposals": [
                {"grant_id": g.grant_id, "kind": g.kind.value,
                 "scope": g.scope.value, "target": g.target}
                for g in proposals
            ],
            "instruction": "بطاقة موافقة المنح — وافق أو ارفض",
        })
        grants_event.wait(timeout=EOE_APPROVAL_TIMEOUT_S)
        if approval_state["grants"] is not True:
            return []   # رفض أو مهلة = لا منح (fail-closed)
        return [engine.approve_grant(g) for g in proposals]

    def approve_push(info):
        """انتظار موافقة المالك الموقعة على الدفع — ثم التوقيع."""
        emit("push.awaiting_owner", {
            "commit_sha": info.get("commit_sha", "")[:12],
            "branch": info.get("branch", ""),
            "instruction": "بطاقة موافقة الدفع — موافقة موقعة أحادية الاستخدام",
        })
        push_event.wait(timeout=EOE_APPROVAL_TIMEOUT_S)
        if approval_state["push"] is not True:
            return None
        return engine.sign_push_approval(
            repository=info.get("repository", ""),
            branch=info.get("branch", ""),
            commit_sha=info.get("commit_sha", ""),
            files_digest=info.get("files_digest", ""),
        )

    with _eoe_lock:
        _eoe_active = {
            "run_id": run_id,
            "done": done_event,
            "grants_event": grants_event,
            "push_event": push_event,
            "approval_state": approval_state,
        }

    def run_eoe_in_thread() -> None:
        try:
            engine._on_event = emit
            result = engine.run_order(
                body.order_text,
                approve_grants=approve_grants,
                approve_push=approve_push,
            )
            emit("eoe.finished", {
                "verdict": result.verdict,
                "hard_stops": result.hard_stops,
                "sections": result.section_states,
                "report_text": result.report.text() if result.report else "",
                "artifact_hash": result.report.artifact_hash if result.report else "",
            })
        except Exception as error:  # noqa: BLE001 — بث الخطأ لا موته صامتًا
            emit("eoe.error", {"error": str(error)})
        finally:
            done_event.set()
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(_eoe_executor, run_eoe_in_thread)

    async def generate():
        global _eoe_active
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        finally:
            # انقطاع المالك = غيابه = رفض (fail-closed): استيقاظ الخيط
            # المنتظر للموافقة برفض صريح فلا يحتجز المنفّذ أبدًا
            with _eoe_lock:
                if _eoe_active and _eoe_active.get("run_id") == run_id:
                    if _eoe_active["approval_state"]["grants"] is None:
                        _eoe_active["approval_state"]["grants"] = False
                    if _eoe_active["approval_state"]["push"] is None:
                        _eoe_active["approval_state"]["push"] = False
                    _eoe_active["grants_event"].set()
                    _eoe_active["push_event"].set()
                    _eoe_active = None

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/eoe/approve")
def eoe_approve(body: EoeApproveIn) -> dict:
    """موافقة المالك الحية — توقظ خيط EOE المنتظر أو ترفضه."""
    with _eoe_lock:
        run = _eoe_active
        if run is None or run["run_id"] != body.run_id:
            raise HTTPException(
                status_code=404, detail=f"عملية EOE غير معروفة: {body.run_id}"
            )
        if body.kind not in ("grants", "push"):
            raise HTTPException(status_code=422, detail="نوع موافقة غير معروف")
        run["approval_state"][body.kind] = body.approved
        (run["grants_event"] if body.kind == "grants" else run["push_event"]).set()
    return {
        "run_id": body.run_id,
        "kind": body.kind,
        "approved": body.approved,
        "note": "الموافقة سارية — استؤنف التنفيذ" if body.approved else "الرفض مسجل — fail-closed",
    }


# ------------------------------------------------------------------ #
# الأمر السادس — المهمة الحية: ربط نموذج حقيقي + PDF عربي (§5+§6)
# ------------------------------------------------------------------ #

class MissionStartIn(BaseModel):
    """جسم بدء المهمة — الهدف (فارغ = المهمة الافتراضية §5.1)."""

    goal: str = ""


class MissionVerifyIn(BaseModel):
    """جسم موافقة المستخدم على مهمة — معرّف الدورة."""

    cycle_id: str = Field(min_length=1)


class MissionStopIn(BaseModel):
    """جسم طلب إيقاف المهمة الحية (الأمر 004)."""

    reason: str = ""


#: موجّه المهمة الحية — يُبنى مرة واحدة كسولًا (المفاتيح من ‎.env).
#: الأمر 004: حقل active يتتبع المهمة الجارية (معرفها + متحكم إيقافها).
_mission_state: dict = {
    "router": None,
    "orchestrator": None,
    "lock": threading.Lock(),
    "active": None,
    "last_state": None,
}


def _mission_router():
    """بناء الموجّه الحي مرة واحدة — فشل صريح إن لم تُحل المفاتيح."""
    with _mission_state["lock"]:
        if _mission_state["router"] is None:
            from router.model_router import ModelRouter

            _mission_state["router"] = ModelRouter.build_live()
        return _mission_state["router"]


async def _stream_mission_run(
    goal: str, resume_from: dict | None
) -> StreamingResponse:
    """بث مهمة حية (SSE) — الإيقاف الفوري مربوط بنقاط التفتيش (004).

    معرّف الدورة يُعلن هنا (لا يولَّد داخليًا) حتى يستطيع المالك طلب
    إيقافها من اللحظة الأولى؛ ونقاط تفتيش المنفذ الحي تُربط بمتحكم
    الإيقاف فيُكرَّم الطلب بين خطوات المنفذ لا بعد دوره كاملًا.
    """
    from core.stop_controller import StopController
    from missions import run_mission

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    cycle_id = f"mission-{uuid.uuid4().hex[:12]}"
    stop = StopController()
    done_event = threading.Event()

    with _mission_state["lock"]:
        active = _mission_state.get("active")
        if active is not None and not active["done"].is_set():
            raise HTTPException(status_code=409, detail="مهمة حية تعمل بالفعل")
        _mission_state["active"] = {
            "cycle_id": cycle_id,
            "stop": stop,
            "done": done_event,
        }
        _mission_state["last_state"] = None

    def sink(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)
        _persist_event(event)
        if event.get("kind") == "state_change":
            _mission_state["last_state"] = event.get("details", {}).get("to")

    def run_mission_in_thread() -> None:
        try:
            router = _mission_router()
            result = run_mission(
                goal,
                router=router,
                on_event=sink,
                cycle_id=cycle_id,
                stop_controller=stop,
                resume_from=resume_from,
            )
            with _mission_state["lock"]:
                _mission_state["orchestrator"] = result.orchestrator
                _mission_state["last_result"] = {
                    "cycle_id": result.cycle_id,
                    "verdict": result.verdict,
                    "pdf_path": result.pdf_path,
                }
        except Exception as error:  # noqa: BLE001 — بث الخطأ لا موته صامتًا
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "seq": 0,
                    "cycle_id": "",
                    "role": "mission",
                    "kind": "mission_error",
                    "state": None,
                    "text": f"المهمة فشلت قبل الدورة: {error}",
                    "duration_ms": 0,
                    "details": {"error": str(error)},
                },
            )
        finally:
            done_event.set()
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(_eoe_executor, run_mission_in_thread)

    async def generate():
        while True:
            event = await queue.get()
            if event is None:
                break
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/mission/stream")
async def mission_stream(body: MissionStartIn) -> StreamingResponse:
    """بث المهمة الحية كاملة (SSE) — LLM حقيقي، لا mock في المسار.

    أحداث الدورة (أدوار/حالات/أدوات بـ sha256) تُبث لحظة حدوثها،
    وختامها mission_done بالحكم الصادق PASS/HARD STOP/STOPPED والأدلة.
    """
    from missions import DEFAULT_MISSION_GOAL

    goal = body.goal.strip() or DEFAULT_MISSION_GOAL
    return await _stream_mission_run(goal, resume_from=None)


@app.post("/api/mission/stop")
def mission_stop(body: MissionStopIn) -> dict:
    """إيقاف المهمة الحية فورًا — يُكرَّم عند أقرب نقطة تفتيش آمنة.

    القبول فوري (علم ذرّي)؛ التكريم عند حدّ آمن — أقصى الانتظار
    استدعاء أدوات/نموذج واحد قيد التنفيذ، ثم STOPPING → STOPPED
    واللقطة القابلة للاستئناف تُكتب في مجلد المهمة.
    """
    with _mission_state["lock"]:
        active = _mission_state.get("active")
        if active is None:
            raise HTTPException(status_code=409, detail="لا مهمة حية قيد التشغيل")
    if active["done"].is_set():
        raise HTTPException(status_code=409, detail="المهمة انتهت أصلًا")
    receipt = active["stop"].request_stop(
        active["cycle_id"], by="owner", reason=body.reason
    )
    return {
        "cycle_id": active["cycle_id"],
        "status": "STOPPING",
        "receipt": {
            "cycle_id": receipt.cycle_id,
            "requested_by": receipt.requested_by,
            "at": receipt.at,
            "reason": receipt.reason,
        },
    }


@app.get("/api/mission/status")
def mission_status() -> dict:
    """حالة المهمة الحية لحظة الطلب — التشغيل وإيصال الإيقاف."""
    with _mission_state["lock"]:
        active = _mission_state.get("active")
        payload = {
            "running": bool(
                active is not None and not active["done"].is_set()
            ),
            "cycle_id": active["cycle_id"] if active else None,
            "state": _mission_state.get("last_state"),
            "last_result": _mission_state.get("last_result"),
            "stop_requested": False,
            "stop_receipt": None,
        }
        if active is not None:
            receipt = active["stop"].receipt(active["cycle_id"])
            payload["stop_requested"] = receipt is not None
            if receipt is not None:
                payload["stop_receipt"] = {
                    "cycle_id": receipt.cycle_id,
                    "requested_by": receipt.requested_by,
                    "at": receipt.at,
                    "reason": receipt.reason,
                }
    return payload


@app.post("/api/mission/resume")
async def mission_resume() -> StreamingResponse:
    """استئناف المهمة الموقوفة من لقطتها — دورة جديدة تُحقن بالخطة (004)."""
    from core.stop_controller import load_resume_point

    path = Path("runtime") / "missions" / "default" / "stop_snapshot.json"
    if not path.is_file():
        raise HTTPException(
            status_code=404, detail="لا لقطة إيقاف — لا شيء للاستئناف"
        )
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        load_resume_point(snapshot)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=f"لقطة غير صالحة: {error}")
    return await _stream_mission_run(str(snapshot.get("goal", "")), snapshot)


@app.get("/api/mission/report")
def mission_report():
    """تسليم PDF المهمة — 404 صريح إن لم يوجد بعد."""
    pdf = Path("runtime") / "missions" / "default" / "mideast_report.pdf"
    if not pdf.is_file():
        raise HTTPException(status_code=404, detail="لا PDF بعد — شغّل المهمة أولًا")
    return FileResponse(pdf, media_type="application/pdf", filename="mideast_report.pdf")


@app.get("/api/mission/evidence")
def mission_evidence() -> dict:
    """تسليم evidence.json — 404 صريح إن لم يوجد بعد."""
    path = Path("runtime") / "missions" / "default" / "evidence.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="لا دليل بعد — شغّل المهمة أولًا")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/mission/verify")
def mission_verify(body: MissionVerifyIn) -> dict:
    """موافقة المستخدم على مهمة — القناة الوحيدة إلى VERIFIED (§6.3)."""
    with _mission_state["lock"]:
        if _mission_state.get("orchestrator") is None:
            raise HTTPException(
                status_code=404, detail="لا مهمة منجزة بعد — شغّل المهمة أولًا"
            )
    orchestrator: object = _mission_state["orchestrator"]
    try:
        outcome = orchestrator.user_verifies(body.cycle_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"دورة غير معروفة: {body.cycle_id}"
        )
    except StateTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return {
        "cycle_id": body.cycle_id,
        "state": outcome["state"],
        "badge": "✔ VERIFIED",
    }


# ------------------------------------------------------------------ #
# الأمر السادس المنقح — المزودات (§1) + مهمة البناء textstats (§4+§5)
# ------------------------------------------------------------------ #

from api.providers import router as providers_router  # noqa: E402

app.include_router(providers_router)

#: تفعيل مرشح تقنيع المفاتيح على السجلات ([REDACTED] — §1.2).
from secrets_store import install_log_redaction  # noqa: E402

install_log_redaction()

TEXTSTATS_APPROVAL_TIMEOUT_S = 600.0
_textstats_state: dict = {"active": None, "lock": threading.Lock()}


class TextstatsApproveIn(BaseModel):
    """موافقة المالك على بوابة مهمة البناء — path_grant أو push."""

    run_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    approved: bool


@app.post("/api/mission/textstats/stream")
async def textstats_stream() -> StreamingResponse:
    """بث مهمة البناء الحية (SSE) — بطاقتا موافقة: منحة المسار والدفع.

    لا موافقة = لا فعل (fail-closed): بوابة المسار قبل أي كتابة،
    وبوابة الدفع قبل أي push — كل واحدة توقظ بخيط الانتظار نفسه.
    """
    global _textstats_state
    with _textstats_state["lock"]:
        if _textstats_state["active"] is not None:
            raise HTTPException(status_code=409, detail="مهمة بناء تعمل بالفعل")

    from missions_textstats import run_textstats_mission
    from router.model_router import ModelRouter

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    run_id = f"textstats-{uuid.uuid4().hex[:10]}"
    seq_box = [0]
    gates = {
        "path_grant": threading.Event(),
        "push": threading.Event(),
    }
    decisions: dict = {"path_grant": None, "push": None}
    done_event = threading.Event()

    def emit(event: dict) -> None:
        seq_box[0] += 1
        wrapped = {
            "seq": seq_box[0],
            "cycle_id": run_id,
            "state": None,
            **event,
        }
        loop.call_soon_threadsafe(queue.put_nowait, wrapped)
        _persist_event(wrapped)

    def approvals(kind: str, payload: dict) -> bool:
        gate = gates.get(kind)
        if gate is None:
            return False
        emit({
            "kind": "approval.card",
            "role": "mission",
            "text": "بطاقة موافقة: " + (
                "منحة المسار (textstats/**)" if kind == "path_grant"
                else "الدفع إلى mission/textstats بموافقة موقعة"
            ),
            "details": {"gate_kind": kind, "payload": payload},
        })
        gate.wait(timeout=TEXTSTATS_APPROVAL_TIMEOUT_S)
        return decisions[kind] is True

    with _textstats_state["lock"]:
        _textstats_state["active"] = {
            "run_id": run_id, "done": done_event,
            "gates": gates, "decisions": decisions,
        }

    def run_in_thread() -> None:
        try:
            try:
                router_obj = ModelRouter.build_live()
            except Exception as error:  # noqa: BLE001 — بث الفشل لا موته
                emit({
                    "kind": "mission_error", "role": "mission",
                    "text": f"لا موجّه حي: {error}",
                    "duration_ms": 0, "details": {"error": str(error)},
                })
                return
            result = run_textstats_mission(
                router=router_obj, on_event=emit, approvals=approvals,
            )
            with _textstats_state["lock"]:
                _textstats_state["last_result"] = {
                    "verdict": result.verdict,
                    "commit_sha": result.commit_sha,
                    "evidence_sha256": result.evidence_sha256,
                }
        except Exception as error:  # noqa: BLE001
            emit({
                "kind": "mission_error", "role": "mission",
                "text": f"مهمة البناء فشلت: {error}",
                "duration_ms": 0, "details": {"error": str(error)},
            })
        finally:
            done_event.set()
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(_eoe_executor, run_in_thread)

    async def generate():
        global _textstats_state
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        finally:
            with _textstats_state["lock"]:
                _textstats_state["active"] = None

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/mission/textstats/approve")
def textstats_approve(body: TextstatsApproveIn) -> dict:
    """موافقة المالك الحية على بوابة مهمة البناء — توقظ الخيط المنتظر."""
    with _textstats_state["lock"]:
        run = _textstats_state["active"]
        if run is None or run["run_id"] != body.run_id:
            raise HTTPException(
                status_code=404, detail=f"مهمة بناء غير معروفة: {body.run_id}"
            )
        if body.kind not in ("path_grant", "push"):
            raise HTTPException(status_code=422, detail="نوع بوابة غير معروف")
        run["decisions"][body.kind] = body.approved
        run["gates"][body.kind].set()
    return {
        "run_id": body.run_id,
        "kind": body.kind,
        "approved": body.approved,
        "note": "الموافقة سارية — استؤنف التنفيذ" if body.approved
                else "الرفض مسجل — fail-closed",
    }


@app.get("/api/mission/textstats/evidence")
def textstats_evidence() -> dict:
    """تسليم دليل مهمة البناء — 404 صريح إن لم يوجد بعد."""
    path = Path("runtime") / "missions" / "textstats" / "evidence.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="لا دليل بعد — شغّل المهمة أولًا")
    return json.loads(path.read_text(encoding="utf-8"))
