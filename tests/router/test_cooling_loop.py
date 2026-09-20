"""اختبار حلقة التبريد — سيناريوهات الأمر الثالث القسم 4-3.

1) مزود يعيد 429 ثلاث مرات → التبريد ينتظر 60/120/240 → نجاح في الرابعة.
2) ميزانية الانتظار مستنفدة → CoolingBudgetExhausted.
3) حد مرات الانتظار (10) مستنفد → CoolingBudgetExhausted.
4) غير الاختناقي يُرفع فورًا — التبدّل يملكه.
5) رأس Retry-After يحترمه التبريد (سلوك v1 حرفيًا).

النوم قابل للحقن: المتتالية 60←120←240←300 تُقاس كأرقام لا كزمن
فعلي — الرياضيات نفسها التي في v1 (‎_throttle_cool).
"""

from __future__ import annotations

import pytest

from router.cooling_loop import CoolingBudgetExhausted, CoolingLoop


class Throttled(Exception):
    """429 — إشارة اختناق."""

    is_throttle = True

    def __init__(self, reason: str = "429 Too Many Requests",
                 retry_after: int | None = None) -> None:
        super().__init__(reason)
        self.retry_after = retry_after


class ServerDown(Exception):
    """503 غير الاختناقي — ملك التبدّل."""

    is_server_error = True


def make_loop(**config) -> tuple[CoolingLoop, list]:
    waits: list[float] = []
    loop = CoolingLoop(
        {
            "cooldown_base": 60,
            "cooldown_max": 300,
            "max_waits": 10,
            "budget_seconds": 1800,
            **config,
        },
        sleeper=waits.append,
    )
    return loop, waits


def test_429_three_times_waits_60_120_240_then_success():
    """المتتالية الأسيّة الحرفية من v1: 60 ← 120 ← 240 ثم نجاح."""
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] <= 3:
            raise Throttled()
        return "نجاح بعد الصبر"

    loop, waits = make_loop()
    result = loop.execute_with_cooling(flaky)

    assert result == "نجاح بعد الصبر"
    assert attempts["n"] == 4  # نجاح في المحاولة الرابعة
    assert waits == [60.0, 120.0, 240.0]  # السيناريو نصّ عليها حرفيًا
    assert loop.last_execution == {
        "cooled": True, "waits": 3, "waited_seconds": 420.0
    }
    cooldown_events = [e for e in loop.events if e["kind"] == "cooling.cooldown"]
    assert [(e["wait_s"], e["attempt"]) for e in cooldown_events] == [
        (60.0, 1), (120.0, 2), (240.0, 3),
    ]


def test_budget_exhausted_raises_cooling_budget_exhausted():
    """مزود يختنق دائمًا: التبريد يتصاعد حتى يتجاوز الميزانية فيتوقف."""
    calls = {"n": 0}

    def always_throttled() -> str:
        calls["n"] += 1
        raise Throttled()

    loop, waits = make_loop()
    with pytest.raises(CoolingBudgetExhausted) as excinfo:
        loop.execute_with_cooling(always_throttled)

    # 60+120+240+300×7 = 2520 > 1800 → الاستنفاد بعد 7 انتظارات:
    # المتبقي بعد السابع = 1800−1620 = 180 < 300 المطلوبة للتالي
    assert len(waits) == 7
    assert sum(waits) == 1620.0
    assert excinfo.value.waits == 7
    assert excinfo.value.waited_seconds == 1620.0
    assert calls["n"] == 8  # 7 محاولات مختنقة + المحاولة التي رفض تبريدها


def test_max_waits_exhausted_raises_cooling_budget_exhausted():
    """حد الانتظارات (10) يسبق الميزانية عندما تكون الميزانية واسعة."""
    def always_throttled() -> str:
        raise Throttled()

    loop, waits = make_loop(budget_seconds=100_000)
    with pytest.raises(CoolingBudgetExhausted) as excinfo:
        loop.execute_with_cooling(always_throttled)

    assert len(waits) == 10  # 60، 120، 240، ثم 300 سبع مرات
    assert waits[:3] == [60.0, 120.0, 240.0]
    assert waits[3:] == [300.0] * 7
    assert excinfo.value.waits == 10


def test_non_throttle_error_raises_immediately():
    """503 لا يدخل التبريد أبدًا — يُرفع فورًا للسلسلة (لا انتظار مزدوج)."""

    def broken() -> str:
        raise ServerDown("503 Service Unavailable")

    loop, waits = make_loop()
    with pytest.raises(ServerDown):
        loop.execute_with_cooling(broken)
    assert waits == []


def test_retry_after_header_is_respected():
    """رأس Retry-After يعلو على التصعيد الأسي (v1: wait = retry_after)."""
    attempts = {"n": 0}

    def with_header() -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise Throttled(retry_after=7)
        return "ok"

    loop, waits = make_loop(cooldown_max=300)
    assert loop.execute_with_cooling(with_header) == "ok"
    assert waits == [7.0]


def test_retry_after_capped_at_cooldown_max():
    """Retry-After يتقلص إلى سقف التبريد — لا انتظار أعمى (v1 حرفيًا)."""
    attempts = {"n": 0}

    def huge_header() -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise Throttled(retry_after=900)
        return "ok"

    loop, waits = make_loop(cooldown_max=300)
    assert loop.execute_with_cooling(huge_header) == "ok"
    assert waits == [300.0]  # السقف يقلص 900 إلى 300
