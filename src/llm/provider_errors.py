"""Provider error taxonomy — AES-FACTORY-RUNTIME-RELIABILITY-001 §1

Canonical seven classes required by the execution order, plus one internal
extension (SERVER_ERROR) for 5xx responses. Every failure reaching the factory
loop is classified BEFORE retry decisions, so transient classes are retried
within the bounded policy and permanent classes surface honestly.

Hard rules (§1):
- No silent downgrade to DRAFT on provider failure.
- No fake success: failures propagate as ProviderFailure with real class.
- Secrets (API keys) must never appear in error messages or events.
"""

from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import httpx

from .provider import (
    LLMAuthenticationError,
    LLMError,
    LLMInvalidResponseError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)


class ProviderErrorClass(str, Enum):
    """§1 taxonomy: seven canonical classes + SERVER_ERROR extension."""

    CONNECT_REFUSED = "CONNECT_REFUSED"    # connection refused/dropped (incl. dead egress bridge)
    DNS_FAILURE = "DNS_FAILURE"            # name resolution failed
    TLS_FAILURE = "TLS_FAILURE"            # handshake/certificate failure
    AUTH_FAILURE = "AUTH_FAILURE"          # 401/403 — not retryable, human action required
    RATE_LIMITED = "RATE_LIMITED"          # 429 — retryable honoring Retry-After
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"    # attempt exceeded timeout
    INVALID_RESPONSE = "INVALID_RESPONSE"  # 4xx/unparseable body — not retryable
    SERVER_ERROR = "SERVER_ERROR"          # 5xx — internal extension, retryable


#: classes eligible for bounded retry (≤ max_retries, exponential backoff)
RETRYABLE_CLASSES = frozenset(
    {
        ProviderErrorClass.CONNECT_REFUSED,
        ProviderErrorClass.RATE_LIMITED,
        ProviderErrorClass.REQUEST_TIMEOUT,
        ProviderErrorClass.SERVER_ERROR,
    }
)

# lower-cased transport-message markers, checked in order
_DNS_MARKERS = (
    "getaddrinfo",
    "name or service not known",
    "temporary failure in name resolution",
    "nodename nor servname",
    "no address associated",
    "name does not resolve",
    "failed to resolve",
)
_TLS_MARKERS = (
    "certificate",
    "certificate_verify_failed",
    "ssl:",
    "ssl error",
    "handshake",
)
_REFUSED_MARKERS = (
    "connection refused",
    "actively refused",
)


class ProviderFailure(LLMError):
    """Classified provider failure carrying §1 metadata.

    Raised (instead of bare transport exceptions) so the factory loop can:
    - retry transient classes within the bounded policy,
    - surface permanent classes with a precise, actionable reason,
    - emit real observability events (class, attempt, elapsed).
    """

    def __init__(
        self,
        error_class: ProviderErrorClass,
        message: str,
        *,
        cause: Optional[BaseException] = None,
        attempt: int = 0,
        elapsed_ms: int = 0,
        retry_after: Optional[float] = None,
    ):
        self.error_class = error_class
        self.message = message
        self.cause = cause
        self.attempt = attempt
        self.elapsed_ms = elapsed_ms
        self.retry_after = retry_after
        super().__init__(f"[{error_class.value}] {message}")

    @property
    def retryable(self) -> bool:
        return self.error_class in RETRYABLE_CLASSES

    def to_event(self) -> dict[str, Any]:
        """Real event payload for the factory event log (§3 contract input)."""
        return {
            "kind": "PROVIDER_FAILURE",
            "error_class": self.error_class.value,
            "message": self.message[:300],
            "attempt": self.attempt,
            "elapsed_ms": self.elapsed_ms,
            "retryable": self.retryable,
        }


def classify_http_status(status_code: int) -> ProviderErrorClass:
    """Map an HTTP status code to the §1 taxonomy."""
    if status_code in (401, 403):
        return ProviderErrorClass.AUTH_FAILURE
    if status_code == 429:
        return ProviderErrorClass.RATE_LIMITED
    if status_code == 408:
        return ProviderErrorClass.REQUEST_TIMEOUT
    if 500 <= status_code <= 599:
        return ProviderErrorClass.SERVER_ERROR
    return ProviderErrorClass.INVALID_RESPONSE


def classify_exception(exc: BaseException) -> ProviderErrorClass:
    """Classify any exception into the §1 taxonomy.

    Walks the __cause__ chain so wrapped transport errors (httpx → socket/ssl)
    are classified by their root condition, not by the wrapper type.
    """
    # typed LLM errors first (raised by provider code on HTTP responses)
    if isinstance(exc, ProviderFailure):
        return exc.error_class
    if isinstance(exc, LLMRateLimitError):
        return ProviderErrorClass.RATE_LIMITED
    if isinstance(exc, LLMAuthenticationError):
        return ProviderErrorClass.AUTH_FAILURE
    if isinstance(exc, LLMTimeoutError):
        return ProviderErrorClass.REQUEST_TIMEOUT
    if isinstance(exc, LLMProviderUnavailableError):
        return ProviderErrorClass.SERVER_ERROR
    if isinstance(exc, LLMInvalidResponseError):
        return ProviderErrorClass.INVALID_RESPONSE
    if isinstance(exc, httpx.HTTPStatusError):
        return classify_http_status(exc.response.status_code)
    if isinstance(exc, httpx.TimeoutException):
        return ProviderErrorClass.REQUEST_TIMEOUT

    # walk cause chain for transport-level root conditions
    seen = 0
    cur: Optional[BaseException] = exc
    while cur is not None and seen < 8:
        if isinstance(cur, (socket.gaierror,)):
            return ProviderErrorClass.DNS_FAILURE
        if isinstance(cur, (ConnectionRefusedError,)):
            return ProviderErrorClass.CONNECT_REFUSED
        if isinstance(cur, (ssl.SSLError,)):
            return ProviderErrorClass.TLS_FAILURE
        text = str(cur).lower()
        if any(m in text for m in _DNS_MARKERS):
            return ProviderErrorClass.DNS_FAILURE
        if any(m in text for m in _TLS_MARKERS):
            return ProviderErrorClass.TLS_FAILURE
        if any(m in text for m in _REFUSED_MARKERS):
            return ProviderErrorClass.CONNECT_REFUSED
        cur = cur.__cause__ or cur.__context__
        seen += 1

    if isinstance(exc, httpx.ConnectError):
        return ProviderErrorClass.CONNECT_REFUSED
    if isinstance(exc, (httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError)):
        # connection established then dropped (e.g. dead egress bridge mid-call)
        return ProviderErrorClass.CONNECT_REFUSED
    if isinstance(exc, httpx.TransportError):
        return ProviderErrorClass.CONNECT_REFUSED
    return ProviderErrorClass.INVALID_RESPONSE


def as_provider_failure(
    exc: BaseException,
    *,
    attempt: int = 0,
    elapsed_ms: int = 0,
) -> ProviderFailure:
    """Normalize any exception into a ProviderFailure (idempotent)."""
    if isinstance(exc, ProviderFailure):
        return exc
    error_class = classify_exception(exc)
    retry_after: Optional[float] = None
    if isinstance(exc, LLMRateLimitError):
        retry_after = float(exc.retry_after)
    message = str(exc)
    cause = exc.__cause__ or exc.__context__
    # never leak secrets into failure payloads
    if "bearer" in message.lower() or "authorization" in message.lower():
        message = "provider failure (auth material redacted)"
    return ProviderFailure(
        error_class,
        message,
        cause=cause,
        attempt=attempt,
        elapsed_ms=elapsed_ms,
        retry_after=retry_after,
    )
