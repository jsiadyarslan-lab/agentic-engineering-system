"""نقاط النهاية النحيفة — FastAPI (الأمر 006: المحادثة والمهمة حيّتان).

- GET  /                    الواجهة (index.html)
- GET  /health              الحالة الصادقة (بما فيها توفر الركيزة)
- GET  /api/conversations   قائمة المحادثات الحقيقية من SQLite (§14)
- GET  /api/conversations/{id}/messages  سجل رسائل محادثة
- POST /api/chat/stream     محادثة بنموذج واحد — SSE (§2 محادثة)
- POST /api/cycle/stream    المهمة: دورة الأدوار الخمسة الحيّة — SSE (§2 مهمة)
                            production wiring حي حصرًا: لا mock أبدًا؛
                            لا مزود/مفتاح = CONFIGURATION_REQUIRED صريح
- POST /api/cycle/verify    موافقة المستخدم — القناة الوحيدة إلى VERIFIED
- POST /api/cycle/stop      الإيقاف الفوري الآمن (الأمر 004)
- GET  /api/cycle/status    حالة المهمة + إمكان الاستئناف
- POST /api/cycle/resume    استئناف من اللقطة (دورة جديدة تُحقن بها)
- POST /api/router/demo     مسار عرض تشخيصي معلن لأحداث الموجه
- POST /api/eoe/stream      بث تنفيذ أمر تنفيذي (الأمر الرابع)
- POST /api/eoe/approve     موافقة المالك على المنح/الدفع
- GET/PUT /api/models/config  اختيار النموذج لكل دور (§13)

لا منطق أدوار هنا — الأدوار مجمّعة في core.wiring والتنسيق كله في
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
from persistence import conversations as convo
from persistence.database import build_engine, init_db, make_session_factory
from persistence.models import Event
from providers_registry import registry
from router import role_config as rc
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

#: الأمر 006 §1+§12: مسار الإنتاج لا يبني orchestrator اشتراكيًا —
#: كل مهمة تبني دورتها الحية بطلبها (اختيارات أدوار المهمة جزء منها)،
#: والمحادثة تبني موجّهها بنموذجها. mock لا يُستورد هنا إطلاقًا —
#: يرسّخ ذلك اختبار الحارس tests/api/test_no_mock_in_production.py.

#: منفّذ المهام والدورات — واحدة في كل لحظة (المنسق يقفل داخليًا أيضًا).
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="v2-cycle")

#: منفّذ EOE مخصص — انتظار موافقة المالك (حتى 600ث) لا يحتجز منفّذ
#: الدورة أبدًا، والعكس صحيح (الأمر الرابع).
_eoe_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="v2-eoe")

#: فصل التركيب الصريح (§12): production يبني الموجّه الحي من مزودات
#: المالك حصرًا. الاختبارات — وحدها — تحقن مصنعًا بديلًا عبر هذا
#: الخطاف (نقلات حتمية للاختبار، لا يمر منه أي مسار إنتاج).
_test_router_factory = None


def _build_live_router(on_event=None) -> ModelRouter:
    """الموجّه الحي — production wiring: مزودات المالك، لا mock أبدًا.

    require_default=False (الأمر 006 §1): الأدوار تختار مزودها صراحة،
    فالفحص الأمامي لكل دور في _stream_task_run هو الحكم الأصدق —
    يُبنى الموجّه بكل المزودات المحلولة، وأي دور بلا مزوده يُسمّى
    في CONFIGURATION_REQUIRED (لا تبدّل صامت ولا mock بديلًا).
    """
    if _test_router_factory is not None:
        return _test_router_factory(on_event=on_event)
    return ModelRouter.build_live(on_event=on_event, require_default=False)


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


class RoleSelectionBody(BaseModel):
    """جسم اختيار نموذج دور واحد داخل طلب المهمة (§3)."""

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=200)


class CycleStartIn(BaseModel):
    """جسم بدء المهمة — الهدف + المحادثة + اختيارات الأدوار (§2+§3)."""

    goal: str = Field(min_length=1)
    conversation_id: int | None = None
    roles: dict[str, RoleSelectionBody] | None = None


class ChatStartIn(BaseModel):
    """جسم رسالة محادثة — نموذج واحد بلا أدوار (§2 محادثة)."""

    message: str = Field(min_length=1, max_length=32_000)
    conversation_id: int | None = None
    provider: str | None = None
    model: str | None = None


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
        "phase": "agentic-engineering-system: durable-projects+autonomous-loop+provider-management",
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
    """قائمة المحادثات الحقيقية — SQLite، الأحدث أولًا (§14)."""
    return {"conversations": convo.list_conversations(_sessions)}


@app.get("/api/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: int) -> dict:
    """سجل رسائل محادثة — 404 صريح إن لم تكن معروفة."""
    if convo.get_conversation(_sessions, conversation_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"محادثة غير معروفة: {conversation_id}",
        )
    return {
        "conversation_id": conversation_id,
        "messages": convo.conversation_messages(_sessions, conversation_id),
    }


# ------------------------------------------------------------------ #
# الأمر 006 — المهمة الحية (المسار الرئيسي) + المحادثة الحية
# ------------------------------------------------------------------ #

#: حالة المهمة الجارية (بنمط المهمة الحية) — واحدة في كل لحظة.
_task_state: dict = {
    "orchestrator": None,
    "lock": threading.Lock(),
    "active": None,
    "last_state": None,
    "last_result": None,
}

#: معرف الدورة الصالح حصرًا — fail-closed ضد اجتياز المسارات.
_CYCLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

#: أسماء الأدوار العربية — للرسائل الصادقة التي تسمي من فشل.
ROLE_LABELS: dict[str, str] = {
    "thinker": "المفكر",
    "reviewer": "المدقق",
    "implementer": "المنفذ",
    "verifier": "المراجع",
    "arbiter": "المحكَّم",
    "chat": "المحادثة",
}


def _resolve_role_selections(
    overrides: dict[str, RoleSelectionBody] | None,
) -> dict[str, rc.RoleSelection]:
    """دمج اختيارات الطلب فوق المحفوظة — كل دور باختياره المستقل (§3).

    (الأمر 007.1 §15): المصدر الدائم هو جدول role_provider_mappings
    في القاعدة — لا ملف JSON بعد الآن في مسار الـAPI.
    """
    selections: dict[str, rc.RoleSelection] = {}
    for key, found in registry.get_mappings(_sessions).items():
        selections[key] = rc.RoleSelection(
            provider=found["provider"],
            model=found["model"],
            configuration=found.get("configuration", ""),
        )
    for key, value in (overrides or {}).items():
        if key not in rc.ROLE_KEYS:
            raise HTTPException(
                status_code=422, detail=f"دور غير معروف في الطلب: {key}"
            )
        selections[key] = rc.RoleSelection(
            provider=value.provider, model=value.model
        )
    return selections


def _config_required_event(
    reason: str, *, cycle_id: str = "", details: dict | None = None
) -> dict:
    """حدث CONFIGURATION_REQUIRED — لا نجاح وهمي ولا mock بديلًا (§1)."""
    return {
        "seq": 0,
        "cycle_id": cycle_id,
        "role": "coordinator",
        "kind": "CONFIGURATION_REQUIRED",
        "state": "FAILED_TO_START",
        "text": reason,
        "duration_ms": 0,
        "details": {"code": "CONFIGURATION_REQUIRED", **(details or {})},
    }


def _emit_single(event: dict):
    """مولد SSE من حدث واحد — إعلان صريح ثم ختام البث."""

    async def generate():
        yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    return generate()


def _sse_response(generator) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_task_run(
    goal: str,
    *,
    conversation_id: int | None,
    role_overrides: dict[str, RoleSelectionBody] | None,
    resume_from: dict | None,
    resume_workspace: Path | None,
) -> StreamingResponse:
    """بث مهمة حية (SSE) — الأدوار الخمسة الحية باختيارات مستقلة.

    لا mock في هذا المسار أبدًا: تعذر حل المزودات أو نموذج أي دور
    = حدث CONFIGURATION_REQUIRED صريح يسمي الدور والسبب (§1)،
    ثم ينتهي البث — لا سقوط إلى أدوار وهمية ولا نجاح مزيف.
    """
    from core.stop_controller import StopController
    from tasks import run_task

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    selections = _resolve_role_selections(role_overrides)
    role_config = {
        key: value for key, value in selections.items() if key != "chat"
    }

    # المحادثة: إنشاء إن لم تعط — النمط مهمة (§14)
    if conversation_id is None:
        conversation = convo.create_conversation(
            _sessions, title=goal, mode="task"
        )
        conversation_id = conversation.id
    elif convo.get_conversation(_sessions, conversation_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"محادثة غير معروفة: {conversation_id}",
        )
    convo.append_message(_sessions, conversation_id, role="user", content=goal)

    # الموجه الحي — فشل الحل = إعلان صريح لا mock (§1)
    # أحداث الموجّه (حد معدل/تبريد/تبدل/سجل استدعاء) تبث في المحادثة
    # نفسها — الواجهة ترى المزود والنموذج والزمن لكل استدعاء (§17).
    router_events: list[dict] = []

    def router_sink(event: dict) -> None:
        router_events.append(event)

    router_error: str | None = None
    try:
        router = _build_live_router(on_event=router_sink)
    except Exception as error:  # noqa: BLE001 — بث الفشل لا موته
        router_error = str(error)
    if router_error is not None:
        return _sse_response(_emit_single(
            _config_required_event(
                f"لا مزود حي قابل للحل — {router_error}",
                details={"conversation_id": conversation_id},
            )
        ))

    # فحص مقدم: أي دور بلا نموذج متاح يسمى قبل بدء الدورة (§1)
    missing_roles = [
        f"{ROLE_LABELS[key]} (المزود {value.transport_key()})"
        for key, value in role_config.items()
        if not router.has_live_provider(value.transport_key())
    ]
    if missing_roles:
        return _sse_response(_emit_single(
            _config_required_event(
                "أدوار بلا نموذج متاح: " + "، ".join(missing_roles),
                details={
                    "missing_roles": missing_roles,
                    "available_providers": router.live_providers(),
                    "conversation_id": conversation_id,
                },
            )
        ))

    cycle_id = f"task-{uuid.uuid4().hex[:12]}"
    stop = StopController()
    done_event = threading.Event()

    with _task_state["lock"]:
        active = _task_state.get("active")
        if active is not None and not active["done"].is_set():
            raise HTTPException(status_code=409, detail="مهمة حية تعمل بالفعل")
        _task_state["active"] = {
            "cycle_id": cycle_id,
            "stop": stop,
            "done": done_event,
            "conversation_id": conversation_id,
        }
        _task_state["last_state"] = None

    task_seq = {"n": 0}

    def sink(event: dict) -> None:
        """تغليف كل حدث بذيل موحد — أحداث الأدوات بلا seq/cycle_id
        كانت تضيع من جدول events (الأمر 006: سجل كامل لا فجوات)."""
        task_seq["n"] += 1
        envelope = {
            "seq": event.get("seq") or task_seq["n"],
            "cycle_id": event.get("cycle_id") or cycle_id,
            "state": None,
            "duration_ms": 0,
            **event,
        }
        # أحداث الموجّه المجمعة تُضخ قبل حدث الدور — بترتيب حدوثها
        while router_events:
            router_event = router_events.pop(0)
            router_envelope = {
                "seq": task_seq["n"],
                "cycle_id": cycle_id,
                "role": "router",
                "state": None,
                "duration_ms": 0,
                **router_event,
            }
            loop.call_soon_threadsafe(queue.put_nowait, router_envelope)
            _persist_event(router_envelope)
        loop.call_soon_threadsafe(queue.put_nowait, envelope)
        _persist_event(envelope)
        if envelope.get("kind") == "state_change":
            _task_state["last_state"] = envelope.get("details", {}).get("to")

    def run_task_in_thread() -> None:
        try:
            result = run_task(
                goal,
                router=router,
                role_config=role_config,
                workspace=resume_workspace,
                on_event=sink,
                cycle_id=cycle_id,
                stop_controller=stop,
                resume_from=resume_from,
            )
            with _task_state["lock"]:
                _task_state["orchestrator"] = result.orchestrator
                _task_state["last_result"] = {
                    "cycle_id": result.cycle_id,
                    "verdict": result.verdict,
                    "reason": result.reason,
                    "evidence_path": result.evidence_path,
                }
            # رسالة خلاصة في المحادثة — الحكم الصادق يحفظ مع التاريخ
            convo.append_message(
                _sessions, conversation_id,
                role="assistant",
                content=(
                    f"[{result.verdict}] {result.reason} — "
                    f"الحالة النهائية: {result.final_state or '—'} · "
                    f"الأدلة: {result.evidence_path or '—'}"
                ),
                state_badge=result.verdict,
            )
        except Exception as error:  # noqa: BLE001 — بث الخطأ لا موته
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "seq": 0,
                    "cycle_id": cycle_id,
                    "role": "coordinator",
                    "kind": "cycle_error",
                    "state": None,
                    "text": f"المهمة فشلت قبل الدورة: {error}",
                    "duration_ms": 0,
                    "details": {"error": str(error)},
                },
            )
        finally:
            done_event.set()
            loop.call_soon_threadsafe(queue.put_nowait, None)  # خاتمة البث

    running = loop.run_in_executor(_executor, run_task_in_thread)

    async def generate():
        yield "data: " + json.dumps(
            {
                "seq": 0,
                "cycle_id": cycle_id,
                "role": "coordinator",
                "kind": "task.conversation",
                "state": None,
                "text": "",
                "duration_ms": 0,
                "details": {"conversation_id": conversation_id},
            },
            ensure_ascii=False,
        ) + "\n\n"
        while True:
            event = await queue.get()
            if event is None:  # خاتمة — الخيط انتهى
                break
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        await running

    return _sse_response(generate())


@app.post("/api/cycle/stream")
async def cycle_stream(body: CycleStartIn) -> StreamingResponse:
    """المهمة الحية (المسار الرئيسي) — دورة الأدوار الخمسة الحية (§2).

    رسالة المستخدم تصل فعلًا إلى نماذج حقيقية عبر الموجه، بتمرير
    اختيار كل دور المستقل، والتنفيذ داخل الركيزة عند الحاجة،
    والأدلة والحالة تبث لحظة حدوثها وتسجل (الأمر 006 كله).
    """
    return await _stream_task_run(
        body.goal,
        conversation_id=body.conversation_id,
        role_overrides=body.roles,
        resume_from=None,
        resume_workspace=None,
    )


# ------------------------------------------------------------------ #
# المحادثة الحية — نموذج واحد بلا أدوار (§2 محادثة)
# ------------------------------------------------------------------ #

#: عدد رسائل التاريخ التي تبنى منها رسائل النموذج (نافذة سياق).
_CHAT_HISTORY_LIMIT = 12

#: حجم قطعة البث — كلمات لكل chat.delta (بث تطبيقي §2).
_CHAT_DELTA_WORDS = 8


def _chunk_text(text: str, words_per_chunk: int = _CHAT_DELTA_WORDS):
    """تقسيم النص الجاهز إلى قطع بث تطبيقية — النقل غير متدفق."""
    words = text.split(" ")
    for start in range(0, len(words), words_per_chunk):
        yield " ".join(words[start:start + words_per_chunk])


@app.post("/api/chat/stream")
async def chat_stream(body: ChatStartIn) -> StreamingResponse:
    """محادثة بنموذج واحد — SSE: chat.start ثم chat.delta* ثم chat.done.

    بث تطبيقي صادق: النقل (urllib) غير متدفق، فالنص الجاهز يقسم
    إلى قطع وتبث لحظة اكتمال الاستدعاء (مسموح صراحة §2). لا mock:
    تعذر المزود = chat.error بـ CONFIGURATION_REQUIRED ثم ختام.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    # المحادثة: إنشاء إن لم تعط — نمط محادثة (§14)
    if body.conversation_id is None:
        conversation = convo.create_conversation(
            _sessions, title=body.message, mode="chat"
        )
        conversation_id = conversation.id
    elif convo.get_conversation(_sessions, body.conversation_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"محادثة غير معروفة: {body.conversation_id}",
        )
    else:
        conversation_id = body.conversation_id
    convo.append_message(
        _sessions, conversation_id, role="user", content=body.message
    )

    # اختيار النموذج: الطلب ثم المحفوظ في القاعدة ثم الافتراضي المعلن
    saved = _resolve_role_selections(None)["chat"]
    provider = body.provider or saved.transport_key()
    model = body.model or saved.model

    chat_seq = {"n": 0}

    def put(event: dict) -> None:
        """تغليف حدث المحادثة بذيل الأحداث الموحد — يسجل في جدول events."""
        chat_seq["n"] += 1
        envelope = {
            "seq": chat_seq["n"],
            "cycle_id": f"chat-{conversation_id}",
            "state": None,
            "role": "chat",
            **event,
        }
        loop.call_soon_threadsafe(queue.put_nowait, envelope)
        _persist_event(envelope)

    def run_chat_in_thread() -> None:
        try:
            router = _build_live_router(on_event=lambda e: put({
                "kind": "router.event", "role": "router", **e
            }))
            if not router.has_live_provider(provider):
                put({
                    "kind": "chat.error",
                    "code": "CONFIGURATION_REQUIRED",
                    "text": (
                        f"المزود '{provider}' غير متاح للربط الحي — "
                        f"المتاح: {router.live_providers()}. "
                        "احفظ مفتاح المزود من الإعدادات أو اختر مزودًا متاحًا"
                    ),
                    "details": {
                        "conversation_id": conversation_id,
                        "provider": provider,
                        "model": model,
                    },
                })
                return
            history = [
                ChatMessage(role=m["role"], content=m["content"])
                for m in convo.conversation_messages(
                    _sessions, conversation_id, limit=_CHAT_HISTORY_LIMIT
                )
                if m["role"] in ("user", "assistant")
            ]
            outcome = router.chat_live(
                history, provider_id=provider, model=model
            )
            for piece in _chunk_text(outcome["text"]):
                put({
                    "kind": "chat.delta",
                    "text": piece,
                    "details": {"conversation_id": conversation_id},
                })
            convo.append_message(
                _sessions, conversation_id,
                role="assistant", content=outcome["text"],
            )
            put({
                "kind": "chat.done",
                "text": "",
                "details": {
                    "conversation_id": conversation_id,
                    "provider": outcome["provider"],
                    "model": outcome["model"],
                    "tokens": outcome["tokens"],
                    "duration_ms": outcome["duration_ms"],
                },
            })
        except Exception as error:  # noqa: BLE001 — بث الخطأ لا موته
            put({
                "kind": "chat.error",
                "code": "PROVIDER_CALL_FAILED",
                "text": f"تعذر الاستدعاء الحي: {error}",
                "details": {
                    "conversation_id": conversation_id,
                    "provider": provider,
                    "model": model,
                    "error": str(error),
                },
            })
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(_executor, run_chat_in_thread)

    async def generate():
        yield "data: " + json.dumps(
            {
                "kind": "chat.start",
                "text": "",
                "details": {
                    "conversation_id": conversation_id,
                    "provider": provider,
                    "model": model,
                },
            },
            ensure_ascii=False,
        ) + "\n\n"
        while True:
            event = await queue.get()
            if event is None:
                break
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    return _sse_response(generate())


