"""طبقة البسط SSE الموحدة (الأمر 008 §17-§19+§42) — replay ثم حي.

كل بث (محادثة/مهمة) يمر من هنا:
1. قراءة الأحداث الدائمة بعد seq المطلوب (جدول events)؛
2. الاشتراك في الناقل الحي قبل القراءة (لا فجوة سباق)؛
3. إرسال الأرشيف ثم الحي مع إسقاط المكرر (seq <= آخر المرسل)؛
4. الخاتمة stream.done عند انتهاء التشغيل أو بعد الأرشيف إن لا حي.

الانقطاع لا يفقد شيئًا (§19): العودة بـ ?after=<آخر seq> تكمل من
حيث توقف — لا إعادة المهمة من الصفر أبدًا.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from core.live_bus import BUS, normalize_event
from persistence.models import Event

#: علامة خاتمة البث — تصل العميل بعد آخر حدث.
STREAM_DONE = {"kind": "stream.done", "text": "", "details": {}}


def next_seq_base(sessions, cycle_id: str) -> int:
    """أعلى seq محفوظ لتيار — التسلسل رتيب عبر الطلبات (لا تصادم)."""
    with sessions() as session:
        rows = session.scalars(
            select(Event.seq).where(Event.cycle_id == cycle_id)
        ).all()
        return max(rows) if rows else 0


def load_events_after(sessions, cycle_id: str, after: int,
                      limit: int = 500) -> list[dict]:
    """الأحداث الدائمة بعد seq — بهيكلها الكامل الموحد."""
    with sessions() as session:
        rows = session.scalars(
            select(Event)
            .where(Event.cycle_id == cycle_id, Event.seq > after)
            .order_by(Event.seq)
            .limit(limit)
        ).all()
    events: list[dict] = []
    for row in rows:
        try:
            payload = json.loads(row.payload or "{}")
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if payload.get("kind"):  # غلاف كامل (008 §19) — أعد بناءه كما كان
            event = normalize_event({**payload, "seq": row.seq,
                                     "cycle_id": row.cycle_id},
                                    stream=cycle_id)
            event.setdefault("timestamp", row.created_at.isoformat()
                             if row.created_at else "")
        else:  # حمولة قديمة (تفاصيل فقط) — رقّقها إلى العقد الموحد
            event = normalize_event({
                "event_id": f"evt-db-{row.id}",
                "timestamp": row.created_at.isoformat()
                if row.created_at else "",
                "cycle_id": row.cycle_id, "seq": row.seq, "role": row.role,
                "kind": row.kind, "state": row.state,
                "status": row.state or "OK",
                "text": payload.get("text", ""),
                "duration_ms": row.duration_ms or 0, "details": payload,
            }, stream=cycle_id)
        events.append(event)
    return events


def sse_line(event: dict) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


async def live_stream(
    sessions,
    stream_key: str,
    *,
    after: int = 0,
    is_running=lambda: False,
    done_kinds: tuple[str, ...] = (),
    replay_only: bool = False,
):
    """مولد SSE: أرشيف بعد-seq ← حي عبر الناقل ← خاتمة.

    is_running: هل التشغيل قائم الآن (يحدد انتظار الحي بعد الأرشيف).
    done_kinds: أنواع أحداث تختم البث مبكرًا (task_done/message_completed).
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    # (لا فجوة سباق) الاشتراك قبل قراءة الأرشيف — الحي يتراكم في الطابور
    sub_id = BUS.subscribe(stream_key, loop, queue)
    try:
        last_seq = after
        archive = load_events_after(sessions, stream_key, after)
        for event in archive:
            if event.get("seq", 0) > last_seq:
                last_seq = event["seq"]
            yield sse_line(event)

        if replay_only and not is_running():
            yield sse_line({**STREAM_DONE, "stream": stream_key,
                            "seq": last_seq})
            return

        # الحي — إسقاط المكرر ثم البث حتى الخاتمة
        idle_timeout = 0.5
        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=idle_timeout
                )
            except asyncio.TimeoutError:
                if not is_running():
                    yield sse_line({**STREAM_DONE, "stream": stream_key,
                                    "seq": last_seq})
                    return
                continue
            seq = event.get("seq", 0)
            if seq and seq <= last_seq:
                continue  # مكرر (سباق الأرشيف/الحي) — لا قطع مضاعفة
            if seq:
                last_seq = seq
            yield sse_line(event)
            kind = event.get("kind", "")
            if kind in done_kinds:
                yield sse_line({**STREAM_DONE, "stream": stream_key,
                                "seq": last_seq})
                return
    finally:
        BUS.unsubscribe(sub_id)


def snapshot_dir_for(cycle_id: str) -> Path:
    return Path("runtime") / "tasks" / cycle_id
