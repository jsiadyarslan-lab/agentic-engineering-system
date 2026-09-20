"""اختبار سلسلة التبدّل — سيناريوهات الأمر الثالث القسم 4-2.

1) مزود أساسي يعيد 503 → استنفاد الإعادات (محاولة + إعادتان — مطابق
   لـ retries_on_5xx=2 في v1) → تبدّل للثاني → نجاح + حدث failover.logged.
2) مهلة المزود الأساسي → تبدّل للثاني → نجاح.
3) كل الأعضاء يفشلون → FailoverExhausted بتقرير لكل عضو.
4) الاختناق (429) يُرفع فورًا بلا إعادة — حلقة التبريد وحدها تملكه.

الأخطاء صنف اختباري بطرفية (is_throttle/is_server_error/is_timeout)
لتوثيق عقد التصنيف الذي تقرؤه الحزم duck-typing من أي استثناء.
"""

from __future__ import annotations

import pytest

from router.failover_chain import FailoverChain, FailoverExhausted


class ServerDown(Exception):
    """503 — خطأ خادم قابل للإعادة."""

    is_server_error = True


class GatewayTimeout(Exception):
    """انتهت مهلة الاتصال."""

    is_timeout = True


class Throttled(Exception):
    """429 — اختناق: ملك حلقة التبريد لا السلسلة."""

    is_throttle = True


class AuthRejected(Exception):
    """401 — خطأ عميل حتمي: مصنّف صراحةً بلا إعادة ولا تبدّل."""

    is_throttle = False
    is_server_error = False
    is_timeout = False


def make_chain(providers, **config) -> tuple[FailoverChain, list]:
    """سلسلة بنوم مزفي (عدّاد التراجع) — بلا أي انتظار حقيقي."""
    waits: list[float] = []
    chain = FailoverChain(
        providers,
        {"max_retries": 2, "backoff_base": 2.0, **config},
        sleeper=waits.append,
    )
    return chain, waits


def test_primary_503_exhausts_retries_then_switches():
    """الأساسي ينهار 503: ثلاث محاولات (1+إعادتان) ثم تبدّل وناجح."""
    calls: list[str] = []

    def dispatch(provider: str) -> str:
        calls.append(provider)
        if provider == "primary":
            raise ServerDown("503 Service Unavailable")
        return "ok-backup"

    chain, waits = make_chain(["primary", "backup"])
    result = chain.execute_with_failover(dispatch)

    assert result == "ok-backup"
    assert calls.count("primary") == 3  # المحاولة + إعادتان (retries_on_5xx=2)
    assert calls.count("backup") == 1
    assert waits == [2.0, 4.0]  # تراجع أُسّي: base × 2^(n-1)
    assert chain.last_execution["failed_over"] is True
    assert chain.last_execution["provider"] == "backup"


def test_primary_timeout_switches_to_backup():
    """مهلة الأساسي تُعامل كخطأ خادم: إعادات ثم تبدّل."""

    def dispatch(provider: str) -> str:
        if provider == "primary":
            raise GatewayTimeout("انتهت مهلة الاتصال بعد 120 ثانية")
        return "ok-after-timeout"

    chain, _waits = make_chain(["primary", "backup"])
    assert chain.execute_with_failover(dispatch) == "ok-after-timeout"
    assert chain.last_execution["failed_over"] is True


def test_all_providers_fail_raises_failover_exhausted():
    """استنفاد السلسلة كاملة → استثناء بتقرير يذكر كل عضو وسببه."""
    attempts: dict[str, int] = {"a": 0, "b": 0, "c": 0}

    def dispatch(provider: str) -> str:
        attempts[provider] += 1
        raise ServerDown(f"503 من {provider}")

    chain, _waits = make_chain(["a", "b", "c"])
    with pytest.raises(FailoverExhausted) as excinfo:
        chain.execute_with_failover(dispatch)

    message = str(excinfo.value)
    for member in ("a", "b", "c"):
        assert member in message  # التقرير يذكر كل عضو
        assert attempts[member] == 3  # كل عضو أخذ محاولته وإعادتيه
    assert excinfo.value.failures[0]["provider"] == "a"
    assert len(excinfo.value.failures) == 3


def test_throttle_propagates_immediately_without_retry():
    """429 لا يُعاد ولا يُبدَّل — يُرفع فورًا لحلقة التبريد (لا انتظار مزدوج)."""
    calls: list[str] = []

    def dispatch(provider: str) -> str:
        calls.append(provider)
        raise Throttled("429 Too Many Requests")

    chain, waits = make_chain(["primary", "backup"])
    with pytest.raises(Throttled):
        chain.execute_with_failover(dispatch)

    assert calls == ["primary"]  # محاولة واحدة فقط — ولا تبدّل للثاني
    assert waits == []  # ولا أي تراجع


def test_client_error_propagates_immediately():
    """خطأ العميل (401) حتمي: لا إعادة ولا تبدّل — يُرفع فورًا."""
    calls: list[str] = []

    def dispatch(provider: str) -> str:
        calls.append(provider)
        raise AuthRejected("401 Unauthorized")

    chain, _waits = make_chain(["primary", "backup"])
    with pytest.raises(AuthRejected):
        chain.execute_with_failover(dispatch)
    assert calls == ["primary"]


def test_failover_logged_event_is_recorded():
    """حدث failover.logged يحمل (من، إلى، السبب) — يُسجَّل دائمًا."""
    received: list[dict] = []

    def dispatch(provider: str) -> str:
        if provider == "primary":
            raise ServerDown("503 Service Unavailable")
        return "ok"

    chain = FailoverChain(
        ["primary", "backup"],
        {"max_retries": 0, "backoff_base": 0.0},
        sleeper=lambda _s: None,
        on_event=received.append,
    )
    chain.execute_with_failover(dispatch)

    assert len(received) == 1
    event = received[0]
    assert event["kind"] == "failover.logged"
    assert event["from"] == "primary"
    assert event["to"] == "backup"
    assert "503" in event["reason"]
    assert chain.events == received  # السجل الداخلي والمستقبِل متطابقان
