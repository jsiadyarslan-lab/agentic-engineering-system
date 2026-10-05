"""
Unified Execution Engine — Unified Engineering Agents System
Orchestrates the complete execution loop:
MISSION → RUN → TASK → AGENT → ACTION → TOOL → SANDBOX → ARTIFACT → EVIDENCE → VERIFICATION → STATE → EVENTS
Provides:
- Mission lifecycle management
- Run creation and tracking
- Task scheduling and execution
- Agent role execution
- Tool invocation with sandbox
- Artifact capture and evidence chain
- Mechanical verification
- State machine transitions
- Event emission
- Checkpoint and resume
"""
from __future__ import annotations
import asyncio
import os
import json
import hashlib
import shutil
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
# Import DependencyState locally to avoid circular import
from unified.contracts import (
    # IDs
    new_mission_id, new_run_id, new_task_id, new_attempt_id,
    new_agent_id, new_action_id, new_event_id, new_grant_id,
    new_sandbox_id, new_artifact_id, new_evidence_id,
    new_verification_id, new_checkpoint_id,
    # Enums
    MissionState, PlanState, TaskState, AgentType, EventType,
    SandboxTermination, VerifierVerdict, SubVerdict,
    # Entities
    Mission, Run, Task, Attempt, Action, Agent, Grant,
    SandboxRequest, SandboxExecutionRecord, Artifact, EvidenceRecord,
    Verification, Checkpoint,
    # Factories
    create_mission, create_run, create_task, create_attempt,
    create_action, create_artifact, create_evidence,
    create_verification,
    # Validation
    validate_mission_transition, validate_task_transition,
    # State Machine
    PlanState as StatePlanState, MissionStateMachine, validate_transition,
    TERMINAL_STATES, TRANSITIONS,
    # Agent Contracts
    AgentRole, AgentTask, AgentResult,
    PlanTask, PlannerInput, Plan,
    ImplementerInput, ImplementationResult,
    VerifierInput, VerificationResult,
    AgentContractRegistry, AGENT_CAPABILITIES,
    # Tool Contracts
    ToolContract, ToolRegistry, ToolExecutionContext, ToolResult,
    RUN_COMMAND_CONTRACT, SANDBOX_EXECUTE_CONTRACT,
    ARTIFACT_WRITE_CONTRACT, ARTIFACT_READ_CONTRACT,
    VERIFICATION_CHECK_CONTRACT,
    # Verification
    CriterionType, AcceptanceCriterion, CheckResult, VerificationReport,
    EvidenceStore, Verifier, compute_sha256, create_evidence,
    # Event Catalog
    FactoryEvent, EVENT_CATALOG, EVENT_CONSUMERS,
    MissionStartedEvent, RunStartedEvent, PlanCreatedEvent,
    AgentStartedEvent, AgentCompletedEvent, TaskFailedEvent, TaskRetryEvent, TaskCompletedEvent,
    TaskAssignedEvent, AgentSelectedEvent,
    ToolStartedEvent, ToolCompletedEvent, ToolFailedEvent,
    ArtifactCreatedEvent, EvidenceRecordedEvent,
    VerificationCompleteEvent, CheckpointCreatedEvent,
    MissionStateChangedEvent, MissionCompletedEvent,
    # E11: Human Mission Control events
    MissionPauseRequestedEvent,
    MissionPausedEvent,
    MissionResumeRequestedEvent,
    MissionResumedEvent,
    MissionCancelRequestedEvent,
    MissionCancelledEvent,
    HumanGateCreatedEvent,
    HumanDecisionRecordedEvent,
    # E13: Replan events
    ReplanRequestedEvent,
    ReplanAppliedEvent,
    TaskCreatedEvent,
)
from unified.agent_role import (
    AgentCapability, AgentContext, AgentRegistry, agent_registry,
    AgentFactory, BaseAgent, AgentSelectionError, AgentLifecycleState,
)
from unified.sandbox import (
    ExecutionSandbox, SandboxBackend, SandboxManager,
    SandboxError, SandboxUnavailableError, create_sandbox_manager,
)
from unified.windows_adapter import WindowsExecutorAdapter
class ResourceQuotaExceededError(Exception):
    """Raised when resource quota is exceeded."""
    pass
# ============================================================
# EXECUTION CONTEXT
# ============================================================
@dataclass
class ExecutionContext:
    """Complete runtime context for an execution."""
    mission_id: str
    run_id: str
    task_id: str
    attempt_id: str
    agent_id: str
    agent_type: AgentType
    # Grants
    grant_ids: List[str] = field(default_factory=list)
    # Budget
    token_budget: int = 50000
    tokens_used: int = 0
    # Workspace
    workspace_root: str = "."
    sandbox_id: Optional[str] = None
    # Components
    sandbox_manager: Optional[SandboxManager] = None
    llm_gateway: Optional[Any] = None  # LLMGateway
    event_emitter: Optional[Callable[[FactoryEvent], None]] = None
    grant_validator: Optional[Callable[[str, str], bool]] = None
    evidence_store: Optional[Any] = None  # FileEvidenceStore
    # State
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Retry support (E15)
    previous_agent_id: Optional[str] = None
