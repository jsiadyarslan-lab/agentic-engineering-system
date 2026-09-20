"""نقاط النهاية النحيفة — FastAPI (تأسيس).

- GET  /                    الواجهة (index.html)
- GET  /health              الحالة الصادقة (بما فيها توفر الركيزة)
- GET  /api/conversations   قائمة المحادثات (فارغة في التأسيس)
- POST /api/chat/stream     بث SSE لرسالة تأسيس واحدة (إثبات الخط — لا كود ميزات)

لا منطق أدوار هنا — الأدوار تأتي بالأمر الثاني.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import settings
from persistence.database import build_engine, init_db

UI_DIR = Path(__file__).resolve().parents[1] / "ui"

app = FastAPI(title=settings.app_name, version=settings.app_version)

_engine = build_engine(settings.db_path)
init_db(_engine)

# ثوابت الواجهة: styles.css + app.js + الخطوط المضمنة محليًا
app.mount("/static", StaticFiles(directory=UI_DIR), name="static")


class ChatIn(BaseModel):
    """جسم طلب البث — رسالة المستخدم."""

    message: str


#: رسالة التأسيس الواحدة — تُبث كلمةً كلمة لإثبات خط SSE كاملًا.
BOOTSTRAP_MESSAGE = (
    "هذه رسالة تأسيس من agent-hub v2 — مرحلة البناء الأولى. "
    "البنية جاهزة: خمسة أدوار (المفكر، المدقق، المنفذ، المراجع، المُحكَّم)، "
    "إحدى عشرة حالة صادقة، وركيزة تنفيذ معزولة اختُبرت بأربعة إثباتات سالبة. "
    "لا دور يمنح النظام نجاحه بنفسه — القرار الأخير لك دائمًا. "
    "دورة الأدوار الكاملة تبدأ في الأمر الثاني بعد موافقتك على هذا الهيكل."
)


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
        "phase": "bootstrap",
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
    """قائمة المحادثات — فارغة في التأسيس (بلا كود ميزات)."""
    return {"conversations": []}


@app.post("/api/chat/stream")
async def chat_stream(body: ChatIn) -> StreamingResponse:
    """بث رسالة التأسيس — إثبات SSE حقيقي بلا أي منطق أدوار."""

    async def gen():
        for word in BOOTSTRAP_MESSAGE.split(" "):
            yield "data: " + json.dumps(
                {"token": word + " "}, ensure_ascii=False
            ) + "\n\n"
            await asyncio.sleep(0.045)
        yield "data: " + json.dumps(
            {"done": True, "role": "coordinator"}, ensure_ascii=False
        ) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
