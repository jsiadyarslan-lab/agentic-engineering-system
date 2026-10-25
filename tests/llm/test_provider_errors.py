"""§1 acceptance tests — provider error taxonomy + bounded retry.

AES-FACTORY-RUNTIME-RELIABILITY-001 §4-A:
- real short request succeeds after transient failures,
- simulated failures classify into the §1 taxonomy,
- retry is bounded (≤3) with exponential backoff honoring Retry-After,
- exhaustion is honest: ProviderFailure raises, no fake success,
- API key material never appears in failure payloads.
"""

from __future__ import annotations

import json
import socket
import ssl
import time

import httpx
import pytest

from src.llm.nvidia_provider import NVIDIAProvider
from src.llm.provider import (
    LLMAuthenticationError,
    LLMMessage,
    RetryPolicy,
)
from src.llm.provider_errors import (
    ProviderErrorClass,
    ProviderFailure,
    as_provider_failure,
    classify_exception,
    classify_http_status,
)
from src.llm.retry import execute_with_retry

API_KEY = "test-key-not-a-secret"
OK_BODY = {
    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    "model": "nvidia/nemotron-3-ultra",
}


def _provider(handler, **kw) -> NVIDIAProvider:
    transport = httpx.MockTransport(handler)
    fast = RetryPolicy(max_retries=3, base_delay=0.01, max_delay=0.05, jitter=False)
    return NVIDIAProvider(
        api_key=API_KEY,
        retry_policy=fast,
        transport=transport,
        **kw,
    )


# ---------------------------------------------------------------- taxonomy


def test_classify_connection_refused():
    e = httpx.ConnectError("boom")
    e.__cause__ = ConnectionRefusedError(111, "Connection refused")
    assert classify_exception(e) is ProviderErrorClass.CONNECT_REFUSED


def test_classify_dns_failure():
    e = httpx.ConnectError("boom")
    e.__cause__ = socket.gaierror(-2, "Name or service not known")
    assert classify_exception(e) is ProviderErrorClass.DNS_FAILURE


def test_classify_tls_failure():
    e = httpx.ConnectError("boom")
    e.__cause__ = ssl.SSLError("certificate verify failed")
    assert classify_exception(e) is ProviderErrorClass.TLS_FAILURE


def test_classify_timeout():
    assert classify_exception(httpx.ConnectTimeout("t")) is ProviderErrorClass.REQUEST_TIMEOUT
    assert classify_exception(httpx.ReadTimeout("t")) is ProviderErrorClass.REQUEST_TIMEOUT


def test_classify_http_statuses():
    assert classify_http_status(401) is ProviderErrorClass.AUTH_FAILURE
    assert classify_http_status(403) is ProviderErrorClass.AUTH_FAILURE
    assert classify_http_status(429) is ProviderErrorClass.RATE_LIMITED
    assert classify_http_status(500) is ProviderErrorClass.SERVER_ERROR
    assert classify_http_status(503) is ProviderErrorClass.SERVER_ERROR
    assert classify_http_status(418) is ProviderErrorClass.INVALID_RESPONSE


def test_connection_dropped_mid_call_is_connect_refused():
    # dead egress bridge manifests as read/remote-protocol errors mid-request
    assert classify_exception(httpx.ReadError("dropped")) is ProviderErrorClass.CONNECT_REFUSED
    assert (
        classify_exception(httpx.RemoteProtocolError("server disconnected"))
        is ProviderErrorClass.CONNECT_REFUSED
    )


# ------------------------------------------------------- retry: bounded


@pytest.mark.asyncio
async def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            e = httpx.ConnectError("boom")
            e.__cause__ = ConnectionRefusedError(111, "Connection refused")
            raise as_provider_failure(e)
        return "value"

    events: list[dict] = []
    result = await execute_with_retry(flaky, RetryPolicy(max_retries=3, base_delay=0.01, jitter=False), on_event=events.append)
    assert result == "value"
    assert calls["n"] == 3
    assert len(events) == 2
    assert events[0]["kind"] == "PROVIDER_RETRY"
    assert events[0]["error_class"] == "CONNECT_REFUSED"


