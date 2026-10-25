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
    ASSIGNED = "ASSIGNED"          # Assigned to a task (reserved)
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
# AGENT RESERVATION / OWNERSHIP (E15)
# ============================================================
@dataclass
class AgentReservation:
    """
    Represents an atomic reservation of an agent instance for a specific attempt.
    This is the ownership token that proves the scheduler owns this agent for this attempt.
    """
    reservation_id: str
    agent_id: str
    task_id: str
    attempt_id: str
    created_at: datetime
    owner: str = "execution_engine"  # Who created this reservation
    
    def is_owner(self, attempt_id: str) -> bool:
        """Check if the given attempt_id owns this reservation."""
        return self.attempt_id == attempt_id

# Global reservation store
_agent_reservations: Dict[str, AgentReservation] = {}  # reservation_id -> reservation
_agent_reservation_by_attempt: Dict[str, str] = {}  # attempt_id -> reservation_id
_agent_reservation_by_agent: Dict[str, str] = {}  # agent_id -> reservation_id


def create_reservation(
    agent_id: str,
    task_id: str,
    attempt_id: str,
    owner: str = "execution_engine"
) -> AgentReservation:
    """Create a new agent reservation."""
    import uuid
    reservation_id = f"res-{uuid.uuid4().hex[:12]}"
    reservation = AgentReservation(
        reservation_id=reservation_id,
        agent_id=agent_id,
        task_id=task_id,
        attempt_id=attempt_id,
        created_at=datetime.now(timezone.utc),
        owner=owner,
    )
    _agent_reservations[reservation_id] = reservation
    _agent_reservation_by_attempt[attempt_id] = reservation_id
    _agent_reservation_by_agent[agent_id] = reservation_id
    return reservation


def get_reservation(reservation_id: str) -> Optional[AgentReservation]:
    """Get reservation by ID."""
    return _agent_reservations.get(reservation_id)


def get_reservation_by_attempt(attempt_id: str) -> Optional[AgentReservation]:
    """Get reservation by attempt ID."""
    res_id = _agent_reservation_by_attempt.get(attempt_id)
    if res_id:
        return _agent_reservations.get(res_id)
    return None


def get_reservation_by_agent(agent_id: str) -> Optional[AgentReservation]:
    """Get reservation by agent ID."""
    res_id = _agent_reservation_by_agent.get(agent_id)
    if res_id:
        return _agent_reservations.get(res_id)
    return None


def release_reservation(attempt_id: str, owner: str = "execution_engine") -> bool:
    """
    Release agent reservation. Only the owner attempt can release.
    Returns True if released, False if not found or not owner.
    """
    reservation = get_reservation_by_attempt(attempt_id)
    if not reservation:
        return False
    if reservation.attempt_id != attempt_id:
        return False  # Not the owner
    # Clean up
    _agent_reservations.pop(reservation.reservation_id, None)
    _agent_reservation_by_attempt.pop(attempt_id, None)
    _agent_reservation_by_agent.pop(reservation.agent_id, None)
    return True


def is_agent_reserved(agent_id: str) -> bool:
    """Check if agent is currently reserved."""
    return agent_id in _agent_reservation_by_agent


def is_agent_available_for_reservation(agent_id: str) -> bool:
    """Check if agent can be reserved (AVAILABLE and not reserved)."""
    reservation = get_reservation_by_agent(agent_id)
    if reservation:
        return False
    # Also check lifecycle state
    return agent_registry._instance_states.get(agent_id) == AgentLifecycleState.AVAILABLE


def get_available_agents_for_reservation(agent_type: Optional[AgentType] = None) -> List[str]:
    """Get agent IDs that are AVAILABLE and not reserved."""
    available = []
    for agent_id, state in agent_registry._instance_states.items():
        if state == AgentLifecycleState.AVAILABLE and not is_agent_reserved(agent_id):
            defn = agent_registry._definitions.get(agent_id)
            if defn and defn.enabled:
                if agent_type is None or defn.agent_type == agent_type:
                    available.append(agent_id)
    return available


