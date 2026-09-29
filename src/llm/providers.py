"""
Universal Provider Adapter - يدعم كل مزودي LLMs
NVIDIA, OpenAI, Anthropic, Google, Ollama, Custom endpoints
"""

from __future__ import annotations

import asyncio
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Type
from enum import Enum

import aiohttp
from pydantic import BaseModel, Field

from .provider import RetryPolicy, LLMRateLimitError, LLMTimeoutError, LLMProviderUnavailableError


class ProviderType(str, Enum):
    NVIDIA = "nvidia"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OLLAMA = "ollama"
    CUSTOM = "custom"


class LLMMessage(BaseModel):
    role: str = Field(..., description="system, user, assistant, tool")
    content: str = Field(..., description="Message content")
    name: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    content: str
    model: str
    usage: LLMUsage
    finish_reason: str = "stop"
    tool_calls: Optional[List[Dict]] = None


class ProviderConfig(BaseModel):
    """إعدادات المزود"""
    provider_type: ProviderType
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: str
    timeout: int = 60
    max_retries: int = 3
    extra_headers: Dict[str, str] = field(default_factory=dict)
    extra_params: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# BASE ADAPTER
# ============================================================

class BaseProviderAdapter(ABC):
    """قاعدة مجردة لكل مزود"""
    
    def __init__(self, config: ProviderConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
    
    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        pass
    
    @property
    @abstractmethod
    def default_base_url(self) -> str:
        pass
    
    @abstractmethod
    def _build_request(self, messages: List[LLMMessage], **kwargs) -> Dict[str, Any]:
        """بناء طلب HTTP للمزود"""
        pass
    
    @abstractmethod
    def _parse_response(self, data: Dict[str, Any]) -> LLMResponse:
        """تحليل رد المزود"""
        pass
    
    @abstractmethod
    def _parse_stream_chunk(self, chunk: str) -> Optional[str]:
        """تحليل جزء من الاستREAMING"""
        pass
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            headers = {
                "Content-Type": "application/json",
                **self.config.extra_headers
            }
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            self._session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def chat(self, messages: List[LLMMessage], **kwargs) -> LLMResponse:
        """محادثة عادية"""
        session = await self._get_session()
        url = f"{self.config.base_url or self.default_base_url}/chat/completions"
        payload = self._build_request(messages, **kwargs)
        
        for attempt in range(self.config.max_retries):
            try:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    return self._parse_response(data)
            except aiohttp.ClientError as e:
                if attempt == self.config.max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
        
        raise RuntimeError("Max retries exceeded")
    
    async def stream_chat(self, messages: List[LLMMessage], **kwargs) -> AsyncIterator[str]:
        """استREAMING محادثة"""
        session = await self._get_session()
        url = f"{self.config.base_url or self.default_base_url}/chat/completions"
        payload = self._build_request(messages, stream=True, **kwargs)
        
        async with session.post(url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.content:
                line = line.decode('utf-8').strip()
                if line.startswith("data: "):
                    chunk_data = line[6:]
                    if chunk_data == "[DONE]":
                        break
                    try:
                        chunk = self._parse_stream_chunk(chunk_data)
                        if chunk:
                            yield chunk
                    except:
                        pass


# ============================================================
# NVIDIA ADAPTER
# ============================================================

class NVIDIAAdapter(BaseProviderAdapter):
    """NVIDIA Nemotron / NIM API"""
    
    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.NVIDIA
    
    @property
    def default_base_url(self) -> str:
        return "https://integrate.api.nvidia.com/v1"
    
    def _build_request(self, messages: List[LLMMessage], **kwargs) -> Dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "top_p": kwargs.get("top_p", 1.0),
            "stream": kwargs.get("stream", False),
        }
        payload.update(self.config.extra_params)
        return payload
    
    def _parse_response(self, data: Dict[str, Any]) -> LLMResponse:
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", self.config.model),
            usage=LLMUsage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            ),
            finish_reason=choice.get("finish_reason", "stop"),
        )
    
    def _parse_stream_chunk(self, chunk: str) -> Optional[str]:
        import json
        data = json.loads(chunk)
        delta = data["choices"][0].get("delta", {})
        return delta.get("content")


