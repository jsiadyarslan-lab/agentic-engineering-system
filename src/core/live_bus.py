"""ناقل الأحداث الحي (الأمر 008 §17-§19+§42) — الفصل المعماري.

    Workflow/Chat Event → Event Store (events) → Live Event Bus → SSE
                                                            → UI Projection

التنفيذ (خيط عامل واحد أو أكثر) ينشر حدثًا واحدًا؛ الناقل يوزعه على
كل مشترك SSE حي (asyncio queue لكل اتصال عبر call_soon_threadsafe) —
فانقطاع اتصال المالك لا يوقف التنفيذ (§33-§34)، والعودة تعيد التشغيل
من جدول events الدائم عبر بعد- seq (§19: replay لا إعادة من الصفر).

العقد الموحد (§17): كل حدث يحمل event_id/timestamp/seq/stream/role/
kind/status/text/details — normalize_event يرقّق أي حدث قديم إلى هذا
الشكل دون كسر الموجود.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import threading
import uuid
from typing import Any


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def normalize_event(event: dict, *, stream: str = "") -> dict:
    """توحيد غلاف الحدث (§17) — متوافق رجعيًا مع كل الأحداث القائمة.

    state القديم يبقى (الواجهة الحالية تقرؤه) ويُضاف status الموحد.
    """
    out = dict(event)
    out.setdefault("event_id", f"evt-{uuid.uuid4().hex[:12]}")
    out.setdefault("timestamp", _now_iso())
    out.setdefault("cycle_id", stream)
    out.setdefault("stream", stream or out.get("cycle_id", ""))
    out.setdefault("seq", 0)
    out.setdefault("role", "system")
    out.setdefault("kind", "event")
    out.setdefault("status", out.get("state") or "OK")
    out.setdefault("text", "")
    out.setdefault("duration_ms", 0)
    details = out.get("details")
    if not isinstance(details, dict):
        # حمولة الحدث الخام (كل الحقول غير القياسية) داخل details
        standard = {
            "event_id", "timestamp", "cycle_id", "stream", "seq", "role",
            "kind", "status", "state", "text", "details", "duration_ms",
        }
        extra = {k: v for k, v in out.items() if k not in standard}
        out["details"] = {**(details or {}), **extra}
    return out


class LiveEventBus:
    """ناقل أحداث خيط-آمن — مشتركو SSE يُوقظون لحظة النشر.

    المشترك يسجل (stream_key, loop, queue)؛ publish من أي خيط يصل كل
    مشترك في stream عبر call_soon_threadsafe — لا حجب للناشر أبدًا.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[int, dict] = {}
        self._next_id = 0

    def subscribe(self, stream_key: str, loop: asyncio.AbstractEventLoop,
                  queue: asyncio.Queue) -> int:
        """تسجيل مشترك — يعيد معرفه للإلغاء."""
        with self._lock:
            self._next_id += 1
            sub_id = self._next_id
            self._subscribers[sub_id] = {
                "stream": stream_key, "loop": loop, "queue": queue,
            }
            return sub_id

    def unsubscribe(self, sub_id: int) -> None:
        with self._lock:
            self._subscribers.pop(sub_id, None)

    def publish(self, event: dict) -> None:
        """نشر حدث لكل مشترك في تياره — مستقبِل فاشل لا يكسر النشر."""
        stream = str(event.get("stream") or event.get("cycle_id") or "")
        with self._lock:
            targets = [
                (sub["loop"], sub["queue"])
                for sub in self._subscribers.values()
                if sub["stream"] == stream
            ]
        for loop, queue in targets:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:  # حلقة مغلقة — اشتراك ميت
                pass

    def subscriber_count(self, stream_key: str | None = None) -> int:
        with self._lock:
            if stream_key is None:
                return len(self._subscribers)
            return sum(
                1 for s in self._subscribers.values()
                if s["stream"] == stream_key
            )


#: الناقل العمومي الوحيد للعملية — كل المسارات الحية تنشر عبره.
BUS = LiveEventBus()


def publish_task_event(on_event: Any, event: dict, *,
                       seq_box: dict | None = None,
                       persist=None) -> dict:
    """مسار النشر الموحد: تسلسل ← تغليف ← دائمة ← ناقل حي.

    seq_box: عداد تسلسل الخيط ({"n": 0}) — كل تيار يملك عداده.
    persist: دالة تسجيل دائمة (جدول events) — فشلها لا يكسر البث.
    """
    if seq_box is not None:
        seq_box["n"] += 1
        event = {**event, "seq": event.get("seq") or seq_box["n"]}
    envelope = normalize_event(event)
    if persist is not None:
        try:
            persist(envelope)
        except Exception:  # noqa: BLE001 — الدائمة لا تكسر الحي
            pass
    BUS.publish(envelope)
    try:  # مراقبة (009 §32) — لا تكسر البث أبدًا
        from readiness import metrics  # noqa: PLC0415

        metrics.count_event_published()
    except Exception:  # noqa: BLE001
        pass
    if on_event is not None:
        try:
            on_event(envelope)
        except Exception:  # noqa: BLE001
            pass
    return envelope
