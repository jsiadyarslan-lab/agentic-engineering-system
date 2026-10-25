"""اختبارات RLR-001 §4-أ — عقد تصنيف مزود النموذج (وحدة، بلا شبكة خارجية).

الغاية: كل صنف من السبعة (CONNECT_REFUSED / DNS_FAILURE / TLS_FAILURE /
AUTH_FAILURE / RATE_LIMITED / REQUEST_TIMEOUT / INVALID_RESPONSE)
يثبت بسلوك حقيقي قابل للتكرار، وتثبت سياسة الإعادة المحدودة (3
محاولات بتراجع تصاعدي) وأن الأسرار لا تسريب في رسائل الفشل.
"""
from __future__ import annotations

import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

try:
    from router.provider_response import (
        classify_network_error,
        read_json_response,
    )
    from router.live_providers import ProviderCallError
    from router.call_tracker import (
        TRANSIENT_PROVIDER_CLASSES,
        classify_failure,
        is_transient_provider_failure,
    )
    from router.failover_chain import FailoverChain, _is_retryable
except ImportError:  # تشغيل مباشر خارج conftest
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from router.provider_response import (
        classify_network_error,
        read_json_response,
    )
    from router.live_providers import ProviderCallError
    from router.call_tracker import (
        TRANSIENT_PROVIDER_CLASSES,
        classify_failure,
        is_transient_provider_failure,
    )
    from router.failover_chain import FailoverChain, _is_retryable


