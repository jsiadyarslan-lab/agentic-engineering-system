"""
Unified Agent Role Protocol — Unified Engineering Agents System

Single protocol that ALL agents must implement.
Unifies AgentFactory agents (8) with EAS v2 roles (5).

Both systems' agents must implement this protocol for interoperability.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable, Type
from pydantic import BaseModel, Field

from unified.contracts import (
    AgentType,
    AgentTask,
    AgentResult,
    Grant,
    SandboxExecutionRecord,
    Artifact,
    EvidenceRecord,
    Verification,
    EventType,
    FactoryEvent,
)


# ============================================================
# AGENT CAPABILITIES
# ============================================================

@dataclass(frozen=True)
class AgentCapability:
    """What an agent can do."""
    tools: List[str] = field(default_factory=list)  # Tool names
    permissions: List[str] = field(default_factory=list)  # Grant permission classes
    max_tokens: int = 50000
    timeout_seconds: int = 300
    can_spawn_subtasks: bool = False
    requires_sandbox: bool = False
    supported_domains: List[str] = field(default_factory=list)


AGENT_CAPABILITIES: Dict[AgentType, AgentCapability] = {
    AgentType.EXPLORER: AgentCapability(
        tools=["read_file", "list_dir", "grep", "find_files", "web_search", "web_fetch", "file_browser"],
        permissions=["read"],
        max_tokens=50000,
        timeout_seconds=300,
        supported_domains=["codebase"],
    ),
    AgentType.ANALYST: AgentCapability(
        tools=["read_file", "llm"],
        permissions=["read"],
        max_tokens=50000,
        timeout_seconds=300,
        supported_domains=["codebase", "security"],
    ),
    AgentType.PLANNER: AgentCapability(
        tools=["read_file", "llm"],
        permissions=["read"],
        max_tokens=50000,
        timeout_seconds=300,
        can_spawn_subtasks=True,
        supported_domains=["codebase", "infrastructure"],
    ),
    AgentType.DESIGNER: AgentCapability(
        tools=["read_file", "llm", "write_file", "edit_file"],
        permissions=["read", "write"],
        max_tokens=50000,
        timeout_seconds=300,
        requires_sandbox=True,
        supported_domains=["codebase", "infrastructure", "data"],
    ),
    AgentType.REVIEWER: AgentCapability(
        tools=["read_file", "llm"],
        permissions=["read"],
        max_tokens=50000,
        timeout_seconds=300,
        supported_domains=["codebase", "security", "testing"],
    ),
    AgentType.IMPLEMENTER: AgentCapability(
        tools=["read_file", "write_file", "edit_file", "run_command", "llm", "git_diff", "git_status"],
        permissions=["read", "write", "execute"],
        max_tokens=100000,
        timeout_seconds=600,
        requires_sandbox=True,
        supported_domains=["codebase", "infrastructure", "testing", "deployment"],
    ),
    AgentType.VERIFIER: AgentCapability(
        tools=["read_file", "run_command", "grep", "llm", "verification_check"],
        permissions=["read", "execute"],
        max_tokens=50000,
        timeout_seconds=300,
        requires_sandbox=True,
        supported_domains=["codebase", "testing", "security"],
    ),
    AgentType.ARBITER: AgentCapability(
        tools=["llm"],
        permissions=[],
        max_tokens=20000,
        timeout_seconds=120,
        supported_domains=[],
    ),
}


# ============================================================
# AGENT CONTEXT
# ============================================================

@dataclass
class AgentContext:
    """Runtime context provided to agent."""
    mission_id: str
    run_id: str
    task_id: str
    attempt_id: str
    agent_id: str
    agent_type: AgentType

    # Grants held by this agent
    grant_ids: List[str] = field(default_factory=list)

    # Budget
    token_budget: int = 50000
    tokens_used: int = 0

    # Workspace
    workspace_root: str = "."
    sandbox_id: Optional[str] = None

    # LLM Gateway
    llm_gateway: Optional[Any] = None  # LLMGateway

    # Event emitter
    event_emitter: Optional[callable] = None

    # Sandbox manager
    sandbox_manager: Optional[Any] = None  # SandboxManager

    # Grant validator
    grant_validator: Optional[callable] = None

    # State
    context_summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# AGENT ROLE PROTOCOL
# ============================================================

@runtime_checkable
class AgentRole(Protocol):
    """
    Unified protocol for ALL agent roles.
    Both AgentFactory agents and EAS v2 roles implement this.

    Lifecycle:
    1. __init__(agent_type, capability) - Construction
    2. on_start(context, task) - Called before execution
    3. execute(context, task) -> AgentResult - Main execution
    4. on_complete(context, task, result) - Called on success
    5. on_failed(context, task, error) - Called on failure
    """

    # Identity (class attributes)
    agent_type: AgentType
    capability: AgentCapability
    version: str = "1.0"

    # Lifecycle hooks
    def on_start(self, context: AgentContext, task: AgentTask) -> None:
        """Called before agent execution starts."""
        ...

    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """Execute the agent's work. Returns AgentResult."""
        ...

    def on_complete(self, context: AgentContext, task: AgentTask, result: AgentResult) -> None:
        """Called after successful execution."""
        ...

    def on_failed(self, context: AgentContext, task: AgentTask, error: Exception) -> None:
        """Called when execution fails."""
        ...

    # Optional: custom validation
    def validate_input(self, task: AgentTask) -> List[str]:
        """Validate task input. Return list of errors (empty = valid)."""
        return []

    def validate_output(self, result: AgentResult) -> List[str]:
        """Validate agent output. Return list of errors (empty = valid)."""
        return []


