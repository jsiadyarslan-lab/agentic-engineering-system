"""
Unified LLM Gateway — Unified Engineering Agents System

Wraps UnifiedLLMClient from src/llm/providers.py with:
- Structured output for agent contracts
- Token budget integration
- Retry policy
- Provider auto-detection
- Cost tracking
- Audit events

This is the single LLM interface for all agents.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Type, TypeVar
from pydantic import BaseModel, Field

from unified.contracts import FactoryEvent, EventType, TokenUsageEvent
from unified.domain_model import MissionState

# Import the actual provider implementation
try:
    from llm.providers import (
        UnifiedLLMClient,
        ProviderType,
        ProviderConfig,
        RetryPolicy,
        create_client_from_env,
        auto_detect_provider,
    )
    PROVIDERS_AVAILABLE = True
except ImportError:
    PROVIDERS_AVAILABLE = False
    UnifiedLLMClient = None
    ProviderType = None
    ProviderConfig = None
    RetryPolicy = None
    create_client_from_env = None
    auto_detect_provider = None


T = TypeVar("T", bound=BaseModel)


# ============================================================
# GATEWAY CONFIGURATION
# ============================================================

class GatewayConfig(BaseModel):
    """Configuration for LLM Gateway."""
    # Provider
    provider_type: Optional[str] = None  # None = auto-detect
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None

    # Behavior
    default_temperature: float = 0.1
    default_max_tokens: int = 4000
    timeout_seconds: int = 120

    # Retry
    retry_policy: Optional[RetryPolicy] = None

    # Budget
    token_budget_per_mission: int = 500000
    token_budget_per_agent: int = 50000
    warn_threshold: float = 0.7
    hard_stop_threshold: float = 1.0

    # Structured output
    structured_output_mode: str = "json_schema"  # "json_schema" | "function_calling" | "prompt"

    # Observability
    log_requests: bool = True
    log_responses: bool = False  # May contain sensitive data
    emit_token_events: bool = True


# ============================================================
# TOKEN BUDGET
# ============================================================

class TokenBudget:
    """
    Token budget tracker with scopes.
    Scopes: global, project, mission, agent
    """

    def __init__(
        self,
        global_limit: int = 1000000,
        project_limit: int = 500000,
        mission_limit: int = 500000,
        agent_limit: int = 50000,
    ):
        self.limits = {
            "global": global_limit,
            "project": project_limit,
            "mission": mission_limit,
            "agent": agent_limit,
        }
        self.usage = {
            "global": 0,
            "project": 0,
            "mission": 0,
            "agent": 0,
        }
        self._warned = set()

    def consume(
        self,
        tokens: int,
        scope: str = "agent",
        mission_id: Optional[str] = None,
        project_id: Optional[str] = None,
        agent_type: Optional[str] = None,
    ) -> bool:
        """
        Consume tokens from budget.
        Returns True if within budget, False if exceeded.
        """
        if scope not in self.usage:
            scope = "agent"

        self.usage[scope] += tokens
        self.usage["global"] += tokens

        if scope == "mission" and mission_id:
            # Track per-mission
            if not hasattr(self, "_mission_usage"):
                self._mission_usage = {}
            self._mission_usage[mission_id] = self._mission_usage.get(mission_id, 0) + tokens

        if scope == "agent" and agent_type:
            if not hasattr(self, "_agent_usage"):
                self._agent_usage = {}
            self._agent_usage[agent_type] = self._agent_usage.get(agent_type, 0) + tokens

        return self.check_budget(scope)

    def check_budget(self, scope: str = "agent") -> bool:
        """Check if budget is exceeded for scope."""
        limit = self.limits.get(scope, self.limits["agent"])
        used = self.usage.get(scope, 0)
        return used < limit

    def get_utilization(self, scope: str = "agent") -> float:
        """Get budget utilization (0.0 to 1.0+)."""
        limit = self.limits.get(scope, self.limits["agent"])
        used = self.usage.get(scope, 0)
        if limit == 0:
            return 0.0
        return used / limit

    def get_remaining(self, scope: str = "agent") -> int:
        """Get remaining tokens for scope."""
        limit = self.limits.get(scope, self.limits["agent"])
        used = self.usage.get(scope, 0)
        return max(0, limit - used)

    def get_status(self) -> Dict[str, Any]:
        """Get full budget status."""
        return {
            "limits": self.limits,
            "usage": self.usage,
            "utilization": {k: self.get_utilization(k) for k in self.limits},
            "remaining": {k: self.get_remaining(k) for k in self.limits},
        }

    def reset_mission(self, mission_id: str) -> None:
        """Reset mission-scoped budget."""
        if hasattr(self, "_mission_usage"):
            self._mission_usage.pop(mission_id, None)

    def reset_agent(self, agent_type: str) -> None:
        """Reset agent-scoped budget."""
        if hasattr(self, "_agent_usage"):
            self._agent_usage.pop(agent_type, None)


# ============================================================
# LLM GATEWAY
# ============================================================

class LLMGateway:
    """
    Unified LLM Gateway for all agents.
    Single entry point for all LLM interactions.
    """

    def __init__(
        self,
        config: Optional[GatewayConfig] = None,
        token_budget: Optional[TokenBudget] = None,
        event_emitter: Optional[callable] = None,
    ):
        self.config = config or GatewayConfig()
        self.token_budget = token_budget or TokenBudget()
        self.event_emitter = event_emitter
        self._client: Optional[UnifiedLLMClient] = None
        self._initialized = False

    def initialize(self) -> None:
        """Initialize the underlying LLM client."""
        if self._initialized:
            return

        if not PROVIDERS_AVAILABLE:
            raise RuntimeError(
                "LLM providers not available. Ensure src/llm/providers.py is importable."
            )

        # Create client
        if self.config.provider_type and self.config.api_key:
            # Explicit configuration
            provider_config = ProviderConfig(
                provider=ProviderType(self.config.provider_type),
                model=self.config.model,
                api_key=self.config.api_key,
                base_url=self.config.base_url,
            )
            self._client = UnifiedLLMClient(provider_config)
        else:
            # Auto-detect from environment
            self._client = create_client_from_env()

        self._initialized = True

    @property
    def client(self) -> UnifiedLLMClient:
        """Get the underlying client, initializing if needed."""
        if not self._initialized:
            self.initialize()
        return self._client

    @property
    def provider_type(self) -> Optional[str]:
        """Get current provider type."""
        if self._client:
            return self._client.provider_config.provider.value
        return None

    @property
    def model(self) -> Optional[str]:
        """Get current model."""
        if self._client:
            return self._client.provider_config.model
        return None

    def structured_chat(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[T],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        mission_id: Optional[str] = None,
        agent_type: Optional[str] = None,
        scope: str = "agent",
    ) -> T:
        """
        Chat with structured output (Pydantic model).
        Enforces token budget and emits events.
        """
        if not self._initialized:
            self.initialize()

        # Check budget before request
        estimated_tokens = max_tokens or self.config.default_max_tokens
        if not self.token_budget.consume(
            estimated_tokens, scope, mission_id, agent_type=agent_type
        ):
            raise BudgetExceededError(
                f"Token budget exceeded for scope '{scope}'",
                scope=scope,
                utilization=self.token_budget.get_utilization(scope),
            )

        # Build request
        start_time = time.time()
        temp = temperature if temperature is not None else self.config.default_temperature
        max_tok = max_tokens or self.config.default_max_tokens

        try:
            # Call structured_chat on underlying client
            response = self.client.structured_chat(
                messages=messages,
                response_model=response_model,
                temperature=temp,
                max_tokens=max_tok,
            )

            # Calculate actual tokens (approximation)
            actual_tokens = self._estimate_tokens(messages, response)

            # Update budget with actual usage
            self.token_budget.consume(
                actual_tokens - estimated_tokens,  # Adjust for actual
                scope, mission_id, agent_type=agent_type
            )

            # Emit token usage event
            if self.config.emit_token_events and self.event_emitter:
                self._emit_token_event(
                    mission_id=mission_id,
                    agent_type=agent_type,
                    tokens_used=actual_tokens,
                    scope=scope,
                )

            return response

        except Exception as e:
            # Emit error event
            if self.event_emitter:
                self._emit_error_event(
                    mission_id=mission_id,
                    agent_type=agent_type,
                    error=str(e),
                )
            raise

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        mission_id: Optional[str] = None,
        agent_type: Optional[str] = None,
        scope: str = "agent",
    ) -> str:
        """Simple chat completion returning text."""
        if not self._initialized:
            self.initialize()

        estimated_tokens = max_tokens or self.config.default_max_tokens
        if not self.token_budget.consume(
            estimated_tokens, scope, mission_id, agent_type=agent_type
        ):
            raise BudgetExceededError(
                f"Token budget exceeded for scope '{scope}'",
                scope=scope,
                utilization=self.token_budget.get_utilization(scope),
            )

        start_time = time.time()
        temp = temperature if temperature is not None else self.config.default_temperature
        max_tok = max_tokens or self.config.default_max_tokens

        try:
            response = self.client.chat(
                messages=messages,
                temperature=temp,
                max_tokens=max_tok,
            )

            actual_tokens = self._estimate_tokens(messages, response)
            self.token_budget.consume(
                actual_tokens - estimated_tokens,
                scope, mission_id, agent_type=agent_type
            )

            if self.config.emit_token_events and self.event_emitter:
                self._emit_token_event(
                    mission_id=mission_id,
                    agent_type=agent_type,
                    tokens_used=actual_tokens,
                    scope=scope,
                )

            return response

        except Exception as e:
            if self.event_emitter:
                self._emit_error_event(
                    mission_id=mission_id,
                    agent_type=agent_type,
                    error=str(e),
                )
            raise

    def _estimate_tokens(self, messages: List[Dict], response: Any) -> int:
        """Rough token estimation (4 chars ≈ 1 token)."""
        total_chars = sum(len(m.get("content", "")) for m in messages)
        if isinstance(response, BaseModel):
            total_chars += len(response.model_dump_json())
        elif isinstance(response, str):
            total_chars += len(response)
        else:
            total_chars += len(str(response))
        return max(1, total_chars // 4)

    def _emit_token_event(
        self,
        mission_id: Optional[str],
        agent_type: Optional[str],
        tokens_used: int,
        scope: str,
    ) -> None:
        """Emit token usage event."""
        if not self.event_emitter:
            return

        event = FactoryEvent.create(
            event_type=EventType.TOKEN_USAGE,
            mission_id=mission_id or "unknown",
            payload=TokenUsageEvent(
                mission_id=mission_id or "unknown",
                agent_type=agent_type,
                tokens_used=tokens_used,
                cost_usd=self._estimate_cost(tokens_used),
                scope=scope,
            ),
            source="llm_gateway",
        )
        self.event_emitter(event)

    def _emit_error_event(
        self,
        mission_id: Optional[str],
        agent_type: Optional[str],
        error: str,
    ) -> None:
        """Emit system error event."""
        if not self.event_emitter:
            return

        from unified.event_catalog import SystemErrorEvent
        event = FactoryEvent.create(
            event_type=EventType.SYSTEM_ERROR,
            mission_id=mission_id or "unknown",
            payload=SystemErrorEvent(
                component="llm_gateway",
                error=error,
                severity="error",
                recoverable=True,
            ),
            source="llm_gateway",
        )
        self.event_emitter(event)

    def _estimate_cost(self, tokens: int) -> float:
        """Estimate cost in USD (rough approximation)."""
        # Very rough: $0.002 per 1K tokens for typical model
        return (tokens / 1000) * 0.002

    def get_budget_status(self) -> Dict[str, Any]:
        """Get current budget status."""
        return self.token_budget.get_status()

    def check_budget_warning(self, scope: str = "agent") -> Optional[Dict[str, Any]]:
        """Check if budget warning threshold reached."""
        util = self.token_budget.get_utilization(scope)
        if util >= self.config.warn_threshold:
            return {
                "scope": scope,
                "utilization": util,
                "threshold": self.config.warn_threshold,
                "remaining": self.token_budget.get_remaining(scope),
            }
        return None


# ============================================================
# EXCEPTIONS
# ============================================================

class BudgetExceededError(Exception):
    """Raised when token budget is exceeded."""

    def __init__(
        self,
        message: str,
        scope: str,
        utilization: float,
    ):
        self.scope = scope
        self.utilization = utilization
        super().__init__(message)


class ProviderNotConfiguredError(Exception):
    """Raised when no provider is configured."""
    pass


# ============================================================
# AGENT-SPECIFIC HELPERS
# ============================================================

class AgentLLMContext:
    """
    Context for an agent's LLM usage.
    Provides pre-configured structured_chat for agent contracts.
    """

    def __init__(
        self,
        gateway: LLMGateway,
        mission_id: str,
        agent_type: str,
        task_id: str,
    ):
        self.gateway = gateway
        self.mission_id = mission_id
        self.agent_type = agent_type
        self.task_id = task_id

    def structured_chat(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[T],
        **kwargs,
    ) -> T:
        """Structured chat with agent context."""
        return self.gateway.structured_chat(
            messages=messages,
            response_model=response_model,
            mission_id=self.mission_id,
            agent_type=self.agent_type,
            scope="agent",
            **kwargs,
        )

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Simple chat with agent context."""
        return self.gateway.chat(
            messages=messages,
            mission_id=self.mission_id,
            agent_type=self.agent_type,
            scope="agent",
            **kwargs,
        )

    def get_budget_remaining(self) -> int:
        """Get remaining token budget for this agent."""
        return self.gateway.token_budget.get_remaining("agent")


