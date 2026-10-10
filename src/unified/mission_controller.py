"""
E33 — MISSION-LEVEL AUTONOMY CONTROLLER
========================================

Mission-level orchestration layer on top of ExecutionEngine.

Turns a declarative mission spec (task graph with real dependencies) into a
durable, long-running mission that can:

1. Execute the graph through the real production path (agent runtime, sandbox,
   artifacts, evidence, verification).
2. DETECT failures from the event stream and CLASSIFY them
   (task execution failure / tool runtime failure / plan deviation /
   process interruption).
3. RECOVER: retry (engine), replan (controller) — including mission-level
   replanning that invalidates downstream tasks, adds remediation tasks and
   rewires dependencies, preserving completed work.
4. CHECKPOINT the full mission state (task states, definitions WITH context,
   dependencies, attempt history) to disk.
5. Resume cross-runtime (including after real process termination).
6. Prove NO FALSE RE-EXECUTION after resume via an attempt ledger derived
   from the event history.
7. Verify mission completion (all required tasks verified, dependencies
   satisfied, no unresolved blockers) and drive the mission state machine to
   EVIDENCED, emitting RUN_COMPLETED / MISSION_COMPLETED.

The owner-gated VERIFIED state is intentionally NOT set autonomously:
the golden rule of the state machine reserves it for the owner.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from unified.contracts import (
    MissionState,
    TaskState,
    AgentType,
    EventType,
    FactoryEvent,
    MissionCompletedEvent,
    TaskAssignedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskRetryEvent,
    VerificationCompleteEvent,
    validate_mission_transition,
    validate_task_transition,
    AgentDefinition,
)
from unified.agent_role import AgentRegistry, agent_registry, AgentDefinition
from unified.agent_contract import (
    AgentTask,
    AgentResult,
)
from unified.agent_role import (
    AgentRegistry,
    agent_registry,
    AgentContext,
    BaseAgent,
)
from unified.domain_model import (
    Mission,
    Run,
    Task,
    Checkpoint,
    Artifact,
    EvidenceRecord,
    new_evidence_id,
)
from unified.execution import (
    ExecutionEngine,
    CheckpointIntegrityError,
)
from unified.contracts import new_attempt_id


# ============================================================
# FAILURE TAXONOMY (DETECT → CLASSIFY)
# ============================================================

class FailureKind(str, Enum):
    TASK_EXECUTION_FAILURE = "task_execution_failure"   # agent-level error (RuntimeError, ...)
    TOOL_RUNTIME_FAILURE = "tool_runtime_failure"       # sandbox / filesystem / tool error
    PLAN_DEVIATION = "plan_deviation"                   # verification failure invalidating plan parts
    PROCESS_INTERRUPTION = "process_interruption"       # runtime death (kill / crash)


class RecoveryAction(str, Enum):
    NONE = "none"
    RETRY = "retry"               # handled by engine retry loop
    REASSIGN = "reassign"         # handled by engine agent reassignment
    REPLAN = "replan"             # mission-level plan invalidation + re-generation
    RESUME = "resume"             # cross-runtime resume from checkpoint





@dataclass
class TaskSpec:
    """Declarative task in a mission spec (key-based, resolved to task_ids)."""
    key: str
    name: str
    description: str
    depends_on: List[str] = field(default_factory=list)  # task keys
    acceptance_criteria: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    agent_type: AgentType = AgentType.IMPLEMENTER


@dataclass
class FailureRecord:
    failure_id: str
    kind: FailureKind
    task_id: str
    task_key: str
    description: str
    evidence: List[str]
    detected_at: str
    classification_reason: str
    recovery_action: RecoveryAction = RecoveryAction.NONE
    resolved: bool = False
    resolved_by: str = ""


@dataclass
class ReplanRecord:
    from_version: str
    to_version: str
    reason: str
    evidence: List[str]
    added_tasks: List[Dict[str, Any]]
    removed_tasks: List[str]
    invalidated_tasks: List[str]
    preserved_tasks: List[str]
    rewired_dependencies: List[Dict[str, Any]]
    modified_tasks: List[Dict[str, Any]]
    timestamp: str


@dataclass
class PlanReviewRecord:
    """E10-RP §3.B — durable record of one plan review (the gate before
    continuation). Latest verdict per plan version wins; a rejected or absent
    review blocks continuation until the plan is corrected and re-reviewed."""
    review_id: str
    run_id: str
    mission_id: str
    plan_version: str
    verdict: str              # "approved" | "rejected"
    reviewer: str
    note: str
    checks: List[Dict[str, Any]]
    reasons: List[str]
    reviewed_at: str


class MissionTaskAgent(BaseAgent):
    """
    Generic context-driven mission agent.

    Behavior is fully determined by task.context:
      - task_key:       stable mission-level key (A..H / X)
      - content:        artifact content to produce
      - output_path:    artifact path
      - sleep_s:        simulated work duration (makes parallel overlap observable)
      - fail_attempt_1: None | "task_execution" | "tool_runtime"
                        injected deterministic first-attempt failure.
                        "task_execution" raises an agent-level RuntimeError.
                        "tool_runtime" performs a REAL sandbox write to a path
                        that the filesystem rejects — the tool error propagates.

    Attempt counting is per-process (registry constructs one instance per
    execution; counters live on the class keyed by task_id).
    """

    ATTEMPT_COUNTERS: Dict[str, int] = {}

    def __init__(self):
        super().__init__(AgentType.IMPLEMENTER)

    @classmethod
    def next_attempt(cls, task_id: str) -> int:
        cls.ATTEMPT_COUNTERS[task_id] = cls.ATTEMPT_COUNTERS.get(task_id, 0) + 1
        return cls.ATTEMPT_COUNTERS[task_id]

    def on_start(self, context: AgentContext, task: AgentTask) -> None:
        pass

    def on_complete(self, context: AgentContext, task: AgentTask, result: AgentResult) -> None:
        pass

    def on_failed(self, context: AgentContext, task: AgentTask, error: Exception) -> None:
        pass

    def validate_input(self, task: AgentTask) -> List[str]:
        return []

    def validate_output(self, result: AgentResult) -> List[str]:
        return []

    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        start_time = asyncio.get_event_loop().time()
        started_at = datetime.now(timezone.utc).isoformat()

        def _result(success: bool, **kw: Any) -> AgentResult:
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            base = dict(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=success,
                output={
                    "task_key": (getattr(task, "context", {}) or {}).get("task_key", ""),
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "process_pid": _current_pid(),
                },
                duration_ms=duration_ms,
            )
            base.update(kw)
            return AgentResult(**base)

        ctx = dict(getattr(task, "context", {}) or {})
        attempt_no = self.next_attempt(task.task_id)
        fail_mode = ctx.get("fail_attempt_1")

        # ---- Deterministic first-attempt failure injection ----
        if fail_mode and attempt_no == 1:
            if fail_mode == "task_execution":
                return _result(
                    False,
                    error=f"Injected task execution failure (attempt 1) for {ctx.get('task_key')}",
                    error_type="RuntimeError",
                )
            if fail_mode == "tool_runtime":
                sandbox = context.sandbox_manager
                try:
                    # Real tool failure, portable across runtimes (E2-R2 §6
                    # root-cause repair of the E33 cross-runtime regression):
                    # first durably write a guard FILE through the real sandbox,
                    # then attempt to write an artifact UNDER that file. The
                    # parent path exists as a regular file, so the filesystem
                    # rejects the write on EVERY supported runtime with a real
                    # OSError (FileExistsError from the adapter's
                    # Path.mkdir(parents=True, exist_ok=True) on POSIX and
                    # Windows alike) and the error propagates from the tool
                    # layer. The previous injection used a Windows-illegal
                    # filename character ('|') which POSIX accepts, so on Linux
                    # the sandbox accepted the write and the injection degraded
                    # to a synthetic agent-level failure.
                    await sandbox.write_artifact(
                        sandbox_id=context.sandbox_id,
                        path="e33_tool_failure_guard.txt",
                        content=b"e33 tool failure probe guard",
                    )
                    await sandbox.write_artifact(
                        sandbox_id=context.sandbox_id,
                        path="e33_tool_failure_guard.txt/e33_child.txt",
                        content=b"e33 tool failure probe",
                    )
                    # Unreachable on a compliant runtime: writing under a
                    # regular file cannot succeed. Kept as an honest failure
                    # marker if some runtime ever permits it.
                    return _result(
                        False,
                        error="tool_runtime injection: sandbox accepted file-as-directory path (unexpected)",
                        error_type="AssertionError",
                    )
                except Exception as e:
                    return _result(
                        False,
                        error=f"Tool/runtime failure from sandbox layer: {type(e).__name__}: {e}",
                        error_type=type(e).__name__,
                    )

        # ---- Normal production path: real sandbox write via ToolExecutor + evidence ----
        try:
            content = str(ctx.get("content", "E33-OUTPUT"))
            output_path = str(ctx.get("output_path", f"e33_{task.task_id}.txt"))
            sleep_s = float(ctx.get("sleep_s", 0.0))
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)

            # E9-R: Use ToolExecutor for governed artifact_write execution
            tool_executor = getattr(context, "tool_executor", None)
            artifact_id = None
            sha256 = None
            
            if tool_executor is not None:
                # Execute through ToolExecutor (governed path)
                tool_result = await tool_executor.execute_tool(
                    context=context,
                    tool_name="artifact_write",
                    tool_input={
                        "sandbox_id": context.sandbox_id,
                        "path": output_path,
                        "content": content,
                        "encoding": "utf-8",
                    }
                )
                if tool_result.success and tool_result.output:
                    artifact_id = tool_result.output.get("artifact_id", "")
                    sha256 = tool_result.output.get("sha256", "")
                    # Action ID is available for traceability
                    action_id = tool_result.action_id
                else:
                    # Tool execution failed
                    return _result(
                        False,
                        error=tool_result.error or "Tool execution failed",
                        error_type=tool_result.error_type or "ToolExecutionError",
                    )
            else:
                # E9-R1: Fail closed - ToolExecutor must be available in production
                raise RuntimeError("ToolExecutor not available in ExecutionContext. Production execution requires governed tool execution via ToolExecutor.")

            # Evidence is recorded by ToolExecutor, but we verify/record here for compatibility
            if artifact_id and sha256 and context.evidence_store:
                evidence = EvidenceRecord(
                    evidence_id=new_evidence_id(),
                    evidence_hash=sha256,
                    content_type="artifact",
                    source_id=artifact_id,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    task_id=context.task_id,
                )
                context.evidence_store.store_evidence(evidence)

            return _result(
                True,
                output={
                    "task_key": ctx.get("task_key", ""),
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "process_pid": _current_pid(),
                    "artifact_id": artifact_id,
                    "artifact_path": output_path,
                    "content": content,
                    "sha256": sha256,
                    "action_id": action_id if tool_executor is not None else None,
                },
                evidence_hash=sha256,
                artifacts=[artifact_id] if artifact_id else [],
            )
        except Exception as e:
            return _result(
                False,
                error=f"{type(e).__name__}: {e}",
                error_type=type(e).__name__,
            )


def _current_pid() -> int:
    import os
    return os.getpid()


E33_MISSION_AGENT_ID = "e33-mission-agent"
E33_AGENT_POOL_SIZE = 12  # agent pool: concurrent tasks each need an exclusive reservation


def register_mission_agent(registry: AgentRegistry, pool_size: int = E33_AGENT_POOL_SIZE) -> List[str]:
    """Register the generic mission agent as a POOL of definitions.

    The registry grants an exclusive reservation per agent (E15): concurrent
    tasks fail with 'No available agent' unless enough definitions exist.
    All pool members share the MissionTaskAgent implementation; behavior is
    driven by task.context.
    """
    registry.replace_implementation(AgentType.IMPLEMENTER, MissionTaskAgent)
    registered: List[str] = []
    for i in range(1, pool_size + 1):
        agent_id = f"{E33_MISSION_AGENT_ID}-{i:02d}"
        if agent_id not in registry._definitions:
            registry.add_definition(AgentDefinition(
                agent_id=agent_id,
                agent_type=AgentType.IMPLEMENTER,
                name=f"E33MissionAgent{i:02d}",
                version="1.0",
                description=f"Context-driven mission task agent (E33 pool member {i})",
                tools=["write_artifact", "read_artifact"],
                permissions=["write"],
                max_tokens=20000,
                timeout_seconds=120,
                requires_sandbox=True,
                supported_domains=["testing"],
                implementation_class="unified.mission_controller.MissionTaskAgent",
            ))
        # enable_agent is state-conditional internally (REGISTERED/DISABLED → AVAILABLE)
        registry.enable_agent(agent_id)
        registered.append(agent_id)
    return registered


# ============================================================
# MISSION CONTROLLER
# ============================================================

class MissionController:
    """Mission-level autonomy: definition, execution, failure recovery,
    replanning, checkpointing, resume verification and completion."""

    def __init__(self, engine: ExecutionEngine, state_dir: Optional[str] = None,
                 require_plan_review: bool = False):
        self.engine = engine
        self.state_dir = Path(state_dir) if state_dir else Path(engine.artifacts_base_dir)
        self.failures: List[FailureRecord] = []
        self.replans: List[ReplanRecord] = []
        self.plan_reviews: List[PlanReviewRecord] = []
        self.require_plan_review = require_plan_review
        self.phase_log: List[Dict[str, Any]] = []
        self.plan_version = "v1"
        self._key_to_task: Dict[str, str] = {}       # key -> task_id
        self._task_to_key: Dict[str, str] = {}       # task_id -> key

    # ---------- Mission definition ----------

    def _transition_mission(self, mission: Mission, to_state: MissionState, actor: str, reason: str) -> None:
        """Validated mission state transition with MISSION_STATE_CHANGED emission."""
        validate_mission_transition(mission.state, to_state, actor=actor)
        from_state = mission.state
        mission.state = to_state
        self.engine._emit(FactoryEvent.create(
            event_type=EventType.MISSION_STATE_CHANGED,
            mission_id=mission.mission_id,
            run_id=mission.current_run_id or "",
            payload={
                "mission_id": mission.mission_id,
                "run_id": mission.current_run_id or "",
                "from_state": from_state.value,
                "to_state": to_state.value,
                "actor": actor,
                "reason": reason,
            },
            source="mission_controller",
        ))

    def define_mission(self, user_request: str, specs: List[TaskSpec]) -> Tuple[Mission, Run, Dict[str, str]]:
        """Create mission + run + full task graph from declarative spec.
        Drives the mission lifecycle RECEIVED → ... → EXECUTING with validated
        transitions. Returns (mission, run, key->task_id map)."""
        mission = self.engine.create_mission(user_request)
        for state in (
            MissionState.ANALYZING, MissionState.PLANNING, MissionState.DESIGNING,
            MissionState.REVIEWING, MissionState.APPROVED, MissionState.AWAITING_APPROVAL,
            MissionState.EXECUTING,
        ):
            self._transition_mission(mission, state, actor="mission_controller", reason="Mission definition (E33)")
        run = self.engine.create_run(mission.mission_id)

        key_to_id: Dict[str, str] = {}
        for spec in specs:
            dep_ids = [key_to_id[k] for k in spec.depends_on]
            task = self.engine.create_task(
                run_id=run.run_id,
                mission_id=mission.mission_id,
                name=spec.name,
                description=spec.description,
                agent_type=spec.agent_type,
                depends_on=dep_ids,
            )
            task.context = dict(spec.context)
            task.context["task_key"] = spec.key
            task.acceptance_criteria = list(spec.acceptance_criteria)
            key_to_id[spec.key] = task.task_id
            self._key_to_task[spec.key] = task.task_id
            self._task_to_key[task.task_id] = spec.key
            self.engine._emit(FactoryEvent.create(
                event_type=EventType.TASK_CREATED,
                mission_id=mission.mission_id,
                run_id=run.run_id,
                payload={
                    "task_id": task.task_id,
                    "mission_id": mission.mission_id,
                    "run_id": run.run_id,
                    "name": spec.name,
                    "task_key": spec.key,
                    "agent_type": spec.agent_type.value if hasattr(spec.agent_type, "value") else str(spec.agent_type),
                    "depends_on": [self._task_to_key.get(d, d) for d in dep_ids],
                    "acceptance_criteria": list(spec.acceptance_criteria),
                },
                source="mission_controller",
                correlation_id=task.task_id,
            ))
        self._persist_ledger(mission.mission_id)
        return mission, run, key_to_id

    def record_plan_v1(self, run_id: str, mission_id: str) -> Dict[str, Any]:
        graph = self.engine.task_graph.get(run_id, {})
        plan = {
            "version": "v1",
            "mission_id": mission_id,
            "run_id": run_id,
            "tasks": {
                self._task_to_key.get(tid, tid): {
                    "task_id": tid,
                    "name": node.get("name") or (self.engine.tasks.get(tid).name if self.engine.tasks.get(tid) else ""),
                    "depends_on": [self._task_to_key.get(d, d) for d in node.get("depends_on", [])],
                    "state": node["state"].value if hasattr(node["state"], "value") else str(node["state"]),
                }
                for tid, node in graph.items()
            },
        }
        return plan

    # ---------- Execution ----------

    async def execute_run(self, run_id: str, max_parallel: int = 1, task_timeout: Optional[float] = None) -> Dict[str, Any]:
        """Execute the graph for a run through the engine's real production path."""
        if getattr(self, "require_plan_review", False):
            self._enforce_plan_review_gate(run_id)
        t0 = time.time()
        result = await self.engine.execute_task_graph(
            run_id=run_id,
            max_parallel=max_parallel,
            task_timeout=task_timeout,
        )
        # Normalize the engine's result shapes: the pause paths merge junk keys
        # ("results", "paused", "pause_info") into task_results, and the inner
        # pause path nests real task entries under "results".
        raw = dict(result.get("task_results", {}) or {})
        nested = raw.pop("results", None)
        if isinstance(nested, dict):
            for tid, r in nested.items():
                raw.setdefault(tid, r)
        raw.pop("paused", None)
        raw.pop("pause_info", None)
        task_results = {
            tid: {k: v for k, v in r.items() if k in ("success", "attempts", "error", "error_type", "resumed", "terminal", "output", "artifacts")}
            for tid, r in raw.items()
            if isinstance(r, dict)
        }
        # Handle human gate pause (E8)
        human_gate = result.get("human_gate", False)
        gate_info = result.get("gate_info", {})
        if human_gate:
            # Human gate pauses execution - treat as paused
            normalized = {
                "success": False,
                "paused": True,
                "pause_info": {"human_gate": True, "gate_info": gate_info},
                "task_results": task_results,
                "final_status": self.engine.get_task_graph_status(run_id),
            }
        else:
            normalized = {
                "success": result.get("success", False),
                "paused": result.get("paused", False),
                "pause_info": result.get("pause_info"),
                "task_results": task_results,
                "final_status": result.get("final_status") or self.engine.get_task_graph_status(run_id),
            }
        self.phase_log.append({
            "run_id": run_id,
            "max_parallel": max_parallel,
            "pid": _current_pid(),
            "wall_seconds": round(time.time() - t0, 3),
            "success": normalized["success"],
            "paused": normalized["paused"],
            "task_results": task_results,
        })
        self._persist_ledger(self._mission_id_for_run(run_id))
        
        # If execution completed successfully (not paused) and all tasks done, transition to EVIDENCED
        # Per E34: MissionController stops at EVIDENCED; VERIFIED requires actor='user'
        # Path: EXECUTING -> EXECUTED -> VERIFYING -> EVIDENCED
        if normalized["success"] and not normalized["paused"]:
            mission_id = self._mission_id_for_run(run_id)
            if mission_id:
                mission = self.engine.missions.get(mission_id)
                if mission and mission.state == MissionState.EXECUTING:
                    # Check if all tasks in the graph are in terminal states
                    graph = self.engine.task_graph.get(run_id, {})
                    all_terminal = all(
                        node["state"] in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED)
                        for node in graph.values()
                    )
                    if all_terminal:
                        from unified.contracts import validate_mission_transition
                        try:
                            # Transition through required path to EVIDENCED
                            for target_state in [MissionState.EXECUTED, MissionState.VERIFYING, MissionState.EVIDENCED]:
                                if mission.state != target_state:
                                    validate_mission_transition(mission.state, target_state)
                                    from_state = mission.state
                                    mission.state = target_state
                                    self.engine._emit(FactoryEvent.create(
                                        event_type=EventType.MISSION_STATE_CHANGED,
                                        mission_id=mission_id,
                                        run_id=run_id,
                                        payload={
                                            "mission_id": mission_id,
                                            "run_id": run_id,
                                            "from_state": from_state.value,
                                            "to_state": target_state.value,
                                            "actor": "mission_controller",
                                            "reason": "All tasks completed successfully",
                                        },
                                        source="mission_controller",
                                    ))
                        except Exception:
                            pass  # Best effort
        
        return normalized

    def _mission_id_for_run(self, run_id: str) -> str:
        graph = self.engine.task_graph.get(run_id, {})
        for node in graph.values():
            if node.get("mission_id"):
                return node["mission_id"]
        return ""

    # ---------- Failure detection & classification ----------

    def scan_failures(
        self,
        events: List[FactoryEvent],
        task_results: Dict[str, Dict[str, Any]],
    ) -> List[FailureRecord]:
        """DETECT + CLASSIFY failures from the event stream and task results.

        Covers both terminal failures (replan/resume territory) and
        intermediate failures recovered by the engine retry loop (their
        records are marked resolved once a TASK_RETRY + eventual
        TASK_COMPLETED for the same task is observed).
        """
        existing = {(f.task_id, f.kind.value) for f in self.failures}
        retry_task_ids = {e.correlation_id for e in events if e.event_type == EventType.TASK_RETRY}
        completed_task_ids = {e.correlation_id for e in events if e.event_type == EventType.TASK_COMPLETED}
        found: List[FailureRecord] = []
        for event in events:
            if event.event_type != EventType.TASK_FAILED:
                continue
            task_id = event.correlation_id
            if not task_id:
                continue
            payload = event.payload
            error = str(payload.get("error", "")) if hasattr(payload, "get") else str(getattr(payload, "error", ""))
            retry_count = payload.get("retry_count", None) if hasattr(payload, "get") else getattr(payload, "retry_count", None)
            max_retries = payload.get("max_retries", None) if hasattr(payload, "get") else getattr(payload, "max_retries", None)
            terminal = True
            if retry_count is not None and max_retries is not None:
                terminal = retry_count >= max_retries
            kind, reason = self._classify(error)
            dedup_key = (task_id, kind.value)
            if dedup_key in existing:
                continue
            existing.add(dedup_key)
            resolved = False
            resolved_by = ""
            if not terminal:
                # Engine-level recovery: retried and eventually completed
                if task_id in retry_task_ids and task_id in completed_task_ids:
                    resolved = True
                    resolved_by = "engine_retry_then_completed"
            record = FailureRecord(
                failure_id=f"fail-{hashlib.sha256(f'{task_id}{kind.value}{event.timestamp.isoformat()}'.encode()).hexdigest()[:12]}",
                kind=kind,
                task_id=task_id,
                task_key=self._task_to_key.get(task_id, task_id),
                description=error[:500],
                evidence=[
                    f"TASK_FAILED event at {event.timestamp.isoformat()}",
                    f"terminal={terminal} retry_count={retry_count} max_retries={max_retries}",
                ],
                detected_at=datetime.now(timezone.utc).isoformat(),
                classification_reason=reason,
                recovery_action=self._recovery_for(kind),
                resolved=resolved,
                resolved_by=resolved_by,
            )
            self.failures.append(record)
            found.append(record)
        return found

    @staticmethod
    def _classify(error: str) -> Tuple[FailureKind, str]:
        err = str(error)
        if "Verification failed" in err:
            return FailureKind.PLAN_DEVIATION, (
                "Acceptance verification failed: the plan's expectation does not match "
                "observed reality; downstream tasks built on that expectation are suspect."
            )
        if "Tool/runtime failure" in err or "sandbox" in err.lower():
            return FailureKind.TOOL_RUNTIME_FAILURE, (
                "Error originates from the sandbox/tool layer (filesystem), not from agent logic."
            )
        return FailureKind.TASK_EXECUTION_FAILURE, (
            "Error originates from agent execution logic."
        )

    @staticmethod
    def _recovery_for(kind: FailureKind) -> RecoveryAction:
        return {
            FailureKind.TASK_EXECUTION_FAILURE: RecoveryAction.RETRY,
            FailureKind.TOOL_RUNTIME_FAILURE: RecoveryAction.RETRY,
            FailureKind.PLAN_DEVIATION: RecoveryAction.REPLAN,
            FailureKind.PROCESS_INTERRUPTION: RecoveryAction.RESUME,
        }[kind]

    # ---------- Recovery ----------

    def recover_failed_task(self, run_id: str, task_id: str, reason: str) -> None:
        """Return a terminally-failed task to READY after plan correction
        (validated transition FAILED → READY; retry counter reset)."""
        task = self.engine.tasks.get(task_id)
        graph = self.engine.task_graph.get(run_id, {})
        if task is None or task_id not in graph:
            raise ValueError(f"recover_failed_task: task {task_id} not in run {run_id}")
        if graph[task_id]["state"] != TaskState.FAILED:
            raise ValueError(f"recover_failed_task: task {task_id} state is {graph[task_id]['state']}, not FAILED")
        self.engine._update_task_graph_state(run_id, task_id, TaskState.READY)
        task.retry_count = 0
        graph[task_id]["retry_count"] = 0
        self.engine._emit(FactoryEvent.create(
            event_type=EventType.STATE_TRANSITION,
            mission_id=task.mission_id,
            run_id=run_id,
            payload={
                "entity_type": "task",
                "entity_id": task_id,
                "from_state": "FAILED",
                "to_state": "READY",
                "trigger": "mission_controller_recovery",
            },
            source="mission_controller",
            correlation_id=task_id,
        ))


    async def resume_approved_task(
        self,
        run_id: str,
        task_id: str,
        *,
        actor: str = "owner",
        reason: str = "resume approved human gate",
        max_parallel: int = 1,
        task_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """E10-RP2.2-R2A1 §2.2/§2.3 — the ENGINE-DESIGNATED resume of a task
        paused at an APPROVED human gate.

        This is the ONLY sanctioned way an approved one-shot approval is
        consumable: the controller (trusted layer, owner/operator driven —
        never the agent) must be able to prove that the continuation it
        launches is the continuation of the operation that paused for the
        approval. Steps, all fail-closed:

        1. locate the task's live v2 gate record with an approve decision
           and NO consumption (a pending/rejected/consumed gate cannot be
           resumed — a new approval is required);
        2. verify the engine-issued one-shot RESUME TICKET for that
           operation exists, is ARMED and unexpired;
        3. PRE-MINT the continuation attempt id and DESIGNATE the ticket
           with it (engine trust decision; the agent has no minting or
           designation surface);
        4. re-arm the task through the engine's own validated FAILED->READY
           transition (retry budget reset) — no test-side state surgery;
        5. relaunch the run through the normal production execution path
           (execute_run -> execute_task_graph -> _execute_single_task), with
           the designated continuation attempt id injected into the launch.

        The designated attempt — and ONLY that attempt — can then consume
        the ticket in ``ToolExecutor._check_human_gate`` (single, atomic
        consumption before execution). If the designated attempt dies
        before the gate, or any other call presents the same identity, the
        approval is NOT consumed and the gate refuses fail-closed.
        """
        engine = self.engine
        mission_id = self._mission_id_for_run(run_id)
        mission = engine.missions.get(mission_id) if mission_id else None
        if mission is None:
            raise ValueError(f"resume_approved_task: no mission for run {run_id}")
        if mission.state != MissionState.EXECUTING:
            raise ValueError(
                f"resume_approved_task: mission state is {mission.state}, not "
                "EXECUTING — an approved gate must have returned the mission "
                "to EXECUTING before a resume can be designated"
            )

        # (1) locate the live approved+unconsumed v2 gate for this task
        op_key = None
        operation = None
        for key in list(mission.metadata.keys()):
            if not key.startswith("action_gate_v2:") or key.endswith(
                ("_decision", "_consumed", "_operation", "_cycles")
            ) or "#cycle" in key:
                continue
            op = mission.metadata.get(f"{key}_operation")
            if not isinstance(op, dict):
                continue
            if op.get("format") != "v2" or op.get("run_id") != run_id:
                continue
            if op.get("task_id") != task_id:
                continue
            decision = mission.metadata.get(f"{key}_decision")
            if not isinstance(decision, dict) or decision.get("decision") != "approve":
                continue
            if mission.metadata.get(f"{key}_consumed") is not None:
                continue
            op_key = key
            operation = op
            break
        if op_key is None:
            raise ValueError(
                f"resume_approved_task: no approved+unconsumed human gate for "
                f"task {task_id} in run {run_id} — a new approval is required"
            )

        # (2) the engine-issued one-shot resume ticket must exist, armed
        ticket = engine._resume_tickets.get(op_key)
        if ticket is None:
            raise ValueError(
                "resume_approved_task: no engine-issued resume ticket for the "
                "approved operation — the approval cannot be consumed "
                "(E10-RP2.2-R2A1 §2.2.5)"
            )
        if ticket.state != "armed":
            raise ValueError(
                f"resume_approved_task: resume ticket is {ticket.state!r} — "
                "only an armed ticket can be designated for a continuation"
            )

        # (3) pre-mint the continuation attempt + DESIGNATE the ticket
        continuation_attempt_id = new_attempt_id()
        engine._designate_resume_continuation(
            op_key, continuation_attempt_id, actor=actor
        )
        engine._designated_continuations[(run_id, task_id)] = continuation_attempt_id

        # (4) re-arm the task through the engine's own validated transition
        graph = engine.task_graph.get(run_id, {})
        node = graph.get(task_id)
        if node is None:
            raise ValueError(f"resume_approved_task: task {task_id} not in run {run_id}")
        state = node["state"]
        if state == TaskState.FAILED:
            self.recover_failed_task(run_id, task_id, reason or "resume_approved_task")
        elif state != TaskState.READY:
            raise ValueError(
                f"resume_approved_task: task {task_id} state is {state}, "
                "neither FAILED nor READY — refusing to resume"
            )

        # (5) relaunch through the normal production path
        result = await self.execute_run(
            run_id, max_parallel=max_parallel, task_timeout=task_timeout
        )
        return {
            "resumed": True,
            "op_key": op_key,
            "continuation_attempt_id": continuation_attempt_id,
            "result": result,
        }

    # ---------- Mission-level replanning ----------

    def replan_mission(
        self,
        run_id: str,
        deviation: FailureRecord,
        invalidate_task_ids: List[str],
        corrected_criteria: Dict[str, List[str]],
        add_specs: List[Dict[str, Any]],
        rewire: Dict[str, List[str]],
        reason: str,
        plan_version: str,
    ) -> ReplanRecord:
        """PLAN INVALIDATION → PLAN vN+1.

        - invalidates/removes tasks invalidated by the deviation (must be
          PENDING/BLOCKED/READY — never re-executes completed work),
        - corrects acceptance criteria of affected tasks (data-driven),
        - adds remediation tasks,
        - rewires dependencies of surviving downstream tasks onto the new
          tasks (values may reference added tasks as "NEW:<task_key>"),
        - re-baselines rewired tasks to BLOCKED while their new dependencies
          are incomplete (removal of invalid tasks leaves dependents
          spuriously READY; the rewire must restore the real dependency
          constraint before any further execution).

        Preserves all completed work: completed tasks are never removed,
        reset or re-executed by this operation.
        """
        graph = self.engine.task_graph.get(run_id, {})
        mission_id = self._mission_id_for_run(run_id)
        preserved = [
            tid for tid, node in graph.items()
            if node["state"] == TaskState.COMPLETED and tid not in invalidate_task_ids
        ]

        # E10-RP2 §3.5: a VERIFIER-triggered replan happens AFTER the run
        # finished (mission reached EVIDENCED through
        # EXECUTED -> VERIFYING -> EVIDENCED inside execute_run). The
        # engine's replan_task_graph only operates on an EXECUTING
        # mission, so the mission must re-enter execution through the
        # LEGAL state-machine path EVIDENCED -> ADJUDICATED -> EXECUTING
        # (adjudication semantics: verification challenged the outcome, a
        # decision was made, execution re-enters under the corrected
        # plan). Each hop is validated + durably emitted.
        if mission_id:
            mission_obj = self.engine.missions.get(mission_id)
            if mission_obj is not None and mission_obj.state != MissionState.EXECUTING:
                return_paths = {
                    MissionState.EVIDENCED: [MissionState.ADJUDICATED, MissionState.EXECUTING],
                    MissionState.VERIFYING: [MissionState.EVIDENCED, MissionState.ADJUDICATED, MissionState.EXECUTING],
                    MissionState.EXECUTED: [MissionState.VERIFYING, MissionState.EVIDENCED, MissionState.ADJUDICATED, MissionState.EXECUTING],
                    MissionState.ADJUDICATED: [MissionState.EXECUTING],
                }
                for target in return_paths.get(mission_obj.state, []):
                    validate_mission_transition(mission_obj.state, target)
                    from_state = mission_obj.state
                    mission_obj.state = target
                    self.engine._emit(FactoryEvent.create(
                        event_type=EventType.MISSION_STATE_CHANGED,
                        mission_id=mission_id,
                        run_id=run_id,
                        payload={
                            "mission_id": mission_id,
                            "run_id": run_id,
                            "from_state": from_state.value,
                            "to_state": target.value,
                            "actor": "mission_controller",
                            "reason": "verification-triggered replan: re-enter execution under the corrected plan",
                        },
                        source="mission_controller",
                    ))
        added_descriptions = [
            {"task_key": s.get("context", {}).get("task_key", ""), "depends_on": s.get("depends_on", []), "name": s.get("name", "")}
            for s in add_specs
        ]

        ok = self.engine.replan_task_graph(
            run_id=run_id,
            new_tasks=add_specs,
            modified_tasks={
                tid: {"acceptance_criteria": crit} for tid, crit in corrected_criteria.items()
            },
            removed_task_ids=list(invalidate_task_ids),
            reason=reason,
            actor="mission_controller",
        )
        if not ok:
            raise RuntimeError(f"replan_task_graph failed for run {run_id}")

        # Register new tasks in the key maps (engine created real Task objects)
        added_by_key: Dict[str, str] = {}
        for spec in add_specs:
            key = spec.get("context", {}).get("task_key", "")
            for tid, task in self.engine.tasks.items():
                if task.name == spec.get("name") and tid not in self._task_to_key:
                    self._key_to_task[key] = tid
                    self._task_to_key[tid] = key
                    added_by_key[key] = tid
                    break

        # Resolve and apply dependency rewiring as a second replan step
        rewire_resolved: Dict[str, List[str]] = {}
        for tid, deps in rewire.items():
            rewire_resolved[tid] = [
                added_by_key.get(d[4:], d) if d.startswith("NEW:") else d
                for d in deps
            ]
        rewired_keys: List[Dict[str, Any]] = []
        if rewire_resolved:
            ok2 = self.engine.replan_task_graph(
                run_id=run_id,
                new_dependencies=rewire_resolved,
                reason="Mission controller: rewire surviving downstream tasks after plan invalidation",
                actor="mission_controller",
            )
            if not ok2:
                raise RuntimeError(f"replan_task_graph (rewire) failed for run {run_id}")
            # Re-baseline: any rewired task whose dependencies are not all
            # COMPLETED must be BLOCKED (removal left it spuriously READY).
            graph = self.engine.task_graph.get(run_id, {})
            for tid in rewire_resolved:
                node = graph.get(tid)
                if node is None:
                    continue
                deps_incomplete = any(
                    graph.get(d, {}).get("state") != TaskState.COMPLETED
                    for d in node.get("depends_on", set())
                )
                if deps_incomplete and node["state"] == TaskState.READY:
                    self.engine._update_task_graph_state(run_id, tid, TaskState.BLOCKED)
                rewired_keys.append({
                    "task_key": self._task_to_key.get(tid, tid),
                    "new_depends_on": [self._task_to_key.get(d, d) for d in rewire_resolved[tid]],
                })

        record = ReplanRecord(
            from_version=self.plan_version,
            to_version=plan_version,
            reason=reason,
            evidence=list(deviation.evidence) if deviation else [],
            added_tasks=added_descriptions,
            removed_tasks=[self._task_to_key.get(t, t) for t in invalidate_task_ids],
            invalidated_tasks=[self._task_to_key.get(t, t) for t in invalidate_task_ids],
            preserved_tasks=[self._task_to_key.get(t, t) for t in preserved],
            rewired_dependencies=rewired_keys,
            modified_tasks=[
                {"task_key": self._task_to_key.get(t, t), "new_acceptance_criteria": crit}
                for t, crit in corrected_criteria.items()
            ],
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.replans.append(record)
        self.plan_version = plan_version
        for f in self.failures:
            if deviation and f.failure_id == deviation.failure_id:
                f.resolved = True
                f.resolved_by = f"replan->{plan_version}"
        self._persist_ledger(mission_id)
        return record

    # ---------- Plan review (E10-RP §3.B: review gate before continuation) ----------

    def _plan_review_checks(self, run_id: str) -> List[Dict[str, Any]]:
        """Fail-closed structural + causal review checks of the CURRENT plan
        version against the live graph and the controller's own durable
        decision records. Nothing is trusted from the caller: every check
        reads REAL state (graph, tasks, replans, failures)."""
        checks: List[Dict[str, Any]] = []
        graph = self.engine.task_graph.get(run_id, {})

        def add(name: str, passed: bool, detail: str) -> None:
            checks.append({"check": name, "passed": bool(passed), "detail": detail})

        latest = self.replans[-1] if self.replans else None

        # C1 — replan chain continuity up to the current plan version
        if latest is None:
            add("C1_version_chain", self.plan_version == "v1",
                f"no replan on record; current plan_version={self.plan_version!r}")
        else:
            prev_to = "v1"
            chain_ok = True
            for r in self.replans:
                if r.from_version != prev_to:
                    chain_ok = False
                    break
                prev_to = r.to_version
            chain_ok = chain_ok and self.plan_version == latest.to_version
            add("C1_version_chain", chain_ok,
                "replan chain " + " -> ".join(
                    [f"{r.from_version}->{r.to_version}" for r in self.replans]
                ) + f"; current plan_version={self.plan_version!r}")

        # C2 — no completed work destroyed by the latest replan
        if latest is None:
            add("C2_no_completed_destroyed", True, "no replan on record")
        else:
            destroyed = []
            for key in latest.invalidated_tasks:
                tid = self._key_to_task.get(key, key)
                node = graph.get(tid)
                if node is not None and node.get("state") == TaskState.COMPLETED:
                    destroyed.append(key)
            add("C2_no_completed_destroyed", not destroyed,
                f"invalidated={latest.invalidated_tasks}; completed-among-them={destroyed or 'none'}")

        # C3 — replan preserved set == tasks actually COMPLETED in the graph
        if latest is None:
            add("C3_preserved_matches_reality", True, "no replan on record")
        else:
            completed_now = {
                self._task_to_key.get(tid, tid)
                for tid, node in graph.items()
                if node.get("state") == TaskState.COMPLETED
            }
            preserved = set(latest.preserved_tasks)
            add("C3_preserved_matches_reality", completed_now == preserved,
                f"completed_in_graph={sorted(completed_now)}; "
                f"replan_preserved={sorted(preserved)}")

        # C4 — every task added by the latest replan exists with valid deps
        if latest is None:
            add("C4_added_tasks_present", True, "no replan on record")
        else:
            problems = []
            for spec in latest.added_tasks:
                key = spec.get("task_key", "")
                tid = self._key_to_task.get(key, "")
                node = graph.get(tid)
                if node is None:
                    problems.append(f"{key}:absent")
                    continue
                for d in node.get("depends_on", set()):
                    if graph.get(d) is None:
                        problems.append(f"{key}:dep-absent")
            add("C4_added_tasks_present", not problems,
                f"added={[s.get('task_key') for s in latest.added_tasks]}; problems={problems or 'none'}")

        # C5 — rewired tasks: deps exist; incomplete deps => BLOCKED (not READY)
        if latest is None:
            add("C5_rewire_blocked_correctness", True, "no replan on record")
        elif not latest.rewired_dependencies:
            add("C5_rewire_blocked_correctness", True, "replan rewired nothing")
        else:
            problems = []
            for rw in latest.rewired_dependencies:
                key = rw.get("task_key", "")
                tid = self._key_to_task.get(key, key)
                node = graph.get(tid)
                if node is None:
                    problems.append(f"{key}:absent")
                    continue
                deps = node.get("depends_on", set())
                for d in deps:
                    if graph.get(d) is None:
                        problems.append(f"{key}:dep-absent")
                incomplete = any(
                    graph.get(d, {}).get("state") != TaskState.COMPLETED for d in deps
                )
                if incomplete and node.get("state") == TaskState.READY:
                    problems.append(f"{key}:spuriously-READY-with-incomplete-deps")
            add("C5_rewire_blocked_correctness", not problems, f"problems={problems or 'none'}")

        # C6 — plan executable: no task may remain FAILED
        failed_tasks = [
            self._task_to_key.get(tid, tid)
            for tid, node in graph.items()
            if node.get("state") == TaskState.FAILED
        ]
        add("C6_plan_executable_no_failed_tasks", not failed_tasks,
            f"failed_tasks={failed_tasks or 'none'} (a FAILED task makes the plan not executable)")

        # C7 — causal link: the deviation record is resolved by THIS replan
        #      and the replan carries exactly the deviation's evidence.
        if latest is None:
            add("C7_causality_deviation_to_replan", True, "no replan on record")
        else:
            linked = [
                f for f in self.failures
                if f.resolved_by == f"replan->{latest.to_version}"
            ]
            ev_match = bool(latest.evidence) and any(
                list(f.evidence) == list(latest.evidence) for f in linked
            )
            add("C7_causality_deviation_to_replan", bool(linked) and ev_match,
                f"failures resolved by 'replan->{latest.to_version}': "
                f"{[f.failure_id for f in linked] or 'MISSING'}; "
                f"replan_evidence == deviation_evidence: {ev_match}")

        # C8 — corrected criteria are actually applied to the real task objects
        if latest is None:
            add("C8_corrected_criteria_applied", True, "no replan on record")
        elif not latest.modified_tasks:
            add("C8_corrected_criteria_applied", True, "replan modified no criteria")
        else:
            unapplied = []
            for m in latest.modified_tasks:
                key = m.get("task_key", "")
                tid = self._key_to_task.get(key, key)
                task = self.engine.tasks.get(tid)
                want = list(m.get("new_acceptance_criteria", []))
                have = list(getattr(task, "acceptance_criteria", []) or [])
                if have != want:
                    unapplied.append(key)
            add("C8_corrected_criteria_applied", not unapplied,
                f"modified={[m.get('task_key') for m in latest.modified_tasks]}; "
                f"unapplied={unapplied or 'none'}")

        return checks

    def review_plan(self, run_id: str, reviewer: str, note: str = "") -> PlanReviewRecord:
        """REVIEW gate for the CURRENT plan version (E10-RP §3.B).

        Fail-closed structural + causal review of the live plan against the
        controller's durable decision records. Emits a durable
        STATE_TRANSITION event (entity_type=plan_review) and appends the
        review to the durable ledger. Continuation is refused by
        execute_run's gate until the CURRENT plan version's LATEST review
        is APPROVED; a rejected review blocks until the plan is corrected
        and re-reviewed."""
        mission_id = self._mission_id_for_run(run_id)
        checks = self._plan_review_checks(run_id)
        verdict = "approved" if all(c["passed"] for c in checks) else "rejected"
        reasons = [f"{c['check']}: {c['detail']}" for c in checks if not c["passed"]]
        review_id = (
            "review-" + hashlib.sha256(
                ("|".join([run_id, self.plan_version, reviewer,
                           datetime.now(timezone.utc).isoformat()])).encode()
            ).hexdigest()[:12]
        )
        record = PlanReviewRecord(
            review_id=review_id,
            run_id=run_id,
            mission_id=mission_id,
            plan_version=self.plan_version,
            verdict=verdict,
            reviewer=reviewer,
            note=note,
            checks=checks,
            reasons=reasons,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
        )
        self.plan_reviews.append(record)
        self._persist_ledger(mission_id)
        self.engine._emit(FactoryEvent.create(
            event_type=EventType.STATE_TRANSITION,
            mission_id=mission_id,
            run_id=run_id,
            payload={
                "entity_type": "plan_review",
                "entity_id": self.plan_version,
                "from_state": "REVIEWING",
                "to_state": "APPROVED" if verdict == "approved" else "REJECTED",
                "trigger": reviewer,
                "review_id": review_id,
                "failed_checks": [c["check"] for c in checks if not c["passed"]],
                "note": note,
            },
            source="mission_controller",
            correlation_id=run_id,
        ))
        return record

    def _enforce_plan_review_gate(self, run_id: str) -> None:
        """E10-RP fail-closed continuation gate: execution may only proceed
        under the CURRENT plan version when that version's LATEST review is
        APPROVED. Anything else refuses (RuntimeError) BEFORE any execution
        starts — unapproved plan, never-reviewed plan, rejected review alike."""
        if not self.plan_reviews:
            raise RuntimeError(
                f"PLAN_REVIEW_GATE: continuation REFUSED for run {run_id}: "
                f"plan {self.plan_version!r} has never been reviewed (fail-closed)"
            )
        for_version = [r for r in self.plan_reviews if r.plan_version == self.plan_version]
        if not for_version:
            raise RuntimeError(
                f"PLAN_REVIEW_GATE: continuation REFUSED for run {run_id}: "
                f"plan {self.plan_version!r} has no review "
                f"(latest review covers {self.plan_reviews[-1].plan_version!r}); fail-closed"
            )
        latest = for_version[-1]
        if latest.verdict != "approved":
            raise RuntimeError(
                f"PLAN_REVIEW_GATE: continuation REFUSED for run {run_id}: "
                f"plan {self.plan_version!r} review {latest.review_id} is "
                f"{latest.verdict.upper()} — "
                f"{'; '.join(latest.reasons) or 'no reasons'}; fail-closed"
            )

    # ---------- Checkpointing ----------

    def emit_marker(self, mission_id: str, run_id: str, trigger: str, detail: Dict[str, Any]) -> None:
        """Emit a controller marker event BEFORE durable operations so that the
        persisted event log includes the intent (the engine emits its own
        CHECKPOINT_CREATED only after persisting)."""
        self.engine._emit(FactoryEvent.create(
            event_type=EventType.STATE_TRANSITION,
            mission_id=mission_id,
            run_id=run_id,
            payload={
                "entity_type": "mission",
                "entity_id": mission_id,
                "from_state": "",
                "to_state": "",
                "trigger": trigger,
                "detail": detail,
            },
            source="mission_controller",
        ))

    def create_full_checkpoint(self, mission_id: str, run_id: str, step: int) -> Checkpoint:
        """Checkpoint with FULL restoration state: definitions incl. context,
        dependencies, attempt history."""
        graph = self.engine.task_graph.get(run_id, {})
        task_states = {tid: node["state"] for tid, node in graph.items()}
        task_definitions: Dict[str, Dict[str, Any]] = {}
        for tid in graph:
            t = self.engine.tasks.get(tid)
            node = graph[tid]
            at = t.agent_type if t else node.get("agent_type", AgentType.IMPLEMENTER)
            # Find the key for this task_id from _key_to_task
            task_key = None
            for k, v in self._key_to_task.items():
                if v == tid:
                    task_key = k
                    break
            task_definitions[tid] = {
                "key": task_key,
                "name": t.name if t else node.get("name", ""),
                "description": t.description if t else node.get("description", ""),
                "agent_type": at.value if hasattr(at, "value") else str(at),
                "acceptance_criteria": list(t.acceptance_criteria) if t else list(node.get("acceptance_criteria", [])),
                "max_retries": getattr(t, "max_retries", 2) if t else node.get("max_retries", 2),
                "retry_count": getattr(t, "retry_count", 0) if t else node.get("retry_count", 0),
                "context": dict(t.context) if t else {},
            }
        task_dependencies = {tid: list(node.get("depends_on", [])) for tid, node in graph.items()}
        task_dependents = {tid: list(node.get("dependents", [])) for tid, node in graph.items()}
        attempt_history: Dict[str, List[Dict[str, Any]]] = {}
        for attempt in self.engine.attempts.values():
            if attempt.task_id in graph:
                attempt_history.setdefault(attempt.task_id, []).append({
                    "attempt_id": attempt.attempt_id,
                    "task_id": attempt.task_id,
                    "agent_id": attempt.agent_id,
                    "state": attempt.state.value if hasattr(attempt.state, "value") else str(attempt.state),
                    "success": attempt.success,
                    "error": attempt.error,
                    "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
                    "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
                })
        artifact_ids = [
            aid for aid, art in self.engine.evidence_store._artifacts.items()
            if getattr(art, "mission_id", "") == mission_id
        ]
        evidence_hashes = [
            ev.evidence_hash for ev in self.engine.evidence_store._evidence.values()
            if ev.mission_id == mission_id
        ]
        mission = self.engine.missions.get(mission_id)
        state = mission.state if mission else MissionState.EXECUTING
        return self.engine.create_checkpoint(
            mission_id=mission_id,
            run_id=run_id,
            step=step,
            state=state,
            task_states=task_states,
            artifact_ids=artifact_ids,
            evidence_hashes=evidence_hashes,
            task_definitions=task_definitions,
            task_dependencies=task_dependencies,
            task_dependents=task_dependents,
            attempt_history=attempt_history,
        )

    # ---------- No-false-re-execution ledger ----------

    def build_reexecution_ledger(
        self,
        mission_id: str,
        resume_marker: Optional[FactoryEvent],
        expected: Dict[str, str],
        absent_tasks: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Derive the attempt ledger from the event history alone.

        expected: key -> one of PRESERVED | EXECUTED_POST_RESUME | INVALIDATED
        absent_tasks: key -> task_id for tasks removed from the final graph by
        replanning (E/F) — verified to have ZERO attempts in the whole history.
        A task is PRESERVED iff it had attempt(s) before the resume marker and
        none after it. FALSE_REEXECUTION = attempts after resume for a task
        expected to be preserved.
        """
        events = [e for e in self.engine.event_bus.history if e.mission_id == mission_id]
        marker_ts = resume_marker.timestamp if resume_marker else datetime.max.replace(tzinfo=timezone.utc)
        rows: Dict[str, Dict[str, Any]] = {}

        def _row(task_id: str) -> Dict[str, Any]:
            key = self._task_to_key.get(task_id, task_id)
            if key not in rows:
                rows[key] = {
                    "task_key": key,
                    "task_id": task_id,
                    "attempts_before_interruption": [],
                    "attempts_after_resume": [],
                }
            return rows[key]

        for e in events:
            if e.event_type != EventType.TASK_ASSIGNED:
                continue
            payload = e.payload
            tid = payload.get("task_id", "") if hasattr(payload, "get") else getattr(payload, "task_id", "")
            aid = payload.get("attempt_id", "") if hasattr(payload, "get") else getattr(payload, "attempt_id", "")
            if not tid:
                continue
            row = _row(tid)
            entry = {"attempt_id": aid, "at": e.timestamp.isoformat()}
            # TASK_ASSIGNED is emitted twice per attempt (engine duplicates the
            # emission) — dedup by attempt_id.
            pool = row["attempts_before_interruption"] if e.timestamp <= marker_ts else row["attempts_after_resume"]
            if not any(a["attempt_id"] == aid for a in pool):
                pool.append(entry)

        graph = self.engine.task_graph
        all_nodes: Dict[str, Dict[str, Any]] = {}
        for rid, g in graph.items():
            for tid, node in g.items():
                all_nodes[tid] = node

        ledger: List[Dict[str, Any]] = []
        seen_keys = set(rows.keys())
        for key in sorted(rows.keys() | set((absent_tasks or {}).keys())):
            if key in (absent_tasks or {}):
                tid = absent_tasks[key]
                total_attempts = sum(
                    1 for e in events
                    if e.event_type == EventType.TASK_ASSIGNED
                    and (e.payload.get("task_id", "") if hasattr(e.payload, "get") else getattr(e.payload, "task_id", "")) == tid
                )
                base = {
                    "task_key": key,
                    "task_id": tid,
                    "attempts_before_interruption": [],
                    "attempts_after_resume": [],
                    "total_attempts_in_history": total_attempts,
                    "final_state": "ABSENT_FROM_FINAL_GRAPH",
                }
                base["expected"] = expected.get(key, "INVALIDATED")
                actual = "INVALIDATED" if total_attempts == 0 else "UNEXPECTED_ATTEMPTS"
            else:
                base = rows[key]
                tid = base["task_id"]
                node = all_nodes.get(tid)
                base["final_state"] = (
                    node["state"].value if node and hasattr(node.get("state"), "value")
                    else (str(node.get("state")) if node else "ABSENT_FROM_FINAL_GRAPH")
                )
                before = len(base["attempts_before_interruption"])
                after = len(base["attempts_after_resume"])
                if expected.get(key) == "PRESERVED":
                    actual = "PRESERVED" if (before > 0 and after == 0) else (
                        "FALSE_REEXECUTION" if after > 0 else "LOST_STATE"
                    )
                elif expected.get(key) == "EXECUTED_POST_RESUME":
                    actual = "EXECUTED_POST_RESUME" if (before == 0 and after > 0) else "UNEXPECTED_PRE_RESUME_ATTEMPTS"
                elif expected.get(key) == "INVALIDATED":
                    actual = "INVALIDATED" if before == 0 and after == 0 else "UNEXPECTED_ATTEMPTS"
                else:
                    actual = "UNEXPECTED_TASK"
            base["expected"] = expected.get(key, "INVALIDATED" if key in (absent_tasks or {}) else "UNSPECIFIED")
            base["actual"] = actual
            base["verdict"] = "OK" if actual == base["expected"] else ("FALSE_REEXECUTION" if actual == "FALSE_REEXECUTION" else "MISMATCH")
            ledger.append(base)
        return ledger

    # ---------- Completion (section 14) ----------

    def verify_completion(self, run_id: str, required_keys: List[str]) -> Tuple[bool, Dict[str, Any]]:
        """Mission completion verification — not 'last task said DONE':
        all required tasks COMPLETED, all declared dependencies satisfied,
        verification evidenced for tasks that had criteria, no unresolved
        blockers, no pending/ready work left."""
        graph = self.engine.task_graph.get(run_id, {})
        report: Dict[str, Any] = {
            "run_id": run_id,
            "required_task_keys": required_keys,
            "checks": {},
        }
        ok = True

        missing = [k for k in required_keys if self._key_to_task.get(k) not in graph]
        report["checks"]["all_required_tasks_present"] = {"passed": not missing, "missing": missing}
        ok = ok and not missing

        not_completed = [
            k for k in required_keys
            if graph.get(self._key_to_task.get(k, ""), {}).get("state") != TaskState.COMPLETED
        ]
        report["checks"]["all_required_tasks_completed"] = {"passed": not not_completed, "not_completed": not_completed}
        ok = ok and not not_completed

        dep_failures = []
        for k in required_keys:
            tid = self._key_to_task.get(k, "")
            node = graph.get(tid, {})
            for dep in node.get("depends_on", set()):
                dep_node = graph.get(dep, {})
                if dep_node.get("state") != TaskState.COMPLETED:
                    dep_failures.append({"task": k, "dependency": dep, "state": str(dep_node.get("state"))})
        report["checks"]["all_dependencies_satisfied"] = {"passed": not dep_failures, "violations": dep_failures}
        ok = ok and not dep_failures

        unresolved = [
            {"task": self._task_to_key.get(tid, tid), "state": node["state"].value}
            for tid, node in graph.items()
            if node["state"] in (TaskState.PENDING, TaskState.READY, TaskState.ASSIGNED, TaskState.RUNNING, TaskState.BLOCKED, TaskState.FAILED)
        ]
        report["checks"]["no_unresolved_work"] = {"passed": not unresolved, "unresolved": unresolved}
        ok = ok and not unresolved

        verif_events = [
            e for e in self.engine.event_bus.history
            if e.mission_id == self._mission_id_for_run(run_id) and e.event_type == EventType.VERIFICATION_COMPLETE
        ]
        evidenced = 0
        not_evidenced = 0
        for e in verif_events:
            payload = e.payload
            verdict = payload.get("verdict", "") if hasattr(payload, "get") else getattr(payload, "verdict", "")
            if verdict in ("evidenced", "passed"):
                evidenced += 1
            else:
                not_evidenced += 1

        # E10-RP2 §3 — VERIFICATION TRUTH (per-task latest-verdict +
        # plan-version validity). The pre-RP2 rule (``evidenced > 0``) let
        # ANY evidenced verification anywhere — another task's, or a stale
        # one predating a criteria correction — cover a CURRENT unresolved
        # not_evidenced result. The new rule, per required task T that has
        # acceptance criteria:
        #   1. T must have been verified at all;
        #   2. T's LATEST verification verdict must be evidenced/passed
        #      (older evidenced + newer unresolved not_evidenced FAILS;
        #      newer evidenced resolves an older not_evidenced —
        #      historical failures never block success forever);
        #   3. that latest evidenced verification must be VERSION-VALID:
        #      performed at/after the plan version in which T's criteria
        #      were last set (a criteria correction invalidates older
        #      evidence — resolution needs NEWER valid evidence bound to
        #      the corrected task + corrected plan).
        # Plan version per event: the payload's plan_version when the
        # emitter stamped it (canonical verifier), else derived from the
        # controller's own replan records by timestamp (engine
        # verify_task events carry no version).
        def _pv_payload(ev, name, default=None):
            p = ev.payload
            if hasattr(p, "get"):
                try:
                    return p.get(name, default)
                except Exception:
                    return default
            return getattr(p, name, default)

        def _replan_touched_ids(r) -> set:
            """task ids + keys whose criteria were (re)set by replan r."""
            touched = set()
            for m in r.modified_tasks:
                key = m.get("task_key", "")
                touched.add(key)
                touched.add(self._key_to_task.get(key, key))
            for a in r.added_tasks:
                key = a.get("task_key", "")
                touched.add(key)
                touched.add(self._key_to_task.get(key, key))
            return touched

        replan_marks = [
            (r.timestamp, r.to_version, _replan_touched_ids(r))
            for r in self.replans
        ]
        version_order = {"v1": 0}
        for i, r in enumerate(self.replans, start=1):
            version_order[r.to_version] = i

        def _version_at(ts_iso: str) -> str:
            version = "v1"
            for rts, to_v, _t in replan_marks:
                if str(rts) <= str(ts_iso):
                    version = to_v
            return version

        def _criteria_version(task_id: str, task_key: str) -> str:
            version = "v1"
            for _rts, to_v, touched in replan_marks:
                if task_id in touched or task_key in touched:
                    version = to_v
            return version

        per_task: Dict[str, list] = {}
        for e in verif_events:
            tid = _pv_payload(e, "task_id", "") or e.correlation_id or ""
            if not tid:
                continue
            verdict = _pv_payload(e, "verdict", "")
            stamped = _pv_payload(e, "plan_version", None)
            plan_version = stamped if stamped is not None else _version_at(e.timestamp.isoformat())
            per_task.setdefault(tid, []).append({
                "verdict": verdict,
                "attempt_id": _pv_payload(e, "attempt_id", ""),
                "plan_version": plan_version,
                "timestamp": e.timestamp.isoformat(),
                "stamped_by_emitter": stamped is not None,
            })

        verification_failures = []
        per_task_report = {}
        for k in required_keys:
            tid = self._key_to_task.get(k, "")
            task_obj = self.engine.tasks.get(tid)
            if task_obj is None or not getattr(task_obj, "acceptance_criteria", None):
                continue  # only tasks that HAD criteria need verification
            history = sorted(per_task.get(tid, []), key=lambda v: v["timestamp"])
            crit_version = _criteria_version(tid, k)
            entry = {
                "task_key": k,
                "verifications": len(history),
                "criteria_version": crit_version,
            }
            if not history:
                verification_failures.append({
                    "task": k, "reason": "no_verification",
                    "detail": "required task with criteria was never verified"})
                entry["latest_verdict"] = None
            else:
                latest = history[-1]
                entry["latest_verdict"] = latest["verdict"]
                entry["latest_plan_version"] = latest["plan_version"]
                if latest["verdict"] not in ("evidenced", "passed"):
                    verification_failures.append({
                        "task": k,
                        "reason": "current_unresolved_verification_failure",
                        "detail": (
                            f"latest verification verdict={latest['verdict']!r} "
                            f"@{latest['timestamp']} (plan {latest['plan_version']}) — "
                            "a current unresolved failure cannot be covered by "
                            "another task's or an older evidenced result")})
                elif (version_order.get(latest["plan_version"], 0)
                        < version_order.get(crit_version, 0)):
                    verification_failures.append({
                        "task": k,
                        "reason": "stale_evidence_for_corrected_criteria",
                        "detail": (
                            f"latest evidenced verification is under plan "
                            f"{latest['plan_version']} but the task's criteria "
                            f"were last set in {crit_version} — corrected "
                            "criteria need newer valid evidence")})
            per_task_report[k] = entry

        report["checks"]["verification_history"] = {
            "passed": evidenced > 0 and not verification_failures,
            "evidenced_verifications": evidenced,
            "not_evidenced_verifications": not_evidenced,
            "per_task": per_task_report,
            "verification_failures": verification_failures,
            "rule": (
                "per-task latest-verdict + plan-version validity "
                "(E10-RP2 §3): a current unresolved not_evidenced result "
                "cannot be covered by another task's success or by stale "
                "evidence predating a criteria correction"),
        }
        ok = ok and evidenced > 0 and not verification_failures
        report["verdict"] = "COMPLETE" if ok else "INCOMPLETE"
        return ok, report

    # ---------- Checkpoint/Resume (E51) ----------
    
    def create_checkpoint(
        self,
        mission_id: str,
        run_id: str,
        step: int,
        state: MissionState,
        task_states: Dict[str, TaskState],
        artifact_ids: List[str],
        evidence_hashes: List[str],
    ) -> Checkpoint:
        """Create a checkpoint for the mission/run."""
        graph = self.engine.task_graph.get(run_id, {})
        
        # Build task definitions from graph and Task objects
        task_definitions = {}
        task_dependencies = {}
        task_dependents = {}
        agent_assignments = {}
        
        for tid, node in graph.items():
            # Get task definition from engine.tasks
            task_obj = self.engine.tasks.get(tid)
            if task_obj:
                task_definitions[tid] = {
                    "name": task_obj.name,
                    "description": task_obj.description,
                    "agent_type": task_obj.agent_type.value if hasattr(task_obj.agent_type, 'value') else str(task_obj.agent_type),
                    "depends_on": task_obj.depends_on,
                    "acceptance_criteria": task_obj.acceptance_criteria,
                    "max_retries": task_obj.max_retries,
                    "retry_count": task_obj.retry_count,
                    "context": task_obj.context,
                }
            task_dependencies[tid] = list(node.get("depends_on", set()))
            # Build dependents
            for dep in node.get("depends_on", set()):
                if dep not in task_dependents:
                    task_dependents[dep] = []
                task_dependents[dep].append(tid)
            if tid not in task_dependents:
                task_dependents[tid] = []
            
            # Agent assignment from event history
            for ev in self.engine.event_bus.history:
                if ev.event_type == EventType.TASK_ASSIGNED and ev.payload.get("task_id") == tid:
                    agent_assignments[tid] = ev.payload.get("agent_id", "")
                    break
        
        # Build attempt history from events
        attempt_history = {}
        for tid in graph:
            attempts = []
            # Track the current attempt state
            current_attempt = {}
            for ev in self.engine.event_bus.history:
                if ev.payload.get("task_id") == tid:
                    if ev.event_type == EventType.TASK_ASSIGNED:
                        # New attempt started
                        if current_attempt:
                            attempts.append(current_attempt)
                        current_attempt = {
                            "attempt_id": ev.payload.get("attempt_id", ""),
                            "task_id": tid,
                            "agent_id": ev.payload.get("agent_id", ""),
                            "state": "ASSIGNED",
                            "success": False,
                            "error": "",
                            "started_at": ev.timestamp.isoformat() if ev.timestamp else "",
                            "completed_at": "",
                        }
                    elif ev.event_type == EventType.TASK_STARTED:
                        if current_attempt:
                            current_attempt["state"] = "RUNNING"
                    elif ev.event_type == EventType.TASK_COMPLETED:
                        if current_attempt:
                            current_attempt["state"] = "COMPLETED"
                            current_attempt["success"] = True
                            current_attempt["completed_at"] = ev.timestamp.isoformat() if ev.timestamp else ""
                            attempts.append(current_attempt)
                            current_attempt = {}
                    elif ev.event_type == EventType.TASK_FAILED:
                        if current_attempt:
                            current_attempt["state"] = "FAILED"
                            current_attempt["success"] = False
                            current_attempt["error"] = ev.payload.get("error", "Task failed")
                            current_attempt["completed_at"] = ev.timestamp.isoformat() if ev.timestamp else ""
                            attempts.append(current_attempt)
                            current_attempt = {}
            if current_attempt:
                attempts.append(current_attempt)
            if attempts:
                attempt_history[tid] = attempts
        
        # Get human gate/decision from mission metadata for durability (E34)
        mission = self.engine.missions.get(mission_id)
        human_gate = mission.metadata.get("human_gate") if mission else None
        human_decision = mission.metadata.get("human_decision") if mission else None
        
        checkpoint = Checkpoint(
            mission_id=mission_id,
            run_id=run_id,
            step=step,
            state=state,
            task_states=task_states,
            artifact_ids=artifact_ids,
            evidence_hashes=evidence_hashes,
            task_definitions=task_definitions,
            task_dependencies=task_dependencies,
            task_dependents=task_dependents,
            attempt_history=attempt_history,
            agent_assignments=agent_assignments,
            human_gate=human_gate,
            human_decision=human_decision,
        )
        # E10-CI-02: real integrity hash over canonical payload before persisting
        checkpoint.hash = checkpoint.compute_integrity_hash()
        
        # Save checkpoint via engine for cross-runtime resume
        self.engine.checkpoints[checkpoint.checkpoint_id] = checkpoint
        self.engine._save_checkpoint_to_disk(checkpoint)
        
        return checkpoint

    def list_checkpoints(self) -> List[Checkpoint]:
        """List all checkpoints for all missions."""
        checkpoints = []
        if self.state_dir:
            cp_base = self.state_dir / "checkpoints"
            if cp_base.exists():
                for mission_dir in cp_base.iterdir():
                    if mission_dir.is_dir():
                        for cp_file in mission_dir.glob("checkpoint-*.json"):
                            with open(cp_file, "r") as f:
                                data = json.load(f)
                                checkpoints.append(Checkpoint(**data))
        return checkpoints

    def restore_from_checkpoint(self, checkpoint_id: str) -> bool:
        """Restore mission/run state from checkpoint."""
        # Find checkpoint file
        cp_file = None
        if self.state_dir:
            cp_base = self.state_dir / "checkpoints"
            if cp_base.exists():
                for mission_dir in cp_base.iterdir():
                    if mission_dir.is_dir():
                        for f in mission_dir.glob("checkpoint-*.json"):
                            with open(f, "r") as ff:
                                data = json.load(ff)
                                if data.get("checkpoint_id") == checkpoint_id:
                                    cp_file = f
                                    break
                    if cp_file:
                        break
        
        if not cp_file:
            return False
        
        with open(cp_file, "r") as f:
            data = json.load(f)
        
        checkpoint = Checkpoint(**data)
        # E10-CI-04 / section 22: reject unverifyable or tampered checkpoints
        # before touching any engine state.
        if not checkpoint.verify():
            raise CheckpointIntegrityError(
                f"Checkpoint {checkpoint_id} integrity verification FAILED on restore: "
                f"stored_hash={checkpoint.hash!r} "
                f"recomputed_hash={checkpoint.compute_integrity_hash()!r}"
            )
        run_id = checkpoint.run_id
        
        # Restore task graph
        graph = self.engine.task_graph.setdefault(run_id, {})
        for tid, state in checkpoint.task_states.items():
            if tid in graph:
                graph[tid]["state"] = state
            else:
                # Rebuild task node from checkpoint
                task_def = checkpoint.task_definitions.get(tid, {})
                graph[tid] = {
                    "state": state,
                    "spec": type('Spec', (), task_def)() if task_def else None,
                    "depends_on": set(checkpoint.task_dependencies.get(tid, [])),
                    "dependents": set(checkpoint.task_dependents.get(tid, [])),
                    "attempts": checkpoint.attempt_history.get(tid, []),
                }
        
        # Restore mission state
        mission = self.engine.missions.get(checkpoint.mission_id)
        if mission:
            mission.state = checkpoint.state
        
        return True

    def finalize_mission(self, mission_id: str, run_id: str, reason: str = "All mission completion conditions verified") -> Dict[str, Any]:
        """Drive the mission state machine to EVIDENCED and emit
        RUN_COMPLETED + MISSION_COMPLETED. Owner-gated VERIFIED is intentionally
        not set autonomously."""
        mission = self.engine.missions.get(mission_id)
        path = []
        
        # Only transition through states if not already at or beyond EVIDENCED
        current_state = mission.state
        target_states = [MissionState.EXECUTED, MissionState.VERIFYING, MissionState.EVIDENCED]
        
        # Define state order for comparison
        state_order = {
            MissionState.RECEIVED: 0,
            MissionState.ANALYZING: 1,
            MissionState.PLANNING: 2,
            MissionState.DESIGNING: 3,
            MissionState.REVIEWING: 4,
            MissionState.APPROVED: 5,
            MissionState.REVISE: 6,
            MissionState.AWAITING_APPROVAL: 7,
            MissionState.EXECUTING: 8,
            MissionState.EXECUTED: 9,
            MissionState.VERIFYING: 10,
            MissionState.EVIDENCED: 11,
            MissionState.VERIFIED: 12,
            MissionState.ADJUDICATED: 13,
            MissionState.PAUSED: 14,
            MissionState.STOPPING: 15,
            MissionState.STOPPED: 16,
            MissionState.CANCEL_REQUESTED: 17,
            MissionState.CANCELLED: 18,
            MissionState.HUMAN_REQUIRED: 19,
            MissionState.ESCALATED_TO_HUMAN: 20,
        }
        
        current_order = state_order.get(current_state, 0)
        
        for state in target_states:
            target_order = state_order.get(state, 0)
            if current_order >= target_order:
                # Already at or beyond this state, skip
                continue
            self._transition_mission(mission, state, actor="mission_controller", reason=reason)
            path.append(state.value)
            current_order = target_order
        self.engine._emit(FactoryEvent.create(
            event_type=EventType.RUN_COMPLETED,
            mission_id=mission_id,
            run_id=run_id,
            payload={
                "run_id": run_id,
                "mission_id": mission_id,
                "success": True,
                "tasks_completed": len([
                    t for t in self.engine.tasks.values() if t.run_id == run_id and t.state == TaskState.COMPLETED
                ]),
                "tasks_failed": 0,
            },
            source="mission_controller",
        ))
        self.engine._emit(FactoryEvent.create(
            event_type=EventType.MISSION_COMPLETED,
            mission_id=mission_id,
            run_id=run_id,
            payload=MissionCompletedEvent(
                mission_id=mission_id,
                final_state=mission.state.value,
                duration_seconds=0.0,
                total_tokens=0,
                artifact_count=len([
                    a for a in self.engine.evidence_store._artifacts.values()
                    if getattr(a, "mission_id", "") == mission_id
                ]),
                verification_result="evidenced",
            ),
            source="mission_controller",
        ))
        self.engine._save_events_to_disk(mission_id)
        self.engine.evidence_store.save_to_disk(mission_id)
        result = {"mission_id": mission_id, "state_path": ["EXECUTING"] + path, "final_state": mission.state.value}
        self._persist_ledger(mission_id)
        return result

    # ---------- Export / persistence ----------

    def export_event_trace(self, mission_id: str) -> List[Dict[str, Any]]:
        trace = []
        for e in self.engine.event_bus.history:
            if e.mission_id != mission_id:
                continue
            payload = e.payload
            if hasattr(payload, "model_dump"):
                payload_out = payload.model_dump(mode="json")
            elif isinstance(payload, dict):
                payload_out = payload
            else:
                payload_out = str(payload)
            trace.append({
                "event_type": e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type),
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "mission_id": e.mission_id,
                "run_id": e.run_id,
                "correlation_id": e.correlation_id,
                "source": e.source,
                "payload": payload_out,
            })
        return trace

    def export_evidence_chain(self, mission_id: str) -> List[Dict[str, Any]]:
        chain = []
        for eid, ev in self.engine.evidence_store._evidence.items():
            if ev.mission_id != mission_id:
                continue
            chain.append({
                "evidence_id": eid,
                "evidence_hash": ev.evidence_hash,
                "content_type": ev.content_type,
                "source_id": ev.source_id,
                "mission_id": ev.mission_id,
                "run_id": ev.run_id,
                "task_id": ev.task_id,
            })
        return chain

    def ledger_snapshot(self) -> Dict[str, Any]:
        return {
            "plan_version": self.plan_version,
            "failures": [asdict(f) for f in self.failures],
            "replans": [asdict(r) for r in self.replans],
            "plan_reviews": [asdict(rv) for rv in self.plan_reviews],
            "phases": self.phase_log,
            "key_map": dict(self._key_to_task),
        }

    def _persist_ledger(self, mission_id: str) -> None:
        if not mission_id:
            return
        d = self.state_dir / "mission_controller" / mission_id
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "ledger.json", "w", encoding="utf-8") as f:
            json.dump(self.ledger_snapshot(), f, indent=2, default=str)
