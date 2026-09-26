"""Structured Output Parsing — Phase 0.5

Robust parsing of LLM responses into Pydantic models with retry logic.
Fail-closed: any parsing failure raises, never returns partial/invalid data.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Type, TypeVar
from pydantic import BaseModel, ValidationError

from .provider import LLMProvider, LLMMessage, LLMResponse, RetryPolicy, LLMError

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(LLMError):
    """Failed to parse structured output after all retries."""
    pass


class MaxRetriesExceeded(StructuredOutputError):
    """Exceeded maximum retries for structured output."""
    pass


def parse_structured_output(
    content: str,
    output_model: Type[T],
    strict: bool = True,
) -> T:
    """Parse LLM response content into a Pydantic model.
    
    Attempts multiple extraction strategies:
    1. Direct JSON parse
    2. Extract JSON from markdown code blocks
    3. Extract JSON from text (first { to last })
    
    Args:
        content: Raw LLM response text
        output_model: Pydantic model class
        strict: If True, raise on any parsing failure. If False, return None.
        
    Returns:
        Validated instance of output_model
        
    Raises:
        StructuredOutputError: If parsing fails and strict=True
    """
    if not content or not content.strip():
        raise StructuredOutputError("Empty response content")
    
    # Strategy 1: Direct JSON parse
    try:
        data = json.loads(content.strip())
        return output_model.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        pass
    
    # Strategy 2: Extract from markdown code blocks
    json_block_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
    matches = re.findall(json_block_pattern, content, re.DOTALL)
    for match in matches:
        try:
            data = json.loads(match.strip())
            return output_model.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            continue
    
    # Strategy 3: Find first { to last } (greedy)
    brace_pattern = r"(\{.*\})"
    matches = re.findall(brace_pattern, content, re.DOTALL)
    for match in matches:
        try:
            data = json.loads(match.strip())
            return output_model.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            continue
    
    # Strategy 4: Find JSON object at start of content
    start_idx = content.find("{")
    end_idx = content.rfind("}")
    if start_idx >= 0 and end_idx > start_idx:
        candidate = content[start_idx:end_idx+1]
        try:
            data = json.loads(candidate)
            return output_model.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            pass
    
    raise StructuredOutputError(
        f"Failed to parse structured output for {output_model.__name__}. "
        f"Content preview: {content[:200]}..."
    )


class StructuredLLM:
    """Wrapper for LLM provider with structured output and retry logic."""
    
    def __init__(
        self,
        provider: LLMProvider,
        retry_policy: Optional[RetryPolicy] = None,
    ):
        self.provider = provider
        self.retry_policy = retry_policy or provider.retry_policy
    
    async def structured_chat(
        self,
        messages: list[LLMMessage],
        output_model: Type[T],
        **kwargs,
    ) -> T:
        """Send chat request with structured output and automatic retry.
        
        Retries on:
        - Parsing failures (malformed JSON, schema mismatch)
        - Rate limits (with backoff)
        - Timeouts
        - Provider unavailable (5xx)
        
        Does NOT retry on:
        - Authentication errors (401)
        - Invalid requests (400)
        - Content policy violations
        
        Args:
            messages: Conversation history
            output_model: Pydantic model to parse response into
            **kwargs: Additional parameters for provider
            
        Returns:
            Validated instance of output_model
            
        Raises:
            MaxRetriesExceeded: All retries exhausted
            LLMError: Non-retryable errors (auth, invalid request)
        """
        last_error: Exception | None = None
        
        for attempt in range(self.retry_policy.max_retries + 1):
            try:
                response = await self.provider.chat(messages, **kwargs)
                return parse_structured_output(response.content, output_model)
            
            except StructuredOutputError as e:
                last_error = e
                if attempt < self.retry_policy.max_retries:
                    # Parsing failure - add feedback to messages for retry
                    feedback_msg = LLMMessage(
                        role="user",
                        content=(
                            f"Your previous response could not be parsed: {e}\n"
                            f"Please output ONLY valid JSON matching the schema. "
                            f"No markdown, no extra text."
                        )
                    )
                    messages = messages + [feedback_msg]
                    await self._wait_before_retry(attempt)
                    continue
                break
            
            except self.retry_policy.retry_on as e:
                last_error = e
                if attempt < self.retry_policy.max_retries:
                    await self._wait_before_retry(attempt)
                    continue
                break
            
            except LLMError:
                # Non-retryable errors (auth, bad request, etc.)
                raise
        
        raise MaxRetriesExceeded(
            f"Failed to get valid structured output after {self.retry_policy.max_retries + 1} attempts. "
            f"Last error: {last_error}"
        )
    
    async def _wait_before_retry(self, attempt: int) -> None:
        """Calculate and wait for exponential backoff with optional jitter."""
        import random
        
        delay = min(
            self.retry_policy.base_delay * (self.retry_policy.exponential_base ** attempt),
            self.retry_policy.max_delay,
        )
        if self.retry_policy.jitter:
            delay *= (0.5 + random.random())  # 0.5x to 1.5x
        
        await asyncio.sleep(delay)
    
    async def chat_with_fallback(
        self,
        messages: list[LLMMessage],
        output_model: Type[T],
        fallback_provider: LLMProvider,
        **kwargs,
    ) -> T:
        """Try primary provider, fall back to secondary on failure.
        
        Falls back on any LLMError from primary.
        """
        try:
            return await self.structured_chat(messages, output_model, **kwargs)
        except LLMError as e:
            # Log fallback
            fallback_llm = StructuredLLM(fallback_provider, self.retry_policy)
            return await fallback_llm.structured_chat(messages, output_model, **kwargs)


# Async import at module level for _wait_before_retry
import asyncio


def create_structured_llm(
    provider: LLMProvider,
    retry_policy: Optional[RetryPolicy] = None,
) -> StructuredLLM:
    """Factory function to create StructuredLLM wrapper."""
    return StructuredLLM(provider, retry_policy)