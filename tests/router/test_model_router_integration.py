"""اختبار تكامل الموجّه — سيناريوهات الأمر الثالث القسم 4-4.

الدورة الكاملة في chat() الواحدة:
  rate_limiter.acquire (⏳ عند الرفض) → cooling_loop (🧊 عند 429)
  → failover_chain (🔄 عند 5xx) → النقل (mock)
وحدث router.call.logged الختامي يحمل: provider + model + tokens +
duration + cooled + failed_over.

كل الأزمنة مزيفة (نوم مزيف + ساعة مزيفة) — التسلسل المنطقي هو
المختبر، لا سرعة الساعة.
"""

from __future__ import annotations

from router.cooling_loop import CoolingLoop
from router.failover_chain import FailoverChain
from router.model_router import (
    ChatMessage,
    ModelRouter,
    ProviderCallError,
    RateLimitBlocked,
)
from router.rate_limiter import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


MESSAGES = [ChatMessage(role="user", content="اكتب ملخص سوق الأسهم اليوم")]


def build_router(
    *, limiter_config: dict | None = None, transports: dict, providers
) -> tuple[ModelRouter, list[dict], list[float]]:
    """موجّه بحزم مزيفة الزمن + عدّاد أحداث وعدّاد نوم."""
    events: list[dict] = []
    sleeps: list[float] = []
    clock = FakeClock()
    limiter = RateLimiter(
        {"rpm": 40, "min_interval": 0.0, "cooldown": 60, "concurrency": 1,
         **(limiter_config or {})},
        clock=clock,
    )
    chain = FailoverChain(
        list(providers),
        {"max_retries": 2, "backoff_base": 0.0},
        sleeper=sleeps.append,
        on_event=events.append,
    )
    cooling = CoolingLoop(
        {"cooldown_base": 60, "cooldown_max": 300, "max_waits": 10,
         "budget_seconds": 1800},
        sleeper=sleeps.append,
        on_event=events.append,
    )
    router = ModelRouter(
        rate_limiter=limiter,
        failover_chain=chain,
        cooling_loop=cooling,
        default_provider=providers[0],
        transports=transports,
        on_event=events.append,
        sleeper=sleeps.append,
    )
    return router, events, sleeps


def test_full_cycle_rate_cool_failover_then_mock_call():
    """p1: 429 مرتين (تبريد) ثم 503 دائمًا (استنفاد إعادات) → p2 ينجح."""
    p1_attempts = {"n": 0}

    def p1(model: str, messages) -> str:
        p1_attempts["n"] += 1
        if p1_attempts["n"] <= 2:
            raise ProviderCallError(
                "429 Too Many Requests", code=429, is_throttle=True
            )
        raise ProviderCallError(
            "503 Service Unavailable", code=503, is_server_error=True
        )

    def p2(model: str, messages) -> str:
        return "رد الاحتياطي"

    router, events, sleeps = build_router(
        transports={"p1": p1, "p2": p2}, providers=["p1", "p2"]
    )
    result = router.chat(MESSAGES, provider_id="p1", model="nvidia-free")

    # النتيجة: نجح عبر p2 بعد تبريد وتبدّل — والحقول كلها صادقة
    assert result["text"] == "رد الاحتياطي"
    assert result["provider"] == "p2"
    assert result["model"] == "nvidia-free"
    assert result["cooled"] is True
    assert result["cooling_waits"] == 2
    assert result["failed_over"] is True
    assert result["failover_from"] == "p1"
    assert result["tokens"] >= 1
    assert result["duration_ms"] >= 0
    # p1: محاولتا اختناق + ثلاث محاولات انهيار (محاولة + إعادتان)
    assert p1_attempts["n"] == 5

    kinds = [e["kind"] for e in events]
    assert kinds.count("cooling.cooldown") == 2  # 60 ثم 120
    assert kinds.count("failover.logged") == 1   # p1 → p2
    assert kinds[-1] == "router.call.logged"     # الختامي أخيرًا دائمًا