# ============================================================
# BASE AGENT IMPLEMENTATION
# ============================================================

class BaseAgent:
    """
    Base implementation of AgentRole.
    Provides common functionality: events, budget, grants, sandbox.
    """

    def __init__(
        self,
        agent_type: AgentType,
        capability: Optional[AgentCapability] = None,
    ):
        self.agent_type = agent_type
        self.capability = capability or AGENT_CAPABILITIES.get(
            agent_type, AgentCapability()
        )
        self._context: Optional[AgentContext] = None
        self._current_task: Optional[AgentTask] = None

    @property
    def context(self) -> Optional[AgentContext]:
        return self._context

    @property
    def current_task(self) -> Optional[AgentTask]:
        return self._current_task

    # --- Lifecycle hooks (override in subclasses) ---

    def on_start(self, context: AgentContext, task: AgentTask) -> None:
        """Default: emit agent.started event."""
        self._context = context
        self._current_task = task
        self._emit_event(
            EventType.AGENT_STARTED,
            {"agent_id": context.agent_id, "task_id": task.task_id},
        )

    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """Must be implemented by subclass."""
        raise NotImplementedError("Subclass must implement execute()")

    def on_complete(self, context: AgentContext, task: AgentTask, result: AgentResult) -> None:
        """Default: emit agent.completed event."""
        self._emit_event(
            EventType.AGENT_COMPLETED,
            {
                "agent_id": context.agent_id,
                "task_id": task.task_id,
                "success": result.success,
                "evidence_hash": result.evidence_hash,
                "duration_ms": result.duration_ms,
            },
        )
        self._context = None
        self._current_task = None

    def on_failed(self, context: AgentContext, task: AgentTask, error: Exception) -> None:
        """Default: emit agent.failed event."""
        self._emit_event(
            EventType.AGENT_FAILED,
            {
                "agent_id": context.agent_id,
                "task_id": task.task_id,
                "error": str(error),
                "error_type": type(error).__name__,
            },
        )
        self._context = None
        self._current_task = None

    # --- Helper methods ---

    def _emit_event(self, event_type: EventType, payload: Dict[str, Any]) -> None:
        """Emit event via context's event emitter."""
        if self._context and self._context.event_emitter:
            event = FactoryEvent.create(
                event_type=event_type,
                mission_id=self._context.mission_id,
                run_id=self._context.run_id,
                payload=payload,
                source=f"agent.{self.agent_type.value}",
                correlation_id=self._context.task_id,
            )
            self._context.event_emitter(event)

    def _emit_tool_event(
        self,
        event_type: EventType,
        tool_name: str,
        action_id: str,
        payload: Dict[str, Any],
    ) -> None:
        """Emit tool event."""
        if self._context and self._context.event_emitter:
            event = FactoryEvent.create(
                event_type=event_type,
                mission_id=self._context.mission_id,
                run_id=self._context.run_id,
                payload={**payload, "tool_name": tool_name, "action_id": action_id},
                source=f"agent.{self.agent_type.value}",
                correlation_id=self._context.task_id,
            )
            self._context.event_emitter(event)

    def _consume_tokens(self, tokens: int) -> bool:
        """Consume tokens from budget. Returns False if exceeded."""
        if self._context:
            self._context.tokens_used += tokens
            remaining = self._context.token_budget - self._context.tokens_used
            if remaining < 0:
                return False
        return True

    def _check_budget(self) -> bool:
        """Check if budget remaining."""
        if self._context:
            return self._context.tokens_used < self._context.token_budget
        return True

    def _validate_grant(self, grant_id: str, required_permission: str) -> bool:
        """Validate grant via context's validator."""
        if self._context and self._context.grant_validator:
            return self._context.grant_validator(grant_id, required_permission)
        return False  # Fail closed

    async def _run_in_sandbox(
        self,
        command: List[str],
        image: str = "python:3.11-slim",
        working_dir: str = "/workspace",
        artifacts_dir: str = "/artifacts",
        **kwargs,
    ) -> SandboxExecutionRecord:
        """Run command in sandbox via sandbox manager."""
        if not self._context or not self._context.sandbox_manager:
            raise RuntimeError("Sandbox manager not available")

        from unified.domain_model import new_sandbox_id, SandboxRequest
        from unified.sandbox import SandboxManager

        sandbox_id = new_sandbox_id()
        request = SandboxRequest(
            sandbox_id=sandbox_id,
            image=image,
            command=command,
            working_dir=working_dir,
            artifacts_dir=artifacts_dir,
            required_grant_ids=self._context.grant_ids if self._context else [],
            **kwargs,
        )

        # Emit tool started
        action_id = f"action-{__import__('uuid').uuid4().hex[:8]}"
        self._emit_tool_event(
            EventType.TOOL_STARTED,
            tool_name="run_command",
            action_id=action_id,
            payload={"command": command, "sandbox_id": sandbox_id},
        )

        # Execute
        record = await self._context.sandbox_manager.execute(request)

        # Emit tool completed/failed
        if record.exit_code == 0:
            self._emit_tool_event(
                EventType.TOOL_COMPLETED,
                tool_name="run_command",
                action_id=action_id,
                payload={
                    "success": True,
                    "exit_code": record.exit_code,
                    "duration_ms": record.duration_ms,
                    "artifacts": record.artifacts,
                },
            )
        else:
            self._emit_tool_event(
                EventType.TOOL_FAILED,
                tool_name="run_command",
                action_id=action_id,
                payload={
                    "success": False,
                    "exit_code": record.exit_code,
                    "error": f"Exit code {record.exit_code}",
                    "duration_ms": record.duration_ms,
                },
            )

        return record

    async def _write_artifact(self, path: str, content: bytes) -> Artifact:
        """Write artifact to sandbox."""
        if not self._context or not self._context.sandbox_manager:
            raise RuntimeError("Sandbox manager not available")
        if not self._context.sandbox_id:
            raise RuntimeError("No sandbox_id in context")

        return await self._context.sandbox_manager.write_artifact(
            self._context.sandbox_id, path, content
        )

    async def _read_artifact(self, path: str) -> bytes:
        """Read artifact from sandbox."""
        if not self._context or not self._context.sandbox_manager:
            raise RuntimeError("Sandbox manager not available")
        if not self._context.sandbox_id:
            raise RuntimeError("No sandbox_id in context")

        return await self._context.sandbox_manager.read_artifact(
            self._context.sandbox_id, path
        )

    def _structured_chat(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[BaseModel],
        **kwargs,
    ) -> BaseModel:
        """Call LLM with structured output."""
        if not self._context or not self._context.llm_gateway:
            raise RuntimeError("LLM gateway not available")

        from unified.llm_gateway import AgentLLMContext
        agent_llm = AgentLLMContext(
            gateway=self._context.llm_gateway,
            mission_id=self._context.mission_id,
            agent_type=self.agent_type.value,
            task_id=self._context.task_id,
        )
        return agent_llm.structured_chat(messages, response_model, **kwargs)