# ============================================================
# FACTORY FUNCTIONS
# ============================================================

def create_gateway(
    provider_type: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    **kwargs,
) -> LLMGateway:
    """Create LLMGateway with configuration."""
    config = GatewayConfig(
        provider_type=provider_type,
        model=model,
        api_key=api_key,
        **kwargs,
    )
    return LLMGateway(config=config)


def create_gateway_from_env() -> LLMGateway:
    """Create LLMGateway with auto-detected provider from environment."""
    return LLMGateway()


# ============================================================
# CONTRACT-SPECIFIC HELPERS
# ============================================================

# Import agent contract types for structured output
try:
    from unified.agent_contract import (
        ExplorationReport,
        Analysis,
        Plan,
        DesignSpec,
        Review,
        ImplementationResult,
        VerificationResult,
        ArbiterResult,
    )
    AGENT_CONTRACTS_AVAILABLE = True
except ImportError:
    AGENT_CONTRACTS_AVAILABLE = False
    ExplorationReport = None
    Analysis = None
    Plan = None
    DesignSpec = None
    Review = None
    ImplementationResult = None
    VerificationResult = None
    ArbiterResult = None


def get_explorer_schema() -> Optional[Type[BaseModel]]:
    """Get Explorer output schema."""
    return ExplorationReport


