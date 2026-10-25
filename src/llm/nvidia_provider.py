"""NVIDIA Nemotron Provider — Phase 0.5

Implementation for NVIDIA Nemotron models (free tier available).
Supports structured output via function calling.

AES-FACTORY-RUNTIME-RELIABILITY-001 §1: bounded classified retry.
Every transport failure is classified into the §1 taxonomy before any retry
decision; retries are capped at 3 with exponential backoff; exhausted failures
raise ProviderFailure — no silent downgrade, no fake success.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from typing import Any, AsyncIterator, Optional

import httpx
from pydantic import BaseModel, Field

from .provider import (
    LLMProvider,
    LLMProviderType,
    LLMMessage,
    LLMResponse,
    LLMUsage,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMAuthenticationError,
    LLMProviderUnavailableError,
    LLMInvalidResponseError,
    RetryPolicy,
    ToolCall,
)
from .provider_errors import ProviderFailure, as_provider_failure
from .retry import execute_with_retry


class NVIDIAConfig(BaseModel):
    """Configuration for NVIDIA provider."""
    api_key: str = Field(default_factory=lambda: os.getenv("NVIDIA_API_KEY", ""))
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model: str = "nvidia/nemotron-3-ultra"
    timeout: float = 60.0
    max_retries: int = 3


class NVIDIAProvider(LLMProvider):
    """NVIDIA Nemotron LLM Provider.

    Uses NVIDIA's OpenAI-compatible API endpoint.
    Supports function calling for structured output.
    """

    def __init__(
        self,
        model: str = "nvidia/nemotron-3-ultra",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        retry_policy: Optional[RetryPolicy] = None,
        default_params: Optional[dict[str, Any]] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        event_sink: Optional[Any] = None,
    ):
        # transport/event_sink: test injection + real observability (§1/§3)
        # Load config from environment if not provided
        config = NVIDIAConfig(
            api_key=api_key or os.getenv("NVIDIA_API_KEY", ""),
            base_url=base_url or "https://integrate.api.nvidia.com/v1",
            model=model,
            timeout=timeout,
        )

        if not config.api_key:
            raise LLMAuthenticationError(
                "NVIDIA API key required. Set NVIDIA_API_KEY environment variable "
                "or pass api_key parameter."
            )

        super().__init__(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
            retry_policy=retry_policy,
            default_params=default_params or {
                "temperature": 0.1,
                "max_tokens": 4096,
            },
        )

        self._client: Optional[httpx.AsyncClient] = None
        self._config = config
        self._transport = transport
        self._event_sink = event_sink
        # ring of the last real provider events (retries/failures) for inspection
        self.recent_events: list[dict[str, Any]] = []
        self.last_failure: Optional[ProviderFailure] = None

    def _emit(self, event: dict[str, Any]) -> None:
        """Record a real provider event; forward to sink when attached."""
        self.recent_events.append(event)
        del self.recent_events[:-20]
        if self._event_sink is not None:
            try:
                self._event_sink(event)
            except Exception:  # sink must never break the provider
                pass

    @property
    def provider_type(self) -> LLMProviderType:
        return LLMProviderType.NVIDIA

    @property
    def supports_structured_output(self) -> bool:
        return True  # NVIDIA supports function calling

    @property
    def supports_streaming(self) -> bool:
        return True

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.timeout),
                transport=self._transport,
                # trust_env stays enabled: honors https_proxy when the
                # deployment provides the egress bridge proxy.
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict]] = None,
        **kwargs,
    ) -> LLMResponse:
        """Send chat completion request with bounded classified retry (§1)."""
        try:
            return await execute_with_retry(
                lambda: self._chat_once(messages, tools=tools, **kwargs),
                self.retry_policy,
                on_event=self._emit,
            )
        except ProviderFailure as pf:
            self.last_failure = pf
            self._emit(pf.to_event())
            raise

    async def _chat_once(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict]] = None,
        **kwargs,
    ) -> LLMResponse:
        """Single attempt: send chat completion request to NVIDIA API."""
        client = await self._get_client()

        # Prepare request payload
        payload = {
            "model": self.model,
            "messages": [msg.to_dict() for msg in messages],
            **self._prepare_request_params(**kwargs),
        }

        # Add tools if provided
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        start_time = time.time()

        try:
            response = await client.post("/chat/completions", json=payload)
            latency_ms = int((time.time() - start_time) * 1000)

            # Handle HTTP errors
            if response.status_code == 401:
                raise LLMAuthenticationError("Invalid NVIDIA API key")
            elif response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 60))
                raise LLMRateLimitError(retry_after=retry_after)
            elif response.status_code >= 500:
                raise LLMProviderUnavailableError(
                    f"NVIDIA API error: {response.status_code} - {response.text}"
                )
            elif response.status_code != 200:
                raise LLMInvalidResponseError(
                    f"NVIDIA API error: {response.status_code} - {response.text}"
                )

            data = response.json()

            # Extract response
            choice = data["choices"][0]
            content = choice["message"].get("content", "")
            tool_calls_raw = choice["message"].get("tool_calls", [])
            tool_calls = [ToolCall.from_dict(tc) for tc in tool_calls_raw]
            finish_reason = choice.get("finish_reason", "stop")

            # Extract usage
            usage_data = data.get("usage", {})
            usage = LLMUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            )

            self._accumulate_usage(usage)

            return LLMResponse(
                content=content,
                model=data.get("model", self.model),
                usage=usage,
                finish_reason=finish_reason,
                tool_calls=tool_calls,
                raw_response=data,
                latency_ms=latency_ms,
            )

        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"Request timed out after {self.timeout}s") from e
        except httpx.RequestError as e:
            raise as_provider_failure(e) from e

    async def stream_chat(
        self,
        messages: list[LLMMessage],
        **kwargs,
    ) -> AsyncIterator[str]:
        """Stream chat response; retries apply only before the first token.

        Mid-stream failures raise a classified ProviderFailure immediately:
        tokens already consumed cannot be replayed, so we fail honestly.
        """
        policy = self.retry_policy
        retries_cap = max(0, min(int(policy.max_retries), 3))
        attempt = 0
        while True:
            emitted = False
            try:
                async for chunk in self._stream_once(messages, **kwargs):
                    emitted = True
                    yield chunk
                return
            except httpx.TimeoutException as e:
                pf = as_provider_failure(LLMTimeoutError("Stream timed out"), attempt=attempt)
                pf.__cause__ = e
            except httpx.RequestError as e:
                pf = as_provider_failure(e, attempt=attempt)
            if emitted:
                self.last_failure = pf
                self._emit(pf.to_event())
                raise pf
            if not pf.retryable or attempt >= retries_cap:
                self.last_failure = pf
                self._emit(pf.to_event())
                raise pf
            delay = min(policy.base_delay * (policy.exponential_base ** attempt), policy.max_delay)
            if pf.retry_after is not None:
                delay = max(delay, float(pf.retry_after))
            if policy.jitter:
                delay = delay * (0.5 + random.random() / 2)
            attempt += 1
            self._emit({
                "kind": "PROVIDER_RETRY",
                "error_class": pf.error_class.value,
                "attempt": attempt,
                "delay_s": round(delay, 3),
                "message": pf.message[:300],
            })
            await asyncio.sleep(delay)

    async def _stream_once(
        self,
        messages: list[LLMMessage],
        **kwargs,
    ) -> AsyncIterator[str]:
        """Single streaming attempt."""
        client = await self._get_client()

        payload = {
            "model": self.model,
            "messages": [msg.to_dict() for msg in messages],
            "stream": True,
            **self._prepare_request_params(**kwargs),
        }

        try:
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code != 200:
                    raise LLMInvalidResponseError(
                        f"Stream error: {response.status_code}"
                    )

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]  # Remove "data: "
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue

        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"Stream timed out") from e
        except httpx.RequestError as e:
            raise as_provider_failure(e) from e

    async def structured_chat(
        self,
        messages: list[LLMMessage],
        output_model: type[BaseModel],
        **kwargs,
    ) -> BaseModel:
        """Use function calling for structured output with bounded retry (§1).

        NVIDIA supports OpenAI-compatible function calling.
        """
        try:
            return await execute_with_retry(
                lambda: self._structured_chat_once(messages, output_model, **kwargs),
                self.retry_policy,
                on_event=self._emit,
            )
        except ProviderFailure as pf:
            self.last_failure = pf
            self._emit(pf.to_event())
            raise

    async def _structured_chat_once(
        self,
        messages: list[LLMMessage],
        output_model: type[BaseModel],
        **kwargs,
    ) -> BaseModel:
        """Single attempt: function calling for structured output."""
        # Convert Pydantic model to function schema
        schema = output_model.model_json_schema()

        function_def = {
            "name": "structured_output",
            "description": f"Output structured data as {output_model.__name__}",
            "parameters": schema,
        }

        payload = {
            "model": self.model,
            "messages": [msg.to_dict() for msg in messages],
            "tools": [{"type": "function", "function": function_def}],
            "tool_choice": {"type": "function", "function": {"name": "structured_output"}},
            **self._prepare_request_params(**kwargs),
        }

        client = await self._get_client()
        start_time = time.time()

        try:
            response = await client.post("/chat/completions", json=payload)
            latency_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 401:
                raise LLMAuthenticationError("Invalid NVIDIA API key")
            elif response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 60))
                raise LLMRateLimitError(retry_after=retry_after)
            elif response.status_code >= 500:
                raise LLMProviderUnavailableError(
                    f"NVIDIA API error: {response.status_code} - {response.text}"
                )
            elif response.status_code != 200:
                raise LLMInvalidResponseError(
                    f"NVIDIA API error: {response.status_code} - {response.text}"
                )

            data = response.json()
            choice = data["choices"][0]
            tool_calls = choice["message"].get("tool_calls", [])

            if not tool_calls:
                # Fallback: try to parse content as JSON
                content = choice["message"].get("content", "")
                from .structured import parse_structured_output
                return parse_structured_output(content, output_model)

            # Parse function call arguments
            function_args = json.loads(tool_calls[0]["function"]["arguments"])

            usage_data = data.get("usage", {})
            usage = LLMUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            )
            self._accumulate_usage(usage)

            return output_model.model_validate(function_args)

        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"Request timed out after {self.timeout}s") from e
        except httpx.RequestError as e:
            raise as_provider_failure(e) from e
        except json.JSONDecodeError as e:
            raise LLMInvalidResponseError(f"Invalid function arguments: {e}") from e


# Register provider
from .provider import ProviderRegistry
ProviderRegistry.register("nvidia", NVIDIAProvider)
ProviderRegistry.register("nemotron", NVIDIAProvider)


async def create_nvidia_provider(
    model: str = "nvidia/nemotron-3-ultra",
    **kwargs,
) -> NVIDIAProvider:
    """Factory function to create NVIDIA provider."""
    return NVIDIAProvider(model=model, **kwargs)
