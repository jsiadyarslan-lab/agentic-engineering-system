"""Orchestrator LLM Provider Adapter

Bridges UnifiedLLMClient (Universal Provider Adapter) to the 
LLMProvider interface expected by AgentFactoryOrchestrator.

The orchestrator requires an object with:
- chat(messages, **kwargs) -> LLMResponse
- structured_chat(messages, output_model, **kwargs) -> T
- retry_policy property
- get_structured_llm(role: str) -> StructuredLLM

This adapter wraps UnifiedLLMClient and provides the required interface.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional, Type, TypeVar

from src.llm.providers import (
    UnifiedLLMClient, 
    LLMMessage, 
    LLMResponse, 
    ProviderType, 
    ProviderConfig
)
from src.llm.structured import StructuredLLM, RetryPolicy
from src.llm.provider import LLMError

T = TypeVar("T")


class OrchestratorLLMProvider:
    """Adapter making UnifiedLLMClient compatible with AgentFactoryOrchestrator."""
    
    def __init__(self, client: UnifiedLLMClient):
        self._client = client
    
    @classmethod
    def from_config(
        cls,
        provider_type: str = "nvidia",
        model: str = "nvidia/nemotron-3-ultra-550b-a55b",
        api_key: Optional[str] = None,
    ) -> "OrchestratorLLMProvider":
        """Create from provider configuration.
        
        Args:
            provider_type: Provider type (nvidia, openai, anthropic, google, ollama, custom)
            model: Model name
            api_key: API key (uses environment variable if not provided)
            
        Returns:
            OrchestratorLLMProvider ready for AgentFactoryOrchestrator
        """
        provider_type_enum = ProviderType(provider_type.lower())
        
        # Get API key from env if not provided (except Ollama)
        if provider_type_enum != ProviderType.OLLAMA:
            env_var = f"{provider_type.upper()}_API_KEY"
            key = api_key or os.getenv(env_var)
            if not key:
                raise ValueError(f"API key required for {provider_type}. Set {env_var} or pass api_key.")
        else:
            key = None
        
        config = ProviderConfig(
            provider_type=provider_type_enum,
            api_key=key,
            model=model,
        )
        
        client = UnifiedLLMClient.from_config(config)
        return cls(client)
    
    @classmethod
    def from_env(cls) -> "OrchestratorLLMProvider":
        """Create by auto-detecting from environment."""
        from src.llm.providers import create_provider_from_env
        client = UnifiedLLMClient(create_provider_from_env())
        return cls(client)
    
    # ============================================================
    # LLMProvider Interface (Phase 0.5 compatible)
    # ============================================================
    
    async def chat(self, messages: List[LLMMessage], **kwargs) -> LLMResponse:
        """Delegate to UnifiedLLMClient.chat"""
        return await self._client.chat(messages, **kwargs)
    
    async def structured_chat(
        self,
        messages: List[LLMMessage],
        output_model: Type[T],
        **kwargs
    ) -> T:
        """Delegate to UnifiedLLMClient.structured_chat"""
        return await self._client.structured_chat(messages, output_model, **kwargs)
    
    @property
    def retry_policy(self) -> RetryPolicy:
        """Return retry policy from underlying client"""
        return self._client.retry_policy
    
    # ============================================================
    # Orchestrator Interface
    # ============================================================
    
    def get_structured_llm(self, role: str) -> StructuredLLM:
        """Return a StructuredLLM configured for the given agent role.
        
        Args:
            role: Agent role name (explorer, thinker, planner, designer, 
                  reviewer, implementer, verifier, security)
                  
        Returns:
            StructuredLLM wrapper with retry logic for structured output
        """
        return StructuredLLM(self, retry_policy=self.retry_policy)
    
    # ============================================================
    # Additional Properties for Compatibility
    # ============================================================
    
    @property
    def provider(self) -> UnifiedLLMClient:
        """Access to underlying UnifiedLLMClient for advanced usage."""
        return self._client


def create_orchestrator_provider(
    provider_type: str = "nvidia",
    model: str = "nvidia/nemotron-3-ultra-550b-a55b",
    api_key: Optional[str] = None,
) -> OrchestratorLLMProvider:
    """Factory function to create orchestrator-compatible provider.
    
    Args:
        provider_type: Provider type (nvidia, openai, anthropic, google, ollama, custom)
        model: Model name
        api_key: API key (uses environment variable if not provided)
        
    Returns:
        OrchestratorLLMProvider ready for AgentFactoryOrchestrator
    """
    return OrchestratorLLMProvider.from_config(provider_type, model, api_key)


def create_orchestrator_provider_from_env() -> OrchestratorLLMProvider:
    """Create orchestrator provider by auto-detecting from environment."""
    return OrchestratorLLMProvider.from_env()