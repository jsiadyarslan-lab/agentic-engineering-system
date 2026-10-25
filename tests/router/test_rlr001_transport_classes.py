"""RLR-001 §1-ب — تصنيف نقل المزوّد بفئات الأمر السبع + نافذة الإعادة البيئية.

العقد الحاسم: Connection refused ليس مهلة — فئة صريحة عابرة تُعاد بنافذة
معلنة، وDNS/TLS/AUTH حتمية تُرفع فورًا. لا رسالة نصية يُخمَّن منها.
"""

from __future__ import annotations

import socket
import urllib.error
import urllib.request

import pytest

from router.failover_chain import FailoverChain, _env_config
from router.live_providers import ProviderCallError
from router.provider_response import read_json_response

BASE = "https://provider.test/v1"


def _request() -> urllib.request.Request:
    return urllib.request.Request(f"{BASE}/chat/completions", method="POST")


def _url_error(reason: BaseException) -> urllib.error.URLError:
    return urllib.error.URLError(reason)


# ------------------------------------------------------- classification


def test_connection_refused_is_not_timeout_and_is_retryable(monkeypatch):
    def boom(req, timeout=None):
        raise _url_error(ConnectionRefusedError(111, "Connection refused"))

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(ProviderCallError) as info:
        read_json_response(_request(), timeout=5, base_url=BASE)
    assert info.value.error_class == "CONNECT_REFUSED"
    assert info.value.is_timeout is False
    assert info.value.is_server_error is True  # قابل للإعادة في السلسلة


def test_dns_failure_fails_immediately(monkeypatch):
    def boom(req, timeout=None):
        raise _url_error(socket.gaierror(-2, "Name or service not known"))

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(ProviderCallError) as info:
        read_json_response(_request(), timeout=5, base_url=BASE)
    assert info.value.error_class == "DNS_FAILURE"
    assert info.value.is_timeout is False
    assert info.value.is_server_error is False  # حتمي: لا إعادة


def test_transport_timeout_classified(monkeypatch):
    def boom(req, timeout=None):
        raise socket.timeout("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(ProviderCallError) as info:
        read_json_response(_request(), timeout=5, base_url=BASE)
    assert info.value.error_class == "REQUEST_TIMEOUT"
    assert info.value.is_timeout is True


def test_401_is_auth_failure(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.HTTPError(
            BASE, 401, "Unauthorized", hdrs=None, fp=None
        )

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(ProviderCallError) as info:
        read_json_response(_request(), timeout=5, base_url=BASE)
    assert info.value.error_class == "AUTH_FAILURE"
    assert info.value.code == 401


def test_429_is_rate_limited_with_class(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.HTTPError(
            BASE, 429, "Too Many Requests", hdrs=None, fp=None
        )

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(ProviderCallError) as info:
        read_json_response(_request(), timeout=5, base_url=BASE)
    assert info.value.error_class == "RATE_LIMITED"
    assert info.value.is_throttle is True


def test_500_is_server_error_with_class(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.HTTPError(BASE, 500, "boom", hdrs=None, fp=None)

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(ProviderCallError) as info:
        read_json_response(_request(), timeout=5, base_url=BASE)
    assert info.value.error_class == "SERVER_ERROR"
    assert info.value.is_server_error is True


# ------------------------------------------------- env-tunable window


def test_env_overrides_raise_window_up_to_cap(monkeypatch):
    monkeypatch.setenv("AES_FAILOVER_MAX_RETRIES", "3")
    monkeypatch.setenv("AES_FAILOVER_BACKOFF_BASE", "15")
    cfg = _env_config()
    assert cfg["max_retries"] == 3  # سقف الأمر — لا أكثر
    assert cfg["backoff_base"] == 15.0


def test_env_override_cannot_exceed_cap(monkeypatch):
    monkeypatch.setenv("AES_FAILOVER_MAX_RETRIES", "10")
    cfg = _env_config()
    assert cfg["max_retries"] == 3


def test_chain_uses_env_window_and_emits_retry_events(monkeypatch):
    monkeypatch.setenv("AES_FAILOVER_MAX_RETRIES", "3")
    monkeypatch.setenv("AES_FAILOVER_BACKOFF_BASE", "0.01")

    def refuse(provider):
        raise ProviderCallError(
            "[CONNECT_REFUSED] فشل نقل",
            is_server_error=True,
            error_class="CONNECT_REFUSED",
        )

    events: list[dict] = []
    chain = FailoverChain(["nvidia"], sleeper=lambda s: None, on_event=events.append)
    with pytest.raises(Exception) as info:
        chain.execute_with_failover(refuse)
    retries = [e for e in events if e["kind"] == "provider.retry"]
    assert len(retries) == 3
    assert all(e["error_class"] == "CONNECT_REFUSED" for e in retries)
    assert info.value.failures[0]["attempts"] == 4  # 1 محاولة + 3 إعادات


def test_bridge_gap_window_is_wide_enough(monkeypatch):
    """العقد التشغيلي: base=15 → 15+30+60 = نافذة ~105ث تفوق فجوات الجسر."""
    monkeypatch.setenv("AES_FAILOVER_MAX_RETRIES", "3")
    monkeypatch.setenv("AES_FAILOVER_BACKOFF_BASE", "15")
    waits: list[float] = []
    chain = FailoverChain(["nvidia"], sleeper=waits.append)

    def refuse(provider):
        raise ProviderCallError(
            "[CONNECT_REFUSED] فشل نقل",
            is_server_error=True,
            error_class="CONNECT_REFUSED",
        )

    with pytest.raises(Exception):
        chain.execute_with_failover(refuse)
    assert waits == [15.0, 30.0, 60.0]
    assert sum(waits) >= 100  # تغطية فجوة جلسة التشغيل
