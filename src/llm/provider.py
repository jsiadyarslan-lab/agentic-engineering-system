"""LLM Provider Abstraction — Phase 0.5

Defines the unified interface all LLM providers must implement.
Fail-closed: any provider that doesn't meet the contract is rejected.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional, Type, TypeVar
from pydantic import BaseModel, Field


T = TypeVar("T", bound=BaseModel)


class LLMProviderType(str, Enum):
    """Supported LLM provider types."""
    NVIDIA = "nvidia"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    LOCAL = "local"


class LLMError(Exception):
    """Base exception for LLM provider errors."""
    pass


class LLMRateLimitError(LLMError):
    """Rate limit exceeded."""
    def __init__(self, retry_after: float = 60.0):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")


class LLMTimeoutError(LLMError):
    """Request timed out."""
    pass


class LLMInvalidResponseError(LLMError):
    """Provider returned invalid/unparseable response."""
    pass


class LLMAuthenticationError(LLMError):
    """Invalid API key or authentication failure."""
    pass


class LLMProviderUnavailableError(LLMError):
    """Provider service unavailable (5xx)."""
    pass


@dataclass(frozen=True)
class LLMMessage:
    """A single message in the conversation."""
    role: str  # "system", "user", "assistant", "tool"
    content: str
    name: Optional[str] = None  # for tool calls
    tool_call_id: Optional[str] = None  # for tool responses
    
    def to_dict(self) -> dict[str, Any]:
        d = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d


@dataclass(frozen=True)
class LLMUsage:
    """Token usage statistics."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    
    def __add__(self, other: "LLMUsage") -> "LLMUsage":
        return LLMUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass(frozen=True)
class LLMResponse:
    """Response from an LLM provider."""
    content: str
    model: str
    usage: LLMUsage
    finish_reason: str = "stop"
    tool_calls: list[dict] = field(default_factory=list)
    raw_response: dict = field(default_factory=dict)
    latency_ms: int = 0
    timestamp: float = field(default_factory=time.time)


class RetryPolicy(BaseModel):
    """Retry configuration for LLM calls."""
    max_retries: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retry_on: tuple[type[Exception], ...] = (
        LLMRateLimitError,
        LLMTimeoutError,
        LLMProviderUnavailableError,
    )


class LLMProvider(abc.ABC):
    """Abstract base class for LLM providers.
    
    All providers must implement chat() and structured_chat().
    Fail-closed: any unimplemented method raises NotImplementedError.
    """
    
    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        retry_policy: Optional[RetryPolicy] = None,
        default_params: Optional[dict[str, Any]] = None,
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.retry_policy = retry_policy or RetryPolicy()
        self.default_params = default_params or {}
        self._usage_accumulator: LLMUsage = LLMUsage()
    
    @property
    @abc.abstractmethod
    def provider_type(self) -> LLMProviderType:
        """Return the provider type identifier."""
        pass
    
    @property
    def supports_structured_output(self) -> bool:
        """Whether the provider supports native structured output (function calling)."""
        return True
    
    @property
    def supports_streaming(self) -> bool:
        """Whether the provider supports streaming responses."""
        return False
    
    @abc.abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        **kwargs,
    ) -> LLMResponse:
        """Send a chat completion request.
        
        Args:
            messages: Conversation history
            **kwargs: Provider-specific parameters (temperature, max_tokens, etc.)
            
        Returns:
            LLMResponse with content and usage
            
        Raises:
            LLMError: On any failure (rate limit, timeout, auth, etc.)
        """
        pass
    
    async def structured_chat(
        self,
        messages: list[LLMMessage],
        output_model: Type[T],
        **kwargs,
    ) -> T:
        """Send a chat completion request with structured output parsing.
        
        Default implementation uses function calling / JSON mode.
        Providers with native support should override for efficiency.
        
        Args:
            messages: Conversation history
            output_model: Pydantic model to parse response into
            **kwargs: Provider-specific parameters
            
        Returns:
            Parsed instance of output_model
            
        Raises:
            LLMError: On failure
            ValidationError: If response doesn't match schema
        """
        # Add schema instruction to system message
        schema = output_model.model_json_schema()
        system_prompt = (
            f"Output ONLY valid JSON matching this schema:\n"
            f"{schema}\n"
            f"No extra text, no markdown, no explanation."
        )
        
        # Prepend system message if not present
        if not messages or messages[0].role != "system":
            messages = [LLMMessage(role="system", content=system_prompt)] + messages
        else:
            # Append schema to existing system message
            messages[0] = LLMMessage(
                role="system",
                content=messages[0].content + "\n\n" + system_prompt
            )
        
        response = await self.chat(messages, **kwargs)
        return parse_structured_output(response.content, output_model)
    
    async def stream_chat(
        self,
        messages: list[LLMMessage],
        **kwargs,
    ) -> AsyncIterator[str]:
        """Stream chat response tokens.
        
        Default implementation raises NotImplementedError.
        Providers supporting streaming should override.
        """
        raise NotImplementedError(f"{self.provider_type} does not support streaming")
    
    def get_usage(self) -> LLMUsage:
        """Get accumulated usage for this provider instance."""
        return self._usage_accumulator
    
    def reset_usage(self) -> None:
        """Reset usage accumulator."""
        self._usage_accumulator = LLMUsage()
    
    def _accumulate_usage(self, usage: LLMUsage) -> None:
        self._usage_accumulator += usage
    
    def _prepare_request_params(self, **kwargs) -> dict[str, Any]:
        """Merge default params with call-specific params."""
        params = self.default_params.copy()
        params.update(kwargs)
        return params


class ProviderRegistry:
    """Registry of available LLM providers."""
    
    _providers: dict[str, type[LLMProvider]] = {}
    
    @classmethod
    def register(cls, name: str, provider_class: type[LLMProvider]) -> None:
        cls._providers[name.lower()] = provider_class
    
    @classmethod
    def get(cls, name: str) -> type[LLMProvider]:
        provider = cls._providers.get(name.lower())
        if not provider:
            raise ValueError(f"Unknown provider: {name}. Available: {list(cls._providers.keys())}")
        return provider
    
    @classmethod
    def create(cls, name: str, **kwargs) -> LLMProvider:
        return cls.get(name)(**kwargs)
    
    @classmethod
    def list_available(cls) -> list[str]:
        return list(cls._providers.keys())


def create_provider(
    provider_type: str | LLMProviderType,
    model: str,
    **kwargs,
) -> LLMProvider:
    """Factory function to create a provider instance."""
    if isinstance(provider_type, LLMProviderType):
        provider_type = provider_type.value
    return ProviderRegistry.create(provider_type, model=model, **kwargs)