@app.post("/api/cycle/verify")
def cycle_verify(body: CycleVerifyIn) -> dict:
    """موافقة المستخدم على نتيجة المهمة — القناة الوحيدة إلى VERIFIED.

    يرفض 404 لدورة غير معروفة و409 لانتقال غير مسموح (مثل طلب الموافقة
    قبل بلوغ EVIDENCED/ADJUDICATED) — جدول الانتقالات والقاعدة الذهبية
    يفرضان في core/state.py لا هنا.
    """
    with _task_state["lock"]:
        orchestrator = _task_state.get("orchestrator")
        if orchestrator is None:
            raise HTTPException(
                status_code=404,
                detail="لا مهمة منجزة بعد — شغل مهمة أولًا",
            )
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
        "badge": "VERIFIED",
        "event": outcome["event"],
    }


# ------------------------------------------------------------------ #
# الأمر 004 — الإيقاف الفوري الآمن للمهمة + الاستئناف من اللقطة
# ------------------------------------------------------------------ #

def _task_snapshot_dir(cycle_id: str) -> Path:
    return Path("runtime") / "tasks" / cycle_id


@app.post("/api/cycle/stop")
def cycle_stop(body: CycleStopIn) -> dict:
    """طلب إيقاف فوري للمهمة — يقبل فورًا ويكرم عند حد آمن.

    القبول يعني: العلم رفع ذريًا والحالة STOPPING؛ التوقف الفعلي
    عند أقرب نقطة تفتيش (أقصى الانتظار = استدعاء دور واحد).
    """
    with _task_state["lock"]:
        active = _task_state.get("active")
        if active is None:
            raise HTTPException(
                status_code=404, detail=f"دورة غير معروفة: {body.cycle_id}"
            )
    if active["cycle_id"] != body.cycle_id:
        raise HTTPException(
            status_code=404, detail=f"دورة غير معروفة: {body.cycle_id}"
        )
    if active["done"].is_set():
        raise HTTPException(
            status_code=409,
            detail="الدورة ليست قيد التشغيل — انتهت أصلًا",
        )
    receipt = active["stop"].request_stop(
        body.cycle_id, by="owner", reason=body.reason
    )
    return {
        "cycle_id": body.cycle_id,
        "status": "STOPPING",
        "receipt": {
            "cycle_id": receipt.cycle_id,
            "requested_by": receipt.requested_by,
            "at": receipt.at,
            "reason": receipt.reason,
        },
    }