def test_router_call_logged_contains_all_required_fields():
    """حدث router.call.logged: provider + model + tokens + duration +
    cooled + failed_over — بالنص الحرفي الذي طلبته المواصفة."""
    def ok_transport(model: str, messages) -> str:
        return "رد فوري من mock"

    router, events, _sleeps = build_router(
        transports={"mock": ok_transport}, providers=["mock"]
    )
    result = router.chat(MESSAGES, provider_id="mock", model="mock-v2")

    logged = next(
        e for e in events if e["kind"] == "router.call.logged"
    )
    for field in (
        "provider", "model", "tokens", "duration_ms", "cooled",
        "failed_over",
    ):
        assert field in logged  # الحقول الستة المطلوبة حرفيًا
    assert logged["provider"] == "mock"
    assert logged["cooled"] is False and logged["failed_over"] is False
    assert result["text"] == "رد فوري من mock"


def test_rate_limit_wait_event_when_min_interval_refuses():
    """رفض acquire → حدث ⏳ rate_limit.wait → نوم → إعادة فحص ناجحة.

    فاصل أدني حقيقي صغير (0.05ث) وساعة حقيقية: الانتظار هنا زمن فعلي
    قصير — السيناريو يختبر بوابة الانتظار لا سرعتها.
    """
    events: list[dict] = []
    limiter = RateLimiter(
        {"rpm": 40, "min_interval": 0.05, "cooldown": 60}
    )
    router = ModelRouter(
        rate_limiter=limiter,
        failover_chain=FailoverChain(
            ["mock"], {"max_retries": 2, "backoff_base": 0}
        ),
        cooling_loop=CoolingLoop(
            {"cooldown_base": 60, "cooldown_max": 300, "max_waits": 10,
             "budget_seconds": 1800}
        ),
        default_provider="mock",
        on_event=events.append,
    )

    first = router.chat(MESSAGES, provider_id="mock", model="m")
    assert first["provider"] == "mock"

    second = router.chat(MESSAGES, provider_id="mock", model="m")
    assert second["provider"] == "mock"
    waits = [e for e in events if e["kind"] == "rate_limit.wait"]
    assert len(waits) == 1  # الاستدعاء الثاني انتظر الفاصل الأدنى
    assert waits[0]["provider"] == "mock"
    assert waits[0]["wait_seconds"] > 0
    # مسار النجاح بعد الانتظار: لا حجب ولا خطأ
    assert second["text"].startswith("[mock:")


def test_rate_limit_blocked_after_bounded_waits():
    """حد المعدل مرفوع دائمًا (تبريد 429 لا ينقضي) → RateLimitBlocked."""
    clock = FakeClock()
    sleeps: list[float] = []
    limiter = RateLimiter(
        {"rpm": 40, "min_interval": 0.0, "cooldown": 600},
        clock=clock,
    )
    limiter.note_429("mock")  # تبريد لا ينقضي (الساعة لا تتقدم)
    router = ModelRouter(
        rate_limiter=limiter,
        default_provider="mock",
        sleeper=sleeps.append,
        max_rate_waits=3,
    )

    try:
        router.chat(MESSAGES, provider_id="mock", model="m")
        raised = False
    except RateLimitBlocked:
        raised = True
    assert raised, "الاستدعاء كان يجب أن يُحجب بعد انتظارات محدودة"
    assert len(sleeps) == 3  # انتظر ثلاث مرات ثم استسلم صراحة


def test_default_construction_uses_provider_settings():
    """بناء بلا حقن: الحزم تُبنى من ProviderConfig — القيم الحرفية للأمر."""
    from core.config import provider_settings

    router = ModelRouter()
    assert router._cooling.config["cooldown_base"] == (
        provider_settings.cooling_base_seconds
    )
    assert router._failover.config["max_retries"] == (
        provider_settings.failover_max_retries
    )
    assert router._limiter._default["rpm"] == provider_settings.default_rpm