# ============================================================
# OPENAI ADAPTER
# ============================================================

class OpenAIAdapter(BaseProviderAdapter):
    """OpenAI GPT-4, GPT-3.5, o1, etc."""
    
    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OPENAI
    
    @property
    def default_base_url(self) -> str:
        return "https://api.openai.com/v1"
    
    def _build_request(self, messages: List[LLMMessage], **kwargs) -> Dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "top_p": kwargs.get("top_p", 1.0),
            "stream": kwargs.get("stream", False),
        }
        # OpenAI specific
        if "response_format" in kwargs:
            payload["response_format"] = kwargs["response_format"]
        payload.update(self.config.extra_params)
        return payload
    
    def _parse_response(self, data: Dict[str, Any]) -> LLMResponse:
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", self.config.model),
            usage=LLMUsage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            ),
            finish_reason=choice.get("finish_reason", "stop"),
        )
    
    def _parse_stream_chunk(self, chunk: str) -> Optional[str]:
        import json
        data = json.loads(chunk)
        delta = data["choices"][0].get("delta", {})
        return delta.get("content")


# ============================================================
# ANTHROPIC ADAPTER
# ============================================================

class AnthropicAdapter(BaseProviderAdapter):
    """Anthropic Claude 3.5 Sonnet, Haiku, Opus"""
    
    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.ANTHROPIC
    
    @property
    def default_base_url(self) -> str:
        return "https://api.anthropic.com/v1"
    
    def _build_request(self, messages: List[LLMMessage], **kwargs) -> Dict[str, Any]:
        # Convert to Anthropic format
        system_msg = ""
        anth_messages = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            else:
                anth_messages.append({"role": m.role, "content": m.content})
        
        payload = {
            "model": self.config.model,
            "messages": anth_messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7),
            "stream": kwargs.get("stream", False),
        }
        if system_msg:
            payload["system"] = system_msg
        payload.update(self.config.extra_params)
        return payload
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.config.api_key or "",
                "anthropic-version": "2023-06-01",
                **self.config.extra_headers
            }
            self._session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self._session
    
    def _parse_response(self, data: Dict[str, Any]) -> LLMResponse:
        usage = data.get("usage", {})
        return LLMResponse(
            content=data["content"][0]["text"],
            model=data.get("model", self.config.model),
            usage=LLMUsage(
                prompt_tokens=usage.get("input_tokens", 0),
                completion_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            ),
            finish_reason=data.get("stop_reason", "stop"),
        )
    
    def _parse_stream_chunk(self, chunk: str) -> Optional[str]:
        import json
        data = json.loads(chunk)
        if data.get("type") == "content_block_delta":
            return data.get("delta", {}).get("text")


# ============================================================
# GOOGLE ADAPTER
# ============================================================

