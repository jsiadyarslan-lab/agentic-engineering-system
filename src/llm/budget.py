"""Token Budget & Cost Tracking — Phase 0.5

Tracks token usage per agent, per mission, per project.
Enforces hard limits with fail-closed behavior.
Integrates with substrate Evidence for audit trail.
"""

from __future__ import annotations

import threading
import time
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Dict, List
from collections import defaultdict

from .provider import LLMUsage


class BudgetScope(str, Enum):
    """Scope at which budget is enforced."""
    AGENT = "agent"           # Per-agent limit
    MISSION = "mission"       # Per-mission limit  
    PROJECT = "project"       # Per-project limit
    GLOBAL = "global"         # System-wide limit


class BudgetAction(str, Enum):
    """Action when budget is exceeded."""
    REJECT = "reject"         # Fail the request (fail-closed)
    WARN = "warn"             # Log warning but allow
    THROTTLE = "throttle"     # Delay until budget refreshes


class BudgetExceeded(Exception):
    """Raised when token budget is exceeded."""
    
    def __init__(
        self,
        scope: BudgetScope,
        scope_id: str,
        limit: int,
        used: int,
        requested: int,
        action: BudgetAction = BudgetAction.REJECT,
    ):
        self.scope = scope
        self.scope_id = scope_id
        self.limit = limit
        self.used = used
        self.requested = requested
        self.action = action
        
        super().__init__(
            f"Budget exceeded: {scope.value}/{scope_id} "
            f"({used + requested}/{limit} tokens). "
            f"Action: {action.value}"
        )


@dataclass(frozen=True)
class TokenLimit:
    """Token limit configuration for a scope."""
    max_tokens: int                    # Hard limit
    warning_threshold: float = 0.8     # Warn at 80%
    action: BudgetAction = BudgetAction.REJECT
    reset_interval_seconds: Optional[int] = None  # None = no auto-reset


@dataclass
class BudgetState:
    """Current state of a budget scope."""
    scope: BudgetScope
    scope_id: str
    limit: TokenLimit
    used_tokens: int = 0
    request_count: int = 0
    last_reset: float = field(default_factory=time.time)
    locked: bool = False
    # Evidence tracking
    evidence_log: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def remaining(self) -> int:
        return max(0, self.limit.max_tokens - self.used_tokens)
    
    @property
    def utilization(self) -> float:
        if self.limit.max_tokens == 0:
            return 0.0
        return self.used_tokens / self.limit.max_tokens
    
    @property
    def is_warning(self) -> bool:
        return self.utilization >= self.limit.warning_threshold
    
    @property
    def is_exceeded(self) -> bool:
        return self.used_tokens >= self.limit.max_tokens
    
    def can_accommodate(self, tokens: int) -> bool:
        return self.used_tokens + tokens <= self.limit.max_tokens
    
    def reset(self) -> None:
        self.used_tokens = 0
        self.request_count = 0
        self.last_reset = time.time()
        self.locked = False
        self.evidence_log.clear()
    
    def add_evidence(self, evidence_hash: str, tokens: int, operation: str) -> None:
        """Record evidence of token consumption."""
        self.evidence_log.append({
            "evidence_hash": evidence_hash,
            "tokens": tokens,
            "operation": operation,
            "timestamp": time.time(),
        })
    
    def get_evidence_log(self) -> List[Dict[str, Any]]:
        return list(self.evidence_log)


