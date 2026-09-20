"""نقاط النهاية النحيفة — FastAPI (الأمر الثاني: أول دورة كاملة).

- GET  /                    الواجهة (index.html)
- GET  /health              الحالة الصادقة (بما فيها توفر الركيزة)
- GET  /api/conversations   قائمة المحادثات (عنصر شاغل في هذه المرحلة)
- POST /api/cycle/stream    بث SSE لأحداث الدورة الكاملة لحظة حدوثها —
                            الدورة تعمل في خيط وكل حدث دور يُدفَع إلى
                            الطابور فور انبعاثه، ويُسجَّل في جدول events
- POST /api/cycle/verify    موافقة المستخدم — القناة الوحيدة إلى VERIFIED

لا منطق أدوار هنا — الأدوار مجمعَّة في core.wiring والتنسيق كله في
core.orchestrator؛ هذه الطبقة نقل وتسجيل فقط.
"""

from __future__ import annotations

import asyncio
import json
import logging
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

logger = logging.getLogger("agent-hub-v2.api")

UI_DIR = Path(__file__).resolve().parents[1] / "ui"

app = FastAPI(title=settings.app_name, version=settings.app_version)

_engine = build_engine(settings.db_path)
init_db(_engine)
_sessions = make_session_factory(_engine)

# ثوابت الواجهة: styles.css + app.js + الخطوط المضمنة محليًا
app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

#: الدورة الافتراضية — أدوار mock فوق الركيزة الحقيقية (الأمر الثاني).
_orchestrator = build_mock_orchestrator()

#: منفّذ الدورات — دورة واحدة في كل لحظة (المنسق يقفل داخليًا أيضًا).
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="v2-cycle")


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
        "phase": "mock-cycle",
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