class GoogleAdapter(BaseProviderAdapter):
    """Google Gemini Pro, Flash"""
    
    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.GOOGLE
    
    @property
    def default_base_url(self) -> str:
        return "https://generativelanguage.googleapis.com/v1beta"
    
    def _build_request(self, messages: List[LLMMessage], **kwargs) -> Dict[str, Any]:
        contents = []
        for m in messages:
            role = "user" if m.role == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m.content}]})
        
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": kwargs.get("temperature", 0.7),
                "maxOutputTokens": kwargs.get("max_tokens", 4096),
                "topP": kwargs.get("top_p", 1.0),
            },
        }
        if kwargs.get("stream"):
            # Streaming handled differently for Google
            pass
        payload.update(self.config.extra_params)
        return payload
    
    async def chat(self, messages: List[LLMMessage], **kwargs) -> LLMResponse:
        session = await self._get_session()
        url = f"{self.default_base_url}/models/{self.config.model}:generateContent?key={self.config.api_key}"
        payload = self._build_request(messages, **kwargs)
        
        async with session.post(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return self._parse_response(data)
    
    def _parse_response(self, data: Dict[str, Any]) -> LLMResponse:
        candidate = data["candidates"][0]
        content = candidate["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {})
        return LLMResponse(
            content=content,
            model=self.config.model,
            usage=LLMUsage(
                prompt_tokens=usage.get("promptTokenCount", 0),
                completion_tokens=usage.get("candidatesTokenCount", 0),
                total_tokens=usage.get("totalTokenCount", 0),
            ),
            finish_reason=candidate.get("finishReason", "STOP"),
        )
    
    def _parse_stream_chunk(self, chunk: str) -> Optional[str]:
        return None  # Not implemented for Google streaming yet


# ============================================================
# OLLAMA ADAPTER (Local)
# ============================================================

class OllamaAdapter(BaseProviderAdapter):
    """Ollama المحلي - llama3, mistral, codellama, etc."""
    
    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OLLAMA
    
    @property
    def default_base_url(self) -> str:
        return "http://localhost:11434"
    
    def _build_request(self, messages: List[LLMMessage], **kwargs) -> Dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": kwargs.get("temperature", 0.7),
            "num_predict": kwargs.get("max_tokens", 4096),
            "stream": kwargs.get("stream", False),
        }
        payload.update(self.config.extra_params)
        return payload
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    def _parse_response(self, data: Dict[str, Any]) -> LLMResponse:
        return LLMResponse(
            content=data["message"]["content"],
            model=data.get("model", self.config.model),
            usage=LLMUsage(
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            ),
            finish_reason=data.get("done_reason", "stop"),
        )
    
    def _parse_stream_chunk(self, chunk: str) -> Optional[str]:
        import json
        data = json.loads(chunk)
        return data.get("message", {}).get("content")


# ============================================================
# CUSTOM ADAPTER (OpenAI-compatible)
# ============================================================

class CustomAdapter(OpenAIAdapter):
    """أي endpoint متوافق مع OpenAI API"""
    
    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.CUSTOM


# ============================================================
# PROVIDER REGISTRY & FACTORY
# ============================================================

_ADAPTERS: Dict[ProviderType, Type[BaseProviderAdapter]] = {
    ProviderType.NVIDIA: NVIDIAAdapter,
    ProviderType.OPENAI: OpenAIAdapter,
    ProviderType.ANTHROPIC: AnthropicAdapter,
    ProviderType.GOOGLE: GoogleAdapter,
    ProviderType.OLLAMA: OllamaAdapter,
    ProviderType.CUSTOM: CustomAdapter,
}


def register_adapter(provider_type: ProviderType, adapter_class: Type[BaseProviderAdapter]):
    """تسجيل مزود مخصص"""
    _ADAPTERS[provider_type] = adapter_class


def create_provider(config: ProviderConfig) -> BaseProviderAdapter:
    """إنشاء مزود من الإعدادات"""
    adapter_class = _ADAPTERS.get(config.provider_type)
    if not adapter_class:
        raise ValueError(f"Unknown provider type: {config.provider_type}")
    return adapter_class(config)


def create_provider_from_env() -> BaseProviderAdapter:
    """إنشاء مزود من متغيرات البيئة تلقائياً"""
    # Priority: NVIDIA > OpenAI > Anthropic > Google > Ollama
    
    if os.getenv("NVIDIA_API_KEY"):
        return create_provider(ProviderConfig(
            provider_type=ProviderType.NVIDIA,
            api_key=os.getenv("NVIDIA_API_KEY"),
            model=os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-ultra"),
        ))
    
    if os.getenv("OPENAI_API_KEY"):
        return create_provider(ProviderConfig(
            provider_type=ProviderType.OPENAI,
            api_key=os.getenv("OPENAI_API_KEY"),
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        ))
    
    if os.getenv("ANTHROPIC_API_KEY"):
        return create_provider(ProviderConfig(
            provider_type=ProviderType.ANTHROPIC,
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
        ))
    
    if os.getenv("GOOGLE_API_KEY"):
        return create_provider(ProviderConfig(
            provider_type=ProviderType.GOOGLE,
            api_key=os.getenv("GOOGLE_API_KEY"),
            model=os.getenv("GOOGLE_MODEL", "gemini-1.5-pro"),
        ))
    
    # Check if Ollama is running
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=2)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            if models:
                return create_provider(ProviderConfig(
                    provider_type=ProviderType.OLLAMA,
                    model=models[0]["name"],
                ))
    except:
        pass
    
    # No provider configured - raise explicit error
    raise ValueError(
        "No LLM provider configured. Set one of: NVIDIA_API_KEY, OPENAI_API_KEY, "
        "ANTHROPIC_API_KEY, GOOGLE_API_KEY, or run Ollama locally on port 11434."
    )