def clear_all_reservations() -> None:
    """Clear all reservations (for testing)."""
    _agent_reservations.clear()
    _agent_reservation_by_attempt.clear()
    _agent_reservation_by_agent.clear()
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
    # (AES-EXP-04) E9-R1 على سياق الوكيل أيضاً: التنفيذ الإنتاجي محكوم
    # عبر ToolExecutor؛ مسار المهمة (mission_controller) يقرأ الحقل
    # بـ getattr منذ E9-R1، لكن العقد القديم كان يحجبه فتتعطل كل دورة
    # مبنية على AgentContext عند بوابة E9-R1 بلا مخرج محكوم.
    tool_executor: Optional[Any] = None  # ToolExecutor
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
            {
                "agent_id": context.agent_id,
                "agent_type": self.agent_type.value,
                "mission_id": context.mission_id,
                "run_id": context.run_id,
                "task_id": task.task_id,
            },
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
                "agent_type": self.agent_type.value,
                "mission_id": context.mission_id,
                "run_id": context.run_id,
                "task_id": task.task_id,
                "success": result.success,
                "output_summary": str(result.output)[:200] if result.output else "",
                "evidence_hash": result.evidence_hash or "",
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
                "agent_type": self.agent_type.value,
                "mission_id": context.mission_id,
                "run_id": context.run_id,
                "task_id": task.task_id,
                "error": str(error),
                "error_type": type(error).__name__,
            },
        )
        self._context = None
        self._current_task = None
    # --- Input/Output validation (optional, default: no validation) ---
    def validate_input(self, task: AgentTask) -> List[str]:
        """Validate task input. Return list of errors (empty = valid)."""
        return []
    def validate_output(self, result: AgentResult) -> List[str]:
        """Validate agent output. Return list of errors (empty = valid)."""
        return []
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
    def select_agent_for_task(self, task: AgentTask, previous_agent_id: Optional[str] = None) -> Optional[AgentDefinition]:
        """Select agent for a task based on its agent_type and acceptance criteria."""
        # First try exact type match
        defn = self.get_definition_by_type(task.agent_type)
        if defn and defn.is_available() and defn.agent_id != previous_agent_id:
            return defn
        # Fall back to capability-based selection
        exclude = {previous_agent_id} if previous_agent_id else None
        return self.select_agent(
            required_tools=[],  # Would need to infer from acceptance criteria
            required_permissions=[],
            required_domains=[],
            exclude_agents=exclude,
        )

    # --- Atomic Reservation (E15) ---
    def reserve_agent(
        self,
        task_id: str,
        attempt_id: str,
        agent_type: Optional[AgentType] = None,
        exclude_agents: Optional[Set[str]] = None,
        owner: str = "execution_engine"
    ) -> Optional[AgentReservation]:
        """
        Atomically reserve an available agent instance.
        This combines selection + reservation in one atomic operation.
        Returns AgentReservation if successful, None if no agent available.
        
        Selection criteria (matching select_agent_for_task):
        1. If agent_type specified, prefer default agent for that type
        2. Must match agent_type if specified
        3. Must be AVAILABLE and not reserved
        4. Must be enabled
        5. Not excluded
        6. Highest max_tokens wins ties (capability-based fallback)
        
        On success: atomically transitions agent AVAILABLE -> ASSIGNED
        """
        exclude_agents = exclude_agents or set()
        
        # First try default agent for type
        if agent_type is not None:
            default_defn = self.get_definition_by_type(agent_type)
            if (default_defn and 
                default_defn.enabled and 
                default_defn.state == AgentLifecycleState.AVAILABLE and
                default_defn.agent_id not in exclude_agents and
                not is_agent_reserved(default_defn.agent_id)):
                
                # ATOMIC: Transition to ASSIGNED and create reservation
                self.set_lifecycle_state(default_defn.agent_id, AgentLifecycleState.ASSIGNED)
                reservation = create_reservation(
                    agent_id=default_defn.agent_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    owner=owner
                )
                return reservation
        
        # Fall back to capability-based selection
        candidates = []
        for defn in self._definitions.values():
            if defn.agent_id in exclude_agents:
                continue
            if not defn.enabled:
                continue
            if agent_type is not None and defn.agent_type != agent_type:
                continue
            # Check availability AND not reserved
            if defn.state != AgentLifecycleState.AVAILABLE:
                continue
            if is_agent_reserved(defn.agent_id):
                continue
            candidates.append(defn)
        
        if not candidates:
            return None
        
        # Deterministic: highest max_tokens, then lexicographically by agent_id
        candidates.sort(key=lambda d: (-d.max_tokens, d.agent_id))
        selected = candidates[0]
        
        # ATOMIC: Transition to ASSIGNED and create reservation
        # This is the critical section - no other thread can reserve this agent now
        self.set_lifecycle_state(selected.agent_id, AgentLifecycleState.ASSIGNED)
        
        reservation = create_reservation(
            agent_id=selected.agent_id,
            task_id=task_id,
            attempt_id=attempt_id,
            owner=owner
        )
        return reservation

    def reserve_specific_agent(
        self,
        agent_id: str,
        task_id: str,
        attempt_id: str,
        owner: str = "execution_engine"
    ) -> Optional[AgentReservation]:
        """
        Atomically reserve a specific agent by ID.
        Returns AgentReservation if successful, None if agent not available.
        """
        defn = self._definitions.get(agent_id)
        if not defn:
            return None
        if not defn.enabled:
            return None
        if defn.state != AgentLifecycleState.AVAILABLE:
            return None
        if is_agent_reserved(agent_id):
            return None
        
        # ATOMIC: Transition to ASSIGNED and create reservation
        self.set_lifecycle_state(agent_id, AgentLifecycleState.ASSIGNED)
        
        reservation = create_reservation(
            agent_id=agent_id,
            task_id=task_id,
            attempt_id=attempt_id,
            owner=owner
        )
        return reservation

    def release_agent_reservation(self, attempt_id: str, owner: str = "execution_engine") -> bool:
        """
        Release agent reservation and transition agent back to AVAILABLE.
        Only the owning attempt can release.
        """
        reservation = get_reservation_by_attempt(attempt_id)
        if not reservation:
            return False
        if reservation.attempt_id != attempt_id:
            return False
        
        agent_id = reservation.agent_id
        current_state = self._instance_states.get(agent_id)
        
        # Only release if agent is in a terminal or assigned state
        if current_state in (AgentLifecycleState.ASSIGNED, AgentLifecycleState.RUNNING, 
                            AgentLifecycleState.COMPLETED, AgentLifecycleState.FAILED):
            self.set_lifecycle_state(agent_id, AgentLifecycleState.AVAILABLE)
        
        return release_reservation(attempt_id, owner)
    # --- Implementation management ---
    def get_implementation(self, agent_type: AgentType) -> Optional[Type[AgentRole]]:
        """Get agent implementation class."""
        return self._implementations.get(agent_type)
    def create_instance(
        self,
        agent_type: AgentType,
        agent_id: Optional[str] = None,
    ) -> AgentRole:
        """Create agent instance. Does not overwrite existing lifecycle state if already ASSIGNED or higher."""
        agent_class = self.get_implementation(agent_type)
        if not agent_class:
            raise ValueError(f"No implementation registered for {agent_type}")
        instance = agent_class()
        if agent_id:
            self._instances[agent_id] = instance
            # Only set AVAILABLE if not already in a reserved/active state
            current_state = self._instance_states.get(agent_id)
            if current_state is None or current_state == AgentLifecycleState.REGISTERED:
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
        """Create agent by specific ID (legacy - use execute_agent for atomic reservation)."""
        defn = self.registry.get_definition(agent_id)
        if not defn:
            raise ValueError(f"Unknown agent: {agent_id}")
        # Allow agents that are AVAILABLE or ASSIGNED (reserved)
        # The reservation system prevents double-booking
        if defn.state not in (AgentLifecycleState.AVAILABLE, AgentLifecycleState.ASSIGNED):
            raise RuntimeError(f"Agent {agent_id} not available (state: {defn.state}, enabled: {defn.enabled})")
        if not defn.enabled:
            raise RuntimeError(f"Agent {agent_id} is disabled")
        agent = self.registry.create_instance(defn.agent_type, agent_id)
        # Update lifecycle - only transition if not already ASSIGNED
        current_state = self.registry.get_lifecycle_state(agent_id)
        if current_state == AgentLifecycleState.AVAILABLE:
            self.registry.set_lifecycle_state(agent_id, AgentLifecycleState.ASSIGNED)
        return agent
    
    async def execute_agent_by_id(
        self,
        agent_id: str,
        context: AgentContext,
        task: AgentTask,
    ) -> AgentResult:
        """
        Execute an already-reserved agent by ID.
        This is used when the caller has already reserved the agent via registry.reserve_agent().
        
        Args:
            agent_id: The reserved agent ID
            context: Execution context
            task: The task to execute
            
        Returns:
            AgentResult with success/failure
        """
        print(f"  [AgentFactory] execute_agent_by_id called: agent_id={agent_id}, task_id={task.task_id}, task.agent_type={task.agent_type}")
        
        defn = self.registry.get_definition(agent_id)
        if not defn:
            print(f"  [AgentFactory] ERROR: Unknown agent: {agent_id}")
            return AgentResult(
                task_id=task.task_id,
                agent_type=task.agent_type,
                success=False,
                error=f"Unknown agent: {agent_id}",
                error_type="AgentNotFound",
            )
        print(f"  [AgentFactory] Found agent definition: {defn.agent_id}, type={defn.agent_type}, state={defn.state}, enabled={defn.enabled}")
        # Allow agents that are ASSIGNED (reserved)
        if defn.state != AgentLifecycleState.ASSIGNED:
            return AgentResult(
                task_id=task.task_id,
                agent_type=defn.agent_type,
                success=False,
                error=f"Agent {agent_id} not in ASSIGNED state (state: {defn.state})",
                error_type="AgentStateError",
            )
        if not defn.enabled:
            return AgentResult(
                task_id=task.task_id,
                agent_type=defn.agent_type,
                success=False,
                error=f"Agent {agent_id} is disabled",
                error_type="AgentDisabled",
            )
        
        # Create agent instance
        print(f"  [AgentFactory] Creating instance for agent_type={defn.agent_type}, agent_id={agent_id}")
        agent_class = self.registry.get_implementation(defn.agent_type)
        print(f"  [AgentFactory] Implementation class: {agent_class}, module: {getattr(agent_class, '__module__', 'N/A')}, bases: {getattr(agent_class, '__bases__', 'N/A')}")
        agent = self.registry.create_instance(defn.agent_type, agent_id)
        print(f"  [AgentFactory] Created agent instance: {type(agent)}, has validate_input: {hasattr(agent, 'validate_input')}")
        
        # Validate input
        errors = agent.validate_input(task)
        if errors:
            # Release reservation on validation failure
            self.registry.release_agent_reservation(context.attempt_id)
            return AgentResult(
                task_id=task.task_id,
                agent_type=defn.agent_type,
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
            # Release reservation AFTER setting state to terminal
            self.registry.release_agent_reservation(context.attempt_id)
            return AgentResult(
                task_id=task.task_id,
                agent_type=defn.agent_type,
                success=False,
                error=f"{type(e).__name__}: {e}",
                error_type=type(e).__name__,
            )
        
        # Update lifecycle based on result BEFORE releasing reservation
        if result.success:
            self.registry.set_lifecycle_state(agent_id, AgentLifecycleState.COMPLETED)
            agent.on_complete(context, task, result)
        else:
            self.registry.set_lifecycle_state(agent_id, AgentLifecycleState.FAILED)
            agent.on_failed(context, task, Exception(result.error or "Unknown error"))
        
        # Release reservation AFTER setting terminal state
        self.registry.release_agent_reservation(context.attempt_id)
        
        # Validate output
        errors = agent.validate_output(result)
        if errors:
            return AgentResult(
                task_id=task.task_id,
                agent_type=defn.agent_type,
                success=False,
                error="; ".join(errors),
                error_type="OutputValidationError",
            )
        
        return result
    
    async def execute_agent_with_reservation(
        self,
        task: AgentTask,
        context: AgentContext,
        attempt_id: str,
        agent_type: Optional[AgentType] = None,
        previous_agent_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Execute agent with atomic reservation.
        This is the E15 atomic execution path.
        
        Args:
            task: The task to execute
            context: Execution context (must have attempt_id set)
            attempt_id: The attempt ID for ownership tracking
            agent_type: Optional agent type filter
            previous_agent_id: Agent to exclude (for retry)
        
        Returns:
            AgentResult with success/failure and ownership info
        """
        exclude = {previous_agent_id} if previous_agent_id else None
        target_type = agent_type or task.agent_type
        
        # ATOMIC: Reserve agent
        reservation = self.registry.reserve_agent(
            task_id=task.task_id,
            attempt_id=attempt_id,
            agent_type=target_type,
            exclude_agents=exclude,
        )
        
        if reservation is None:
            return AgentResult(
                task_id=task.task_id,
                agent_type=target_type,
                success=False,
                error="No available agent",
                error_type="AgentUnavailable",
            )
        
        agent_id = reservation.agent_id
        context.agent_id = agent_id
        
        # Create agent instance
        defn = self.registry.get_definition(agent_id)
        print(f"  [AgentFactory] Creating instance for agent_type={defn.agent_type}, agent_id={agent_id}")
        agent_class = self.registry.get_implementation(defn.agent_type)
        print(f"  [AgentFactory] Implementation class: {agent_class}, module: {getattr(agent_class, '__module__', 'N/A')}, bases: {getattr(agent_class, '__bases__', 'N/A')}")
        agent = self.registry.create_instance(defn.agent_type, agent_id)
        print(f"  [AgentFactory] Created agent instance: {type(agent)}, has validate_input: {hasattr(agent, 'validate_input')}")
        
        # Validate input
        errors = agent.validate_input(task)
        if errors:
            # Release reservation on validation failure
            self.registry.release_agent_reservation(attempt_id)
            return AgentResult(
                task_id=task.task_id,
                agent_type=defn.agent_type,
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
            # Release reservation
            self.registry.release_agent_reservation(attempt_id)
            return AgentResult(
                task_id=task.task_id,
                agent_type=defn.agent_type,
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
        
        # Release reservation (ownership transfer complete)
        self.registry.release_agent_reservation(attempt_id)
        
        return result

    async def execute_agent(
        self,
        agent_type: AgentType,
        context: AgentContext,
        task: AgentTask,
    ) -> AgentResult:
        """Create and execute agent in one call (legacy path)."""
        # Use atomic reservation if attempt_id is available
        if hasattr(context, 'attempt_id') and context.attempt_id:
            return await self.execute_agent_with_reservation(
                task=task,
                context=context,
                attempt_id=context.attempt_id,
                agent_type=agent_type,
            )
        
        # Legacy path for backward compatibility
        if context.agent_id:
            agent = self.create_agent_by_id(context.agent_id, context)
            agent_id = context.agent_id
        else:
            agent = self.create_agent(agent_type, context)
            agent_id = context.agent_id
            self.registry.set_lifecycle_state(agent_id, AgentLifecycleState.ASSIGNED)
        
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
        
        agent.on_start(context, task)
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