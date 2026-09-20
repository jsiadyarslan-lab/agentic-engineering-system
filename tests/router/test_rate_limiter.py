"""اختبار محدد المعدل — سيناريوهات الأمر الثالث القسم 4-1.

1) 50 طلبًا في الدقيقة → 40 ناجحًا و10 انتظارًا (wait_seconds > 0).
2) concurrency=1 → طلبان متوازيان → الثاني ينتظر على الإشارة.
3) النافذة المنزلقة: بعد 60 ثانية تعود الطلبات للعمل.

الساعة قابلة للحقن: الخوارزمية نفسها تعمل بلا نوم حقيقي — تقديم
الزمن يُثبت سلوك النافذة دون تسريع أي فحص.
"""

from __future__ import annotations

import threading

from router.rate_limiter import RateLimiter


class FakeClock:
    """ساعة رتيبة قابلة للتقديم — تُحقن في RateLimiter."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_limiter(**overrides) -> tuple[RateLimiter, FakeClock]:
    clock = FakeClock()
    config = {
        "rpm": 40,
        "tpm": 0,
        "min_interval": 0.0,
        "cooldown": 60,
        "concurrency": 1,
        **overrides,
    }
    return RateLimiter(config, clock=clock), clock


def test_burst_of_50_forty_allowed_ten_wait():
    """نافذة نفيديا المجانية: 50 طلبًا متتاليًا → 40 مسموحًا و10 رفضًا."""
    limiter, _clock = make_limiter()
    results = [limiter.acquire("nvidia", 1000) for _ in range(50)]
    allowed = [ok for ok, _ in results if ok]
    rejected_waits = [w for ok, w in results if not ok]
    assert len(allowed) == 40
    assert len(rejected_waits) == 10
    assert all(w > 0 for w in rejected_waits)  # السيناريو نصّ عليها حرفيًا


def test_sliding_window_recovers_after_60_seconds():
    """النافذة منزلقة لا ثابتة: أقدم طلب يحرر مكانه بعد 60 ثانية."""
    limiter, clock = make_limiter()
    for _ in range(40):
        assert limiter.acquire("nvidia", 1000)[0] is True
    assert limiter.acquire("nvidia", 1000)[0] is False  # ممتلئة

    clock.advance(60.5)  # مرور دقيقة كاملة — النافذة تفرغ
    ok, wait = limiter.acquire("nvidia", 1000)
    assert ok is True and wait == 0.0
    assert limiter.status("nvidia")["requests_last_minute"] == 1


def test_concurrency_one_makes_second_parallel_call_wait():
    """concurrency=1: إشارة لكل مزود — الثاني ينتظر حتى يفرج الأول."""
    limiter, _clock = make_limiter()
    acquired = threading.Event()
    release = threading.Event()

    def hold_slot() -> None:
        limiter.acquire_slot("nvidia", timeout=5.0)
        acquired.set()  # الحامل انتزع الفتحة فعلًا
        release.wait(timeout=5.0)
        limiter.release_slot("nvidia")

    holder = threading.Thread(target=hold_slot)
    holder.start()
    assert acquired.wait(timeout=5.0)

    # المنافس: مهلة قصيرة → لا فتحة خلالها → (False, ~timeout)
    got, waited = limiter.acquire_slot("nvidia", timeout=0.3)
    assert got is False and waited >= 0.2

    release.set()
    holder.join(timeout=5.0)
    # بعد التحرير: الفتحة متاحة فورًا
    got2, _waited2 = limiter.acquire_slot("nvidia", timeout=1.0)
    assert got2 is True
    limiter.release_slot("nvidia")


def test_note_429_forces_cooldown_then_recovers():
    """429 فعلية → تبريد إجباري كامل يرفض acquire ثم يزول بمروره."""
    limiter, clock = make_limiter()
    assert limiter.acquire("nvidia", 1000)[0] is True
    cooldown = limiter.note_429("nvidia")
    assert cooldown == 60.0

    ok, wait = limiter.acquire("nvidia", 1000)
    assert ok is False and 59.0 < wait <= 60.0  # التبريد أولًا وقبل كل شيء

    clock.advance(61.0)  # انقضى التبريد
    ok2, wait2 = limiter.acquire("nvidia", 1000)
    assert ok2 is True and wait2 == 0.0
    assert limiter.status("nvidia")["total_429"] == 1


def test_min_interval_enforces_gap_between_requests():
    """الفاصل الأدنى (1.5 ثانية لنفيديا في v1): الطلب المبكر يُرفض."""
    limiter, clock = make_limiter(rpm=0, min_interval=1.5)
    assert limiter.acquire("nvidia", 1000) == (True, 0.0)
    ok, wait = limiter.acquire("nvidia", 1000)
    assert ok is False and 0.0 < wait <= 1.5
    clock.advance(1.5)  # انقضى الفاصل
    assert limiter.acquire("nvidia", 1000) == (True, 0.0)


def test_unlimited_provider_passes_without_limits():
    """مزود بلا حدود (mock): صفر rpm/interval/tpm → تسليم دائمًا."""
    limiter, _clock = make_limiter(rpm=0, min_interval=0.0, cooldown=0)
    for _ in range(60):
        assert limiter.acquire("mock", 1000) == (True, 0.0)
