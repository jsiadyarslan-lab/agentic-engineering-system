"""LLM Integration Layer — Phase 0.5

Unified interface for LLM providers with structured output, budget tracking, and retry logic.
"""

from .provider import LLMProvider, LLMMessage, LLMResponse, ToolCall
from .structured import StructuredLLM, parse_structured_output
from .budget import TokenBudget, BudgetExceeded, estimate_tokens
from .nvidia_provider import NVIDIAProvider
from .providers import (
    ProviderType,
    ProviderConfig,
    BaseProviderAdapter,
    NVIDIAAdapter,
    OpenAIAdapter,
    AnthropicAdapter,
    GoogleAdapter,
    OllamaAdapter,
    CustomAdapter,
    register_adapter,
    create_provider,
    create_provider_from_env,
    UnifiedLLMClient,
    quick_chat,
)
from .orchestrator_adapter import OrchestratorLLMProvider, create_orchestrator_provider, create_orchestrator_provider_from_env
from .provider_errors import (
    ProviderErrorClass,
    ProviderFailure,
    as_provider_failure,
    classify_exception,
    classify_http_status,
)
from .retry import execute_with_retry

__all__ = [
    "LLMProvider",
    "LLMMessage", 
    "LLMResponse",
    "ToolCall",
    "StructuredLLM",
    "parse_structured_output",
    "TokenBudget",
    "BudgetExceeded",
    "estimate_tokens",
    "NVIDIAProvider",
    # New Universal Providers
    "ProviderType",
    "ProviderConfig",
    "BaseProviderAdapter",
    "NVIDIAAdapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "GoogleAdapter",
    "OllamaAdapter",
    "CustomAdapter",
    "register_adapter",
    "create_provider",
    "create_provider_from_env",
    "UnifiedLLMClient",
    "quick_chat",
    # Orchestrator Adapter
    "OrchestratorLLMProvider",
    "create_orchestrator_provider",
    "create_orchestrator_provider_from_env",
    # §1 reliability: classified provider failures + bounded retry
    "ProviderErrorClass",
    "ProviderFailure",
    "as_provider_failure",
    "classify_exception",
    "classify_http_status",
    "execute_with_retry",
]