# ============================================================
# AGENT REGISTRY
# ============================================================

class AgentRegistry:
    """Registry of all agent implementations."""

    def __init__(self):
        self._agents: Dict[AgentType, Type[AgentRole]] = {}
        self._instances: Dict[str, AgentRole] = {}

    def register(self, agent_type: AgentType, agent_class: Type[AgentRole]) -> None:
        """Register agent class for type."""
        if agent_type in self._agents:
            raise ValueError(f"Agent type {agent_type} already registered")
        self._agents[agent_type] = agent_class

    def unregister(self, agent_type: AgentType) -> None:
        """Unregister agent type."""
        self._agents.pop(agent_type, None)

    def get_class(self, agent_type: AgentType) -> Optional[Type[AgentRole]]:
        """Get agent class."""
        return self._agents.get(agent_type)

    def create_instance(
        self,
        agent_type: AgentType,
        agent_id: Optional[str] = None,
    ) -> AgentRole:
        """Create agent instance."""
        agent_class = self.get_class(agent_type)
        if not agent_class:
            raise ValueError(f"No agent registered for {agent_type}")

        instance = agent_class()
        if agent_id:
            self._instances[agent_id] = instance
        return instance

    def get_instance(self, agent_id: str) -> Optional[AgentRole]:
        """Get agent instance by ID."""
        return self._instances.get(agent_id)

    def list_registered(self) -> List[AgentType]:
        """List all registered agent types."""
        return list(self._agents.keys())

    def validate_all_registered(self) -> List[str]:
        """Check if all 8 agent types are registered. Returns missing."""
        all_types = set(AgentType)
        registered = set(self._agents.keys())
        missing = all_types - registered
        return [t.value for t in missing]