class TokenBudget:
    """Manages token budgets across multiple scopes.
    
    Thread-safe. Enforces limits fail-closed by default.
    Integrates with substrate Evidence for audit trail.
    """
    
    def __init__(
        self,
        default_limits: Optional[dict[BudgetScope, TokenLimit]] = None,
        global_limit: Optional[int] = None,
    ):
        self._lock = threading.RLock()
        self._budgets: dict[str, BudgetState] = {}
        
        # Default limits
        self.default_limits = default_limits or {
            BudgetScope.AGENT: TokenLimit(max_tokens=50000),
            BudgetScope.MISSION: TokenLimit(max_tokens=200000),
            BudgetScope.PROJECT: TokenLimit(max_tokens=1000000),
            BudgetScope.GLOBAL: TokenLimit(max_tokens=global_limit or 10000000),
        }
    
    def _budget_key(self, scope: BudgetScope, scope_id: str) -> str:
        return f"{scope.value}:{scope_id}"
    
    def _get_or_create_budget(self, scope: BudgetScope, scope_id: str) -> BudgetState:
        key = self._budget_key(scope, scope_id)
        if key not in self._budgets:
            limit = self.default_limits.get(scope, TokenLimit(max_tokens=1000000))
            self._budgets[key] = BudgetState(
                scope=scope,
                scope_id=scope_id,
                limit=limit,
            )
        return self._budgets[key]
    
    def _budget_key(self, scope: BudgetScope, scope_id: str) -> str:
        return f"{scope.value}:{scope_id}"
    
    def _get_or_create_budget(self, scope: BudgetScope, scope_id: str) -> BudgetState:
        key = self._budget_key(scope, scope_id)
        if key not in self._budgets:
            limit = self.default_limits.get(scope, TokenLimit(max_tokens=1000000))
            self._budgets[key] = BudgetState(
                scope=scope,
                scope_id=scope_id,
                limit=limit,
            )
        return self._budgets[key]
    
    def _budget_key(self, scope: BudgetScope, scope_id: str) -> str:
        return f"{scope.value}:{scope_id}"
    
    def _get_or_create_budget(self, scope: BudgetScope, scope_id: str) -> BudgetState:
        key = self._budget_key(scope, scope_id)
        if key not in self._budgets:
            limit = self.default_limits.get(scope, TokenLimit(max_tokens=1000000))
            self._budgets[key] = BudgetState(
                scope=scope,
                scope_id=scope_id,
                limit=limit,
            )
        return self._budgets[key]
    
    def _budget_key(self, scope: BudgetScope, scope_id: str) -> str:
        return f"{scope.value}:{scope_id}"
    
    def _get_or_create_budget(self, scope: BudgetScope, scope_id: str) -> BudgetState:
        key = self._budget_key(scope, scope_id)
        if key not in self._budgets:
            limit = self.default_limits.get(scope, TokenLimit(max_tokens=1000000))
            self._budgets[key] = BudgetState(
                scope=scope,
                scope_id=scope_id,
                limit=limit,
            )
        return self._budgets[key]
    
    def check_budget(
        self,
        estimated_tokens: int,
        scopes: list[tuple[BudgetScope, str]],
    ) -> bool:
        """Check if estimated tokens fit within all specified budgets.
        
        Args:
            estimated_tokens: Estimated tokens for the request
            scopes: List of (scope, scope_id) to check
            
        Returns:
            True if all budgets can accommodate
            
        Raises:
            BudgetExceeded: If any budget would be exceeded (fail-closed)
        """
        with self._lock:
            for scope, scope_id in scopes:
                budget = self._get_or_create_budget(scope, scope_id)
                if budget.locked:
                    raise BudgetExceeded(
                        scope, scope_id, budget.limit.max_tokens,
                        budget.used_tokens, estimated_tokens,
                        BudgetAction.REJECT,
                    )
                if not budget.can_accommodate(estimated_tokens):
                    if budget.limit.action == BudgetAction.REJECT:
                        raise BudgetExceeded(
                            scope, scope_id, budget.limit.max_tokens,
                            budget.used_tokens, estimated_tokens,
                            BudgetAction.REJECT,
                        )
                    elif budget.limit.action == BudgetAction.THROTTLE:
                        # In a real implementation, this would wait
                        raise BudgetExceeded(
                            scope, scope_id, budget.limit.max_tokens,
                            budget.used_tokens, estimated_tokens,
                            BudgetAction.THROTTLE,
                        )
            return True
    
    def consume(
        self,
        actual_usage: LLMUsage,
        scopes: list[tuple[BudgetScope, str]],
        evidence: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Record actual token usage against budgets.
        
        Args:
            actual_usage: Actual tokens used (from provider response)
            scopes: List of (scope, scope_id) to charge
            evidence: Optional evidence dict from substrate (evidence_hash, etc.)
            
        Returns:
            evidence_hash: SHA256 hash of the evidence for audit trail
        """
        # Create evidence record
        evidence_record = {
            "usage": actual_usage.__dict__,
            "scopes": [(s.value, sid) for s, sid in scopes],
            "timestamp": time.time(),
        }
        
        if evidence:
            evidence_record["substrate_evidence"] = evidence
        
        # Create evidence hash for audit trail
        evidence_json = json.dumps(evidence_record, sort_keys=True)
        evidence_hash = hashlib.sha256(evidence_json.encode()).hexdigest()
        
        with self._lock:
            for scope, scope_id in scopes:
                budget = self._get_or_create_budget(scope, scope_id)
                budget.used_tokens += actual_usage.total_tokens
                budget.request_count += 1
                # Record evidence
                budget.add_evidence(evidence_hash, actual_usage.total_tokens, "llm_usage")
        
        return evidence_hash
    
    def get_budget_state(
        self,
        scope: BudgetScope,
        scope_id: str,
    ) -> Optional[BudgetState]:
        """Get current state of a budget (read-only)."""
        with self._lock:
            key = self._budget_key(scope, scope_id)
            return self._budgets.get(key)
    
    def get_all_budgets(self) -> dict[str, BudgetState]:
        """Get all budget states."""
        with self._lock:
            return dict(self._budgets)
    
    def reset_budget(self, scope: BudgetScope, scope_id: str) -> bool:
        """Manually reset a budget."""
        with self._lock:
            key = self._budget_key(scope, scope_id)
            if key in self._budgets:
                self._budgets[key].reset()
                return True
            return False
    
    def set_limit(
        self,
        scope: BudgetScope,
        scope_id: str,
        limit: TokenLimit,
    ) -> None:
        """Set custom limit for a specific scope."""
        with self._lock:
            budget = self._get_or_create_budget(scope, scope_id)
            budget.limit = limit
    
    def lock_budget(self, scope: BudgetScope, scope_id: str) -> None:
        """Lock a budget (prevent further consumption)."""
        with self._lock:
            budget = self._get_or_create_budget(scope, scope_id)
            budget.locked = True
    
    def unlock_budget(self, scope: BudgetScope, scope_id: str) -> None:
        """Unlock a budget."""
        with self._lock:
            budget = self._get_or_create_budget(scope, scope_id)
            budget.locked = False

    def get_evidence_audit_trail(
        self,
        scope: BudgetScope,
        scope_id: str,
    ) -> List[Dict[str, Any]]:
        """Get full evidence audit trail for a budget."""
        with self._lock:
            key = self._budget_key(scope, scope_id)
            budget = self._budgets.get(key)
            if budget:
                return budget.get_evidence_log()
            return []


# Global budget manager instance
_global_budget: Optional[TokenBudget] = None


def get_global_budget() -> TokenBudget:
    """Get or create global budget manager."""
    global _global_budget
    if _global_budget is None:
        _global_budget = TokenBudget()
    return _global_budget


def set_global_budget(budget: TokenBudget) -> None:
    """Set global budget manager (for testing)."""
    global _global_budget
    _global_budget = budget


# Convenience functions for common scopes

def check_agent_budget(agent_id: str, estimated_tokens: int) -> bool:
    """Check agent-level budget."""
    return get_global_budget().check_budget(estimated_tokens, [(BudgetScope.AGENT, agent_id)])


def check_mission_budget(mission_id: str, estimated_tokens: int) -> bool:
    """Check mission-level budget."""
    return get_global_budget().check_budget(estimated_tokens, [(BudgetScope.MISSION, mission_id)])


def consume_agent_budget(agent_id: str, usage: LLMUsage, evidence: Optional[Dict[str, Any]] = None) -> str:
    """Record usage against agent budget with evidence."""
    return get_global_budget().consume(usage, [(BudgetScope.AGENT, agent_id)], evidence)


def consume_mission_budget(mission_id: str, usage: LLMUsage, evidence: Optional[Dict[str, Any]] = None) -> str:
    """Record usage against mission budget with evidence."""
    return get_global_budget().consume(usage, [(BudgetScope.MISSION, mission_id)], evidence)


# Token estimation utilities

# Rough token estimation constants
CHARS_PER_TOKEN = 4  # Approximate for English
TOKEN_OVERHEAD_PER_MESSAGE = 3  # Role + formatting overhead


def estimate_tokens(text: str, model: str = "default") -> int:
    """Estimate token count for text.
    
    Rough approximation: ~4 chars per token for English.
    For more accuracy, use tiktoken with the specific model.
    """
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_messages_tokens(messages: list[dict], model: str = "default") -> int:
    """Estimate tokens for a list of messages."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        total += estimate_tokens(content, model)
        total += TOKEN_OVERHEAD_PER_MESSAGE
    return total


def estimate_prompt_tokens(
    system_prompt: str,
    user_prompt: str,
    context: list[dict] = None,
    model: str = "default",
) -> int:
    """Estimate total tokens for a prompt."""
    total = estimate_tokens(system_prompt, model)
    total += estimate_tokens(user_prompt, model)
    if context:
        total += estimate_messages_tokens(context, model)
    return total


# Evidence utilities

def compute_evidence_hash(usage: LLMUsage, scopes: list[tuple], substrate_evidence: Optional[Dict] = None) -> str:
    """Compute SHA256 hash of evidence for audit trail."""
    evidence_record = {
        "usage": usage.__dict__,
        "scopes": [(s.value, sid) for s, sid in scopes],
        "timestamp": time.time(),
    }
    
    if substrate_evidence:
        evidence_record["substrate_evidence"] = substrate_evidence
    
    evidence_json = json.dumps(evidence_record, sort_keys=True)
    return hashlib.sha256(evidence_json.encode()).hexdigest()


def compute_substrate_evidence_hash(
    command: List[str],
    stdout: str,
    stderr: str,
    limits: Dict[str, Any],
    artifacts: List[Dict],
) -> str:
    """Compute SHA256 hash of substrate execution evidence."""
    evidence_record = {
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "limits": limits,
        "artifacts": artifacts,
        "timestamp": time.time(),
    }
    evidence_json = json.dumps(evidence_record, sort_keys=True)
    return hashlib.sha256(evidence_json.encode()).hexdigest()


# Token estimation utilities

# Rough token estimation constants
CHARS_PER_TOKEN = 4  # Approximate for English
TOKEN_OVERHEAD_PER_MESSAGE = 3  # Role + formatting overhead


def estimate_tokens(text: str, model: str = "default") -> int:
    """Estimate token count for text.
    
    Rough approximation: ~4 chars per token for English.
    For more accuracy, use tiktoken with the specific model.
    """
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_messages_tokens(messages: list[dict], model: str = "default") -> int:
    """Estimate tokens for a list of messages."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        total += estimate_tokens(content, model)
        total += TOKEN_OVERHEAD_PER_MESSAGE
    return total


def estimate_prompt_tokens(
    system_prompt: str,
    user_prompt: str,
    context: list[dict] = None,
    model: str = "default",
) -> int:
    """Estimate total tokens for a prompt."""
    total = estimate_tokens(system_prompt, model)
    total += estimate_tokens(user_prompt, model)
    if context:
        total += estimate_messages_tokens(context, model)
    return total