"""
Unified Agent Role Protocol — Unified Engineering Agents System
Single protocol that ALL agents must implement.
Unifies AgentFactory agents (8) with EAS v2 roles (5).
Both systems' agents must implement this protocol for interoperability.
"""
from __future__ import annotations
import abc
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable, Type, Set
from pydantic import BaseModel, Field, field_validator
import uuid
from unified.domain_model import (
    AgentType,
    EventType,
)
from unified.agent_contract import (
    AgentTask,
    AgentResult,
    Grant,
    SandboxExecutionRecord,
    Artifact,
    EvidenceRecord,
    Verification,
)
from unified.event_catalog import FactoryEvent
# ============================================================
# AGENT LIFECYCLE STATE MACHINE
# ============================================================
class AgentLifecycleState(str, Enum):
    """Agent lifecycle states."""
    REGISTERED = "REGISTERED"      # Definition registered, not yet available
    AVAILABLE = "AVAILABLE"        # Ready for assignment
    ASSIGNED = "ASSIGNED"          # Assigned to a task
    RUNNING = "RUNNING"            # Currently executing
    COMPLETED = "COMPLETED"        # Last execution succeeded
    FAILED = "FAILED"              # Last execution failed
    DISABLED = "DISABLED"          # Explicitly disabled
AGENT_LIFECYCLE_TRANSITIONS: Dict[AgentLifecycleState, Set[AgentLifecycleState]] = {
    AgentLifecycleState.REGISTERED: {AgentLifecycleState.AVAILABLE, AgentLifecycleState.DISABLED},
    AgentLifecycleState.AVAILABLE: {AgentLifecycleState.ASSIGNED, AgentLifecycleState.DISABLED},
    AgentLifecycleState.ASSIGNED: {AgentLifecycleState.RUNNING, AgentLifecycleState.AVAILABLE, AgentLifecycleState.FAILED, AgentLifecycleState.COMPLETED},
    AgentLifecycleState.RUNNING: {AgentLifecycleState.COMPLETED, AgentLifecycleState.FAILED},
    AgentLifecycleState.COMPLETED: {AgentLifecycleState.AVAILABLE, AgentLifecycleState.DISABLED},
    AgentLifecycleState.FAILED: {AgentLifecycleState.AVAILABLE, AgentLifecycleState.DISABLED},
    AgentLifecycleState.DISABLED: {AgentLifecycleState.AVAILABLE},
}
def validate_agent_lifecycle_transition(
    from_state: AgentLifecycleState,
    to_state: AgentLifecycleState
) -> None:
    """Validate agent lifecycle state transition."""
    allowed = AGENT_LIFECYCLE_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise ValueError(f"Invalid agent lifecycle transition: {from_state} -> {to_state}")
# ============================================================
# AGENT DEFINITION CONTRACT
# ============================================================
class AgentDefinition(BaseModel):
    """
    Serializable, versioned, validated agent definition.
    This is the contract for what an agent IS (not an instance).
    """
    agent_id: str = Field(default_factory=lambda: f"agent-{uuid.uuid4().hex[:8]}")
    agent_type: AgentType
    name: str
    version: str = "1.0"
    description: str = ""
    # Capabilities (override defaults)
    tools: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    max_tokens: int = 50000
    timeout_seconds: int = 300
    can_spawn_subtasks: bool = False
    requires_sandbox: bool = False
    supported_domains: List[str] = Field(default_factory=list)
    # Implementation
    implementation_class: str = ""  # Fully qualified class name
    # Lifecycle
    state: AgentLifecycleState = AgentLifecycleState.REGISTERED
    enabled: bool = True
    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)
    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if not v:
            raise ValueError("version cannot be empty")
        return v
    @field_validator("implementation_class")
    @classmethod
    def validate_implementation_class(cls, v: str) -> str:
        if not v:
            raise ValueError("implementation_class cannot be empty")
        return v
    def to_capability(self) -> "AgentCapability":
        """Convert to AgentCapability."""
        return AgentCapability(
            tools=self.tools,
            permissions=self.permissions,
            max_tokens=self.max_tokens,
            timeout_seconds=self.timeout_seconds,
            can_spawn_subtasks=self.can_spawn_subtasks,
            requires_sandbox=self.requires_sandbox,
            supported_domains=self.supported_domains,
        )
    def is_available(self) -> bool:
        """Check if agent is available for assignment."""
        return self.enabled and self.state == AgentLifecycleState.AVAILABLE
    def can_execute(self) -> bool:
        """Check if agent can execute."""
        return self.enabled and self.state in {
            AgentLifecycleState.AVAILABLE,
            AgentLifecycleState.ASSIGNED,
        }
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
    # Evidence store
    evidence_store: Optional[Any] = None  # EvidenceStore
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
    4. on_failed(context, task, error) - Called on failure
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
    # --- Tool permission enforcement ---
    def _check_tool_permission(self, tool_name: str) -> bool:
        """Check if agent has permission to use tool."""
        return tool_name in self.capability.tools
    def _require_tool_permission(self, tool_name: str) -> None:
        """Enforce tool permission. Raises if not allowed."""
        if not self._check_tool_permission(tool_name):
            raise PermissionError(
                f"Agent {self.agent_type.value} not permitted to use tool: {tool_name}. "
                f"Allowed: {self.capability.tools}"
            )
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
# ENHANCED AGENT REGISTRY
# ============================================================
class AgentSelectionError(Exception):
    """Raised when agent selection fails."""
    pass