# ============================================================
# UNIFIED LLM CLIENT
# ============================================================

class UnifiedLLMClient:
    """عميل موحد للتعامل مع أي مزود"""
    
    def __init__(self, provider: BaseProviderAdapter):
        self.provider = provider
    
    @classmethod
    def from_config(cls, config: ProviderConfig) -> "UnifiedLLMClient":
        return cls(create_provider(config))
    
    @classmethod
    def from_env(cls) -> "UnifiedLLMClient":
        return cls(create_provider_from_env())
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "UnifiedLLMClient":
        config = ProviderConfig(**config_dict)
        return cls(create_provider(config))
    
    @property
    def retry_policy(self) -> RetryPolicy:
        """Return default retry policy for StructuredLLM compatibility."""
        return RetryPolicy(
            max_retries=3,
            base_delay=1.0,
            max_delay=60.0,
            exponential_base=2.0,
            jitter=True,
            retry_on=(LLMRateLimitError, LLMTimeoutError, LLMProviderUnavailableError),
        )
    
    async def chat(self, messages: List[LLMMessage], **kwargs) -> LLMResponse:
        return await self.provider.chat(messages, **kwargs)
    
    async def stream_chat(self, messages: List[LLMMessage], **kwargs) -> AsyncIterator[str]:
        async for chunk in self.provider.stream_chat(messages, **kwargs):
            yield chunk
    
    async def structured_chat(
        self,
        messages: list[LLMMessage],
        output_model: Type[T],
        **kwargs,
    ) -> T:
        """Send chat request with structured output parsing.
        
        Injects JSON schema into system message, calls chat(), then parses response.
        """
        from src.llm.structured import parse_structured_output
        
        schema = output_model.model_json_schema()
        system_prompt = (
            f"Output ONLY valid JSON matching this schema:\n"
            f"{json.dumps(schema, indent=2)}\n"
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

    async def close(self):
        await self.provider.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# ============================================================
# HELPER FUNCTIONS
# ============================================================

async def quick_chat(
    message: str,
    provider_type: Optional[ProviderType] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    **kwargs
) -> str:
    """محادثة سريعة بسطر واحد"""
    if provider_type:
        config = ProviderConfig(
            provider_type=provider_type,
            api_key=api_key,
            model=model or _default_model_for_provider(provider_type),
        )
        async with UnifiedLLMClient.from_config(config) as client:
            resp = await client.chat([LLMMessage(role="user", content=message)], **kwargs)
            return resp.content
    else:
        # Auto-detect from environment
        provider = create_provider_from_env()
        return (await provider.chat([LLMMessage(role="user", content=message)], **kwargs)).content


def _default_model_for_provider(p: ProviderType) -> str:
    defaults = {
        ProviderType.NVIDIA: "nvidia/nemotron-3-ultra",
        ProviderType.OPENAI: "gpt-4o",
        ProviderType.ANTHROPIC: "claude-3-5-sonnet-20241022",
        ProviderType.GOOGLE: "gemini-1.5-pro",
        ProviderType.OLLAMA: "llama3",
        ProviderType.CUSTOM: "custom",
    }
    return defaults.get(p, "custom")


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Types
    "ProviderType",
    "LLMMessage",
    "LLMResponse",
    "LLMUsage",
    "ProviderConfig",
    # Adapters
    "BaseProviderAdapter",
    "NVIDIAAdapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "GoogleAdapter",
    "OllamaAdapter",
    "CustomAdapter",
    # Factory
    "register_adapter",
    "create_provider",
    "create_provider_from_env",
    # Client
    "UnifiedLLMClient",
    "quick_chat",
]