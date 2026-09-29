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
        
        # First try exact type match
        defn = self.agent_registry.get_definition_by_type(task.agent_type)
        if defn and defn.is_available():
            # On retry, if the default agent is the same as previous, try to find another
            if previous_agent_id and defn.agent_id == previous_agent_id:
                # Try to find an alternative agent of the same type
                alternative = self._find_alternative_agent(task.agent_type, previous_agent_id)
                if alternative:
                    return alternative
            return defn
        
        # If default agent exists but is in COMPLETED/FAILED state, reset to AVAILABLE for reuse
        if defn and defn.state in (AgentLifecycleState.COMPLETED, AgentLifecycleState.FAILED):
            self.agent_registry.set_lifecycle_state(defn.agent_id, AgentLifecycleState.AVAILABLE)
            # On retry, check if this is the same as previous agent
            if previous_agent_id and defn.agent_id == previous_agent_id:
                alternative = self._find_alternative_agent(task.agent_type, previous_agent_id)
                if alternative:
                    return alternative
            return defn
        
        # Also check all definitions of this type and reset any FAILED ones to AVAILABLE
        # This enables retry with different agents of the same type
        for d in self.agent_registry.list_definitions():
            if d.agent_type == task.agent_type and d.state == AgentLifecycleState.FAILED:
                self.agent_registry.set_lifecycle_state(d.agent_id, AgentLifecycleState.AVAILABLE)
        
        # Fall back to capability-based selection
        # On retry, try to exclude the previous agent
        if previous_agent_id:
            # Get all available agents of this type, excluding previous
            alternatives = self._get_alternative_agents(task.agent_type, previous_agent_id)
            if alternatives:
                # Select the one with highest max_tokens
                return max(alternatives, key=lambda d: d.max_tokens)
        
        # For now, require no specific tools/permissions/domains
        # The registry will select the best available agent
        return self.agent_registry.select_agent(
            required_tools=[],
            required_permissions=[],
            required_domains=[],
        )
    
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
    
    def _get_checkpoint_dir(self, mission_id: str) -> Path:
        """Get checkpoint directory for mission."""
        base = Path(self.artifacts_base_dir) / "checkpoints" / mission_id
        base.mkdir(parents=True, exist_ok=True)
        return base
    
    def _save_checkpoint_to_disk(self, checkpoint: Checkpoint) -> Path:
        """Save checkpoint to filesystem for durability."""
        checkpoint_dir = self._get_checkpoint_dir(checkpoint.mission_id)
        checkpoint_file = checkpoint_dir / f"{checkpoint.checkpoint_id}.json"
        
        # Serialize checkpoint to JSON
        data = checkpoint.model_dump(mode='json')
        
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
        )
        self.checkpoints[checkpoint.checkpoint_id] = checkpoint
        
        # Persist to disk for durability
        self._save_checkpoint_to_disk(checkpoint)
        
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
                        started_at=datetime.fromisoformat(attempt_data["started_at"]) if attempt_data.get("started_at") else None,
                        completed_at=datetime.fromisoformat(attempt_data["completed_at"]) if attempt_data.get("completed_at") else None,
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
                "depends_on": checkpoint.task_dependencies.get(task_id, []),
                "dependents": checkpoint.task_dependents.get(task_id, []),
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
            )
            task.retry_count = task_def.get("retry_count", 0)
            self.tasks[task_id] = task
            
            # Add to runnable cache
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
    
    async def execute_task_graph(
        self,
        run_id: str,
        sandbox_manager=None,
        event_collector=None,
        max_parallel: int = 1,
        checkpoint_id: Optional[str] = None,
        checkpoint_every: int = 1,  # Create checkpoint every N tasks
    ) -> Dict[str, Any]:
        """
        Execute all tasks in the task graph for a run.
        
        Respects dependencies: only runs tasks when all dependencies are COMPLETED.
        Supports retry, failure propagation, and checkpoint/resume.
        
        Args:
            run_id: The run ID containing the task graph
            sandbox_manager: Optional sandbox manager (uses engine's if not provided)
            event_collector: Optional event collector
            max_parallel: Maximum parallel tasks (currently sequential only)
            checkpoint_id: Optional checkpoint ID to resume from
            checkpoint_every: Create checkpoint every N completed tasks (default 1)
        
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
            # Find mission_id for this run
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
        
        # Execute tasks in dependency order
        while True:
            runnable = self.get_runnable_tasks(run_id)
            if not runnable:
                # Check if any tasks are still pending/running/blocked/retrying
                all_done = True
                for task_id, node in graph.items():
                    if node["state"] not in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
                        all_done = False
                        break
                if all_done:
                    # All tasks are done - populate results for COMPLETED tasks that weren't executed
                    for task_id, node in graph.items():
                        if node["state"] == TaskState.COMPLETED and task_id not in results:
                            results[task_id] = {"success": True, "resumed": True}
                            completed_since_checkpoint += 1
                    break
                # No runnable tasks but not all done - deadlock or all blocked
                break
            
            # For now, execute sequentially (one at a time)
            for task in runnable:
                # Skip already completed tasks (resume case)
                if task.state == TaskState.COMPLETED:
                    results[task.task_id] = {"success": True, "resumed": True}
                    completed_since_checkpoint += 1
                    continue
                
                if task.state != TaskState.READY:
                    continue
                
                # Update task state to ASSIGNED
                self._update_task_graph_state(run_id, task.task_id, TaskState.ASSIGNED)
                
                # Retry loop for this task
                max_retries = task.max_retries if hasattr(task, 'max_retries') else 2
                task.retry_count = getattr(task, 'retry_count', 0)
                
                while task.retry_count <= max_retries:
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
                    
                    try:
                        # Select agent - on retry, try to select a different agent
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
                        
                        # Pass retry info to allow agent reassignment
                        previous_agent_id = self._previous_agent_ids.get(task.task_id) if task.retry_count > 0 else None
                        defn = self.select_agent_for_task(agent_task, previous_agent_id=previous_agent_id)
                        if defn is None:
                            self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                            results[task.task_id] = {"success": False, "error": "No available agent", "terminal": True}
                            attempt.success = False
                            attempt.error = "No available agent"
                            attempt.completed_at = datetime.now(timezone.utc)
                            attempt.state = TaskState.FAILED
                            break
                        
                        # Update attempt with selected agent
                        attempt.agent_id = defn.agent_id
                        
                        # Create execution context with new attempt_id for each retry
                        sandbox_id = f"sandbox-{task.task_id}"
                        context = ExecutionContext(
                            mission_id=task.mission_id,
                            run_id=run_id,
                            task_id=task.task_id,
                            attempt_id=attempt_id,
                            agent_id=defn.agent_id,
                            agent_type=task.agent_type,
                            sandbox_id=sandbox_id,
                            sandbox_manager=sandbox_manager,
                            event_emitter=self.event_bus.emit,
                            evidence_store=self.evidence_store,
                        )
                        
                        # Update task state to RUNNING
                        self._update_task_graph_state(run_id, task.task_id, TaskState.RUNNING)
                        
                        # Execute agent
                        result = await self.execute_agent(
                            agent_type=None,
                            context=context,
                            task=agent_task,
                        )
                        
                        task_failed = False
                        failure_error = None
                        
                        if result.success:
                            # Verify if acceptance criteria exist
                            if task.acceptance_criteria:
                                report = await self.verify_task(context, agent_task, context.attempt_id)
                                if report.verdict not in ("evidenced", "passed"):
                                    # Verification failed
                                    task_failed = True
                                    failure_error = f"Verification failed: {report.verdict}"
                            # else: success, no verification needed
                        else:
                            task_failed = True
                            failure_error = result.error
                        
                        if not task_failed:
                            # Task succeeded
                            attempt.success = True
                            attempt.completed_at = datetime.now(timezone.utc)
                            attempt.state = TaskState.COMPLETED
                            
                            results[task.task_id] = {"success": True, "attempts": task.retry_count + 1}
                            completed_since_checkpoint += 1
                            
                            # Create checkpoint if needed
                            if completed_since_checkpoint >= checkpoint_every:
                                await self._create_execution_checkpoint(run_id)
                                completed_since_checkpoint = 0
                            
                            break  # Exit retry loop
                        
                        # Task failed - update attempt
                        attempt.success = False
                        attempt.error = failure_error
                        attempt.completed_at = datetime.now(timezone.utc)
                        attempt.state = TaskState.FAILED
                        
                        # Task failed - check if we can retry
                        task.retry_count += 1
                        # Store the failed agent_id for reassignment on retry
                        if not hasattr(self, '_previous_agent_ids'):
                            self._previous_agent_ids = {}
                        self._previous_agent_ids[task.task_id] = attempt.agent_id
                        if task.retry_count <= max_retries:
                            # Retry: reset to READY and emit retry event
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
                            self._emit(FactoryEvent.create(
                                event_type=EventType.TASK_FAILED,
                                mission_id=context.mission_id,
                                run_id=context.run_id,
                                payload=TaskFailedEvent(
                                    task_id=context.task_id,
                                    mission_id=context.mission_id,
                                    run_id=context.run_id,
                                    error=failure_error or "Unknown error",
                                    retry_count=task.retry_count - 1,
                                    max_retries=max_retries,
                                ),
                                source=f"agent.{task.agent_type.value}",
                                correlation_id=context.task_id,
                            ))
                            results[task.task_id] = {
                                "success": False, 
                                "error": failure_error,
                                "attempts": task.retry_count,
                                "terminal": True
                            }
                            break
                    
                    except Exception as e:
                        task.retry_count += 1
                        attempt.success = False
                        attempt.error = str(e)
                        attempt.completed_at = datetime.now(timezone.utc)
                        attempt.state = TaskState.FAILED
                        
                        if task.retry_count <= max_retries:
                            # Retry on exception
                            self._update_task_graph_state(run_id, task.task_id, TaskState.READY)
                            self._emit(FactoryEvent.create(
                                event_type=EventType.TASK_RETRY,
                                mission_id=task.mission_id,
                                run_id=run_id,
                                payload=TaskRetryEvent(
                                    task_id=task.task_id,
                                    mission_id=task.mission_id,
                                    run_id=run_id,
                                    attempt_id=new_attempt_id(),
                                    retry_count=task.retry_count,
                                    max_retries=max_retries,
                                    error=str(e),
                                ),
                                source=f"agent.{task.agent_type.value}",
                                correlation_id=task.task_id,
                            ))
                            continue
                        else:
                            # Retry exhausted
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
                                    retry_count=task.retry_count - 1,
                                    max_retries=max_retries,
                                ),
                                source=f"agent.{task.agent_type.value}",
                                correlation_id=task.task_id,
                            ))
                            results[task.task_id] = {
                                "success": False, 
                                "error": str(e),
                                "attempts": task.retry_count,
                                "terminal": True
                            }
                            break
        
        # Final checkpoint
        if completed_since_checkpoint > 0:
            await self._create_execution_checkpoint(run_id)
        
        # Final status
        final_status = self.get_task_graph_status(run_id)
        all_success = all(r.get("success", False) for r in results.values())
        
        return {
            "run_id": run_id,
            "success": all_success,
            "task_results": results,
            "final_status": final_status,
        }
    
    async def _create_execution_checkpoint(self, run_id: str) -> None:
        """Create a checkpoint from current execution state."""
        if run_id not in self.task_graph:
            return
        
        graph = self.task_graph[run_id]
        
        # Collect mission_id from first task
        mission_id = None
        for node in graph.values():
            if node.get("mission_id"):
                mission_id = node["mission_id"]
                break
        
        if not mission_id:
            return
        
        # Build task states dict
        task_states = {}
        artifact_ids = []
        evidence_hashes = []
        
        # Build full task graph for cross-runtime restoration
        task_definitions = {}
        task_dependencies = {}
        task_dependents = {}
        attempt_history = {}
        agent_assignments = {}
        
        for task_id, node in graph.items():
            task_states[task_id] = node["state"]
            artifact_ids.extend(node.get("artifact_ids", []))
            evidence_hashes.extend(node.get("evidence_hashes", []))
            
            # Capture task definition
            task_definitions[task_id] = {
                "name": node.get("name", ""),
                "description": node.get("description", ""),
                "agent_type": node.get("agent_type", "").value if hasattr(node.get("agent_type", ""), 'value') else str(node.get("agent_type", "")),
                "acceptance_criteria": node.get("acceptance_criteria", []),
                "max_retries": node.get("max_retries", 2),
                "retry_count": node.get("retry_count", 0),
            }
            
            # Capture dependencies
            task_dependencies[task_id] = node.get("depends_on", [])
            task_dependents[task_id] = node.get("dependents", [])
            
            # Capture agent assignment
            if node.get("agent_id"):
                agent_assignments[task_id] = node["agent_id"]
        
        # Capture attempt history
        if hasattr(self, '_attempts'):
            for attempt_id, attempt in self._attempts.items():
                task_id = attempt.task_id
                if task_id not in attempt_history:
                    attempt_history[task_id] = []
                attempt_history[task_id].append({
                    "attempt_id": attempt.attempt_id,
                    "task_id": attempt.task_id,
                    "agent_id": attempt.agent_id,
                    "state": attempt.state.value if hasattr(attempt.state, 'value') else str(attempt.state),
                    "success": attempt.success,
                    "error": attempt.error,
                    "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
                    "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
                })
        
        # Get current plan state (simplified)
        plan_state = PlanState.EXECUTING
        
        # Count completed tasks as step
        step = sum(1 for s in task_states.values() if s == TaskState.COMPLETED)
        
        self.create_checkpoint(
            mission_id=mission_id,
            run_id=run_id,
            step=step,
            state=plan_state,
            task_states=task_states,
            artifact_ids=artifact_ids,
            evidence_hashes=evidence_hashes,
            task_definitions=task_definitions,
            task_dependencies=task_dependencies,
            task_dependents=task_dependents,
            attempt_history=attempt_history,
            agent_assignments=agent_assignments,
        )
    
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