@app.get("/api/cycle/status/{cycle_id}")
def cycle_status(cycle_id: str) -> dict:
    """حالة المهمة لحظة الطلب — التشغيل وإيصال الإيقاف وإمكان الاستئناف."""
    if not _CYCLE_ID_RE.match(cycle_id):
        raise HTTPException(status_code=422, detail="معرف دورة غير صالح")
    with _task_state["lock"]:
        active = _task_state.get("active")
        orchestrator = _task_state.get("orchestrator")
    running = bool(
        active is not None
        and active["cycle_id"] == cycle_id
        and not active["done"].is_set()
    )
    status: dict = {
        "cycle_id": cycle_id,
        "running": running,
        "state": _task_state.get("last_state") if running else None,
        "stop_requested": False,
        "stop_receipt": None,
    }
    if active is not None and active["cycle_id"] == cycle_id:
        receipt = active["stop"].receipt(cycle_id)
        status["stop_requested"] = receipt is not None
        if receipt is not None:
            status["stop_receipt"] = {
                "cycle_id": receipt.cycle_id,
                "requested_by": receipt.requested_by,
                "at": receipt.at,
                "reason": receipt.reason,
            }
    if orchestrator is not None:
        detail = orchestrator.cycle_status(cycle_id)
    else:
        detail = None
    if detail is not None:
        status.update(detail)
    elif not running:
        raise HTTPException(
            status_code=404, detail=f"دورة غير معروفة: {cycle_id}"
        )
    status["can_resume"] = (_task_snapshot_dir(cycle_id) / "stop_snapshot.json").is_file()
    return status


