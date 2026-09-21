"""باثر أحداث الدورة — نُقل من المنسق (الأمر 004) ليظل تحت سقف 800.

نقطة الاستقبال (sink) تُستدعى لحظة الحدوث؛ الحدث محفوظ في القائمة
مهما فشل المستقبِل. حقل state يحمل الحالة الصادقة للدور صاحب الحدث
(أو الحكم الفرعي NOT_EVIDENCED/STAGNANT) — لا حالة الخطة بالضرورة.
"""

from __future__ import annotations

from typing import Callable


class CycleEventEmitter:
    """باثر أحداث الدورة — تسلسل + حفظ + بث فوري لمستقبِل خارجي."""

    def __init__(self, cycle_id: str, on_event: Callable[[dict], None] | None):
        self.cycle_id = cycle_id
        self._on_event = on_event
        self._seq = 0
        self.events: list[dict] = []

    def emit(
        self,
        *,
        role: str,
        kind: str,
        state: str | None = None,
        text: str = "",
        duration_ms: int = 0,
        details: dict | None = None,
    ) -> dict:
        self._seq += 1
        event = {
            "seq": self._seq,
            "cycle_id": self.cycle_id,
            "role": role,
            "kind": kind,
            "state": state,
            "text": text,
            "duration_ms": duration_ms,
            "details": details or {},
        }
        self.events.append(event)
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:  # noqa: BLE001 — نقطة الاستقبال لا تكسر الدورة
                pass  # الحدث محفوظ في القائمة مهما فشل المستقبِل
        return event
