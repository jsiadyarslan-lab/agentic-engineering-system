"""LLM Integration Layer — Phase 0.5

Unified interface for LLM providers with structured output, budget tracking, and retry logic.
"""

from .provider import LLMProvider, LLMMessage, LLMResponse, ToolCall
from .structured import StructuredLLM, parse_structured_output
from .budget import TokenBudget, BudgetExceeded, estimate_tokens
from .nvidia_provider import NVIDIAProvider
from .mock_provider import MockLLMProvider

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
    "MockLLMProvider",
]