def get_analyst_schema() -> Optional[Type[BaseModel]]:
    """Get Analyst output schema."""
    return Analysis


def get_planner_schema() -> Optional[Type[BaseModel]]:
    """Get Planner output schema."""
    return Plan


def get_designer_schema() -> Optional[Type[BaseModel]]:
    """Get Designer output schema."""
    return DesignSpec


def get_reviewer_schema() -> Optional[Type[BaseModel]]:
    """Get Reviewer output schema."""
    return Review


def get_implementer_schema() -> Optional[Type[BaseModel]]:
    """Get Implementer output schema."""
    return ImplementationResult


def get_verifier_schema() -> Optional[Type[BaseModel]]:
    """Get Verifier output schema."""
    return VerificationResult


def get_arbiter_schema() -> Optional[Type[BaseModel]]:
    """Get Arbiter output schema."""
    return ArbiterResult


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "GatewayConfig",
    "TokenBudget",
    "LLMGateway",
    "AgentLLMContext",
    "BudgetExceededError",
    "ProviderNotConfiguredError",
    "create_gateway",
    "create_gateway_from_env",
    "get_explorer_schema",
    "get_analyst_schema",
    "get_planner_schema",
    "get_designer_schema",
    "get_reviewer_schema",
    "get_implementer_schema",
    "get_verifier_schema",
    "get_arbiter_schema",
]