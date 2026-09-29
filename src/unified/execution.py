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
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

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
    AgentStartedEvent, AgentCompletedEvent, TaskFailedEvent,
    ToolStartedEvent, ToolCompletedEvent, ToolFailedEvent,
    ArtifactCreatedEvent, EvidenceRecordedEvent,
    VerificationCompleteEvent, CheckpointCreatedEvent,
    MissionStateChangedEvent, MissionCompletedEvent,
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
    ):
        self.sandbox_backend = sandbox_backend
        self.artifacts_base_dir = artifacts_base_dir or os.path.join(
            tempfile.gettempdir(), "unified_execution"
        )
        self.default_limits = default_limits or {}
        self.grant_validator = grant_validator
        
        # Create sandbox manager
        self.sandbox_manager = create_sandbox_manager(
            backend=sandbox_backend,
            grant_validator=grant_validator,
            artifacts_base_dir=self.artifacts_base_dir,
        )
        
        # Event bus
        self.event_bus = SimpleEventBus()
        
        # Agent registry and factory
        self.agent_registry = agent_registry
        self.agent_factory = AgentFactory(self.agent_registry)
        
        # Evidence store
        self.evidence_store = FileEvidenceStore(self.artifacts_base_dir)
        
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
    
    # --- Mission Lifecycle ---
    
    def create_mission(self, user_request: str) -> Mission:
        """Create a new mission."""
        mission = create_mission(user_request)
        self.missions[mission.mission_id] = mission
        self._current_mission = mission
        
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
        
        # Add to task graph
        if run_id not in self.task_graph:
            self.task_graph[run_id] = {}
            self.task_runnable_cache[run_id] = set()
        
        # Initialize task node in graph
        self.task_graph[run_id][task.task_id] = {
            "depends_on": set(depends_on or []),
            "dependents": set(),
            "state": TaskState.PENDING,
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
    
    def select_agent_for_task(self, task: AgentTask) -> Optional[AgentDefinition]:
        """
        Select the best agent for a task using capability-based deterministic selection.
        
        Uses AgentRegistry.select_agent() which considers:
        - Required tools from task acceptance criteria (inferred)
        - Required permissions
        - Supported domains
        - Agent availability (enabled + AVAILABLE state)
        - Max tokens (higher wins ties)
        """
        # Infer required capabilities from task
        # For now, use the agent_type as primary filter
        # In future, parse acceptance_criteria to infer tools/permissions/domains
        
        # First try exact type match
        defn = self.agent_registry.get_definition_by_type(task.agent_type)
        if defn and defn.is_available():
            return defn
        
        # If agent exists but is in COMPLETED/FAILED state, reset to AVAILABLE for reuse
        if defn and defn.state in (AgentLifecycleState.COMPLETED, AgentLifecycleState.FAILED):
            self.agent_registry.set_lifecycle_state(defn.agent_id, AgentLifecycleState.AVAILABLE)
            return defn
        
        # Fall back to capability-based selection
        # For now, require no specific tools/permissions/domains
        # The registry will select the best available agent
        return self.agent_registry.select_agent(
            required_tools=[],
            required_permissions=[],
            required_domains=[],
        )
    
    # --- Task Graph Dependency Resolution ---
    
    def _update_task_graph_state(self, run_id: str, task_id: str, new_state: TaskState) -> None:
        """Update task state in graph and propagate to dependents."""
        if run_id not in self.task_graph:
            return
        
        graph = self.task_graph[run_id]
        if task_id not in graph:
            return
        
        old_state = graph[task_id]["state"]
        if old_state == new_state:
            return  # No change
        
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
            
            # Check if all dependencies are completed
            all_deps_completed = True
            for req_dep_id in graph[dep_id]["depends_on"]:
                req_task = self.tasks.get(req_dep_id)
                if not req_task or req_task.state != TaskState.COMPLETED:
                    all_deps_completed = False
                    break
            
            if all_deps_completed:
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
                graph[dep_id]["state"] = TaskState.BLOCKED
                self.task_runnable_cache[run_id].discard(dep_id)
                
                # Update task object
                if dep_id in self.tasks:
                    self.tasks[dep_id].state = TaskState.BLOCKED
                
                # Emit event
                self._emit(FactoryEvent.create(
                    event_type=EventType.STATE_TRANSITION,
                    mission_id=self.tasks[dep_id].mission_id if dep_id in self.tasks else "",
                    run_id=run_id,
                    payload={
                        "task_id": dep_id,
                        "from_state": graph[dep_id]["state"],
                        "to_state": "BLOCKED",
                        "reason": reason,
                    },
                    source="task_graph",
                    correlation_id=dep_id,
                ))
    
    def get_runnable_tasks(self, run_id: str) -> List[Task]:
        """Get all tasks that are ready to run (READY state)."""
        if run_id not in self.task_runnable_cache:
            return []
        
        runnable = []
        for task_id in self.task_runnable_cache[run_id]:
            task = self.tasks.get(task_id)
            if task and task.state == TaskState.READY:
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
    
    # --- Agent Execution ---
    
    async def execute_agent(
        self,
        agent_type: Optional[AgentType] = None,
        context: Optional[ExecutionContext] = None,
        task: Optional[AgentTask] = None,
    ) -> AgentResult:
        """
        Execute an agent role.
        
        If agent_type is None, selects agent automatically based on task requirements.
        """
        # Determine agent to use
        if agent_type is None:
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
        
        # Execute via agent factory (agent will emit AGENT_STARTED and AGENT_COMPLETED)
        result = await self.agent_factory.execute_agent(
            agent_type=agent_type,
            context=context,
            task=task,
        )
        
        # Update task graph state
        task_id = context.task_id
        run_id = context.run_id
        if result.success:
            self._update_task_graph_state(run_id, task_id, TaskState.COMPLETED)
        else:
            self._update_task_graph_state(run_id, task_id, TaskState.FAILED)
        
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
                        artifact_ids.append(art.artifact_id)
                        self.artifacts[art.artifact_id] = art
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
                
                self.artifacts[artifact.artifact_id] = artifact
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
        # Prepare artifacts map
        artifacts = {}
        for art in self.artifacts.values():
            artifacts[art.artifact_id] = {
                "path": art.path,
                "sha256": art.sha256,
                "size": art.size_bytes,
            }
        
        # Convert acceptance criteria from strings to AcceptanceCriterion objects
        criteria = []
        for i, criterion_str in enumerate(task.acceptance_criteria if hasattr(task, 'acceptance_criteria') else []):
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
    
    def create_checkpoint(
        self,
        mission_id: str,
        run_id: str,
        step: int,
        state: PlanState,
        task_states: Dict[str, TaskState],
        artifact_ids: List[str],
        evidence_hashes: List[str],
    ) -> Checkpoint:
        """Create execution checkpoint."""
        checkpoint = Checkpoint(
            checkpoint_id=new_checkpoint_id(),
            mission_id=mission_id,
            run_id=run_id,
            step=step,
            state=state,
            task_states=task_states,
            artifact_ids=artifact_ids,
            evidence_hashes=evidence_hashes,
        )
        self.checkpoints[checkpoint.checkpoint_id] = checkpoint
        
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
    ) -> Optional[Run]:
        """Resume execution from checkpoint."""
        checkpoint = self.checkpoints.get(checkpoint_id)
        if not checkpoint:
            return None
        
        # Create new run as child of original
        new_run = self.create_run(
            mission_id=checkpoint.mission_id,
            parent_run_id=checkpoint.run_id,
        )
        
        # Emit checkpoint loaded
        self._emit(FactoryEvent.create(
            event_type=EventType.CHECKPOINT_LOADED,
            mission_id=checkpoint.mission_id,
            run_id=new_run.run_id,
            payload={"checkpoint_id": checkpoint_id, "resumed_run": new_run.run_id},
            source="execution_engine",
        ))
        
        return new_run
    
    # --- Task Graph Execution ---
    
    async def execute_task_graph(
        self,
        run_id: str,
        sandbox_manager=None,
        event_collector=None,
        max_parallel: int = 1,
    ) -> Dict[str, Any]:
        """
        Execute all tasks in the task graph for a run.
        
        Respects dependencies: only runs tasks when all dependencies are COMPLETED.
        Supports retry and failure propagation.
        
        Args:
            run_id: The run ID containing the task graph
            sandbox_manager: Optional sandbox manager (uses engine's if not provided)
            event_collector: Optional event collector
            max_parallel: Maximum parallel tasks (currently sequential only)
        
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
        
        # Execute tasks in dependency order
        while True:
                runnable = self.get_runnable_tasks(run_id)
                if not runnable:
                    # Check if any tasks are still pending/running/blocked
                    all_done = True
                    for task_id, node in graph.items():
                        if node["state"] not in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
                            all_done = False
                            break
                    if all_done:
                        break
                    # No runnable tasks but not all done - deadlock or all blocked
                    break
                
                # For now, execute sequentially (one at a time)
                for task in runnable:
                    if task.state != TaskState.READY:
                        continue
                    
                    # Update task state to ASSIGNED
                    self._update_task_graph_state(run_id, task.task_id, TaskState.ASSIGNED)
                    
                    try:
                        # Select agent
                        agent_task = AgentTask(
                            task_id=task.task_id,
                            run_id=run_id,
                            mission_id=task.mission_id,
                            name=task.name,
                            description=task.description,
                            agent_type=task.agent_type,
                            acceptance_criteria=task.acceptance_criteria,
                            depends_on=task.depends_on,
                        )
                        
                        defn = self.select_agent_for_task(agent_task)
                        if defn is None:
                            self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                            results[task.task_id] = {"success": False, "error": "No available agent"}
                            continue
                        
                        # Create execution context
                        sandbox_id = f"sandbox-{task.task_id}"
                        context = ExecutionContext(
                            mission_id=task.mission_id,
                            run_id=run_id,
                            task_id=task.task_id,
                            attempt_id=new_attempt_id(),
                            agent_id=defn.agent_id,
                            agent_type=task.agent_type,
                            sandbox_id=sandbox_id,
                            sandbox_manager=sandbox_manager,
                            event_emitter=self.event_bus.emit,  # Use event bus emit to avoid duplicate events
                            evidence_store=self.evidence_store,
                        )
                        
                        # Update task state to RUNNING
                        self._update_task_graph_state(run_id, task.task_id, TaskState.RUNNING)
                        
                        # Execute agent
                        result = await self.execute_agent(
                            agent_type=task.agent_type,
                            context=context,
                            task=agent_task,
                        )
                        
                        if result.success:
                            # Verify if acceptance criteria exist
                            if task.acceptance_criteria:
                                report = await self.verify_task(context, agent_task, context.attempt_id)
                                if report.verdict not in ("evidenced", "passed"):
                                    # Verification failed - mark task as failed
                                    self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                                    # Emit task failed event
                                    self._emit(FactoryEvent.create(
                                        event_type=EventType.TASK_FAILED,
                                        mission_id=context.mission_id,
                                        run_id=context.run_id,
                                        payload=TaskFailedEvent(
                                            task_id=context.task_id,
                                            mission_id=context.mission_id,
                                            run_id=context.run_id,
                                            error=f"Verification failed: {report.verdict}",
                                            retry_count=0,
                                            max_retries=task.max_retries if hasattr(task, 'max_retries') else 2,
                                        ),
                                        source=f"agent.{task.agent_type.value}",
                                        correlation_id=context.task_id,
                                    ))
                                    results[task.task_id] = {
                                        "success": False,
                                        "error": f"Verification failed: {report.verdict}",
                                        "verification": report.verdict,
                                    }
                                else:
                                    results[task.task_id] = {"success": True, "verification": report.verdict}
                            else:
                                results[task.task_id] = {"success": True}
                        else:
                            self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                            results[task.task_id] = {"success": False, "error": result.error}
                        
                    except Exception as e:
                        self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                        results[task.task_id] = {"success": False, "error": str(e)}
        
        # Final status
        final_status = self.get_task_graph_status(run_id)
        all_success = all(r.get("success", False) for r in results.values())
        
        return {
            "run_id": run_id,
            "success": all_success,
            "task_results": results,
            "final_status": final_status,
        }
    
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


# ============================================================
# FACTORY FUNCTION
# ============================================================

def create_execution_engine(
    sandbox_backend: SandboxBackend = SandboxBackend.WINDOWS_EXECUTOR,
    artifacts_base_dir: Optional[str] = None,
    default_limits: Optional[Dict[str, Any]] = None,
    grant_validator: Optional[Callable[[str, str], bool]] = None,
) -> ExecutionEngine:
    """Create execution engine with default configuration."""
    return ExecutionEngine(
        sandbox_backend=sandbox_backend,
        artifacts_base_dir=artifacts_base_dir,
        default_limits=default_limits,
        grant_validator=grant_validator,
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