@app.post("/api/cycle/resume")
async def cycle_resume(body: CycleResumeIn) -> StreamingResponse:
    """استئناف مهمة موقوفة من لقطتها — دورة جديدة ت حقن بها (الأمر 004).

    الخطة الموقعة تحقن فتتخطى التفكير والمراجعة، والمهام المثبتة
    لا تعاد؛ مساحة العمل نفسها تعاد الاستخدام حتى تبقى الأدلة متصلة.
    """
    from core.stop_controller import load_resume_point

    if not _CYCLE_ID_RE.match(body.cycle_id):
        raise HTTPException(status_code=422, detail="معرف دورة غير صالح")
    snapshot_path = _task_snapshot_dir(body.cycle_id) / "stop_snapshot.json"
    if not snapshot_path.is_file():
        raise HTTPException(status_code=404, detail="لا لقطة إيقاف لهذه الدورة")
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        load_resume_point(snapshot)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=f"لقطة غير صالحة: {error}")

    with _task_state["lock"]:
        active = _task_state.get("active")
        if active is not None and not active["done"].is_set():
            raise HTTPException(status_code=409, detail="مهمة حية تعمل بالفعل")
        conversation_id = (active or {}).get("conversation_id")

    return await _stream_task_run(
        str(snapshot.get("goal", "")),
        conversation_id=conversation_id,
        role_overrides=None,
        resume_from=snapshot,
        resume_workspace=snapshot_path.parent,  # مساحة العمل نفسها — الأدلة متصلة
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
        SubstrateUnavailable,
        default_local_images,
        local_git_image,
        local_sandbox_manager,
    )

    # الأمر 006 §11: منصة غير مدعومة = إعلان صادق لا استثناء خام —
    # المحرك يُبنى بلا صورة git، وكل قسم git سيفشل FAILED_TO_START بسبب واضح.
    try:
        images = {**default_local_images(), "git": local_git_image()}
    except SubstrateUnavailable:
        images = dict(default_local_images())
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