class AgentRegistry:
    """
    Registry of all agent definitions and implementations.
    Supports:
    - Agent definition registration (serializable, versioned)
    - Capability-based deterministic selection
    - Lifecycle state management
    - Tool permission enforcement
    - Disabled/unknown agent handling
    """
    def __init__(self):
        self._definitions: Dict[str, AgentDefinition] = {}  # agent_id -> definition
        self._type_to_definition: Dict[AgentType, str] = {}  # agent_type -> agent_id (default)
        self._implementations: Dict[AgentType, Type[AgentRole]] = {}
        self._instances: Dict[str, AgentRole] = {}  # agent_id -> instance
        self._instance_states: Dict[str, AgentLifecycleState] = {}  # agent_id -> lifecycle state
    # --- Definition management ---
    def register_definition(self, definition: AgentDefinition) -> None:
        """Register agent definition."""
        if definition.agent_id in self._definitions:
            raise ValueError(f"Agent definition {definition.agent_id} already exists")
        if definition.agent_type in self._type_to_definition:
            raise ValueError(f"Agent type {definition.agent_type} already has a default definition")
        self._definitions[definition.agent_id] = definition
        self._type_to_definition[definition.agent_type] = definition.agent_id
        self._instance_states[definition.agent_id] = AgentLifecycleState.REGISTERED
    def replace_definition(self, definition: AgentDefinition) -> None:
        """Replace agent definition (for testing only)."""
        # Remove old default mapping for this type
        old_agent_id = self._type_to_definition.get(definition.agent_type)
        if old_agent_id and old_agent_id != definition.agent_id:
            # Safe delete - ignore if already removed
            self._definitions.pop(old_agent_id, None)
        self._definitions[definition.agent_id] = definition
        self._type_to_definition[definition.agent_type] = definition.agent_id
        self._instance_states[definition.agent_id] = AgentLifecycleState.REGISTERED
    def add_definition(self, definition: AgentDefinition) -> None:
        """Add additional agent definition for same type (doesn't change default)."""
        if definition.agent_id in self._definitions:
            raise ValueError(f"Agent definition {definition.agent_id} already exists")
        self._definitions[definition.agent_id] = definition
        # Don't change _type_to_definition - keeps original default
        self._instance_states[definition.agent_id] = AgentLifecycleState.REGISTERED
    def register_implementation(
        self,
        agent_type: AgentType,
        agent_class: Type[AgentRole]
    ) -> None:
        """Register agent implementation class."""
        if agent_type in self._implementations:
            raise ValueError(f"Agent type {agent_type} already has implementation")
        self._implementations[agent_type] = agent_class
    def replace_implementation(
        self,
        agent_type: AgentType,
        agent_class: Type[AgentRole]
    ) -> None:
        """Replace agent implementation class (for testing only)."""
        self._implementations[agent_type] = agent_class
    def get_definition(self, agent_id: str) -> Optional[AgentDefinition]:
        """Get agent definition by ID."""
        return self._definitions.get(agent_id)
    def get_definition_by_type(self, agent_type: AgentType) -> Optional[AgentDefinition]:
        """Get default definition for agent type."""
        agent_id = self._type_to_definition.get(agent_type)
        if agent_id:
            return self._definitions.get(agent_id)
        return None
    def list_definitions(self) -> List[AgentDefinition]:
        """List all registered definitions."""
        return list(self._definitions.values())
    def list_available_agents(self) -> List[AgentDefinition]:
        """List agents available for assignment."""
        return [
            d for d in self._definitions.values()
            if d.is_available()
        ]
    # --- Capability-based selection ---
    def select_agent(
        self,
        required_tools: List[str],
        required_permissions: List[str],
        required_domains: Optional[List[str]] = None,
        exclude_agents: Optional[Set[str]] = None,
    ) -> Optional[AgentDefinition]:
        """
        Deterministic agent selection based on capabilities.
        Selection criteria (in order):
        1. Must have all required tools
        2. Must have all required permissions
        3. Must support required domains (if specified)
        4. Must be available (enabled, AVAILABLE state)
        5. Not excluded
        6. Highest max_tokens (more capable) wins ties
        """
        exclude_agents = exclude_agents or set()
        candidates = []
        for defn in self.list_available_agents():
            if defn.agent_id in exclude_agents:
                continue
            # Check tools
            if required_tools and not all(t in defn.tools for t in required_tools):
                continue
            # Check permissions
            if required_permissions and not all(p in defn.permissions for p in required_permissions):
                continue
            # Check domains
            if required_domains and not all(d in defn.supported_domains for d in required_domains):
                continue
            candidates.append(defn)
        if not candidates:
            return None
        # Deterministic: highest max_tokens, then lexicographically by agent_id
        candidates.sort(key=lambda d: (-d.max_tokens, d.agent_id))
        return candidates[0]
    def select_agent_for_task(self, task: AgentTask) -> Optional[AgentDefinition]:
        """Select agent for a task based on its agent_type and acceptance criteria."""
        # First try exact type match
        defn = self.get_definition_by_type(task.agent_type)
        if defn and defn.is_available():
            return defn
        # Fall back to capability-based selection
        return self.select_agent(
            required_tools=[],  # Would need to infer from acceptance criteria
            required_permissions=[],
            required_domains=[],
        )
    # --- Implementation management ---
    def get_implementation(self, agent_type: AgentType) -> Optional[Type[AgentRole]]:
        """Get agent implementation class."""
        return self._implementations.get(agent_type)
    def create_instance(
        self,
        agent_type: AgentType,
        agent_id: Optional[str] = None,
    ) -> AgentRole:
        """Create agent instance."""
        agent_class = self.get_implementation(agent_type)
        if not agent_class:
            raise ValueError(f"No implementation registered for {agent_type}")
        instance = agent_class()
        if agent_id:
            self._instances[agent_id] = instance
            self._instance_states[agent_id] = AgentLifecycleState.AVAILABLE
        return instance
    def get_instance(self, agent_id: str) -> Optional[AgentRole]:
        """Get agent instance by ID."""
        return self._instances.get(agent_id)
    # --- Lifecycle management ---
    def get_lifecycle_state(self, agent_id: str) -> Optional[AgentLifecycleState]:
        """Get agent lifecycle state."""
        return self._instance_states.get(agent_id)
    def set_lifecycle_state(self, agent_id: str, state: AgentLifecycleState) -> None:
        """Set agent lifecycle state with validation."""
        current = self._instance_states.get(agent_id)
        if current is None:
            raise ValueError(f"Unknown agent: {agent_id}")
        validate_agent_lifecycle_transition(current, state)
        self._instance_states[agent_id] = state
        # Update definition if it exists
        if agent_id in self._definitions:
            self._definitions[agent_id].state = state
            self._definitions[agent_id].updated_at = datetime.now(timezone.utc)
    def enable_agent(self, agent_id: str) -> None:
        """Enable agent (REGISTERED -> AVAILABLE)."""
        defn = self._definitions.get(agent_id)
        if not defn:
            raise ValueError(f"Unknown agent: {agent_id}")
        if defn.state == AgentLifecycleState.DISABLED:
            self.set_lifecycle_state(agent_id, AgentLifecycleState.AVAILABLE)
            defn.enabled = True
            defn.updated_at = datetime.now(timezone.utc)
        elif defn.state == AgentLifecycleState.REGISTERED:
            self.set_lifecycle_state(agent_id, AgentLifecycleState.AVAILABLE)
            defn.enabled = True
            defn.updated_at = datetime.now(timezone.utc)
    def disable_agent(self, agent_id: str) -> None:
        """Disable agent (any -> DISABLED)."""
        defn = self._definitions.get(agent_id)
        if not defn:
            raise ValueError(f"Unknown agent: {agent_id}")
        self.set_lifecycle_state(agent_id, AgentLifecycleState.DISABLED)
        defn.enabled = False
        defn.updated_at = datetime.now(timezone.utc)
    def validate_all_registered(self) -> List[str]:
        """Check if all 8 agent types have definitions. Returns missing."""
        all_types = set(AgentType)
        registered = set(self._type_to_definition.keys())
        missing = all_types - registered
        return [t.value for t in missing]
    def validate_all_implemented(self) -> List[str]:
        """Check if all 8 agent types have implementations. Returns missing."""
        all_types = set(AgentType)
        implemented = set(self._implementations.keys())
        missing = all_types - implemented
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
    def create_agent_by_id(
        self,
        agent_id: str,
        context: AgentContext,
    ) -> AgentRole:
        """Create agent by specific ID."""
        defn = self.registry.get_definition(agent_id)
        if not defn:
            raise ValueError(f"Unknown agent: {agent_id}")
        if not defn.is_available():
            raise RuntimeError(f"Agent {agent_id} not available (state: {defn.state}, enabled: {defn.enabled})")
        agent = self.registry.create_instance(defn.agent_type, agent_id)
        # Update lifecycle
        self.registry.set_lifecycle_state(agent_id, AgentLifecycleState.ASSIGNED)
        return agent
    async def execute_agent(
        self,
        agent_type: AgentType,
        context: AgentContext,
        task: AgentTask,
    ) -> AgentResult:
        """Create and execute agent in one call."""
        # Use create_agent_by_id if agent_id is already set in context (for retry/reuse)
        if context.agent_id:
            agent = self.create_agent_by_id(context.agent_id, context)
            agent_id = context.agent_id
            # create_agent_by_id already sets lifecycle to ASSIGNED
        else:
            agent = self.create_agent(agent_type, context)
            # Get the agent_id from the created agent
            agent_id = context.agent_id
            # Set lifecycle to ASSIGNED
            self.registry.set_lifecycle_state(agent_id, AgentLifecycleState.ASSIGNED)
        # Validate input
        errors = agent.validate_input(task)
        if errors:
            self.registry.set_lifecycle_state(agent_id, AgentLifecycleState.FAILED)
            return AgentResult(
                task_id=task.task_id,
                agent_type=agent_type,
                success=False,
                error="; ".join(errors),
                error_type="ValidationError",
            )
        # Execute with lifecycle
        agent.on_start(context, task)
        # Transition to RUNNING
        self.registry.set_lifecycle_state(agent_id, AgentLifecycleState.RUNNING)
        try:
            result = await agent.execute(context, task)
        except Exception as e:
            agent.on_failed(context, task, e)
            self.registry.set_lifecycle_state(agent_id, AgentLifecycleState.FAILED)
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
            self.registry.set_lifecycle_state(agent_id, AgentLifecycleState.COMPLETED)
        else:
            agent.on_failed(context, task, Exception(result.error or "Validation failed"))
            self.registry.set_lifecycle_state(agent_id, AgentLifecycleState.FAILED)
        return result
    async def execute_agent_by_id(
        self,
        agent_id: str,
        context: AgentContext,
        task: AgentTask,
    ) -> AgentResult:
        """Create and execute specific agent by ID."""
        agent = self.create_agent_by_id(agent_id, context)
        # Validate input
        errors = agent.validate_input(task)
        if errors:
            return AgentResult(
                task_id=task.task_id,
                agent_type=agent.agent_type,
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
            self.registry.set_lifecycle_state(agent_id, AgentLifecycleState.FAILED)
            return AgentResult(
                task_id=task.task_id,
                agent_type=agent.agent_type,
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
            self.registry.set_lifecycle_state(agent_id, AgentLifecycleState.COMPLETED)
        else:
            agent.on_failed(context, task, Exception(result.error or "Validation failed"))
            self.registry.set_lifecycle_state(agent_id, AgentLifecycleState.FAILED)
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
    # Lifecycle
    "AgentLifecycleState",
    "AGENT_LIFECYCLE_TRANSITIONS",
    "validate_agent_lifecycle_transition",
    # Definition
    "AgentDefinition",
    # Capability
    "AgentCapability",
    "AGENT_CAPABILITIES",
    # Context
    "AgentContext",
    # Protocol
    "AgentRole",
    # Base
    "BaseAgent",
    # Registry
    "AgentRegistry",
    "agent_registry",
    "AgentSelectionError",
    # Factory
    "AgentFactory",
    # Adapter
    "EASRoleAdapter",
]