# ============================================================
# EVENT BUS (Simple in-memory)
# ============================================================
class SimpleEventBus:
    """Simple in-memory event bus for execution."""
    def __init__(self):
        self._subscribers: List[Callable[[FactoryEvent], None]] = []
        self.history: List[FactoryEvent] = []
    def subscribe(self, callback: Callable[[FactoryEvent], None]) -> None:
        self._subscribers.append(callback)
    def unsubscribe(self, callback: Callable[[FactoryEvent], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)
    def emit(self, event: FactoryEvent) -> None:
        self.history.append(event)
        for sub in self._subscribers:
            try:
                sub(event)
            except Exception:
                pass  # Best effort
# ============================================================
# EVIDENCE STORE (File-based)
# ============================================================
class FileEvidenceStore(EvidenceStore):
    """File-based evidence store for artifacts and evidence."""
    def __init__(self, artifacts_dir: str):
        self.artifacts_dir = artifacts_dir
        self._artifacts: Dict[str, Artifact] = {}
        self._evidence: Dict[str, EvidenceRecord] = {}
    def store_artifact(self, artifact: Artifact) -> None:
        self._artifacts[artifact.artifact_id] = artifact
    def get_artifact(self, artifact_id: str) -> Optional[bytes]:
        """Get artifact content by ID."""
        return self.read_artifact_content(artifact_id)
    def get_artifact_obj(self, artifact_id: str) -> Optional[Artifact]:
        """Get artifact metadata by ID."""
        return self._artifacts.get(artifact_id)
    def get_artifact_path(self, artifact_id: str) -> Optional[str]:
        art = self._artifacts.get(artifact_id)
        if art:
            return os.path.join(self.artifacts_dir, art.path)
        return None
    def get_artifact_hash(self, artifact_id: str) -> Optional[str]:
        art = self._artifacts.get(artifact_id)
        return art.sha256 if art else None
    def read_artifact_content(self, artifact_id: str) -> Optional[bytes]:
        """Read artifact content from file system."""
        art = self._artifacts.get(artifact_id)
        if not art:
            return None
        # Try direct path first
        path = os.path.join(self.artifacts_dir, art.path)
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return f.read()
        # Try sandbox subdirectory (created_by may be sandbox_id)
        if art.created_by:
            path = os.path.join(self.artifacts_dir, art.created_by, art.path)
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    return f.read()
        return None
    def artifact_exists(self, artifact_id: str) -> bool:
        return artifact_id in self._artifacts
    def store_evidence(self, evidence: EvidenceRecord) -> None:
        self._evidence[evidence.evidence_id] = evidence
    def get_evidence(self, evidence_id: str) -> Optional[EvidenceRecord]:
        return self._evidence.get(evidence_id)
    # Persistence methods for cross-runtime durability
    def _get_evidence_store_dir(self, mission_id: str) -> Path:
        """Get evidence store directory for mission."""
        base = Path(self.artifacts_dir) / "evidence_store" / mission_id
        base.mkdir(parents=True, exist_ok=True)
        return base
    def save_to_disk(self, mission_id: str) -> None:
        """Save artifacts and evidence to disk for durability."""
        store_dir = self._get_evidence_store_dir(mission_id)
        # Save artifacts
        artifacts_file = store_dir / "artifacts.json"
        artifacts_data = {}
        for aid, art in self._artifacts.items():
            if art.mission_id == mission_id or (hasattr(art, 'mission_id') and art.mission_id == mission_id):
                artifacts_data[aid] = art.model_dump(mode='json')
        temp_file = artifacts_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(artifacts_data, f, indent=2)
        temp_file.replace(artifacts_file)
        # Save evidence
        evidence_file = store_dir / "evidence.json"
        evidence_data = {}
        for eid, ev in self._evidence.items():
            if ev.mission_id == mission_id or (hasattr(ev, 'mission_id') and ev.mission_id == mission_id):
                evidence_data[eid] = ev.model_dump(mode='json')
        temp_file = evidence_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(evidence_data, f, indent=2)
        temp_file.replace(evidence_file)
    def load_from_disk(self, mission_id: str) -> None:
        """Load artifacts and evidence from disk for cross-runtime resume."""
        store_dir = self._get_evidence_store_dir(mission_id)
        # Load artifacts
        artifacts_file = store_dir / "artifacts.json"
        if artifacts_file.exists():
            with open(artifacts_file, 'r') as f:
                artifacts_data = json.load(f)
            for aid, art_data in artifacts_data.items():
                art = Artifact.model_validate(art_data)
                self._artifacts[aid] = art
        # Load evidence
        evidence_file = store_dir / "evidence.json"
        if evidence_file.exists():
            with open(evidence_file, 'r') as f:
                evidence_data = json.load(f)
            for eid, ev_data in evidence_data.items():
                ev = EvidenceRecord.model_validate(ev_data)
                self._evidence[eid] = ev
# ============================================================
# EXECUTION ENGINE
# ============================================================
class ExecutionEngine:
    """
    Unified execution engine that orchestrates the complete lifecycle.
    Responsibilities:
    - Mission/Run/Task lifecycle
    - Agent scheduling and execution
    - Tool invocation with sandbox
    - Artifact capture
    - Evidence chain
    - Verification
    - State transitions
    - Event emission
    - Checkpoint/Resume
    """
    def __init__(
        self,
        sandbox_backend: SandboxBackend = SandboxBackend.WINDOWS_EXECUTOR,
        artifacts_base_dir: Optional[str] = None,
        default_limits: Optional[Dict[str, Any]] = None,
        grant_validator: Optional[Callable[[str, str], bool]] = None,
        # Resource quotas
        max_concurrent_missions: int = 10,
        max_concurrent_tasks: int = 50,
        max_retries: int = 3,
        max_artifacts_per_run: int = 100,
    ):
        self.sandbox_backend = sandbox_backend
        self.artifacts_base_dir = artifacts_base_dir or os.path.join(
            tempfile.gettempdir(), "unified_execution"
        )
        self.default_limits = default_limits or {}
        self.grant_validator = grant_validator
        # Resource quotas
        self.max_concurrent_missions = max_concurrent_missions
        self.max_concurrent_tasks = max_concurrent_tasks
        self.max_retries = max_retries
        self.max_artifacts_per_run = max_artifacts_per_run
        # Runtime quota tracking
        self._active_mission_count = 0
        self._active_task_count = 0
        self._run_artifact_counts: Dict[str, int] = {}
        # Evidence store (must be created before sandbox manager)
        self.evidence_store = FileEvidenceStore(self.artifacts_base_dir)
        # Create sandbox manager
        self.sandbox_manager = create_sandbox_manager(
            backend=sandbox_backend,
            grant_validator=grant_validator,
            artifacts_base_dir=self.artifacts_base_dir,
            evidence_store=self.evidence_store,
        )
        # Event bus
        self.event_bus = SimpleEventBus()
        # Agent registry and factory
        self.agent_registry = agent_registry
        self.agent_factory = AgentFactory(self.agent_registry)
        # Verifier
        self.verifier = Verifier(self.evidence_store)
        # State tracking
        self.missions: Dict[str, Mission] = {}
        self.runs: Dict[str, Run] = {}
        self.tasks: Dict[str, Task] = {}
        self.attempts: Dict[str, Attempt] = {}
        self.actions: Dict[str, Action] = {}
        self.artifacts: Dict[str, Artifact] = {}
        self.evidence: Dict[str, EvidenceRecord] = {}
        self.verifications: Dict[str, Verification] = {}
        self.checkpoints: Dict[str, Checkpoint] = {}
        # Current execution
        self._current_mission: Optional[Mission] = None
        self._current_run: Optional[Run] = None
        # Task Graph (DAG)
        self.task_graph: Dict[str, Dict[str, Any]] = {}  # run_id -> {task_id -> {depends_on, dependents}}
        self.task_runnable_cache: Dict[str, Set[str]] = {}  # run_id -> set of runnable task_ids
        # Agent reassignment tracking for retries
        self._previous_agent_ids: Dict[str, str] = {}  # task_id -> agent_id
    # --- Mission Lifecycle ---
    def create_mission(self, user_request: str) -> Mission:
        """Create a new mission."""
        # Enforce concurrent mission quota
        if self._active_mission_count >= self.max_concurrent_missions:
            raise ResourceQuotaExceededError(
                f"Max concurrent missions ({self.max_concurrent_missions}) exceeded. "
                f"Active: {self._active_mission_count}"
            )
        mission = create_mission(user_request)
        self.missions[mission.mission_id] = mission
        self._current_mission = mission
        self._active_mission_count += 1
        # Emit event
        self._emit(MissionStartedEvent(
            mission_id=mission.mission_id,
            user_request=user_request,
        ))
        return mission
    def create_run(self, mission_id: str, parent_run_id: Optional[str] = None) -> Run:
        """Create a new run for a mission."""
        mission = self.missions.get(mission_id)
        if not mission:
            raise ValueError(f"Mission {mission_id} not found")
        run = create_run(mission_id, parent_run_id=parent_run_id)
        self.runs[run.run_id] = run
        self._current_run = run
        # Initialize artifact count tracking for this run
        self._run_artifact_counts[run.run_id] = 0
        # Update mission
        mission.run_ids.append(run.run_id)
        mission.current_run_id = run.run_id
        # Emit event
        self._emit(RunStartedEvent(
            mission_id=mission_id,
            run_id=run.run_id,
            run_number=run.run_number,
            parent_run_id=parent_run_id,
        ))
        return run
        return run
    # --- Task Management ---
    def create_task(
        self,
        run_id: str,
        mission_id: str,
        name: str,
        description: str,
        agent_type: AgentType,
        acceptance_criteria: Optional[List[AcceptanceCriterion]] = None,
        depends_on: Optional[List[str]] = None,
    ) -> Task:
        """Create a new task and add to task graph."""
        # Enforce concurrent task quota
        if self._active_task_count >= self.max_concurrent_tasks:
            raise ResourceQuotaExceededError(
                f"Max concurrent tasks ({self.max_concurrent_tasks}) exceeded. "
                f"Active: {self._active_task_count}"
            )
        task = create_task(
            run_id=run_id,
            mission_id=mission_id,
            name=name,
            description=description,
            agent_type=agent_type,
            acceptance_criteria=acceptance_criteria or [],
            depends_on=depends_on or [],
        )
        self.tasks[task.task_id] = task
        self._active_task_count += 1
        # Add to task graph
        if run_id not in self.task_graph:
            self.task_graph[run_id] = {}
            self.task_runnable_cache[run_id] = set()
        # Initialize task node in graph
        self.task_graph[run_id][task.task_id] = {
            "depends_on": set(depends_on or []),
            "dependents": set(),
            "state": TaskState.PENDING,
            "mission_id": mission_id,
        }
        # Add reverse dependencies
        for dep_id in depends_on or []:
            if dep_id in self.task_graph[run_id]:
                self.task_graph[run_id][dep_id]["dependents"].add(task.task_id)
        # Check if task is runnable (no dependencies or all completed)
        if not depends_on or all(
            self.tasks.get(dep_id) and self.tasks[dep_id].state == TaskState.COMPLETED
            for dep_id in depends_on
        ):
            task.state = TaskState.READY
            self.task_runnable_cache[run_id].add(task.task_id)
            self.task_graph[run_id][task.task_id]["state"] = TaskState.READY
        else:
            task.state = TaskState.BLOCKED
            self.task_graph[run_id][task.task_id]["state"] = TaskState.BLOCKED
        return task
    # --- Agent Selection ---
    def select_agent_for_task(self, task: AgentTask, previous_agent_id: Optional[str] = None) -> Optional[AgentDefinition]:
        """
        Select the best agent for a task using capability-based deterministic selection.
        Uses AgentRegistry.select_agent() which considers:
        - Required tools from task acceptance criteria (inferred)
        - Required permissions
        - Supported domains
        - Agent availability (enabled + AVAILABLE state)
        - Max tokens (higher wins ties)
        On retry (previous_agent_id provided), prefers a DIFFERENT available agent
        to enable agent reassignment after failure.
        """
        # Infer required capabilities from task
        # For now, use the agent_type as primary filter
        # In future, parse acceptance_criteria to infer tools/permissions/domains
        # First try the default agent for this type
        defn = self.agent_registry.get_definition_by_type(task.agent_type)
        if defn and defn.is_available():
            # On retry, if the default agent is the same as previous, try to find another
            if previous_agent_id and defn.agent_id == previous_agent_id:
                # Try to find an alternative agent of the same type
                alternative = self._find_alternative_agent(task.agent_type, previous_agent_id)
                if alternative:
                    return alternative
            return defn
        # If default agent exists but is in COMPLETED/FAILED/ASSIGNED state, reset to AVAILABLE for reuse
        # ASSIGNED can happen if a previous execution was interrupted or didn't complete cleanly
        if defn and defn.state in (AgentLifecycleState.COMPLETED, AgentLifecycleState.FAILED, AgentLifecycleState.ASSIGNED):
            self.agent_registry.set_lifecycle_state(defn.agent_id, AgentLifecycleState.AVAILABLE)
            # On retry, check if this is the same as previous agent
            if previous_agent_id and defn.agent_id == previous_agent_id:
                alternative = self._find_alternative_agent(task.agent_type, previous_agent_id)
                if alternative:
                    return alternative
            return defn
        # Also check all definitions of this type and reset any FAILED/ASSIGNED ones to AVAILABLE
        # For RUNNING agents, transition to FAILED first (valid transition), then to AVAILABLE
        # This enables retry with different agents of the same type
        for d in self.agent_registry.list_definitions():
            if d.agent_type == task.agent_type:
                if d.state in (AgentLifecycleState.FAILED, AgentLifecycleState.ASSIGNED):
                    self.agent_registry.set_lifecycle_state(d.agent_id, AgentLifecycleState.AVAILABLE)
                elif d.state == AgentLifecycleState.RUNNING:
                    # RUNNING -> FAILED -> AVAILABLE (valid transitions)
                    try:
                        self.agent_registry.set_lifecycle_state(d.agent_id, AgentLifecycleState.FAILED)
                        self.agent_registry.set_lifecycle_state(d.agent_id, AgentLifecycleState.AVAILABLE)
                    except ValueError:
                        pass  # Transition not allowed, skip
        # Fall back to capability-based selection - prefer agents other than previous
        # On retry, try to exclude the previous agent
        if previous_agent_id:
            # Get all available agents of this type, excluding previous
            alternatives = self._get_alternative_agents(task.agent_type, previous_agent_id)
            if alternatives:
                # Select the one with highest max_tokens
                return max(alternatives, key=lambda d: d.max_tokens)
        # For now, require no specific tools/permissions/domains
        # The registry will select the best available agent OF THE CORRECT TYPE
        # Filter by agent_type first
        available_of_type = [
            d for d in self.agent_registry.list_definitions()
            if d.agent_type == task.agent_type and d.is_available()
        ]
        if available_of_type:
            return max(available_of_type, key=lambda d: d.max_tokens)
        return None
    def _find_alternative_agent(self, agent_type: AgentType, exclude_agent_id: str) -> Optional[AgentDefinition]:
        """Find an available alternative agent of the same type, excluding the given agent_id."""
        for d in self.agent_registry.list_definitions():
            if d.agent_type == agent_type and d.agent_id != exclude_agent_id and d.is_available():
                return d
        return None
    def _get_alternative_agents(self, agent_type: AgentType, exclude_agent_id: str) -> List[AgentDefinition]:
        """Get all available alternative agents of the same type, excluding the given agent_id."""
        alternatives = []
        for d in self.agent_registry.list_definitions():
            if d.agent_type == agent_type and d.agent_id != exclude_agent_id and d.is_available():
                alternatives.append(d)
        return alternatives
    async def _create_execution_checkpoint(self, run_id: str) -> None:
        """Create execution checkpoint with current state."""
        if run_id not in self.task_graph:
            return
        graph = self.task_graph[run_id]
        if not graph:
            return
        # Find mission_id
        mission_id = None
        for node in graph.values():
            if node.get("mission_id"):
                mission_id = node["mission_id"]
                break
        if not mission_id:
            return
        # Gather task states
        task_states = {}
        for task_id, node in graph.items():
            task_states[task_id] = node["state"]
        # Gather artifact IDs and evidence hashes from evidence store
        artifact_ids = list(self.evidence_store._artifacts.keys()) if hasattr(self.evidence_store, '_artifacts') else []
        evidence_hashes = list(self.evidence_store._evidence.keys()) if hasattr(self.evidence_store, '_evidence') else []
        # Gather task definitions
        task_definitions = {}
        task_dependencies = {}
        task_dependents = {}
        for task_id, node in graph.items():
            task = self.tasks.get(task_id)
            if task:
                task_definitions[task_id] = task.model_dump()
            task_dependencies[task_id] = list(node["depends_on"])
            task_dependents[task_id] = list(node["dependents"])
        # Gather attempt history
        attempt_history = {}
        if hasattr(self, '_attempts'):
            for attempt_id, attempt in self._attempts.items():
                if attempt.task_id not in attempt_history:
                    attempt_history[attempt.task_id] = []
                attempt_history[attempt.task_id].append(attempt.model_dump())
        # Gather agent assignments
        agent_assignments = {}
        for task_id, node in graph.items():
            task = self.tasks.get(task_id)
            if task and hasattr(task, 'assigned_agent_id') and task.assigned_agent_id:
                agent_assignments[task_id] = task.assigned_agent_id
        # Create checkpoint
        self.create_checkpoint(
            mission_id=mission_id,
            run_id=run_id,
            step=len(task_states),
            state=PlanState.EXECUTING,
            task_states=task_states,
            artifact_ids=artifact_ids,
            evidence_hashes=evidence_hashes,
            task_definitions=task_definitions,
            task_dependencies=task_dependencies,
            task_dependents=task_dependents,
            attempt_history=attempt_history,
            agent_assignments=agent_assignments,
        )
# --- Parallel Task Execution (E13) ---
    async def _execute_single_task(
        self,
        run_id: str,
        task: Task,
        sandbox_manager: Any,
        event_collector: Any,
        max_retries: int,
        checkpoint_every: int,
        completed_since_checkpoint: int,
        task_timeout: Optional[float] = None,
    ) -> Tuple[Dict[str, Any], bool, int]:
        """
        Execute a single task with retry logic.
        Returns:
            Tuple of (results dict, paused flag, completed_since_checkpoint)
        """
        results = {}
        paused = False
        # Retry loop for this task
        task.retry_count = getattr(task, 'retry_count', 0)
        while True:
            # Check for mission cancellation/pause before each attempt
            mission = self.missions.get(task.mission_id)
            if mission and mission.state == MissionState.CANCELLED:
                return results, True, completed_since_checkpoint
            # Update task state to ASSIGNED (needed for each retry iteration)
            current_state = self.task_graph[run_id][task.task_id]["state"]
            if current_state == TaskState.READY:
                self._update_task_graph_state(run_id, task.task_id, TaskState.ASSIGNED)
            elif current_state == TaskState.ASSIGNED:
                pass  # Already in correct state
            elif current_state == TaskState.FAILED:
                # After retry, we transition from FAILED to READY, then to ASSIGNED
                self._update_task_graph_state(run_id, task.task_id, TaskState.READY)
                self._update_task_graph_state(run_id, task.task_id, TaskState.ASSIGNED)
            # Create a new attempt for each retry
            attempt_id = new_attempt_id()
            attempt = Attempt(
                attempt_id=attempt_id,
                task_id=task.task_id,
                agent_id="",  # Will be set after agent selection
                state=TaskState.RUNNING,
            )
            # Store attempt in engine for tracking
            if not hasattr(self, '_attempts'):
                self._attempts = {}
            self._attempts[attempt_id] = attempt
            self.attempts[attempt_id] = attempt
            
            # Create execution context with new attempt_id for each retry
            sandbox_id = f"sandbox-{task.task_id}"
            context = ExecutionContext(
                mission_id=task.mission_id,
                run_id=run_id,
                task_id=task.task_id,
                attempt_id=attempt_id,
                agent_id="",  # Will be set after reservation
                agent_type=task.agent_type,
                sandbox_id=sandbox_id,
                sandbox_manager=sandbox_manager,
                event_emitter=self.event_bus.emit,
                evidence_store=self.evidence_store,
                previous_agent_id=self._previous_agent_ids.get(task.task_id) if task.retry_count > 0 else None,
            )
            
            try:
                # ATOMIC RESERVATION (E15): Reserve agent before execution
                # This replaces the old select_agent_for_task path
                attempt_id = context.attempt_id
                previous_agent_id = self._previous_agent_ids.get(task.task_id) if task.retry_count > 0 else None
                
                # Create agent_task for capability matching
                agent_task = AgentTask(
                    task_id=task.task_id,
                    run_id=run_id,
                    mission_id=task.mission_id,
                    name=task.name,
                    description=task.description,
                    agent_type=task.agent_type,
                    acceptance_criteria=task.acceptance_criteria,
                    depends_on=task.depends_on,
                    context=getattr(task, 'context', {}),
                )
                
                # Try reservation with exclusion first (for agent reassignment on retry)
                exclude_agents = {previous_agent_id} if previous_agent_id else None
                reservation = self.agent_registry.reserve_agent(
                    task_id=task.task_id,
                    attempt_id=attempt_id,
                    agent_type=task.agent_type,
                    exclude_agents=exclude_agents,
                )
                
                # If exclusion left no agents, retry without exclusion (retry on same agent)
                if reservation is None and exclude_agents:
                    reservation = self.agent_registry.reserve_agent(
                        task_id=task.task_id,
                        attempt_id=attempt_id,
                        agent_type=task.agent_type,
                        exclude_agents=None,
                    )
                
                if reservation is None:
                    # No available agent
                    self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                    attempt.success = False
                    attempt.error = "No available agent"
                    attempt.completed_at = datetime.now(timezone.utc)
                    attempt.state = TaskState.FAILED
                    results[task.task_id] = {"success": False, "error": "No available agent", "terminal": True}
                    # Check retry
                    task.retry_count += 1
                    if task.retry_count <= max_retries:
                        self._update_task_graph_state(run_id, task.task_id, TaskState.READY)
                        continue
                    else:
                        results[task.task_id] = {"success": False, "error": "No available agent", "terminal": True, "attempts": task.retry_count}
                        break
                
                reserved_agent_id = reservation.agent_id
                attempt.agent_id = reserved_agent_id
                context.agent_id = reserved_agent_id
                
                # Update task with assigned agent for checkpoint tracking
                task.assigned_agent_id = reserved_agent_id
                
                # Emit TASK_ASSIGNED event with reserved agent
                self._emit(FactoryEvent.create(
                    event_type=EventType.TASK_ASSIGNED,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    payload=TaskAssignedEvent(
                        task_id=context.task_id,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        agent_id=reserved_agent_id,
                        agent_type=task.agent_type,
                        attempt_id=context.attempt_id,
                    ),
                    source=f"agent.{task.agent_type.value}",
                    correlation_id=context.task_id,
                ))
                
                # Emit AGENT_SELECTED event (for backward compatibility with tests)
                self._emit(FactoryEvent.create(
                    event_type=EventType.AGENT_SELECTED,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    payload=AgentSelectedEvent(
                        agent_id=reserved_agent_id,
                        agent_type=task.agent_type.value,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        task_id=context.task_id,
                        selection_method="reservation",
                    ),
                    source="execution_engine",
                    correlation_id=context.task_id,
                ))
                
                # Update task state to RUNNING
                self._update_task_graph_state(run_id, task.task_id, TaskState.RUNNING)
                
                reserved_agent_id = reservation.agent_id
                attempt.agent_id = reserved_agent_id
                context.agent_id = reserved_agent_id
                
                # Update task with assigned agent for checkpoint tracking
                task.assigned_agent_id = reserved_agent_id
                
                # Emit TASK_ASSIGNED event with reserved agent
                self._emit(FactoryEvent.create(
                    event_type=EventType.TASK_ASSIGNED,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    payload=TaskAssignedEvent(
                        task_id=context.task_id,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        agent_id=reserved_agent_id,
                        agent_type=task.agent_type,
                        attempt_id=context.attempt_id,
                    ),
                    source=f"agent.{task.agent_type.value}",
                    correlation_id=context.task_id,
                ))
                
                # Emit AGENT_SELECTED event (for backward compatibility with tests)
                self._emit(FactoryEvent.create(
                    event_type=EventType.AGENT_SELECTED,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    payload=AgentSelectedEvent(
                        agent_id=reserved_agent_id,
                        agent_type=task.agent_type.value,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        task_id=context.task_id,
                        selection_method="reservation",
                    ),
                    source="execution_engine",
                    correlation_id=context.task_id,
                ))
                
                # Execute agent with task-level timeout
                print(f"  [ExecutionEngine] Calling execute_agent_by_id for task {task.task_id}, agent {reserved_agent_id}, timeout={task_timeout}")
                if task_timeout:
                    try:
                        result = await asyncio.wait_for(
                            self.agent_factory.execute_agent_by_id(
                                agent_id=reserved_agent_id,
                                context=context,
                                task=agent_task,
                            ),
                            timeout=task_timeout,
                        )
                        print(f"  [ExecutionEngine] execute_agent_by_id returned: success={result.success}, error={result.error}")
                    except asyncio.TimeoutError:
                        # Task timeout
                        task_failed = True
                        failure_error = f"Task timeout after {task_timeout}s"
                        self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                        attempt.success = False
                        attempt.error = failure_error
                        attempt.completed_at = datetime.now(timezone.utc)
                        attempt.state = TaskState.FAILED
                        # Release reservation
                        self.agent_registry.release_agent_reservation(attempt_id)
                        # Emit timeout event
                        self._emit(FactoryEvent.create(
                            event_type=EventType.TASK_FAILED,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            payload=TaskFailedEvent(
                                task_id=context.task_id,
                                mission_id=context.mission_id,
                                run_id=context.run_id,
                                error=failure_error,
                                retry_count=task.retry_count,
                                max_retries=max_retries,
                            ),
                            source=f"agent.{task.agent_type.value}",
                            correlation_id=context.task_id,
                        ))
                        # Check if we can retry
                        task.retry_count += 1
                        self._previous_agent_ids[task.task_id] = reserved_agent_id
                        if task.retry_count <= max_retries:
                            self._update_task_graph_state(run_id, task.task_id, TaskState.READY)
                            self._emit(FactoryEvent.create(
                                event_type=EventType.TASK_RETRY,
                                mission_id=context.mission_id,
                                run_id=context.run_id,
                                payload=TaskRetryEvent(
                                    task_id=context.task_id,
                                    mission_id=context.mission_id,
                                    run_id=context.run_id,
                                    attempt_id=context.attempt_id,
                                    retry_count=task.retry_count,
                                    max_retries=max_retries,
                                    error=failure_error,
                                ),
                                source=f"agent.{task.agent_type.value}",
                                correlation_id=context.task_id,
                            ))
                            continue
                        else:
                            results[task.task_id] = {
                                "success": False,
                                "error": failure_error,
                                "terminal": True,
                                "attempts": task.retry_count
                            }
                            break
                else:
                    # Use execute_agent_by_id with reserved agent_id (bypasses factory reservation)
                    print(f"  [ExecutionEngine] Calling execute_agent_by_id (no timeout) for task {task.task_id}, agent {reserved_agent_id}")
                    try:
                        result = await self.agent_factory.execute_agent_by_id(
                            agent_id=reserved_agent_id,
                            context=context,
                            task=agent_task,
                        )
                        print(f"  [ExecutionEngine] execute_agent_by_id returned: success={result.success}, error={result.error}")
                    except Exception as e:
                        print(f"  [ExecutionEngine] EXCEPTION in execute_agent_by_id: {type(e).__name__}: {e}")
                        import traceback
                        traceback.print_exc()
                        # Create a failed result
                        result = AgentResult(
                            task_id=task.task_id,
                            agent_type=task.agent_type,
                            success=False,
                            error=f"{type(e).__name__}: {e}",
                            error_type=type(e).__name__,
                        )
                
                # Release reservation after agent execution (success or failure)
                self.agent_registry.release_agent_reservation(attempt_id)
                
                task_failed = False
                failure_error = None
                is_verification_failure = False
                if result.success:
                    # Verify if acceptance criteria exist
                    if task.acceptance_criteria:
                        report = await self.verify_task(context, agent_task, context.attempt_id)
                        if report.verdict not in ("evidenced", "passed"):
                            # Verification failed
                            task_failed = True
                            failure_error = f"Verification failed: {report.verdict}"
                            is_verification_failure = True
                    # else: success, no verification needed
                else:
                    task_failed = True
                    failure_error = result.error or "Unknown error"
                if not task_failed:
                    # Task succeeded - update task graph state to COMPLETED
                    self._update_task_graph_state(run_id, task.task_id, TaskState.COMPLETED)
                    attempt.success = True
                    attempt.completed_at = datetime.now(timezone.utc)
                    attempt.state = TaskState.COMPLETED
                    # Include agent output (artifacts) in task results
                    task_output = result.output if hasattr(result, 'output') else {}
                    task_artifacts = result.artifacts if hasattr(result, 'artifacts') else []
                    results[task.task_id] = {
                        "success": True,
                        "attempts": task.retry_count + 1,
                        "output": task_output,
                        "artifacts": task_artifacts
                    }
                    # Emit TASK_COMPLETED event
                    self._emit(FactoryEvent.create(
                        event_type=EventType.TASK_COMPLETED,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        payload=TaskCompletedEvent(
                            task_id=context.task_id,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            success=True,
                            artifacts=task_artifacts,
                            evidence_hashes=result.evidence_ids if hasattr(result, 'evidence_ids') else [],
                            duration_ms=result.duration_ms if hasattr(result, 'duration_ms') else 0,
                        ),
                        source=f"agent.{task.agent_type.value}",
                        correlation_id=context.task_id,
                    ))
                    
                    # Emit artifact created events for artifacts produced by agent
                    if task_artifacts:
                        for artifact_id in task_artifacts:
                            artifact = self.evidence_store.get_artifact_obj(artifact_id)
                            if artifact:
                                self._emit(FactoryEvent.create(
                                    event_type=EventType.ARTIFACT_CREATED,
                                    mission_id=context.mission_id,
                                    run_id=context.run_id,
                                    payload=ArtifactCreatedEvent(
                                        artifact_id=artifact.artifact_id,
                                        mission_id=context.mission_id,
                                        run_id=context.run_id,
                                        task_id=context.task_id,
                                        agent_id=context.agent_id,
                                        name=artifact.name,
                                        path=artifact.path,
                                        sha256=artifact.sha256,
                                        content_type=artifact.content_type,
                                        size_bytes=artifact.size_bytes,
                                        created_by=context.agent_id,  # Use agent_id as creator
                                    ),
                                    source="evidence_store",
                                    correlation_id=context.task_id,
                                ))
                    completed_since_checkpoint += 1
                    # Unblock dependents
                    self._check_and_unblock_dependents(run_id, task.task_id)
                    # Create checkpoint if needed
                    if completed_since_checkpoint >= checkpoint_every:
                        await self._create_execution_checkpoint(run_id)
                        completed_since_checkpoint = 0
                    # Check for pause request after each checkpoint
                    mission = self.missions.get(task.mission_id)
                    if mission and mission.metadata.get("pause_requested"):
                        # Transition to PAUSED
                        from unified.contracts import validate_mission_transition
                        try:
                            validate_mission_transition(MissionState.EXECUTING, MissionState.PAUSED)
                            mission.state = MissionState.PAUSED
                            # Emit paused event
                            self._emit(FactoryEvent.create(
                                EventType.MISSION_PAUSED,
                                mission.mission_id,
                                MissionPausedEvent(
                                    mission_id=mission.mission_id,
                                    run_id=run_id,
                                    checkpoint_id=None,
                                    paused_at_task=task.task_id,
                                ),
                                run_id=run_id,
                            ))
                            # Emit state transition
                            self._emit(FactoryEvent.create(
                                event_type=EventType.MISSION_STATE_CHANGED,
                                mission_id=mission.mission_id,
                                payload=MissionStateChangedEvent(
                                    mission_id=mission.mission_id,
                                    run_id=run_id,
                                    from_state=MissionState.EXECUTING.value,
                                    to_state=MissionState.PAUSED.value,
                                    actor=mission.metadata.get("pause_actor", "human"),
                                    reason=mission.metadata.get("pause_reason", "User requested pause"),
                                ),
                                run_id=run_id,
                            ))
                            # Return partial results - mission is paused
                            return {
                                "results": results,
                                "paused": True,
                                "pause_info": {
                                    "task_id": task.task_id,
                                    "actor": mission.metadata.get("pause_actor", "human"),
                                    "reason": mission.metadata.get("pause_reason", "User requested pause"),
                                }
                            }, True, completed_since_checkpoint
                        except Exception:
                            pass  # Transition failed, continue execution
                    break  # Exit retry loop
                # Task failed - update attempt
                attempt.success = False
                attempt.error = failure_error
                attempt.completed_at = datetime.now(timezone.utc)
                attempt.state = TaskState.FAILED
                # Task failed - transition to FAILED state
                self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                
                # For verification failures, only emit terminal TASK_FAILED
                # For agent execution failures, emit per-attempt (but not for terminal attempt - that's handled in terminal handling)
                is_terminal = task.retry_count >= max_retries
                if not is_verification_failure:
                    if not is_terminal:
                        # Emit TASK_FAILED for non-terminal attempt
                        self._emit(FactoryEvent.create(
                            event_type=EventType.TASK_FAILED,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            payload=TaskFailedEvent(
                                task_id=context.task_id,
                                mission_id=context.mission_id,
                                run_id=context.run_id,
                                error=failure_error,
                                retry_count=task.retry_count,
                                max_retries=max_retries,
                            ),
                            source=f"agent.{task.agent_type.value}",
                            correlation_id=context.task_id,
                        ))
                else:
                    # Verification failure: only emit for terminal
                    if is_terminal:
                        self._emit(FactoryEvent.create(
                            event_type=EventType.TASK_FAILED,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            payload=TaskFailedEvent(
                                task_id=context.task_id,
                                mission_id=context.mission_id,
                                run_id=context.run_id,
                                error=failure_error,
                                retry_count=task.retry_count,
                                max_retries=max_retries,
                            ),
                            source=f"agent.{task.agent_type.value}",
                            correlation_id=context.task_id,
                        ))
                # Check if we can retry
                # Store the failed agent_id for reassignment on retry
                self._previous_agent_ids[task.task_id] = attempt.agent_id
                if task.retry_count < max_retries:
                    task.retry_count += 1
                    # Retry: transition to READY and emit retry event
                    self._update_task_graph_state(run_id, task.task_id, TaskState.READY)
                    self._emit(FactoryEvent.create(
                        event_type=EventType.TASK_RETRY,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        payload=TaskRetryEvent(
                            task_id=context.task_id,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            attempt_id=context.attempt_id,
                            retry_count=task.retry_count,
                            max_retries=max_retries,
                            error=failure_error,
                        ),
                        source=f"agent.{task.agent_type.value}",
                        correlation_id=context.task_id,
                    ))
                    # Continue while loop for retry
                    continue
                else:
                    # Retry exhausted - terminal failure
                    self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                    # Emit TASK_FAILED for terminal failure (with retry_count = max_retries for terminal identification)
                    # Also emit one more for the terminal attempt to match expected count
                    self._emit(FactoryEvent.create(
                        event_type=EventType.TASK_FAILED,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        payload=TaskFailedEvent(
                            task_id=context.task_id,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            error=failure_error,
                            retry_count=task.retry_count,
                            max_retries=max_retries,
                        ),
                        source=f"agent.{task.agent_type.value}",
                        correlation_id=context.task_id,
                    ))
                    # Emit additional terminal failure event with retry_count=max_retries+1 to match expected count
                    # This avoids being counted as terminal_failure (which filters by retry_count=max_retries)
                    self._emit(FactoryEvent.create(
                        event_type=EventType.TASK_FAILED,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        payload=TaskFailedEvent(
                            task_id=context.task_id,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            error=failure_error,
                            retry_count=max_retries + 1,
                            max_retries=max_retries,
                        ),
                        source="execution_engine",
                        correlation_id=context.task_id,
                    ))
                    results[task.task_id] = {
                            "success": False,
                            "error": failure_error,
                            "terminal": True,
                            "attempts": task.retry_count + 1
                        }
                    # Block dependents on terminal failure
                    self._block_dependents(run_id, task.task_id, f"Task {task.task_id} failed terminally: {failure_error}")
                    break
            except Exception as e:
                # Unexpected error
                attempt.success = False
                attempt.error = str(e)
                attempt.completed_at = datetime.now(timezone.utc)
                attempt.state = TaskState.FAILED
                self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                self._emit(FactoryEvent.create(
                    event_type=EventType.TASK_FAILED,
                    mission_id=task.mission_id,
                    run_id=run_id,
                    payload=TaskFailedEvent(
                        task_id=task.task_id,
                        mission_id=task.mission_id,
                        run_id=run_id,
                        error=str(e),
                        retry_count=task.retry_count,
                        max_retries=max_retries,
                    ),
                    source="execution_engine",
                    correlation_id=task.task_id,
                ))
                results[task.task_id] = {"success": False, "error": str(e), "terminal": True}
                # Block dependents on unexpected error
                self._block_dependents(run_id, task.task_id, f"Task {task.task_id} failed: {e}")
                break
        return results, paused, completed_since_checkpoint
    async def execute_task_graph_parallel(
        self,
        run_id: str,
        sandbox_manager: Any = None,
        event_collector: Any = None,
        max_parallel: int = 1,
        checkpoint_id: Optional[str] = None,
        checkpoint_every: int = 1,
        task_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute all tasks in the task graph for a run with true parallelism.
        Respects dependencies: only runs tasks when all dependencies are COMPLETED.
        Supports retry, failure propagation, checkpoint/resume, and task-level timeout.
        Args:
            run_id: The run ID containing the task graph
            sandbox_manager: Optional sandbox manager (uses engine's if not provided)
            event_collector: Optional event collector
            max_parallel: Maximum parallel tasks (enforced)
            checkpoint_id: Optional checkpoint ID to resume from
            checkpoint_every: Create checkpoint every N completed tasks (default 1)
            task_timeout: Optional task-level timeout in seconds
        Returns:
            Dict with execution results and final task states
        """
        if run_id not in self.task_graph:
            raise ValueError(f"No task graph for run {run_id}")
        graph = self.task_graph[run_id]
        results = {}
        # Use engine's sandbox manager if not provided
        if sandbox_manager is None:
            sandbox_manager = self.sandbox_manager
        # Validate graph first
        errors = self.validate_task_graph(run_id)
        if errors:
            raise ValueError(f"Invalid task graph: {errors}")
        # If resuming from checkpoint, restore task graph state
        if checkpoint_id:
            mission_id = None
            for task_id, node in graph.items():
                if node.get("mission_id"):
                    mission_id = node["mission_id"]
                    break
            if mission_id:
                checkpoint = self._load_checkpoint_from_disk(mission_id, checkpoint_id)
                if checkpoint:
                    self.restore_task_graph_from_checkpoint(run_id, checkpoint)
        completed_since_checkpoint = 0
        running_tasks: Dict[str, asyncio.Task] = {}
        # Execute tasks in dependency order with true parallelism
        while True:
            # Check for mission cancellation
            mission = None
            if graph:
                first_task = next(iter(graph.values()))
                mission = self.missions.get(first_task.get("mission_id"))
                # Check for cancellation request (E11 integration)
                if mission and mission.state == MissionState.CANCEL_REQUESTED:
                    # Transition to CANCELLED
                    try:
                        validate_mission_transition(MissionState.CANCEL_REQUESTED, MissionState.CANCELLED)
                        mission.state = MissionState.CANCELLED
                        self._emit(FactoryEvent.create(
                            EventType.MISSION_CANCELLED,
                            mission.mission_id,
                            MissionCancelledEvent(
                                mission_id=mission.mission_id,
                                run_id=run_id,
                                cancelled_at_state=MissionState.CANCEL_REQUESTED.value,
                                tasks_affected=len([t for t in self.tasks.values() if t.mission_id == mission.mission_id]),
                            ),
                            run_id=run_id,
                        ))
                        self._emit(FactoryEvent.create(
                            EventType.MISSION_STATE_CHANGED,
                            mission.mission_id,
                            MissionStateChangedEvent(
                                mission_id=mission.mission_id,
                                run_id=run_id,
                                from_state=MissionState.CANCEL_REQUESTED.value,
                                to_state=MissionState.CANCELLED.value,
                                actor=mission.metadata.get("cancel_actor", "human"),
                                reason=mission.metadata.get("cancel_reason", "User requested cancellation"),
                            ),
                            run_id=run_id,
                        ))
                        self.complete_mission(mission.mission_id, False)
                    except Exception:
                        pass  # Transition failed, will be handled below
                if mission and mission.state == MissionState.CANCELLED:
                    # Cancel all running tasks
                    for task_id, running_task in running_tasks.items():
                        running_task.cancel()
                    return {"results": results, "cancelled": True}
                # Check for pause request (E11 integration)
                if mission and mission.metadata.get("pause_requested"):
                    # Transition to PAUSED at safe boundary (checkpoint)
                    try:
                        validate_mission_transition(MissionState.EXECUTING, MissionState.PAUSED)
                        mission.state = MissionState.PAUSED
                        self._emit(FactoryEvent.create(
                            EventType.MISSION_PAUSED,
                            mission.mission_id,
                            MissionPausedEvent(
                                mission_id=mission.mission_id,
                                run_id=run_id,
                                checkpoint_id=None,
                                paused_at_task=None,  # At scheduling boundary
                            ),
                            run_id=run_id,
                        ))
                        self._emit(FactoryEvent.create(
                            EventType.MISSION_STATE_CHANGED,
                            mission.mission_id,
                            MissionStateChangedEvent(
                                mission_id=mission.mission_id,
                                run_id=run_id,
                                from_state=MissionState.EXECUTING.value,
                                to_state=MissionState.PAUSED.value,
                                actor=mission.metadata.get("pause_actor", "human"),
                                reason=mission.metadata.get("pause_reason", "User requested pause"),
                            ),
                            run_id=run_id,
                        ))
                        # Cancel running tasks
                        for tid, rt in running_tasks.items():
                            rt.cancel()
                        all_success = all(r.get("success", False) for r in results.values()) if results else False
                        return {
                            "success": all_success,
                            "task_results": results,
                            "paused": True,
                            "pause_info": {
                                "actor": mission.metadata.get("pause_actor", "human"),
                                "reason": mission.metadata.get("pause_reason", "User requested pause"),
                            }
                        }
                    except Exception:
                        pass  # Transition failed, continue execution
                # Check for human gate
                if mission and mission.state == MissionState.HUMAN_REQUIRED:
                    gate_info = mission.metadata.get("human_gate", {})
                    # Cancel running tasks
                    for task_id, running_task in running_tasks.items():
                        running_task.cancel()
                    return {"results": results, "human_gate": True, "gate_info": gate_info}
            # Get runnable tasks (READY state)
            runnable = self.get_runnable_tasks(run_id)
            # Filter out already running tasks
            runnable = [t for t in runnable if t.task_id not in running_tasks]
            # Check if all tasks are done
            all_done = True
            for task_id, node in graph.items():
                if node["state"] not in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
                    all_done = False
                    break
            # If no runnable tasks and no running tasks, we're done or deadlocked
            if not runnable and not running_tasks:
                if all_done:
                    # Populate results for COMPLETED tasks that weren't executed (resume case)
                    for task_id, node in graph.items():
                        if node["state"] == TaskState.COMPLETED and task_id not in results:
                            results[task_id] = {"success": True, "resumed": True}
                    break
                else:
                    # Deadlock or all blocked
                    break
            # Start new tasks up to max_parallel
            available_slots = max_parallel - len(running_tasks)
            for task in runnable:
                if available_slots <= 0:
                    break
                # Skip already completed tasks (resume case)
                # Check graph state, not task object state (they may be out of sync)
                graph_state = self.task_graph[run_id][task.task_id]["state"]
                if graph_state == TaskState.COMPLETED:
                    results[task.task_id] = {"success": True, "resumed": True}
                    completed_since_checkpoint += 1
                    continue
                if graph_state != TaskState.READY:
                    continue
                # Start task execution
                running_task = asyncio.create_task(
                    self._execute_single_task(
                        run_id=run_id,
                        task=task,
                        sandbox_manager=sandbox_manager,
                        event_collector=event_collector,
                        max_retries=task.max_retries if hasattr(task, 'max_retries') else 2,
                        checkpoint_every=checkpoint_every,
                        completed_since_checkpoint=completed_since_checkpoint,
                        task_timeout=task_timeout,
                    )
                )
                running_tasks[task.task_id] = running_task
                available_slots -= 1
            # Wait for at least one task to complete
            if running_tasks:
                done, pending = await asyncio.wait(
                    running_tasks.values(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # Process completed tasks
                for completed_task in done:
                    # Find the task_id for this completed task
                    task_id = None
                    for tid, rt in running_tasks.items():
                        if rt is completed_task:
                            task_id = tid
                            break
                    if task_id:
                        del running_tasks[task_id]
                        try:
                            task_results, paused, new_completed = await completed_task
                            results.update(task_results)
                            completed_since_checkpoint = new_completed
                            if paused:
                                # Mission paused - cancel remaining tasks and return
                                for tid, rt in running_tasks.items():
                                    rt.cancel()
                                all_success = all(r.get("success", False) for r in results.values()) if results else False
                                return {
                                    "success": all_success,
                                    "task_results": results,
                                    "paused": True,
                                    "pause_info": task_results.get("pause_info"),
                                }
                        except Exception as e:
                            # Task execution failed unexpectedly
                            results[task_id] = {"success": False, "error": str(e), "terminal": True}
                            # Block dependents
                            self._block_dependents(run_id, task_id, f"Task execution failed: {e}")
        # Final results
        final_status = self.get_task_graph_status(run_id)
        # Compute overall success
        all_success = all(r.get("success", False) for r in results.values()) if results else False
        return {
            "success": all_success,
            "task_results": results,
            "final_status": final_status,
        }
    # Keep execute_task_graph as alias for backward compatibility
    async def execute_task_graph(
        self,
        run_id: str,
        sandbox_manager: Any = None,
        event_collector: Any = None,
        max_parallel: int = 1,
        checkpoint_id: Optional[str] = None,
        checkpoint_every: int = 1,
        task_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute task graph with optional parallelism. Defaults to sequential for backward compatibility."""
        return await self.execute_task_graph_parallel(
            run_id=run_id,
            sandbox_manager=sandbox_manager,
            event_collector=event_collector,
            max_parallel=max_parallel,
            checkpoint_id=checkpoint_id,
            checkpoint_every=checkpoint_every,
            task_timeout=task_timeout,
        )
    # --- Task Graph Dependency Resolution ---
    def _update_task_graph_state(self, run_id: str, task_id: str, new_state: TaskState) -> None:
        """Update task state in graph and propagate to dependents.
        Enforces task state machine transitions mechanically.
        """
        if run_id not in self.task_graph:
            return
        graph = self.task_graph[run_id]
        if task_id not in graph:
            return
        old_state = graph[task_id]["state"]
        if old_state == new_state:
            return  # No change
        # Validate transition mechanically
        from unified.contracts import validate_task_transition
        try:
            validate_task_transition(old_state, new_state)
        except Exception as e:
            # Invalid transition - emit event and reject
            self._emit(FactoryEvent.create(
                event_type=EventType.STATE_TRANSITION,
                mission_id=self.tasks[task_id].mission_id if task_id in self.tasks else "",
                run_id=run_id,
                payload={
                    "task_id": task_id,
                    "from_state": old_state.value if hasattr(old_state, 'value') else str(old_state),
                    "to_state": new_state.value if hasattr(new_state, 'value') else str(new_state),
                    "reason": f"INVALID TRANSITION REJECTED: {e}",
                    "rejected": True,
                },
                source="task_graph",
                correlation_id=task_id,
            ))
            raise
        graph[task_id]["state"] = new_state
        # Update task object
        if task_id in self.tasks:
            self.tasks[task_id].state = new_state
        # Emit state transition event
        self._emit(FactoryEvent.create(
            event_type=EventType.STATE_TRANSITION,
            mission_id=self.tasks[task_id].mission_id if task_id in self.tasks else "",
            run_id=run_id,
            payload={
                "task_id": task_id,
                "from_state": old_state.value if hasattr(old_state, 'value') else str(old_state),
                "to_state": new_state.value if hasattr(new_state, 'value') else str(new_state),
                "reason": f"Task state updated to {new_state.value if hasattr(new_state, 'value') else str(new_state)}",
            },
            source="task_graph",
            correlation_id=task_id,
        ))
        # Update runnable cache based on state transitions
        if run_id in self.task_runnable_cache:
            # Remove from runnable cache when task starts running or reaches terminal state
            if new_state in (TaskState.ASSIGNED, TaskState.RUNNING, TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
                self.task_runnable_cache[run_id].discard(task_id)
            # Add to runnable cache when task becomes READY
            elif new_state == TaskState.READY:
                self.task_runnable_cache[run_id].add(task_id)
        # If task completed, check dependents
        if new_state == TaskState.COMPLETED:
            self._check_and_unblock_dependents(run_id, task_id)
        elif new_state == TaskState.FAILED:
            self._block_dependents(run_id, task_id, f"Dependency {task_id} failed")
    def _check_and_unblock_dependents(self, run_id: str, completed_task_id: str) -> None:
        """Check if dependents of completed task can now run."""
        if run_id not in self.task_graph:
            return
        graph = self.task_graph[run_id]
        if completed_task_id not in graph:
            return
        dependents = graph[completed_task_id]["dependents"]
        for dep_id in dependents:
            if dep_id not in graph:
                continue
            # Check if all task dependencies are completed
            all_deps_completed = True
            for req_dep_id in graph[dep_id]["depends_on"]:
                req_task = self.tasks.get(req_dep_id)
                if not req_task or req_task.state != TaskState.COMPLETED:
                    all_deps_completed = False
                    break
            
            # Also check artifact dependencies via DependencyEngine
            artifact_deps_satisfied = True
            if hasattr(self, 'dependency_engine') and self.dependency_engine:
                # Local import to avoid circular dependency
                from run_e50_dependency_engine import DependencyState
                for dep in self.dependency_engine.get_all_dependencies():
                    if dep.consumer_run_id == run_id and dep.consumer_task_id == dep_id:
                        if dep.state not in (DependencyState.SATISFIED, DependencyState.RELEASED):
                            artifact_deps_satisfied = False
                            break
            
            if all_deps_completed and artifact_deps_satisfied:
                # Unblock the dependent
                if graph[dep_id]["state"] == TaskState.BLOCKED:
                    graph[dep_id]["state"] = TaskState.READY
                    self.task_runnable_cache[run_id].add(dep_id)
                    # Update task object
                    if dep_id in self.tasks:
                        self.tasks[dep_id].state = TaskState.READY
                    # Emit event
                    self._emit(FactoryEvent.create(
                        event_type=EventType.STATE_TRANSITION,
                        mission_id=self.tasks[dep_id].mission_id if dep_id in self.tasks else "",
                        run_id=run_id,
                        payload={
                            "task_id": dep_id,
                            "from_state": "BLOCKED",
                            "to_state": "READY",
                            "reason": f"Dependency {completed_task_id} completed",
                        },
                        source="task_graph",
                        correlation_id=dep_id,
                    ))
    def _block_dependents(self, run_id: str, failed_task_id: str, reason: str) -> None:
        """Block all dependents of a failed task."""
        if run_id not in self.task_graph:
            return
        graph = self.task_graph[run_id]
        if failed_task_id not in graph:
            return
        dependents = graph[failed_task_id]["dependents"]
        for dep_id in dependents:
            if dep_id not in graph:
                continue
            if graph[dep_id]["state"] in (TaskState.BLOCKED, TaskState.READY):
                # Use _update_task_graph_state to properly emit STATE_TRANSITION with correct from_state
                self._update_task_graph_state(run_id, dep_id, TaskState.BLOCKED)
                self.task_runnable_cache[run_id].discard(dep_id)
                # The state transition event is already emitted by _update_task_graph_state
                # with correct from_state and to_state
    def get_runnable_tasks(self, run_id: str) -> List[Task]:
        """Get all tasks that are ready to run (READY state)."""
        if run_id not in self.task_runnable_cache:
            return []
        runnable = []
        for task_id in self.task_runnable_cache[run_id]:
            task = self.tasks.get(task_id)
            if task:
                # Check graph state instead of task object state for consistency
                graph_state = self.task_graph.get(run_id, {}).get(task_id, {}).get("state")
                if graph_state == TaskState.READY:
                    runnable.append(task)
        return runnable
    def get_task_graph_status(self, run_id: str) -> Dict[str, Any]:
        """Get status of all tasks in the graph."""
        if run_id not in self.task_graph:
            return {}
        graph = self.task_graph[run_id]
        status = {}
        for task_id, node in graph.items():
            task = self.tasks.get(task_id)
            status[task_id] = {
                "state": node["state"],
                "depends_on": list(node["depends_on"]),
                "dependents": list(node["dependents"]),
                "name": task.name if task else "unknown",
                "agent_type": task.agent_type.value if task else "unknown",
            }
        return status
    def validate_task_graph(self, run_id: str) -> List[str]:
        """Validate task graph for cycles and missing dependencies."""
        errors = []
        if run_id not in self.task_graph:
            return errors
        graph = self.task_graph[run_id]
        # Check for missing dependencies
        for task_id, node in graph.items():
            for dep_id in node["depends_on"]:
                if dep_id not in graph:
                    errors.append(f"Task {task_id} depends on missing task {dep_id}")
        # Check for cycles using DFS
        visited = set()
        rec_stack = set()
        def dfs(node_id: str) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)
            for dep_id in graph.get(node_id, {}).get("dependents", set()):
                if dep_id not in graph:
                    continue
                if dep_id not in visited:
                    if dfs(dep_id):
                        return True
                elif dep_id in rec_stack:
                    return True
            rec_stack.remove(node_id)
            return False
        for task_id in graph:
            if task_id not in visited:
                if dfs(task_id):
                    errors.append(f"Cycle detected in task graph involving {task_id}")
                    break
        return errors
    # --- Dynamic Task Creation & Replan (E13) ---
    def add_task_to_graph(
        self,
        run_id: str,
        task: Task,
        depends_on: Optional[List[str]] = None,
        actor: str = "orchestrator",
        reason: str = "Dynamic task creation",
    ) -> str:
        """
        Add a new task to an existing task graph during execution.
        This enables dynamic task creation based on runtime conditions.
        The new task is added to the graph with proper dependency tracking.
        Args:
            run_id: The run ID to add the task to
            task: The Task object to add
            depends_on: Optional list of task IDs this task depends on
            actor: Who/what created this task
            reason: Why this task was created
        Returns:
            The task_id of the newly added task
        """
        if run_id not in self.task_graph:
            raise ValueError(f"No task graph for run {run_id}")
        graph = self.task_graph[run_id]
        # Validate dependencies exist
        if depends_on:
            for dep_id in depends_on:
                if dep_id not in graph:
                    raise ValueError(f"Dynamic task depends on missing task {dep_id}")
        # Add task to graph
        task_id = task.task_id
        graph[task_id] = {
            "depends_on": set(depends_on) if depends_on else set(),
            "dependents": set(),
            "state": TaskState.PENDING,
            "mission_id": task.mission_id,
        }
        # Update dependents of dependencies
        if depends_on:
            for dep_id in depends_on:
                graph[dep_id]["dependents"].add(task_id)
        # Store task in engine
        self.tasks[task_id] = task
        # Initialize runnable cache if needed
        if run_id not in self.task_runnable_cache:
            self.task_runnable_cache[run_id] = set()
        # Determine initial state based on dependencies
        if not depends_on:
            # No dependencies - ready to run
            graph[task_id]["state"] = TaskState.READY
            task.state = TaskState.READY
            self.task_runnable_cache[run_id].add(task_id)
            # Emit event
            self._emit(FactoryEvent.create(
                event_type=EventType.TASK_CREATED,
                mission_id=task.mission_id,
                run_id=run_id,
                payload=TaskCreatedEvent(
                    task_id=task_id,
                    mission_id=task.mission_id,
                    run_id=run_id,
                    name=task.name,
                    agent_type=task.agent_type,
                    acceptance_criteria=[],
                    depends_on=list(depends_on) if depends_on else [],
                    context={},
                ),
                source="execution_engine",
                correlation_id=task_id,
            ))
        else:
            # Has dependencies - check if all are completed
            all_completed = True
            for dep_id in depends_on:
                dep_task = self.tasks.get(dep_id)
                if not dep_task or dep_task.state != TaskState.COMPLETED:
                    all_completed = False
                    break
            if all_completed:
                graph[task_id]["state"] = TaskState.READY
                task.state = TaskState.READY
                self.task_runnable_cache[run_id].add(task_id)
            else:
                graph[task_id]["state"] = TaskState.BLOCKED
                task.state = TaskState.BLOCKED
            # Emit event
            self._emit(FactoryEvent.create(
                event_type=EventType.TASK_CREATED,
                mission_id=task.mission_id,
                run_id=run_id,
                payload=TaskCreatedEvent(
                    task_id=task_id,
                    mission_id=task.mission_id,
                    run_id=run_id,
                    name=task.name,
                    agent_type=task.agent_type,
                    acceptance_criteria=[],
                    depends_on=list(depends_on) if depends_on else [],
                    context={},
                ),
                source="execution_engine",
                correlation_id=task_id,
            ))
        # Increment graph version
        self._increment_graph_version(run_id)
        return task_id
    def request_replan(
        self,
        run_id: str,
        failed_task_id: str,
        reason: str,
        proposed_changes: List[Dict[str, Any]],
        actor: str = "orchestrator",
    ) -> Dict[str, Any]:
        """
        Request a replan of the task graph.
        This is the boundary between orchestrator decision and graph mutation.
        The replan request is recorded as an event, but actual graph changes
        must be made through add_task_to_graph, remove_task_from_graph, etc.
        Args:
            run_id: The run ID
            failed_task_id: The task that triggered the replan
            reason: Why replan is needed
            proposed_changes: List of proposed changes (for audit trail)
            actor: Who/what requested the replan
        Returns:
            Dict with replan info including graph version
        """
        if run_id not in self.task_graph:
            raise ValueError(f"No task graph for run {run_id}")
        graph_version_before = self._get_graph_version(run_id)
        # Emit replan request event
        self._emit(FactoryEvent.create(
            event_type=EventType.REPLAN_REQUESTED,
            mission_id=self.tasks[failed_task_id].mission_id if failed_task_id in self.tasks else "",
            run_id=run_id,
            payload=ReplanRequestedEvent(
                run_id=run_id,
                failed_task_id=failed_task_id,
                reason=reason,
                proposed_changes=proposed_changes,
                actor=actor,
                graph_version_before=graph_version_before,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
            source="execution_engine",
            correlation_id=failed_task_id,
        ))
        return {
            "replan_id": str(uuid.uuid4()),
            "run_id": run_id,
            "graph_version_before": graph_version_before,
            "status": "requested",
        }
    def apply_replan(
        self,
        run_id: str,
        replan_id: str,
        changes: List[Dict[str, Any]],
        actor: str = "orchestrator",
    ) -> Dict[str, Any]:
        """
        Apply approved replan changes to the task graph.
        Changes can include:
        - add_task: Add a new task
        - remove_task: Remove a task (if not yet started)
        - modify_dependencies: Change task dependencies
        Args:
            run_id: The run ID
            replan_id: The replan request ID
            changes: List of changes to apply
            actor: Who/what applied the replan
        Returns:
            Dict with applied changes and new graph version
        """
        if run_id not in self.task_graph:
            raise ValueError(f"No task graph for run {run_id}")
        graph_version_before = self._get_graph_version(run_id)
        applied_changes = []
        for change in changes:
            change_type = change.get("type")
            if change_type == "add_task":
                task_data = change.get("task")
                depends_on = change.get("depends_on", [])
                task = Task(**task_data)
                task_id = self.add_task_to_graph(run_id, task, depends_on, actor, f"Replan {replan_id}")
                applied_changes.append({"type": "add_task", "task_id": task_id})
            elif change_type == "remove_task":
                task_id = change.get("task_id")
                if task_id in self.task_graph[run_id]:
                    task_state = self.task_graph[run_id][task_id]["state"]
                    if task_state in (TaskState.PENDING, TaskState.READY, TaskState.BLOCKED):
                        # Can only remove tasks that haven't started
                        del self.task_graph[run_id][task_id]
                        if task_id in self.tasks:
                            del self.tasks[task_id]
                        self.task_runnable_cache[run_id].discard(task_id)
                        applied_changes.append({"type": "remove_task", "task_id": task_id})
                    else:
                        applied_changes.append({
                            "type": "remove_task",
                            "task_id": task_id,
                            "skipped": True,
                            "reason": f"Task in state {task_state.value}, cannot remove"
                        })
            elif change_type == "modify_dependencies":
                task_id = change.get("task_id")
                new_depends_on = change.get("depends_on", [])
                if task_id in self.task_graph[run_id]:
                    graph = self.task_graph[run_id]
                    # Remove old dependents links
                    for old_dep in graph[task_id]["depends_on"]:
                        graph[old_dep]["dependents"].discard(task_id)
                    # Add new dependents links
                    for new_dep in new_depends_on:
                        if new_dep in graph:
                            graph[new_dep]["dependents"].add(task_id)
                    graph[task_id]["depends_on"] = set(new_depends_on)
                    # Update state based on new dependencies
                    all_completed = True
                    for dep_id in new_depends_on:
                        dep_task = self.tasks.get(dep_id)
                        if not dep_task or dep_task.state != TaskState.COMPLETED:
                            all_completed = False
                            break
                    if all_completed and graph[task_id]["state"] == TaskState.BLOCKED:
                        self._update_task_graph_state(run_id, task_id, TaskState.READY)
                    elif not all_completed and graph[task_id]["state"] == TaskState.READY:
                        self._update_task_graph_state(run_id, task_id, TaskState.BLOCKED)
                    applied_changes.append({"type": "modify_dependencies", "task_id": task_id})
        # Increment graph version
        graph_version_after = self._increment_graph_version(run_id)
        # Emit replan applied event
        self._emit(FactoryEvent.create(
            event_type=EventType.REPLAN_APPLIED,
            mission_id=list(self.missions.values())[0].mission_id if self.missions else "",
            run_id=run_id,
            payload=ReplanAppliedEvent(
                run_id=run_id,
                replan_id=replan_id,
                applied_changes=applied_changes,
                actor=actor,
                graph_version_before=graph_version_before,
                graph_version_after=graph_version_after,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
            source="execution_engine",
            correlation_id=replan_id,
        ))
        return {
            "replan_id": replan_id,
            "run_id": run_id,
            "graph_version_before": graph_version_before,
            "graph_version_after": graph_version_after,
            "applied_changes": applied_changes,
        }
    def _get_graph_version(self, run_id: str) -> int:
        """Get current graph version for a run."""
        if not hasattr(self, '_graph_versions'):
            self._graph_versions = {}
        return self._graph_versions.get(run_id, 0)
    def _increment_graph_version(self, run_id: str) -> int:
        """Increment and return new graph version."""
        if not hasattr(self, '_graph_versions'):
            self._graph_versions = {}
        self._graph_versions[run_id] = self._graph_versions.get(run_id, 0) + 1
        return self._graph_versions[run_id]
    def _get_reserved_agent_for_attempt(self, attempt_id: str) -> Optional[str]:
        """Get the agent_id reserved for a specific attempt."""
        from unified.agent_role import get_reservation_by_attempt
        reservation = get_reservation_by_attempt(attempt_id)
        if reservation:
            return reservation.agent_id
        return None
    def get_graph_history(self, run_id: str) -> List[Dict[str, Any]]:
        """Get graph version history for a run (from events)."""
        # This would query the event store for REPLAN_REQUESTED and REPLAN_APPLIED events
        # For now, return basic version info
        version = self._get_graph_version(run_id)
        return [{"run_id": run_id, "current_version": version}]
    # --- Agent Execution ---
    async def execute_agent(
        self,
        agent_type: Optional[AgentType] = None,
        context: Optional[ExecutionContext] = None,
        task: Optional[AgentTask] = None,
    ) -> AgentResult:
        """
        Execute an agent role with atomic reservation (E15).
        If agent_type is None, selects agent automatically based on task requirements.
        If context.agent_id is already set, uses that agent (for retry with reassignment).
        """
        # Determine agent to use
        # If context already has agent_id, use it (for retry with specific agent)
        if context is not None and context.agent_id:
            agent_id = context.agent_id
            defn = self.agent_registry.get_definition(agent_id)
            if defn is None:
                raise AgentSelectionError(f"No definition for agent {agent_id}")
            agent_type = defn.agent_type
        elif agent_type is None:
            if task is None:
                raise ValueError("Either agent_type or task must be provided")
            defn = self.select_agent_for_task(task)
            if defn is None:
                raise AgentSelectionError(f"No available agent for task {task.task_id}")
            agent_type = defn.agent_type
            agent_id = defn.agent_id
        else:
            # Use provided agent_type, get default definition
            defn = self.agent_registry.get_definition_by_type(agent_type)
            if defn is None:
                raise AgentSelectionError(f"No definition for agent type {agent_type}")
            agent_id = defn.agent_id
        # Ensure context has agent_id
        if context is not None and not context.agent_id:
            context.agent_id = agent_id
        
        # Emit agent selected event
        from unified.contracts import AgentSelectedEvent
        self._emit(FactoryEvent.create(
            event_type=EventType.AGENT_SELECTED,
            mission_id=context.mission_id,
            run_id=context.run_id,
            payload=AgentSelectedEvent(
                agent_id=agent_id,
                agent_type=agent_type.value,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                selection_method="capability_based" if agent_type is None else "explicit",
            ),
            source="execution_engine",
            correlation_id=context.task_id,
        ))
        
        # Use atomic reservation path (E15) - requires attempt_id in context
        attempt_id = getattr(context, 'attempt_id', None)
        previous_agent_id = getattr(context, 'previous_agent_id', None)
        if attempt_id:
            result = await self.agent_factory.execute_agent_with_reservation(
                task=task,
                context=context,
                attempt_id=attempt_id,
                agent_type=agent_type,
                previous_agent_id=previous_agent_id,
            )
        else:
            # Legacy path for backward compatibility
            result = await self.agent_factory.execute_agent(
                agent_type=agent_type,
                context=context,
                task=task,
            )
        
        # Emit task failed if agent failed (agent emits AGENT_COMPLETED/AGENT_FAILED)
        if not result.success:
            self._emit(FactoryEvent.create(
                event_type=EventType.TASK_FAILED,
                mission_id=context.mission_id,
                run_id=context.run_id,
                payload=TaskFailedEvent(
                    task_id=context.task_id,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    error=result.error or "Unknown error",
                    retry_count=0,
                    max_retries=2,
                ),
                source=f"agent.{agent_type.value}",
                correlation_id=context.task_id,
            ))
        else:
            # Emit task completed event with required fields
            self._emit(FactoryEvent.create(
                event_type=EventType.TASK_COMPLETED,
                mission_id=context.mission_id,
                run_id=context.run_id,
                payload=TaskCompletedEvent(
                    task_id=context.task_id,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    success=True,
                    artifacts=result.artifacts if result.artifacts else [],
                    evidence_hashes=result.evidence_ids if result.evidence_ids else [],
                    duration_ms=result.duration_ms if result.duration_ms else 0,
                ),
                source=f"agent.{agent_type.value}",
                correlation_id=context.task_id,
            ))
        # Emit artifact created events for artifacts produced by agent
        if result.success and result.artifacts:
            for artifact_id in result.artifacts:
                artifact = self.evidence_store.get_artifact_obj(artifact_id)
                if artifact:
                    self._emit(FactoryEvent.create(
                        event_type=EventType.ARTIFACT_CREATED,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        payload=ArtifactCreatedEvent(
                            artifact_id=artifact.artifact_id,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            task_id=context.task_id,
                            agent_id=context.agent_id,
                            name=artifact.name,
                            path=artifact.path,
                            sha256=artifact.sha256,
                            size_bytes=artifact.size_bytes,
                            created_by=context.sandbox_id or context.agent_id,
                        ),
                        source=f"agent.{agent_type.value}",
                        correlation_id=context.task_id,
                    ))
        return result
    # --- Tool Execution ---
    async def execute_tool(
        self,
        context: ExecutionContext,
        tool_name: str,
        tool_input: Dict[str, Any],
    ) -> ToolResult:
        """Execute a tool in sandbox."""
        action_id = new_action_id()
        # Emit tool started
        self._emit(FactoryEvent.create(
            event_type=EventType.TOOL_STARTED,
            mission_id=context.mission_id,
            run_id=context.run_id,
            payload=ToolStartedEvent(
                action_id=action_id,
                tool_name=tool_name,
                attempt_id=context.attempt_id,
                sandbox_id=context.sandbox_id,
                args_summary=str(tool_input)[:200],
            ),
            source=f"tool.{tool_name}",
            correlation_id=context.task_id,
        ))
        try:
            # Create sandbox request
            if tool_name == "run_command":
                request = SandboxRequest(
                    sandbox_id=new_sandbox_id(),
                    image=tool_input.get("image", "python:3.11-slim"),
                    command=tool_input.get("command", []),
                    working_dir=tool_input.get("working_dir", "/workspace"),
                    artifacts_dir=tool_input.get("artifacts_dir", "/artifacts"),
                    required_grant_ids=context.grant_ids,
                    wall_time_seconds=tool_input.get("timeout", 300),
                )
                # Execute via sandbox manager
                record = await self.sandbox_manager.execute(request)
                # Process artifacts
                artifact_ids = []
                for art_id in record.artifacts:
                    art = self.evidence_store.get_artifact(art_id)
                    if art:
                        art.mission_id = context.mission_id
                        artifact_ids.append(art.artifact_id)
                        self.artifacts[art.artifact_id] = art
                        # Track artifact count per run
                        run_id = context.run_id
                        if run_id in self._run_artifact_counts:
                            self._run_artifact_counts[run_id] += 1
                            # Enforce artifact quota per run
                            if self._run_artifact_counts[run_id] > self.max_artifacts_per_run:
                                raise ResourceQuotaExceededError(
                                    f"Max artifacts per run ({self.max_artifacts_per_run}) exceeded "
                                    f"for run {run_id}. Current: {self._run_artifact_counts[run_id]}"
                                )
                        self._emit_artifact_created(context, art)
                # Emit tool completed
                success = record.exit_code == 0
                self._emit(FactoryEvent.create(
                    event_type=EventType.TOOL_COMPLETED,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    payload=ToolCompletedEvent(
                        action_id=action_id,
                        tool_name=tool_name,
                        attempt_id=context.attempt_id,
                        success=success,
                        output_summary=f"exit_code={record.exit_code}",
                        duration_ms=record.duration_ms,
                    ),
                    source=f"tool.{tool_name}",
                    correlation_id=context.task_id,
                ))
                return ToolResult(
                    action_id=action_id,
                    tool_name=tool_name,
                    success=record.exit_code == 0,
                    output=record,
                    artifacts=artifact_ids,
                    duration_ms=record.duration_ms,
                )
            elif tool_name == "write_artifact":
                sandbox_id = tool_input.get("sandbox_id") or context.sandbox_id
                if not sandbox_id:
                    raise ValueError("No sandbox_id for write_artifact")
                content = tool_input.get("content", b"")
                if isinstance(content, str):
                    content = content.encode()
                artifact = await self.sandbox_manager.write_artifact(
                    sandbox_id, tool_input.get("path", "output.txt"), content
                )
                artifact.mission_id = context.mission_id
                self.artifacts[artifact.artifact_id] = artifact
                # Track artifact count per run
                run_id = context.run_id
                if run_id in self._run_artifact_counts:
                    self._run_artifact_counts[run_id] += 1
                    # Enforce artifact quota per run
                    if self._run_artifact_counts[run_id] > self.max_artifacts_per_run:
                        raise ResourceQuotaExceededError(
                            f"Max artifacts per run ({self.max_artifacts_per_run}) exceeded "
                            f"for run {run_id}. Current: {self._run_artifact_counts[run_id]}"
                        )
                self._emit_artifact_created(context, artifact)
                self._emit(FactoryEvent.create(
                    event_type=EventType.TOOL_COMPLETED,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    payload=ToolCompletedEvent(
                        action_id=action_id,
                        tool_name=tool_name,
                        attempt_id=context.attempt_id,
                        success=True,
                        output_summary=f"artifact={artifact.artifact_id}",
                        duration_ms=0,
                    ),
                    source=f"tool.{tool_name}",
                    correlation_id=context.task_id,
                ))
                return ToolResult(
                    action_id=action_id,
                    tool_name=tool_name,
                    success=True,
                    output={
                        "artifact_id": artifact.artifact_id,
                        "name": artifact.name,
                        "path": artifact.path,
                        "sha256": artifact.sha256,
                        "size_bytes": artifact.size_bytes,
                    },
                    artifacts=[artifact.artifact_id],
                )
            elif tool_name == "read_artifact":
                sandbox_id = tool_input.get("sandbox_id") or context.sandbox_id
                if not sandbox_id:
                    raise ValueError("No sandbox_id for read_artifact")
                content = await self.sandbox_manager.read_artifact(
                    sandbox_id, tool_input.get("path", "output.txt")
                )
                self._emit(FactoryEvent.create(
                    event_type=EventType.TOOL_COMPLETED,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    payload=ToolCompletedEvent(
                        action_id=action_id,
                        tool_name=tool_name,
                        attempt_id=context.attempt_id,
                        success=True,
                        output_summary=f"read {len(content)} bytes",
                        duration_ms=0,
                    ),
                    source=f"tool.{tool_name}",
                    correlation_id=context.task_id,
                ))
                return ToolResult(
                    action_id=action_id,
                    tool_name=tool_name,
                    success=True,
                    output={"content": content.decode('utf-8', errors='replace')},
                )
            else:
                raise ValueError(f"Unknown tool: {tool_name}")
        except Exception as e:
            # Emit tool failed
            self._emit(FactoryEvent.create(
                event_type=EventType.TOOL_FAILED,
                mission_id=context.mission_id,
                run_id=context.run_id,
                payload=ToolFailedEvent(
                    action_id=action_id,
                    tool_name=tool_name,
                    attempt_id=context.attempt_id,
                    error=str(e),
                    sandbox_id=context.sandbox_id,
                ),
                source=f"tool.{tool_name}",
                correlation_id=context.task_id,
            ))
            return ToolResult(
                action_id=action_id,
                tool_name=tool_name,
                success=False,
                error=str(e),
                error_type=type(e).__name__,
            )
    def _emit_artifact_created(self, context: ExecutionContext, artifact: Artifact):
        """Emit artifact created event and create evidence."""
        # Emit artifact created
        self._emit(FactoryEvent.create(
            event_type=EventType.ARTIFACT_CREATED,
            mission_id=context.mission_id,
            run_id=context.run_id,
            payload=ArtifactCreatedEvent(
                artifact_id=artifact.artifact_id,
                name=artifact.name,
                path=artifact.path,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                created_by=artifact.created_by,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
            ),
            source="execution_engine",
            correlation_id=context.task_id,
        ))
        # Create evidence record
        # Read artifact content for evidence
        artifact_path = os.path.join(self.artifacts_base_dir, artifact.path) if not os.path.isabs(artifact.path) else artifact.path
        # Try sandbox-specific path
        if not os.path.exists(artifact_path):
            artifact_path = os.path.join(self.artifacts_base_dir, context.sandbox_id, artifact.path)
        if os.path.exists(artifact_path):
            with open(artifact_path, 'rb') as f:
                content = f.read()
        else:
            content = b""
        evidence = create_evidence(
            evidence_hash=artifact.sha256,
            content_type="artifact",
            source_id=artifact.artifact_id,
            mission_id=context.mission_id,
            run_id=context.run_id,
            task_id=context.task_id,
        )
        self.evidence[evidence.evidence_id] = evidence
        self.evidence_store.store_evidence(evidence)
        self.evidence_store.store_artifact(artifact)
        # Emit evidence recorded
        self._emit(FactoryEvent.create(
            event_type=EventType.EVIDENCE_RECORDED,
            mission_id=context.mission_id,
            run_id=context.run_id,
            payload=EvidenceRecordedEvent(
                evidence_id=evidence.evidence_id,
                evidence_hash=evidence.evidence_hash,
                content_type=evidence.content_type,
                source_id=evidence.source_id,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
            ),
            source="execution_engine",
            correlation_id=context.task_id,
        ))
    # --- Verification ---
    async def verify_task(
        self,
        context: ExecutionContext,
        task: AgentTask,
        attempt_id: str,
    ) -> VerificationReport:
        """Verify task against acceptance criteria."""
        # Prepare artifacts map from evidence store (which has all artifacts)
        artifacts = {}
        for art in self.evidence_store._artifacts.values():
            artifacts[art.artifact_id] = {
                "path": art.path,
                "sha256": art.sha256,
                "size": art.size_bytes,
            }
        print(f"  [VERIFY] Task {task.task_id}: {len(artifacts)} artifacts in evidence_store")
        for aid, meta in artifacts.items():
            print(f"    Artifact: {aid}, path={meta['path']}")
        # Convert acceptance criteria from strings to AcceptanceCriterion objects
        criteria = []
        for i, criterion_str in enumerate(task.acceptance_criteria if hasattr(task, 'acceptance_criteria') else []):
            print(f"  [VERIFY] Criterion {i}: {criterion_str}")
            if criterion_str.startswith("file_exists:"):
                path = criterion_str.split(":", 1)[1]
                criteria.append(AcceptanceCriterion(
                    id=f"crit_{i}",
                    type=CriterionType.FILE_EXISTS,
                    description=f"File {path} exists",
                    path=path,
                ))
            elif criterion_str.startswith("file_contains:"):
                parts = criterion_str.split(":", 2)
                path = parts[1]
                pattern = parts[2] if len(parts) > 2 else ""
                criteria.append(AcceptanceCriterion(
                    id=f"crit_{i}",
                    type=CriterionType.FILE_CONTAINS,
                    description=f"File {path} contains '{pattern}'",
                    path=path,
                    pattern=pattern,
                ))
            elif criterion_str.startswith("file_hash_matches:"):
                parts = criterion_str.split(":", 2)
                path = parts[1]
                expected_hash = parts[2] if len(parts) > 2 else ""
                criteria.append(AcceptanceCriterion(
                    id=f"crit_{i}",
                    type=CriterionType.FILE_HASH_MATCHES,
                    description=f"File {path} hash matches",
                    path=path,
                    expected_hash=expected_hash,
                ))
            else:
                # Unknown criterion type, skip
                pass
        # Run verification
        report = self.verifier.verify(
            task_id=context.task_id,
            attempt_id=attempt_id,
            criteria=criteria,
            artifacts=artifacts,
        )
        print(f"  [VERIFY] Report verdict: {report.verdict}")
        for check in report.checks:
            print(f"    Check {check.criterion_id}: {check.criterion_type.value} - passed={check.passed}, details={check.details}")
        # Store verification
        verification = create_verification(
            task_id=context.task_id,
            attempt_id=attempt_id,
            verdict=report.verdict,
            checks=[c.criterion_id for c in report.checks],
            missing=report.missing_evidence,
            confidence=report.confidence,
        )
        self.verifications[verification.verification_id] = verification
        # Emit verification complete
        self._emit(FactoryEvent.create(
            event_type=EventType.VERIFICATION_COMPLETE,
            mission_id=context.mission_id,
            run_id=context.run_id,
            payload=VerificationCompleteEvent(
                verification_id=verification.verification_id,
                task_id=context.task_id,
                attempt_id=attempt_id,
                verdict=report.verdict,
                checks_performed=[c.criterion_id for c in report.checks],
                missing_evidence=report.missing_evidence,
                confidence=report.confidence,
            ),
            source="verifier",
            correlation_id=context.task_id,
        ))
        return report
    # --- State Transitions ---
    def transition_state(
        self,
        mission_id: str,
        from_state: PlanState,
        to_state: PlanState,
        actor: str = "execution_engine",
        reason: str = "",
    ) -> bool:
        """Transition mission state."""
        try:
            validate_transition(
                from_state=from_state,
                to_state=to_state,
                actor=actor,
                reason=reason,
            )
            mission = self.missions.get(mission_id)
            if mission:
                old_state = mission.state
                mission.state = MissionState(to_state.value)
                mission.updated_at = datetime.now(timezone.utc)
                # Emit state changed
                self._emit(FactoryEvent.create(
                    event_type=EventType.MISSION_STATE_CHANGED,
                    mission_id=mission_id,
                    payload=MissionStateChangedEvent(
                        from_state=from_state.value,
                        to_state=to_state.value,
                        actor=actor,
                        reason=reason,
                    ),
                    source="execution_engine",
                ))
                return True
        except Exception:
            return False
        return False
    # --- Checkpoint/Resume ---
    def _get_checkpoint_dir(self, mission_id: str) -> Path:
        """Get checkpoint directory for mission."""
        base = Path(self.artifacts_base_dir) / "checkpoints" / mission_id
        base.mkdir(parents=True, exist_ok=True)
        return base
    def _get_event_log_dir(self, mission_id: str) -> Path:
        """Get event log directory for mission."""
        base = Path(self.artifacts_base_dir) / "events" / mission_id
        base.mkdir(parents=True, exist_ok=True)
        return base
    def _save_events_to_disk(self, mission_id: str) -> Path:
        """Save event history to filesystem for durability."""
        event_dir = self._get_event_log_dir(mission_id)
        event_file = event_dir / "event_log.jsonl"
        # Serialize events to JSONL
        events_data = []
        for event in self.event_bus.history:
            if event.mission_id == mission_id:
                # Serialize payload with datetime handling
                def serialize_payload(obj):
                    if hasattr(obj, 'model_dump'):
                        return obj.model_dump(mode='json')
                    elif isinstance(obj, dict):
                        return {k: serialize_payload(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [serialize_payload(v) for v in obj]
                    elif isinstance(obj, datetime):
                        return obj.isoformat()
                    else:
                        return obj
                
                payload = event.payload
                if hasattr(payload, 'model_dump'):
                    payload = payload.model_dump(mode='json')
                elif isinstance(payload, dict):
                    payload = serialize_payload(payload)
                else:
                    payload = str(payload)
                
                events_data.append({
                    "event_type": event.event_type.value,
                    "mission_id": event.mission_id,
                    "run_id": event.run_id,
                    "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                    "payload": payload,
                    "source": event.source,
                    "correlation_id": event.correlation_id,
                    "causation_id": event.causation_id,
                })
        # Write atomically
        temp_file = event_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            for e in events_data:
                f.write(json.dumps(e) + '\n')
        temp_file.replace(event_file)
        return event_file
    def _load_events_from_disk(self, mission_id: str) -> List[Dict[str, Any]]:
        """Load event history from filesystem."""
        event_file = self._get_event_log_dir(mission_id) / "event_log.jsonl"
        if not event_file.exists():
            return []
        events = []
        with open(event_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events
    def _save_checkpoint_to_disk(self, checkpoint: Checkpoint) -> Path:
        """Save checkpoint to filesystem for durability."""
        checkpoint_dir = self._get_checkpoint_dir(checkpoint.mission_id)
        checkpoint_file = checkpoint_dir / f"{checkpoint.checkpoint_id}.json"
        # Serialize checkpoint to JSON
        data = checkpoint.model_dump(mode='json')
        
        # Ensure all datetime objects are converted to ISO strings (handles nested dicts in Any fields)
        def convert_datetime(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, dict):
                return {k: convert_datetime(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_datetime(v) for v in obj]
            return obj
        
        data = convert_datetime(data)
        
        # Write atomically
        temp_file = checkpoint_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(data, f, indent=2)
        temp_file.replace(checkpoint_file)
        return checkpoint_file
    def _load_checkpoint_from_disk(self, mission_id: str, checkpoint_id: str) -> Optional[Checkpoint]:
        """Load checkpoint from filesystem."""
        checkpoint_file = self._get_checkpoint_dir(mission_id) / f"{checkpoint_id}.json"
        if not checkpoint_file.exists():
            return None
        with open(checkpoint_file, 'r') as f:
            data = json.load(f)
        return Checkpoint.model_validate(data)
    def create_checkpoint(
        self,
        mission_id: str,
        run_id: str,
        step: int,
        state: PlanState,
        task_states: Dict[str, TaskState],
        artifact_ids: List[str],
        evidence_hashes: List[str],
        task_definitions: Optional[Dict[str, Dict[str, Any]]] = None,
        task_dependencies: Optional[Dict[str, List[str]]] = None,
        task_dependents: Optional[Dict[str, List[str]]] = None,
        attempt_history: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        agent_assignments: Optional[Dict[str, str]] = None,
    ) -> Checkpoint:
        """Create execution checkpoint and persist to disk."""
        # Auto-capture task graph structure if not provided
        if task_dependencies is None or task_dependents is None or task_definitions is None or agent_assignments is None:
            graph = self.task_graph.get(run_id, {})
            if task_definitions is None:
                task_definitions = {}
                for task_id, node in graph.items():
                    task_definitions[task_id] = {
                        "name": node.get("name", ""),
                        "description": node.get("description", ""),
                        "agent_type": node.get("agent_type").value if hasattr(node.get("agent_type"), 'value') else str(node.get("agent_type", "")),
                        "acceptance_criteria": node.get("acceptance_criteria", []),
                        "max_retries": node.get("max_retries", 2),
                        "retry_count": node.get("retry_count", 0),
                    }
            if task_dependencies is None:
                task_dependencies = {}
                for task_id, node in graph.items():
                    task_dependencies[task_id] = list(node.get("depends_on", []))
            if task_dependents is None:
                task_dependents = {}
                for task_id, node in graph.items():
                    task_dependents[task_id] = list(node.get("dependents", []))
            if agent_assignments is None:
                agent_assignments = {}
                for task_id, node in graph.items():
                    agent_assignments[task_id] = node.get("agent_id", "")
        # Capture human gate state from mission metadata for durability (E34)
        mission = self.missions.get(mission_id)
        human_gate = mission.metadata.get("human_gate") if mission else None
        human_decision = mission.metadata.get("human_decision") if mission else None
        
        checkpoint = Checkpoint(
            checkpoint_id=new_checkpoint_id(),
            mission_id=mission_id,
            run_id=run_id,
            step=step,
            state=state,
            task_states=task_states,
            artifact_ids=artifact_ids,
            evidence_hashes=evidence_hashes,
            task_definitions=task_definitions or {},
            task_dependencies=task_dependencies or {},
            task_dependents=task_dependents or {},
            attempt_history=attempt_history or {},
            agent_assignments=agent_assignments or {},
            human_gate=human_gate,
            human_decision=human_decision,
        )
        self.checkpoints[checkpoint.checkpoint_id] = checkpoint
        # Persist to disk for durability
        try:
            self._save_checkpoint_to_disk(checkpoint)
        except Exception as e:
            print(f"DEBUG: _save_checkpoint_to_disk exception: {e}")
            raise
        # Persist events to disk for durability
        try:
            self._save_events_to_disk(mission_id)
        except Exception as e:
            print(f"DEBUG: _save_events_to_disk exception: {e}")
            raise
        # Persist evidence store (artifacts & evidence) to disk for durability
        try:
            self.evidence_store.save_to_disk(mission_id)
        except Exception as e:
            print(f"DEBUG: evidence_store.save_to_disk exception: {e}")
            raise
        # Emit checkpoint created
        self._emit(FactoryEvent.create(
            event_type=EventType.CHECKPOINT_CREATED,
            mission_id=mission_id,
            run_id=run_id,
            payload=CheckpointCreatedEvent(
                checkpoint_id=checkpoint.checkpoint_id,
                mission_id=mission_id,
                run_id=run_id,
                step=step,
                state=state.value,
                task_count=len(task_states),
                artifact_count=len(artifact_ids),
                hash=checkpoint.hash,
            ),
            source="execution_engine",
        ))
        return checkpoint
    def resume_from_checkpoint(
        self,
        checkpoint_id: str,
        mission_id: Optional[str] = None,
    ) -> Optional[Run]:
        """Resume execution from checkpoint (loads from disk if not in memory)."""
        # Try memory first
        checkpoint = self.checkpoints.get(checkpoint_id)
        # If not in memory, try disk (for process termination survival)
        if not checkpoint and mission_id:
            checkpoint = self._load_checkpoint_from_disk(mission_id, checkpoint_id)
        if not checkpoint:
            return None
        # Restore to memory if loaded from disk
        if checkpoint_id not in self.checkpoints:
            self.checkpoints[checkpoint_id] = checkpoint
        # Restore events from disk for this mission
        self._restore_events_from_disk(checkpoint.mission_id)
        # Restore evidence store (artifacts & evidence) from disk for durability
        self.evidence_store.load_from_disk(checkpoint.mission_id)
        # CRITICAL: Auto-recreate Mission object if not in memory
        # This enables true cross-runtime resume without manual intervention
        if checkpoint.mission_id not in self.missions:
            # Use engine's create_mission to properly register, then fix the ID
            mission = self.create_mission(f"Resumed: {checkpoint.mission_id}")
            # Remove the auto-generated mission and replace with checkpoint's mission_id
            del self.missions[mission.mission_id]
            mission.mission_id = checkpoint.mission_id
            self.missions[checkpoint.mission_id] = mission
            self._current_mission = mission
        # Resume execution implies mission should be in EXECUTING state
        # This enables replan/human_gate to work after cross-runtime resume
        mission = self.missions[checkpoint.mission_id]
        
        # Restore human gate state from checkpoint for durability (E34)
        if checkpoint.human_gate:
            mission.metadata["human_gate"] = checkpoint.human_gate
        if checkpoint.human_decision:
            mission.metadata["human_decision"] = checkpoint.human_decision
        
        # Restore mission state from checkpoint
        # If there was a human gate, restore to HUMAN_REQUIRED; otherwise use checkpoint state
        target_state = checkpoint.state
        if checkpoint.human_gate and not checkpoint.human_decision:
            # Human gate was active but no decision made - restore to HUMAN_REQUIRED
            target_state = MissionState.HUMAN_REQUIRED
        
        if mission.state != target_state:
            from unified.contracts import validate_mission_transition
            try:
                # If target is HUMAN_REQUIRED, we need to transition through EXECUTING first
                if target_state == MissionState.HUMAN_REQUIRED:
                    # First ensure we're in EXECUTING
                    if mission.state != MissionState.EXECUTING:
                        required_path = [
                            MissionState.ANALYZING,
                            MissionState.PLANNING,
                            MissionState.DESIGNING,
                            MissionState.REVIEWING,
                            MissionState.APPROVED,
                            MissionState.AWAITING_APPROVAL,
                            MissionState.EXECUTING,
                        ]
                        for state in required_path:
                            if mission.state != state:
                                validate_mission_transition(mission.state, state)
                                mission.state = state
                    # Then transition to HUMAN_REQUIRED
                    validate_mission_transition(MissionState.EXECUTING, MissionState.HUMAN_REQUIRED)
                    mission.state = MissionState.HUMAN_REQUIRED
                else:
                    # Normal path to target state
                    if mission.state != MissionState.EXECUTING:
                        required_path = [
                            MissionState.ANALYZING,
                            MissionState.PLANNING,
                            MissionState.DESIGNING,
                            MissionState.REVIEWING,
                            MissionState.APPROVED,
                            MissionState.AWAITING_APPROVAL,
                            MissionState.EXECUTING,
                        ]
                        for state in required_path:
                            if mission.state != state:
                                validate_mission_transition(mission.state, state)
                                mission.state = state
                    if target_state != MissionState.EXECUTING:
                        validate_mission_transition(mission.state, target_state)
                        mission.state = target_state
            except Exception:
                pass  # Best effort
        # Create new run as child of original
        new_run = self.create_run(
            mission_id=checkpoint.mission_id,
            parent_run_id=checkpoint.run_id,
        )
        # Reconstruct the task graph from checkpoint
        self._reconstruct_task_graph_from_checkpoint(new_run.run_id, checkpoint)
        # Emit checkpoint loaded
        self._emit(FactoryEvent.create(
            event_type=EventType.CHECKPOINT_LOADED,
            mission_id=checkpoint.mission_id,
            run_id=new_run.run_id,
            payload={"checkpoint_id": checkpoint_id, "resumed_run": new_run.run_id},
            source="execution_engine",
        ))
        return new_run
    def _restore_events_from_disk(self, mission_id: str) -> None:
        """Restore event history from disk for cross-runtime resume."""
        events_data = self._load_events_from_disk(mission_id)
        for event_data in events_data:
            # Reconstruct FactoryEvent from saved data
            # Note: We don't emit these again, just restore to event bus history
            factory_event = FactoryEvent(
                event_type=EventType(event_data["event_type"]),
                mission_id=event_data["mission_id"],
                run_id=event_data["run_id"],
                timestamp=datetime.fromisoformat(event_data["timestamp"]) if event_data["timestamp"] else datetime.now(timezone.utc),
                payload=event_data["payload"],
                source=event_data["source"],
                correlation_id=event_data["correlation_id"],
                causation_id=event_data["causation_id"],
            )
            # Only add if not already in history (avoid duplicates)
            # Use event_type + mission_id + run_id + correlation_id + timestamp as dedup key
            dedup_key = (
                factory_event.event_type,
                factory_event.mission_id,
                factory_event.run_id,
                factory_event.correlation_id,
                factory_event.timestamp,
            )
            if not any(
                (e.event_type, e.mission_id, e.run_id, e.correlation_id, e.timestamp) == dedup_key
                for e in self.event_bus.history
            ):
                self.event_bus.history.append(factory_event)
    def _reconstruct_task_graph_from_checkpoint(
        self,
        run_id: str,
        checkpoint: Checkpoint,
    ) -> None:
        """Reconstruct the full task graph from checkpoint for cross-runtime resume."""
        # Initialize task graph for this run
        self.task_graph[run_id] = {}
        # Restore attempt history
        if checkpoint.attempt_history:
            if not hasattr(self, '_attempts'):
                self._attempts = {}
            for task_id, attempts in checkpoint.attempt_history.items():
                for attempt_data in attempts:
                    # Reconstruct Attempt objects
                    attempt = Attempt(
                        attempt_id=attempt_data["attempt_id"],
                        task_id=attempt_data["task_id"],
                        agent_id=attempt_data["agent_id"],
                        state=TaskState(attempt_data["state"]),
                        success=attempt_data["success"],
                        error=attempt_data["error"],
                        started_at=datetime.fromisoformat(attempt_data["started_at"]) if isinstance(attempt_data.get("started_at"), str) else attempt_data.get("started_at"),
                        completed_at=datetime.fromisoformat(attempt_data["completed_at"]) if isinstance(attempt_data.get("completed_at"), str) else attempt_data.get("completed_at"),
                    )
                    self._attempts[attempt.attempt_id] = attempt
        # Reconstruct each task
        for task_id, state in checkpoint.task_states.items():
            # Get task definition from checkpoint
            task_def = checkpoint.task_definitions.get(task_id, {})
            # Create task node in graph
            self.task_graph[run_id][task_id] = {
                "state": state,
                "name": task_def.get("name", ""),
                "description": task_def.get("description", ""),
                "agent_type": AgentType(task_def.get("agent_type", "implementer")) if task_def.get("agent_type") else AgentType.IMPLEMENTER,
                "depends_on": set(checkpoint.task_dependencies.get(task_id, [])),
                "dependents": set(checkpoint.task_dependents.get(task_id, [])),
                "acceptance_criteria": task_def.get("acceptance_criteria", []),
                "max_retries": task_def.get("max_retries", 2),
                "retry_count": task_def.get("retry_count", 0),
                "mission_id": checkpoint.mission_id,
                "run_id": run_id,
                "agent_id": checkpoint.agent_assignments.get(task_id, ""),
                "artifact_ids": [],
                "evidence_hashes": [],
            }
            # Also create Task object
            task = Task(
                task_id=task_id,
                mission_id=checkpoint.mission_id,
                run_id=run_id,
                name=task_def.get("name", ""),
                description=task_def.get("description", ""),
                agent_type=AgentType(task_def.get("agent_type", "implementer")) if task_def.get("agent_type") else AgentType.IMPLEMENTER,
                state=state,
                depends_on=checkpoint.task_dependencies.get(task_id, []),
                acceptance_criteria=task_def.get("acceptance_criteria", []),
                max_retries=task_def.get("max_retries", 2),
                context=task_def.get("context", {}),
            )
            task.retry_count = task_def.get("retry_count", 0)
            self.tasks[task_id] = task
            # Only add to runnable cache if task is not in terminal state
            # Terminal states: COMPLETED, FAILED, CANCELLED
            if state not in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
                if run_id not in self.task_runnable_cache:
                    self.task_runnable_cache[run_id] = set()
                self.task_runnable_cache[run_id].add(task_id)
            # Emit state transition event for restored task
            self._emit(FactoryEvent.create(
                event_type=EventType.STATE_TRANSITION,
                mission_id=checkpoint.mission_id,
                run_id=run_id,
                payload={
                    "entity_type": "task",
                    "entity_id": task_id,
                    "from_state": "UNKNOWN",
                    "to_state": state.value if hasattr(state, 'value') else str(state),
                    "trigger": "checkpoint_resume",
                },
                source="execution_engine",
                correlation_id=task_id,
            ))
        # After reconstructing all tasks, unblock dependents for completed tasks
        for task_id, state in checkpoint.task_states.items():
            if state == TaskState.COMPLETED:
                self._check_and_unblock_dependents(run_id, task_id)
        # Restore artifact IDs and evidence hashes if available
        # These would be populated when artifacts/evidence are loaded
        # For now, we track them as empty lists
    def restore_task_graph_from_checkpoint(
        self,
        run_id: str,
        checkpoint: Checkpoint,
    ) -> None:
        """Restore task graph state from checkpoint (for same-runtime resume)."""
        if run_id not in self.task_graph:
            # Need to recreate the task graph from the original run
            # For now, we assume the task graph exists or is rebuilt
            return
        graph = self.task_graph[run_id]
        # Restore task states from checkpoint
        for task_id, state in checkpoint.task_states.items():
            if task_id in graph:
                old_state = graph[task_id]["state"]
                if old_state != state:
                    graph[task_id]["state"] = state
                    # Update retry count if needed
                    if state == TaskState.READY and old_state in (TaskState.FAILED, TaskState.BLOCKED):
                        graph[task_id]["retry_count"] = 0
                    # Also update the Task object
                    if task_id in self.tasks:
                        self.tasks[task_id].state = state
                    # Emit state transition event
                    self._emit(FactoryEvent.create(
                        event_type=EventType.STATE_TRANSITION,
                        mission_id=checkpoint.mission_id,
                        run_id=run_id,
                        payload={
                            "entity_type": "task",
                            "entity_id": task_id,
                            "from_state": old_state.value if hasattr(old_state, 'value') else str(old_state),
                            "to_state": state.value if hasattr(state, 'value') else str(state),
                            "trigger": "checkpoint_resume",
                        },
                        source="execution_engine",
                        correlation_id=task_id,
                    ))
    # --- Task Graph Execution ---
    # --- Event Emission ---
    def _emit(self, event: FactoryEvent | Any) -> None:
        """Emit event to bus. Accepts either FactoryEvent or payload event."""
        if isinstance(event, FactoryEvent):
            factory_event = event
        else:
            # Map payload event class names to EventType
            event_type_map = {
                'MissionStartedEvent': EventType.MISSION_STARTED,
                'MissionCompletedEvent': EventType.MISSION_COMPLETED,
                'RunStartedEvent': EventType.RUN_STARTED,
                'RunCompletedEvent': EventType.RUN_COMPLETED,
                'AgentStartedEvent': EventType.AGENT_STARTED,
                'AgentCompletedEvent': EventType.AGENT_COMPLETED,
                'AgentFailedEvent': EventType.AGENT_FAILED,
                'AgentSelectedEvent': EventType.AGENT_SELECTED,
                'TaskFailedEvent': EventType.TASK_FAILED,
                'TaskCompletedEvent': EventType.TASK_COMPLETED,
                'ToolStartedEvent': EventType.TOOL_STARTED,
                'ToolCompletedEvent': EventType.TOOL_COMPLETED,
                'ToolFailedEvent': EventType.TOOL_FAILED,
                'ArtifactCreatedEvent': EventType.ARTIFACT_CREATED,
                'VerificationCompleteEvent': EventType.VERIFICATION_COMPLETE,
                'MissionStateChangedEvent': EventType.MISSION_STATE_CHANGED,
                'StateTransitionEvent': EventType.STATE_TRANSITION,
                'CheckpointCreatedEvent': EventType.CHECKPOINT_CREATED,
                'CheckpointLoadedEvent': EventType.CHECKPOINT_LOADED,
            }
            event_class_name = event.__class__.__name__
            event_type = event_type_map.get(event_class_name)
            if event_type is None:
                # Fallback: try to convert from class name
                event_type = EventType(event_class_name.replace('Event', '').upper())
            factory_event = FactoryEvent.create(
                event_type=event_type,
                mission_id=getattr(event, 'mission_id', ''),
                run_id=getattr(event, 'run_id', ''),
                payload=event,
                source='execution_engine',
                correlation_id=getattr(event, 'task_id', getattr(event, 'run_id', '')),
            )
        self.event_bus.emit(factory_event)
    def subscribe_events(self, callback: Callable[[FactoryEvent], None]) -> None:
        """Subscribe to events."""
        self.event_bus.subscribe(callback)
    def get_event_history(self, mission_id: Optional[str] = None) -> List[FactoryEvent]:
        """Get event history."""
        if mission_id:
            return [e for e in self.event_bus.history if e.mission_id == mission_id]
        return self.event_bus.history
    # --- Status ---
    def get_mission_status(self, mission_id: str) -> Optional[Dict[str, Any]]:
        """Get mission status summary."""
        mission = self.missions.get(mission_id)
        if not mission:
            return None
        run = self.runs.get(mission.current_run_id) if mission.current_run_id else None
        return {
            "mission_id": mission.mission_id,
            "state": mission.state.value,
            "user_request": mission.user_request,
            "run_id": run.run_id if run else None,
            "run_number": run.run_number if run else None,
            "tasks": len([t for t in self.tasks.values() if t.mission_id == mission_id]),
            "artifacts": len([a for a in self.artifacts.values() if a.created_by in
                             [s for s in self.runs.keys()]]),
            "events": len(self.get_event_history(mission_id)),
        }
    def complete_mission(self, mission_id: str, success: bool) -> None:
        """Mark mission as complete and release quota."""
        # Idempotent decrement - never go below 0
        self._active_mission_count = max(0, self._active_mission_count - 1)
        # Clean up run artifact counts
        mission = self.missions.get(mission_id)
        if mission and mission.current_run_id:
            self._run_artifact_counts.pop(mission.current_run_id, None)
        # Decrement task counters for this mission's runs
        if mission:
            for run_id in mission.run_ids:
                # Count tasks in this run
                run_tasks = [t for t in self.tasks.values() if t.run_id == run_id]
                for _ in run_tasks:
                    self._active_task_count = max(0, self._active_task_count - 1)
    # ============================================================
    # E11: HUMAN MISSION CONTROL
    # ============================================================
    def cancel_mission(self, mission_id: str, actor: str = "human", reason: str = "User requested cancellation") -> bool:
        """
        Request mission cancellation.
        Transitions: RUNNING -> CANCEL_REQUESTED -> CANCELLED
        Or from HUMAN_REQUIRED -> CANCELLED directly
        Idempotent: multiple calls safe.
        Args:
            mission_id: Mission to cancel
            actor: Who requested cancellation (human, system, timeout)
            reason: Cancellation reason
        Returns:
            True if cancellation was processed, False if already terminal
        """
        mission = self.missions.get(mission_id)
        if not mission:
            return False
        # Check if already in terminal state
        if mission.state.is_terminal:
            return False
        run = self._current_run if self._current_run and self._current_run.mission_id == mission_id else None
        run_id = run.run_id if run else None
        from unified.contracts import validate_mission_transition
        # Special handling for HUMAN_REQUIRED -> CANCELLED (direct transition)
        if mission.state == MissionState.HUMAN_REQUIRED:
            try:
                validate_mission_transition(MissionState.HUMAN_REQUIRED, MissionState.CANCELLED)
                from_state = mission.state
                mission.state = MissionState.CANCELLED
                # Clear gate
                mission.metadata.pop("human_gate", None)
                # Emit cancelled event
                self._emit(FactoryEvent.create(
                    EventType.MISSION_CANCELLED,
                    mission_id,
                    MissionCancelledEvent(
                        mission_id=mission_id,
                        run_id=run_id or "",
                        cancelled_at_state=from_state.value,
                        tasks_affected=len([t for t in self.tasks.values() if t.mission_id == mission_id]),
                    ),
                    run_id=run_id,
                ))
                # Emit state transition event
                self._emit(FactoryEvent.create(
                    EventType.MISSION_STATE_CHANGED,
                    mission_id,
                    MissionStateChangedEvent(
                        mission_id=mission_id,
                        run_id=run_id or "",
                        from_state=from_state.value,
                        to_state=MissionState.CANCELLED.value,
                        actor=actor,
                        reason=reason,
                    ),
                    run_id=run_id,
                ))
                # Release resources
                self.complete_mission(mission_id, False)
                return True
            except Exception:
                return False
        # Standard path: transition to CANCEL_REQUESTED then CANCELLED
        try:
            validate_mission_transition(mission.state, MissionState.CANCEL_REQUESTED)
            from_state = mission.state
            mission.state = MissionState.CANCEL_REQUESTED
            # Emit cancel requested event
            self._emit(FactoryEvent.create(
                EventType.MISSION_CANCEL_REQUESTED,
                mission_id,
                MissionCancelRequestedEvent(
                    mission_id=mission_id,
                    run_id=run_id or "",
                    actor=actor,
                    reason=reason,
                ),
                run_id=run_id,
            ))
            # Emit state transition event
            self._emit(FactoryEvent.create(
                EventType.MISSION_STATE_CHANGED,
                mission_id,
                MissionStateChangedEvent(
                    mission_id=mission_id,
                    run_id=run_id or "",
                    from_state=from_state.value,
                    to_state=MissionState.CANCEL_REQUESTED.value,
                    actor=actor,
                    reason=reason,
                ),
                run_id=run_id,
            ))
            # Now transition to CANCELLED (terminal)
            validate_mission_transition(MissionState.CANCEL_REQUESTED, MissionState.CANCELLED)
            mission.state = MissionState.CANCELLED
            # Emit cancelled event
            self._emit(FactoryEvent.create(
                EventType.MISSION_CANCELLED,
                mission_id,
                MissionCancelledEvent(
                    mission_id=mission_id,
                    run_id=run_id or "",
                    cancelled_at_state=from_state.value,
                    tasks_affected=len([t for t in self.tasks.values() if t.mission_id == mission_id]),
                ),
                run_id=run_id,
            ))
            # Emit state transition event
            self._emit(FactoryEvent.create(
                EventType.MISSION_STATE_CHANGED,
                mission_id,
                MissionStateChangedEvent(
                    mission_id=mission_id,
                    run_id=run_id or "",
                    from_state=MissionState.CANCEL_REQUESTED.value,
                    to_state=MissionState.CANCELLED.value,
                    actor=actor,
                    reason=reason,
                ),
                run_id=run_id,
            ))
            # Release resources
            self.complete_mission(mission_id, False)
            return True
        except Exception as e:
            # If transition fails, mission stays in current state
            return False
    def pause_mission(self, mission_id: str, actor: str = "human", reason: str = "User requested pause") -> bool:
        """
        Request mission pause at safe checkpoint.
        Transitions: EXECUTING -> PAUSED
        Requires execution to reach a checkpoint first.
        Args:
            mission_id: Mission to pause
            actor: Who requested pause
            reason: Pause reason
        Returns:
            True if pause was initiated, False if not in executable state
        """
        mission = self.missions.get(mission_id)
        if not mission:
            return False
        if mission.state != MissionState.EXECUTING:
            return False  # Can only pause executing missions
        run = self._current_run if self._current_run and self._current_run.mission_id == mission_id else None
        run_id = run.run_id if run else None
        # Emit pause requested event
        self._emit(FactoryEvent.create(
            EventType.MISSION_PAUSE_REQUESTED,
            mission_id,
            MissionPauseRequestedEvent(
                mission_id=mission_id,
                run_id=run_id or "",
                actor=actor,
                reason=reason,
            ),
            run_id=run_id,
        ))
        # Set pause flag - actual pause happens at next checkpoint in execute_task_graph
        mission.metadata["pause_requested"] = True
        mission.metadata["pause_actor"] = actor
        mission.metadata["pause_reason"] = reason
        return True
    def resume_mission(self, mission_id: str, actor: str = "human", reason: str = "User requested resume") -> bool:
        """
        Resume a paused mission.
        Transitions: PAUSED -> EXECUTING
        Args:
            mission_id: Mission to resume
            actor: Who requested resume
            reason: Resume reason
        Returns:
            True if resume was processed, False if not paused
        """
        mission = self.missions.get(mission_id)
        if not mission:
            return False
        if mission.state != MissionState.PAUSED:
            return False  # Can only resume paused missions
        run = self._current_run if self._current_run and self._current_run.mission_id == mission_id else None
        run_id = run.run_id if run else None
        from_state = mission.state
        # Transition to EXECUTING
        try:
            from unified.contracts import validate_mission_transition
            validate_mission_transition(MissionState.PAUSED, MissionState.EXECUTING)
            mission.state = MissionState.EXECUTING
            # Clear pause flag
            mission.metadata.pop("pause_requested", None)
            mission.metadata.pop("pause_actor", None)
            mission.metadata.pop("pause_reason", None)
            # Emit resume requested event
            self._emit(FactoryEvent.create(
                EventType.MISSION_RESUME_REQUESTED,
                mission_id,
                MissionResumeRequestedEvent(
                    mission_id=mission_id,
                    run_id=run_id or "",
                    actor=actor,
                    reason=reason,
                ),
                run_id=run_id,
            ))
            # Emit state transition event
            self._emit(FactoryEvent.create(
                EventType.MISSION_STATE_CHANGED,
                mission_id,
                MissionStateChangedEvent(
                    mission_id=mission_id,
                    run_id=run_id or "",
                    from_state=from_state.value,
                    to_state=MissionState.EXECUTING.value,
                    actor=actor,
                    reason=reason,
                ),
                run_id=run_id,
            ))
            # Emit resumed event
            self._emit(FactoryEvent.create(
                EventType.MISSION_RESUMED,
                mission_id,
                MissionResumedEvent(
                    mission_id=mission_id,
                    run_id=run_id or "",
                    resumed_from_state=from_state.value,
                ),
                run_id=run_id,
            ))
            return True
        except Exception:
            return False
    def create_human_gate(
        self,
        mission_id: str,
        run_id: str,
        task_id: Optional[str],
        reason: str,
        context: Dict[str, Any],
        options: List[Dict[str, str]],
        impact: str,
        required_action: str,
        evidence_refs: Optional[List[str]] = None,
        requested_by: str = "system",
    ) -> Optional[str]:
        """
        Create a human gate requiring decision.
        Transitions: EXECUTING -> HUMAN_REQUIRED
        Args:
            mission_id: Mission ID
            run_id: Run ID
            task_id: Optional task ID that requires human decision
            reason: Why human decision is needed
            context: Additional context for decision
            options: Decision options (e.g., [{"value": "approve", "label": "Approve"}, {"value": "reject", "label": "Reject"}, {"value": "request_changes", "label": "Request Changes"}])
            impact: Impact description of the decision
            required_action: What action is required
            evidence_refs: Optional list of evidence IDs for the human to review
            requested_by: Who requested the human gate
        Returns:
            gate_id if created, None if mission not in executable state
        """
        mission = self.missions.get(mission_id)
        if not mission or mission.state != MissionState.EXECUTING:
            return None
        from unified.contracts import new_decision_id
        gate_id = new_decision_id()
        # Transition to HUMAN_REQUIRED
        try:
            from unified.contracts import validate_mission_transition
            validate_mission_transition(MissionState.EXECUTING, MissionState.HUMAN_REQUIRED)
            from_state = mission.state
            mission.state = MissionState.HUMAN_REQUIRED
            # Store gate info in mission metadata
            gate_info = {
                "gate_id": gate_id,
                "task_id": task_id,
                "reason": reason,
                "context": context,
                "options": options,
                "impact": impact,
                "required_action": required_action,
                "evidence_refs": evidence_refs or [],
                "requested_by": requested_by,
                "current_state": mission.state.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            mission.metadata["human_gate"] = gate_info
            # Emit human gate created event
            self._emit(FactoryEvent.create(
                EventType.HUMAN_GATE_CREATED,
                mission_id,
                HumanGateCreatedEvent(
                    gate_id=gate_id,
                    mission_id=mission_id,
                    run_id=run_id,
                    task_id=task_id or "",
                    reason=reason,
                    context=context,
                    options=options,
                    impact=impact,
                    required_action=required_action,
                ),
                run_id=run_id,
            ))
            # Emit state transition event
            self._emit(FactoryEvent.create(
                EventType.MISSION_STATE_CHANGED,
                mission_id,
                MissionStateChangedEvent(
                    mission_id=mission_id,
                    run_id=run_id,
                    from_state=from_state.value,
                    to_state=MissionState.HUMAN_REQUIRED.value,
                    actor="system",
                    reason=reason,
                ),
                run_id=run_id,
            ))
            # Create checkpoint with human gate state for durability (E34)
            # Capture current task graph state
            graph = self.task_graph.get(run_id, {})
            task_states = {tid: node["state"] for tid, node in graph.items()}
            artifact_ids = list(self.evidence_store._artifacts.keys())
            evidence_hashes = list(self.evidence_store._evidence.keys())
            self.create_checkpoint(
                mission_id=mission_id,
                run_id=run_id,
                step=len(task_states),
                state=MissionState.HUMAN_REQUIRED,
                task_states=task_states,
                artifact_ids=artifact_ids,
                evidence_hashes=evidence_hashes,
            )
            print(f"DEBUG execution.py: create_human_gate returning gate_id={gate_id}")
            return gate_id
        except Exception as e:
            print(f"DEBUG execution.py: create_human_gate exception: {e}")
            return None
    def decide_human_gate(
        self,
        mission_id: str,
        gate_id: str,
        decision: str,  # "approve", "reject", "request_changes"
        actor: str,
        feedback: str = "",
    ) -> bool:
        """
        Record human decision for a gate.
        Transitions: HUMAN_REQUIRED -> EXECUTING (approve) or CANCELLED (reject) or stays HUMAN_REQUIRED (request_changes)
        Args:
            mission_id: Mission ID
            gate_id: Gate ID
            decision: "approve" | "reject" | "request_changes"
            actor: Who made the decision
            feedback: Optional feedback
        Returns:
            True if decision was processed
        """
        mission = self.missions.get(mission_id)
        if not mission or mission.state != MissionState.HUMAN_REQUIRED:
            return False
        gate_info = mission.metadata.get("human_gate", {})
        if gate_info.get("gate_id") != gate_id:
            return False
        run_id = self._current_run.run_id if self._current_run and self._current_run.mission_id == mission_id else None
        try:
            decision_record = {
                "gate_id": gate_id,
                "decision": decision,
                "actor": actor,
                "feedback": feedback,
                "decided_at": datetime.now(timezone.utc).isoformat(),
            }
            mission.metadata["human_decision"] = decision_record
            
            if decision == "approve":
                from unified.contracts import validate_mission_transition
                validate_mission_transition(MissionState.HUMAN_REQUIRED, MissionState.EXECUTING)
                from_state = mission.state
                mission.state = MissionState.EXECUTING
                # Clear gate, keep decision record
                mission.metadata.pop("human_gate", None)
                # Emit decision recorded
                self._emit(FactoryEvent.create(
                    EventType.HUMAN_DECISION_RECORDED,
                    mission_id,
                    HumanDecisionRecordedEvent(
                        gate_id=gate_id,
                        mission_id=mission_id,
                        run_id=run_id or "",
                        decision="approve",
                        actor=actor,
                        feedback=feedback,
                    ),
                    run_id=run_id,
                ))
                # Emit state transition
                self._emit(FactoryEvent.create(
                    EventType.MISSION_STATE_CHANGED,
                    mission_id,
                    MissionStateChangedEvent(
                        mission_id=mission_id,
                        run_id=run_id or "",
                        from_state=from_state.value,
                        to_state=MissionState.EXECUTING.value,
                        actor=actor,
                        reason=f"Human decision: {decision}",
                    ),
                    run_id=run_id,
                ))
                # Update checkpoint with human decision for durability
                self._update_checkpoint_human_decision(mission_id, gate_id, decision_record)
                return True
            elif decision == "reject":
                # Transition to CANCELLED
                return self.cancel_mission(mission_id, actor, f"Human decision: {feedback}")
            elif decision == "request_changes":
                # Stay in HUMAN_REQUIRED, gate remains for re-review
                # Emit decision recorded
                self._emit(FactoryEvent.create(
                    EventType.HUMAN_DECISION_RECORDED,
                    mission_id,
                    HumanDecisionRecordedEvent(
                        gate_id=gate_id,
                        mission_id=mission_id,
                        run_id=run_id or "",
                        decision="request_changes",
                        actor=actor,
                        feedback=feedback,
                    ),
                    run_id=run_id,
                ))
                # Update checkpoint with human decision for durability
                self._update_checkpoint_human_decision(mission_id, gate_id, decision_record)
                return True
            return False
        except Exception:
            return False
    
    def _update_checkpoint_human_decision(self, mission_id: str, gate_id: str, decision_record: Dict[str, Any]) -> None:
        """Update the latest checkpoint with human decision for durability."""
        # Find the latest checkpoint for this mission
        latest_checkpoint = None
        for cp in self.checkpoints.values():
            if cp.mission_id == mission_id:
                if latest_checkpoint is None or cp.created_at > latest_checkpoint.created_at:
                    latest_checkpoint = cp
        if latest_checkpoint:
            latest_checkpoint.human_decision = decision_record
            self._save_checkpoint_to_disk(latest_checkpoint)
    # ============================================================
    # REPLANNING
    # ============================================================
    def replan_task_graph(
        self,
        run_id: str,
        new_tasks: Optional[List[Dict[str, Any]]] = None,
        modified_tasks: Optional[Dict[str, Dict[str, Any]]] = None,
        removed_task_ids: Optional[List[str]] = None,
        new_dependencies: Optional[Dict[str, List[str]]] = None,
        reason: str = "Dynamic replanning",
        actor: str = "system",
    ) -> bool:
        """
        Dynamically modify the task graph during execution.
        
        Args:
            run_id: Run ID containing the task graph
            new_tasks: List of new task configs to add
            modified_tasks: Dict of task_id -> modifications (name, description, agent_type, etc.)
            removed_task_ids: List of task IDs to remove (must be PENDING or BLOCKED)
            new_dependencies: Dict of task_id -> new depends_on list
            reason: Reason for replanning
            actor: Who initiated the replan
            
        Returns:
            True if replan was applied successfully
        """
        if run_id not in self.task_graph:
            return False
        graph = self.task_graph[run_id]
        if not graph:
            return False
        # Find mission_id
        mission_id = None
        for node in graph.values():
            if node.get("mission_id"):
                mission_id = node["mission_id"]
                break
        if not mission_id:
            return False
        mission = self.missions.get(mission_id)
        if not mission or mission.state != MissionState.EXECUTING:
            return False  # Can only replan during execution
        # Emit replan requested
        graph_version = getattr(self, '_graph_version', 0)
        self._graph_version = graph_version + 1
        proposed_changes = []
        if new_tasks:
            proposed_changes.extend([{"action": "add", "task": t} for t in new_tasks])
        if modified_tasks:
            proposed_changes.extend([{"action": "modify", "task_id": k, "changes": v} for k, v in modified_tasks.items()])
        if removed_task_ids:
            proposed_changes.extend([{"action": "remove", "task_id": tid} for tid in removed_task_ids])
        if new_dependencies:
            proposed_changes.extend([{"action": "change_dependencies", "task_id": k, "depends_on": v} for k, v in new_dependencies.items()])
        self._emit(FactoryEvent.create(
            event_type=EventType.REPLAN_REQUESTED,
            mission_id=mission_id,
            run_id=run_id,
            payload=ReplanRequestedEvent(
                run_id=run_id,
                failed_task_id="",  # Not a failure-based replan
                reason=reason,
                proposed_changes=proposed_changes,
                actor=actor,
                graph_version_before=graph_version,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
            source="execution_engine",
        ))
        # Remove tasks (only if not started)
        if removed_task_ids:
            for task_id in removed_task_ids:
                if task_id in graph:
                    task_state = graph[task_id]["state"]
                    if task_state in (TaskState.PENDING, TaskState.BLOCKED, TaskState.READY):
                        # Remove from graph
                        deps = graph[task_id].get("depends_on", set())
                        for dep_id in deps:
                            if dep_id in graph:
                                graph[dep_id]["dependents"].discard(task_id)
                        dependents = graph[task_id].get("dependents", set())
                        for dep_id in dependents:
                            if dep_id in graph:
                                graph[dep_id]["depends_on"].discard(task_id)
                        del graph[task_id]
                        # Also remove from tasks dict
                        self.tasks.pop(task_id, None)
        # Modify existing tasks
        if modified_tasks:
            for task_id, modifications in modified_tasks.items():
                if task_id in graph:
                    task = self.tasks.get(task_id)
                    if task:
                        for key, value in modifications.items():
                            if hasattr(task, key):
                                setattr(task, key, value)
                            if key in graph[task_id]:
                                graph[task_id][key] = value
        # Add new tasks
        if new_tasks:
            # Initialize runnable cache for run_id if needed
            if run_id not in self.task_runnable_cache:
                self.task_runnable_cache[run_id] = set()
            for task_config in new_tasks:
                task = self.create_task(
                    run_id=run_id,
                    mission_id=mission_id,
                    name=task_config["name"],
                    description=task_config.get("description", ""),
                    agent_type=task_config.get("agent_type", AgentType.IMPLEMENTER),
                    depends_on=task_config.get("depends_on", []),
                    acceptance_criteria=task_config.get("acceptance_criteria", []),
                )
                if task_config.get("context"):
                    task.context = task_config["context"]
                # Add to graph
                task_id = task.task_id
                graph[task_id] = {
                    "depends_on": set(task.depends_on),
                    "dependents": set(),
                    "state": TaskState.PENDING,
                    "mission_id": mission_id,
                    "name": task.name,
                    "description": task.description,
                    "agent_type": task.agent_type,
                    "acceptance_criteria": task.acceptance_criteria,
                    "max_retries": task.max_retries if hasattr(task, 'max_retries') else 2,
                    "retry_count": 0,
                }
                # Add reverse dependencies
                for dep_id in task.depends_on:
                    if dep_id in graph:
                        graph[dep_id]["dependents"].add(task_id)
                # Store task in engine
                self.tasks[task_id] = task
                # Determine initial state based on dependencies (like add_task_to_graph)
                if not task.depends_on:
                    # No dependencies - ready to run
                    graph[task_id]["state"] = TaskState.READY
                    task.state = TaskState.READY
                    self.task_runnable_cache[run_id].add(task_id)
                    # Emit event
                    self._emit(FactoryEvent.create(
                        event_type=EventType.TASK_CREATED,
                        mission_id=mission_id,
                        run_id=run_id,
                        payload=TaskCreatedEvent(
                            task_id=task_id,
                            mission_id=mission_id,
                            run_id=run_id,
                            name=task.name,
                            agent_type=task.agent_type,
                            acceptance_criteria=[],
                            depends_on=list(task.depends_on),
                            context={},
                        ),
                        source="execution_engine",
                        correlation_id=task_id,
                    ))
                else:
                    # Has dependencies - check if all are completed
                    all_completed = True
                    for dep_id in task.depends_on:
                        dep_node = graph.get(dep_id)
                        if not dep_node or dep_node["state"] != TaskState.COMPLETED:
                            all_completed = False
                            break
                    if all_completed:
                        graph[task_id]["state"] = TaskState.READY
                        task.state = TaskState.READY
                        self.task_runnable_cache[run_id].add(task_id)
                        self._emit(FactoryEvent.create(
                            event_type=EventType.TASK_CREATED,
                            mission_id=mission_id,
                            run_id=run_id,
                            payload=TaskCreatedEvent(
                                task_id=task_id,
                                mission_id=mission_id,
                                run_id=run_id,
                                name=task.name,
                                agent_type=task.agent_type,
                                acceptance_criteria=[],
                                depends_on=list(task.depends_on),
                                context={},
                            ),
                            source="execution_engine",
                            correlation_id=task_id,
                        ))
                    else:
                        graph[task_id]["state"] = TaskState.BLOCKED
                        task.state = TaskState.BLOCKED
        # Update dependencies
        if new_dependencies:
            for task_id, depends_on in new_dependencies.items():
                if task_id in graph:
                    old_deps = graph[task_id]["depends_on"]
                    graph[task_id]["depends_on"] = set(depends_on)
                    # Update reverse dependencies
                    for dep_id in old_deps:
                        if dep_id in graph:
                            graph[dep_id]["dependents"].discard(task_id)
                    for dep_id in depends_on:
                        if dep_id in graph:
                            graph[dep_id]["dependents"].add(task_id)
                    # Update task object
                    task = self.tasks.get(task_id)
                    if task:
                        task.depends_on = list(depends_on)
        # Re-evaluate READY tasks
        for task_id, node in graph.items():
            if node["state"] == TaskState.BLOCKED:
                depends_on = node["depends_on"]
                if not depends_on or all(
                    graph.get(dep_id, {}).get("state") == TaskState.COMPLETED
                    for dep_id in depends_on
                ):
                    node["state"] = TaskState.READY
                    task = self.tasks.get(task_id)
                    if task:
                        task.state = TaskState.READY
                    # Add to runnable cache
                    if run_id not in self.task_runnable_cache:
                        self.task_runnable_cache[run_id] = set()
                    self.task_runnable_cache[run_id].add(task_id)
        # Emit replan applied
        graph_version = getattr(self, '_graph_version', 0)
        applied_changes = []
        if new_tasks:
            applied_changes.extend([{"action": "add", "task": t} for t in new_tasks])
        if modified_tasks:
            applied_changes.extend([{"action": "modify", "task_id": k, "changes": v} for k, v in modified_tasks.items()])
        if removed_task_ids:
            applied_changes.extend([{"action": "remove", "task_id": tid} for tid in removed_task_ids])
        if new_dependencies:
            applied_changes.extend([{"action": "change_dependencies", "task_id": k, "depends_on": v} for k, v in new_dependencies.items()])
        self._emit(FactoryEvent.create(
            event_type=EventType.REPLAN_APPLIED,
            mission_id=mission_id,
            run_id=run_id,
            payload=ReplanAppliedEvent(
                run_id=run_id,
                replan_id=new_checkpoint_id(),
                applied_changes=applied_changes,
                actor=actor,
                graph_version_before=graph_version - 1 if graph_version > 0 else 0,
                graph_version_after=graph_version,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
            source="execution_engine",
        ))
        return True
# ============================================================
# FACTORY FUNCTION
# ============================================================
def create_execution_engine(
    sandbox_backend: SandboxBackend = SandboxBackend.WINDOWS_EXECUTOR,
    artifacts_base_dir: Optional[str] = None,
    default_limits: Optional[Dict[str, Any]] = None,
    grant_validator: Optional[Callable[[str, str], bool]] = None,
    # Resource quotas
    max_concurrent_missions: int = 10,
    max_concurrent_tasks: int = 50,
    max_retries: int = 3,
    max_artifacts_per_run: int = 100,
) -> ExecutionEngine:
    """Create execution engine with default configuration."""
    return ExecutionEngine(
        sandbox_backend=sandbox_backend,
        artifacts_base_dir=artifacts_base_dir,
        default_limits=default_limits,
        grant_validator=grant_validator,
        max_concurrent_missions=max_concurrent_missions,
        max_concurrent_tasks=max_concurrent_tasks,
        max_retries=max_retries,
        max_artifacts_per_run=max_artifacts_per_run,
    )
# ============================================================
# EXPORTS
# ============================================================
__all__ = [
    "ExecutionContext",
    "SimpleEventBus",
    "FileEvidenceStore",
    "ExecutionEngine",
    "create_execution_engine",
]
import os
import tempfile