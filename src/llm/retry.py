"""Bounded exponential-backoff retry — AES-FACTORY-RUNTIME-RELIABILITY-001 §1

Contract:
- At most `min(policy.max_retries, 3)` retries (execution order cap: 3).
- Exponential delay: base_delay * exponential_base**attempt, capped at max_delay.
- RATE_LIMITED honors Retry-After: final delay = max(backoff, retry_after).
- Only RETRYABLE_CLASSES are retried; permanent classes raise immediately.
- Every retry emits a REAL event through `on_event` — no synthetic activity.
- On exhaustion the last ProviderFailure propagates: no fake success.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Awaitable, Callable, Optional, TypeVar

import httpx

from .provider import LLMError, RetryPolicy
from .provider_errors import ProviderErrorClass, ProviderFailure, as_provider_failure

T = TypeVar("T")

#: execution-order cap on retries (≤3)
MAX_RETRIES_CAP = 3


async def execute_with_retry(
    fn: Callable[[], Awaitable[T]],
    policy: Optional[RetryPolicy] = None,
    *,
    on_event: Optional[Callable[[dict[str, Any]], None]] = None,
) -> T:
    """Run `fn()` with bounded, classified, exponential-backoff retries."""
    policy = policy or RetryPolicy()
    effective_retries = max(0, min(int(policy.max_retries), MAX_RETRIES_CAP))
    attempt = 0  # retries consumed so far

    while True:
        start = time.monotonic()
        try:
            return await fn()
        except (LLMError, httpx.HTTPStatusError, httpx.TransportError) as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            pf = as_provider_failure(exc, attempt=attempt, elapsed_ms=elapsed_ms)
            if not pf.retryable or attempt >= effective_retries:
                raise pf from pf.cause
            delay = min(
                policy.base_delay * (policy.exponential_base ** attempt),
                policy.max_delay,
            )
            if pf.retry_after is not None:
                delay = max(delay, float(pf.retry_after))
            if policy.jitter:
                delay = delay * (0.5 + random.random() / 2)
            attempt += 1
            if on_event is not None:
                on_event(
                    {
                        "kind": "PROVIDER_RETRY",
                        "error_class": pf.error_class.value,
                        "attempt": attempt,
                        "delay_s": round(delay, 3),
                        "elapsed_ms": elapsed_ms,
                        "message": pf.message[:300],
                    }
                )
            await asyncio.sleep(delay)