@pytest.mark.asyncio
async def test_retry_capped_at_three_and_raises_honestly():
    attempts = {"n": 0}

    async def always_refused():
        attempts["n"] += 1
        e = httpx.ConnectError("boom")
        e.__cause__ = ConnectionRefusedError(111, "Connection refused")
        raise as_provider_failure(e)

    with pytest.raises(ProviderFailure) as info:
        await execute_with_retry(always_refused, RetryPolicy(max_retries=3, base_delay=0.01, jitter=False))
    assert attempts["n"] == 4  # 1 initial + 3 retries (order cap ≤3)
    assert info.value.error_class is ProviderErrorClass.CONNECT_REFUSED


@pytest.mark.asyncio
async def test_non_retryable_auth_fails_immediately():
    attempts = {"n": 0}

    async def auth_fail():
        attempts["n"] += 1
        raise LLMAuthenticationError("Invalid NVIDIA API key")

    with pytest.raises(ProviderFailure) as info:
        await execute_with_retry(auth_fail, RetryPolicy(max_retries=3, base_delay=0.01))
    assert attempts["n"] == 1  # no retry on AUTH_FAILURE
    assert info.value.error_class is ProviderErrorClass.AUTH_FAILURE


@pytest.mark.asyncio
async def test_rate_limit_honors_retry_after():
    async def limited():
        raise ProviderFailure(ProviderErrorClass.RATE_LIMITED, "429", retry_after=0.2)

    start = time.monotonic()
    with pytest.raises(ProviderFailure):
        await execute_with_retry(limited, RetryPolicy(max_retries=1, base_delay=0.01, max_delay=0.02, jitter=False))
    assert (time.monotonic() - start) >= 0.2  # waited at least Retry-After


# ------------------------------------------- provider over mock transport


def test_provider_chat_succeeds_after_5xx_then_ok():
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] < 3:
            return httpx.Response(503, text="upstream busy")
        return httpx.Response(200, json=OK_BODY)

    provider = _provider(handler)
    resp = _run(provider.chat([LLMMessage(role="user", content="ping")]))
    assert resp.content == "ok"
    assert state["n"] == 3
    retries = [e for e in provider.recent_events if e["kind"] == "PROVIDER_RETRY"]
    assert len(retries) == 2
    assert retries[0]["error_class"] == "SERVER_ERROR"


def test_provider_chat_connect_refused_is_classified_and_bounded():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    provider = _provider(handler)
    with pytest.raises(ProviderFailure) as info:
        _run(provider.chat([LLMMessage(role="user", content="ping")]))
    assert info.value.error_class is ProviderErrorClass.CONNECT_REFUSED
    assert provider.last_failure is not None
    assert provider.last_failure.retryable is True
    failures = [e for e in provider.recent_events if e["kind"] == "PROVIDER_FAILURE"]
    assert len(failures) == 1  # final honest failure recorded once
    assert failures[0]["error_class"] == "CONNECT_REFUSED"


def test_provider_401_maps_to_auth_failure_without_retry():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    provider = _provider(handler)
    with pytest.raises(ProviderFailure) as info:
        _run(provider.chat([LLMMessage(role="user", content="ping")]))
    assert info.value.error_class is ProviderErrorClass.AUTH_FAILURE
    assert info.value.attempt == 0


def test_provider_429_maps_to_rate_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0.1"}, text="slow down")

    provider = _provider(handler)
    with pytest.raises(ProviderFailure) as info:
        _run(provider.chat([LLMMessage(role="user", content="ping")]))
    assert info.value.error_class is ProviderErrorClass.RATE_LIMITED
    assert info.value.retry_after == pytest.approx(0.1)


def test_secrets_never_leak_into_failure_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    provider = _provider(handler)
    with pytest.raises(ProviderFailure) as info:
        _run(provider.chat([LLMMessage(role="user", content="ping")]))
    assert API_KEY not in str(info.value)
    assert API_KEY not in json.dumps(provider.recent_events)


def test_structured_chat_retries_then_parses():
    from pydantic import BaseModel as _BM

    class Out(_BM):
        answer: str

    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(500, text="boom")
        body = dict(OK_BODY)
        body["choices"] = [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "t1",
                            "function": {
                                "name": "structured_output",
                                "arguments": json.dumps({"answer": "42"}),
                            },
                        }
                    ],
                }
            }
        ]
        return httpx.Response(200, json=body)

    provider = _provider(handler)
    out = _run(provider.structured_chat([LLMMessage(role="user", content="q")], Out))
    assert out.answer == "42"
    assert state["n"] == 2


# ------------------------------------------------------------- runner


def _run(coro):
    import asyncio

    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)