@pytest.fixture(autouse=True)
def _no_proxy_direct_connections():
    """حسم البيئة: كل اتصالات الاختبار مباشرة بلا وسيط — حتمية."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    urllib.request.install_opener(opener)
    yield
    urllib.request.install_opener(None)


# ------------------------------------------------------------ #
# أدوات — خادم HTTP محلي مصغّر (لا شبكة خارجية إطلاقًا)
# ------------------------------------------------------------ #

def _serve(handler_cls: type) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


class _Status(BaseHTTPRequestHandler):
    code = 200
    body = b'{"choices":[{"message":{"content":"ok"}}]}'
    stall_s = 0.0

    def do_POST(self):  # noqa: N802 — عقد http.server
        if self.stall_s:
            time.sleep(self.stall_s)
            return
        self.send_response(self.code)
        self.send_header("Content-Type", "application/json")
        if self.code == 429:
            self.send_header("Retry-After", "1")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):  # صمت — لا سجلات في الاختبار
        pass


def _post(url: str, timeout: float = 3.0):
    request = urllib.request.Request(
        url + "/chat/completions",
        data=b'{"model":"m","messages":[]}',
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer aes-rlr-test-secret"},
        method="POST",
    )
    return read_json_response(request, timeout, url)


# ------------------------------------------------------------ #
# الأصناف السبعة — سلوك حقيقي
# ------------------------------------------------------------ #

def test_connect_refused_is_not_timeout():
    """منفذ ميت = CONNECT_REFUSED عابر — ليس MODEL_TIMEOUT كاذب."""
    err = classify_network_error(
        urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")),
        "http://x/v1",
    )
    assert err.error_class == "CONNECT_REFUSED"
    assert err.is_transient is True
    assert err.is_timeout is False
    assert _is_retryable(err) is True


def test_dns_failure():
    err = classify_network_error(
        urllib.error.URLError(socket.gaierror(-2, "Name or service not known")),
        "http://x/v1",
    )
    assert err.error_class == "DNS_FAILURE"
    assert _is_retryable(err) is False  # قاتل داخل النداء — لا عمى


def test_tls_failure():
    err = classify_network_error(
        urllib.error.URLError(
            ssl.SSLCertVerificationError("certificate verify failed")),
        "https://x/v1",
    )
    assert err.error_class == "TLS_FAILURE"
    assert _is_retryable(err) is False


def test_request_timeout_is_transient():
    err = classify_network_error(TimeoutError("timed out"), "http://x/v1")
    assert err.error_class == "REQUEST_TIMEOUT"
    assert err.is_transient is True
    assert _is_retryable(err) is True


def test_real_connect_refused_over_socket():
    """ميناء مغلق فعلًا على الحلقة المحلية — السلوك لا النمو فقط."""
    with pytest.raises(ProviderCallError) as ei:
        _post("http://127.0.0.1:1")  # منفذ 1: رفض شبه مؤكد
    assert ei.value.error_class == "CONNECT_REFUSED"


def test_real_request_timeout_over_stalling_server():
    class _Stall(_Status):
        stall_s = 0.6

    server, url = _serve(_Stall)
    try:
        with pytest.raises(ProviderCallError) as ei:
            _post(url, timeout=0.2)
        assert ei.value.error_class == "REQUEST_TIMEOUT"
        assert ei.value.is_transient is True
    finally:
        server.shutdown()


def test_auth_failure_401_not_retried():
    class _Unauth(_Status):
        code = 401
        body = b'{"error":"invalid api key"}'

    server, url = _serve(_Unauth)
    try:
        with pytest.raises(ProviderCallError) as ei:
            _post(url)
        assert ei.value.error_class == "AUTH_FAILURE"
        assert _is_retryable(ei.value) is False
    finally:
        server.shutdown()


def test_rate_limited_429():
    class _Throttle(_Status):
        code = 429
        body = b'{"error":"rate limited"}'

    server, url = _serve(_Throttle)
    try:
        with pytest.raises(ProviderCallError) as ei:
            _post(url)
        assert ei.value.error_class == "RATE_LIMITED"
        assert ei.value.is_throttle is True
        assert ei.value.retry_after == 1
    finally:
        server.shutdown()


def test_server_error_500_retryable():
    class _Boom(_Status):
        code = 500
        body = b'{"error":"boom"}'

    server, url = _serve(_Boom)
    try:
        with pytest.raises(ProviderCallError) as ei:
            _post(url)
        assert ei.value.error_class == "SERVER_ERROR"
        assert ei.value.is_server_error is True
        assert _is_retryable(ei.value) is True
    finally:
        server.shutdown()


def test_invalid_response_400():
    class _Bad(_Status):
        code = 400
        body = b'{"error":"bad request"}'

    server, url = _serve(_Bad)
    try:
        with pytest.raises(ProviderCallError) as ei:
            _post(url)
        assert ei.value.error_class == "INVALID_RESPONSE"
        assert _is_retryable(ei.value) is False
    finally:
        server.shutdown()


# ------------------------------------------------------------ #
# تمرير التصنيف عبر call_tracker + سياسة الإعادة المحدودة
# ------------------------------------------------------------ #

def test_classify_failure_passthrough_explicit_class():
    err = ProviderCallError("رفض اتصال مع x", error_class="CONNECT_REFUSED")
    error_class, _ = classify_failure(err)
    assert error_class == "CONNECT_REFUSED"
    assert is_transient_provider_failure(error_class) is True


def test_classify_failure_urerror_refused_not_timeout():
    error_class, _ = classify_failure(
        urllib.error.URLError(ConnectionRefusedError(111, "refused")))
    assert error_class == "CONNECT_REFUSED"


def test_transient_classes_contract():
    """الأصناف العابرة الخمسة موثقة — الأصناف القاتلة خارجها."""
    assert TRANSIENT_PROVIDER_CLASSES == frozenset({
        "CONNECT_REFUSED", "REQUEST_TIMEOUT", "SERVER_ERROR",
        "RATE_LIMITED", "NETWORK_UNREACHABLE",
    })
    for fatal in ("DNS_FAILURE", "TLS_FAILURE", "AUTH_FAILURE",
                  "INVALID_RESPONSE"):
        assert is_transient_provider_failure(fatal) is False


def test_failover_retries_transient_max_three():
    """عابر: محاولة أولى + إعادتان = 3 محاولات ثم نجاح — بلا لانهاية."""
    chain = FailoverChain(["a"], config={"max_retries": 2,
                                         "backoff_base": 0.0},
                          sleeper=lambda _s: None)
    calls = {"n": 0}

    def fn(_provider):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderCallError("رفض اتصال",
                                    error_class="CONNECT_REFUSED",
                                    is_transient=True)
        return "ok"

    assert chain.execute_with_failover(fn) == "ok"
    assert calls["n"] == 3


def test_failover_auth_fails_fast():
    """مصادقة مرفوضة: محاولة واحدة — لا حرق ميزانية إعادة عبثًا."""
    chain = FailoverChain(["a"], config={"max_retries": 2,
                                         "backoff_base": 0.0},
                          sleeper=lambda _s: None)
    calls = {"n": 0}

    def fn(_provider):
        calls["n"] += 1
        raise ProviderCallError("401 فشل مصادقة", error_class="AUTH_FAILURE")

    with pytest.raises(ProviderCallError):
        chain.execute_with_failover(fn)
    assert calls["n"] == 1


def test_failover_exhausted_reports_each_attempt():
    """استنفاد السلسلة = تقرير صريح بعدد المحاولات والسبب المصنف."""
    chain = FailoverChain(["a"], config={"max_retries": 2,
                                         "backoff_base": 0.0},
                          sleeper=lambda _s: None)

    def fn(_provider):
        raise ProviderCallError("رفض اتصال",
                                error_class="CONNECT_REFUSED",
                                is_transient=True)

    with pytest.raises(RuntimeError) as ei:
        chain.execute_with_failover(fn)
    assert "CONNECT_REFUSED" in str(ei.value) or "3 محاولة" in str(ei.value)


# ------------------------------------------------------------ #
# §4-أ (الأخيرة) — الأسرار لا تسريب في رسائل الفشل
# ------------------------------------------------------------ #

def test_secrets_never_in_error_messages():
    """مفتاح النقل لا يظهر أبدًا في نص ProviderCallError/SJL الفشل."""
    class _Unauth(_Status):
        code = 401
        body = b'{"error":"denied"}'

    server, url = _serve(_Unauth)
    try:
        with pytest.raises(ProviderCallError) as ei:
            _post(url)
        assert "aes-rlr-test-secret" not in str(ei.value)
        assert "aes-rlr-test-secret" not in repr(ei.value)
    finally:
        server.shutdown()