# Global registry
agent_registry = AgentRegistry()


# ============================================================
# AGENT FACTORY (for creating agents with context)
# ============================================================

class AgentFactory:
    """Factory for creating configured agent instances."""

    def __init__(self, registry: Optional[AgentRegistry] = None):
        self.registry = registry or agent_registry

    def create_agent(
        self,
        agent_type: AgentType,
        context: AgentContext,
    ) -> AgentRole:
        """Create agent with context injected."""
        agent = self.registry.create_instance(agent_type)
        # Context is passed at execution time, not construction
        return agent

    async def execute_agent(
        self,
        agent_type: AgentType,
        context: AgentContext,
        task: AgentTask,
    ) -> AgentResult:
        """Create and execute agent in one call."""
        agent = self.create_agent(agent_type, context)

        # Validate input
        errors = agent.validate_input(task)
        if errors:
            return AgentResult(
                task_id=task.task_id,
                agent_type=agent_type,
                success=False,
                error="; ".join(errors),
                error_type="ValidationError",
            )

        # Execute with lifecycle
        agent.on_start(context, task)
        try:
            result = await agent.execute(context, task)
        except Exception as e:
            agent.on_failed(context, task, e)
            return AgentResult(
                task_id=task.task_id,
                agent_type=agent_type,
                success=False,
                error=str(e),
                error_type=type(e).__name__,
            )

        # Validate output
        errors = agent.validate_output(result)
        if errors:
            result.success = False
            result.error = "; ".join(errors)
            result.error_type = "ValidationError"

        if result.success:
            agent.on_complete(context, task, result)
        else:
            agent.on_failed(context, task, Exception(result.error or "Validation failed"))

        return result


# ============================================================
# ADAPTER FOR EAS v2 ROLES
# ============================================================

class EASRoleAdapter(BaseAgent):
    """
    Adapter to wrap EAS v2 role classes (Thinker, Reviewer, etc.)
    into the unified AgentRole protocol.
    """

    def __init__(self, agent_type: AgentType, eas_role_instance: Any):
        capability = AGENT_CAPABILITIES.get(agent_type, AgentCapability())
        super().__init__(agent_type, capability)
        self.eas_role = eas_role_instance

    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """Delegate to EAS v2 role."""
        # Convert AgentTask to EAS v2 format
        # This is adapter-specific
        raise NotImplementedError("EASRoleAdapter requires concrete implementation")


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "AgentCapability",
    "AGENT_CAPABILITIES",
    "AgentContext",
    "AgentRole",
    "BaseAgent",
    "AgentRegistry",
    "agent_registry",
    "AgentFactory",
    "EASRoleAdapter",
]