from api.models_config import router as models_config_router  # noqa: E402
from api.projects import router as projects_router  # noqa: E402
from api.projects import run_startup_recovery  # noqa: E402
from api.providers import configurations_router, router as providers_router  # noqa: E402

app.include_router(providers_router)
app.include_router(configurations_router)
app.include_router(models_config_router)
app.include_router(projects_router)

#: تفعيل مرشح تقنيع المفاتيح على السجلات ([REDACTED] — §1.2).
from secrets_store import install_log_redaction  # noqa: E402

install_log_redaction()

#: استرداد الإقلاع (الأمر 007 §19): مرة واحدة لكل عملية — اكتشاف
#: المشاريع غير النهائية وتقييمها (checkpoint/بوابات/قابلية الاستئناف)
#: وتسجيل RECOVERY_ASSESSED. لا تنفيذ عشوائي أبدًا — الاستئناف قرار
#: صريح عبر /api/projects/{id}/resume.
_RECOVERY_DONE = False


@app.on_event("startup")
def _startup_recovery() -> None:
    global _RECOVERY_DONE
    if _RECOVERY_DONE:
        return
    _RECOVERY_DONE = True
    try:
        assessments = run_startup_recovery(_sessions)
        if assessments:
            logger.info(
                "استرداد الإقلاع: %d مشروعًا غير منتهٍ — %s",
                len(assessments),
                ", ".join(
                    f"#{a['project_id']} {a['recommendation']}"
                    for a in assessments
                ),
            )
    except Exception as error:  # noqa: BLE001 — الاسترداد لا يمنع الإقلاع
        logger.warning("تعذر استرداد الإقلاع: %s", error)

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
