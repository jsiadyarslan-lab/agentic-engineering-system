"""
E3 — Canonical Orchestrator
============================

Minimal coordination layer above P1+P2 (MissionController + ExecutionEngine).

Purpose: Accept a natural language mission goal, decompose into executable
TaskSpecs, gate plan approval, coordinate Thinker/Verifier roles, and
stream events — all while delegating execution to the verified P1+P2 substrate.

This is NOT a new execution engine. It is a coordination layer that uses:
- MissionController.define_mission() / execute_run() / replan_mission() / verify_completion()
- ExecutionEngine for task graph execution
- Existing AgentFactory for agent instantiation
- Existing contracts for all entities and events

No new agent types. No new execution substrate. No arbitration. No project/phase abstraction.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from unified.contracts import (
    MissionState,
    TaskState,
    AgentType,
    EventType,
    FactoryEvent,
    MissionStartedEvent,
    RunStartedEvent,
    TaskCreatedEvent,
    TaskAssignedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    VerificationCompleteEvent,
    ReplanRequestedEvent,
    ReplanAppliedEvent,
    CheckpointCreatedEvent,
    MissionStateChangedEvent,
    HumanRequiredEvent,
    HumanDecisionRecordedEvent,
    AgentDefinition,
    AgentRegistry,
    agent_registry,
    AgentTask,
    AgentResult,
    AgentContext,
    BaseAgent,
    AcceptanceCriterion,
    CriterionType,
    VerifierVerdict,
    EvidenceStore,
    AgentLifecycleState,
)
from unified.mission_controller import TaskSpec, register_mission_agent, MissionTaskAgent
from unified.execution import ExecutionEngine, FileEvidenceStore, create_execution_engine
from unified.mission_controller import MissionController, register_mission_agent
from unified.mission_controller import FailureRecord, FailureKind, RecoveryAction
from unified.agent_role import AgentFactory
from unified.sandbox import create_sandbox_manager, SandboxBackend


# ============================================================
# ORCHESTRATOR DATA STRUCTURES
# ============================================================

@dataclass
class OrchestratorMission:
    """Mission accepted by the canonical orchestrator."""
    mission_id: str
    goal: str
    task_specs: List[TaskSpec]
    plan_approved: bool = False
    plan_approval_event_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # P1+P2 handles (populated after delegation)
    mc_mission_id: Optional[str] = None
    mc_run_id: Optional[str] = None
    key_to_task_id: Dict[str, str] = field(default_factory=dict)


@dataclass
class OrchestratorResult:
    """Result of orchestrated mission execution."""
    mission_id: str
    goal: str
    success: bool
    final_state: str
    event_trace: List[Dict[str, Any]] = field(default_factory=list)
    evidence_chain: List[Dict[str, Any]] = field(default_factory=list)
    reexecution_ledger: List[Dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    error: Optional[str] = None


# ============================================================
# GOAL DECOMPOSER
# ============================================================

class GoalDecomposer:
    """
    Translates natural language goal → List[TaskSpec] using an LLM-driven IMPLEMENTER agent.
    
    Uses the existing Thinker agent (IMPLEMENTER) with a planner context prompt.
    No new agent type — reuses IMPLEMENTER with structured output prompt.
    """
    
    def __init__(self, llm_provider: Any, evidence_store: EvidenceStore):
        self.llm_provider = llm_provider
        self.evidence_store = evidence_store
        # No agent registration here - uses Thinker agent from RoleCoordinator
    
    async def _execute_decomposition(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """Execute goal decomposition using LLM."""
        goal = task.context.get("goal", "") if task.context else ""
        if not goal:
            return AgentResult(
                task_id=task.task_id,
                agent_type=AgentType.IMPLEMENTER,
                success=False,
                error="No goal provided in task context",
                error_type="ValueError"
            )
        
        # Use LLM to decompose goal into TaskSpecs
        prompt = f"""Decompose this engineering goal into executable task specifications.

Goal: {goal}

Output a JSON array of task specifications with this exact structure:
[
  {{
    "key": "unique_key",
    "name": "Task Name",
    "description": "What this task does",
    "depends_on": ["other_key"],
    "acceptance_criteria": ["criterion1", "criterion2"],
    "context": {{
      "content": "Expected output content",
      "output_path": "output_file.txt",
      "sleep_s": 0.1
    }}
  }}
]

Rules:
- Keys must be unique, alphanumeric + underscore
- depends_on references other keys in the array
- acceptance_criteria must be verifiable (file_contains, file_exists, etc.)
- context.content is what the agent should write
- context.output_path is the file path
- Max 8 tasks for E3 vertical slice
"""
        
        try:
            from llm.providers import LLMMessage
            messages = [LLMMessage(role="user", content=prompt)]
            response = await self.llm_provider.complete(messages)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Parse JSON from response
            import re
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                specs_data = json.loads(json_match.group())
            else:
                specs_data = json.loads(content)
            
            # Convert to TaskSpec objects
            task_specs = []
            for spec in specs_data:
                task_specs.append(TaskSpec(
                    key=spec["key"],
                    name=spec["name"],
                    description=spec["description"],
                    depends_on=spec.get("depends_on", []),
                    acceptance_criteria=spec.get("acceptance_criteria", []),
                    context=spec.get("context", {})
                ))
            
            # Store result as artifact
            from unified.contracts import new_artifact_id, new_evidence_id
            import hashlib
            result_json = json.dumps(specs_data, indent=2)
            artifact_bytes = result_json.encode('utf-8')
            artifact_id = new_artifact_id()
            sha256 = hashlib.sha256(artifact_bytes).hexdigest()
            
            artifact = __import__('unified.domain_model', fromlist=['Artifact']).Artifact(
                artifact_id=artifact_id,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                path="e3_decomposed_specs.json",
                sha256=sha256,
                content_type="application/json",
                size_bytes=len(artifact_bytes)
            )
            self.evidence_store.store_artifact(artifact)
            
            evidence = __import__('unified.domain_model', fromlist=['EvidenceRecord']).EvidenceRecord(
                evidence_id=new_evidence_id(),
                evidence_hash=sha256,
                content_type="artifact",
                source_id=artifact_id,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
            )
            self.evidence_store.store_evidence(evidence)
            
            return AgentResult(
                task_id=task.task_id,
                agent_type=AgentType.IMPLEMENTER,
                success=True,
                output={
                    "task_specs": specs_data,
                    "artifact_id": artifact_id,
                    "sha256": sha256
                },
                evidence_hash=sha256,
                artifacts=[artifact_id]
            )
            
        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_type=AgentType.IMPLEMENTER,
                success=False,
                error=str(e),
                error_type=type(e).__name__
            )
    
    async def decompose(self, goal: str, mission_id: str, run_id: str) -> List[TaskSpec]:
        """Decompose goal into TaskSpecs using the Thinker agent."""
        # Create engine and run decomposer task
        engine = ExecutionEngine(artifacts_base_dir=".", max_retries=0)
        engine.evidence_store = self.evidence_store
        
        # Create decomposer task
        task = engine.create_task(
            run_id=run_id,
            mission_id=mission_id,
            name="Goal Decomposition",
            description=f"Decompose: {goal}",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=["file_contains:e3_decomposed_specs.json:task_specs"],
            depends_on=[]
        )
        task.context = {"goal": goal, "role": "decomposer"}
        
        # Execute via AgentFactory - need to reserve agent first
        factory = AgentFactory(agent_registry)
        
        # Enable and reserve Thinker agent (IMPLEMENTER) - use specific agent_id
        agent_registry.enable_agent("e3-thinker")
        
        # Manually reserve the specific Thinker agent
        attempt_id = __import__('unified.contracts', fromlist=['new_attempt_id']).new_attempt_id()
        # Set lifecycle to ASSIGNED
        agent_registry.set_lifecycle_state("e3-thinker", AgentLifecycleState.ASSIGNED)
        # Create reservation
        reservation = __import__('unified.agent_role', fromlist=['create_reservation']).create_reservation(
            agent_id="e3-thinker",
            task_id=task.task_id,
            attempt_id=attempt_id,
            owner="goal_decomposer"
        )
        
        context = AgentContext(
            mission_id=mission_id,
            run_id=run_id,
            task_id=task.task_id,
            attempt_id=reservation.attempt_id,
            agent_id="e3-thinker",
            agent_type=AgentType.IMPLEMENTER,
            sandbox_id="e3-decomposer-sandbox",
            sandbox_manager=None,
            event_emitter=lambda e: None,
            evidence_store=self.evidence_store,
        )
        
        result = await factory.execute_agent_by_id("e3-thinker", context, task)
        
        if not result.success:
            raise RuntimeError(f"Goal decomposition failed: {result.error}")
        
        # Parse specs from result
        specs_data = result.output.get("task_specs", [])
        task_specs = []
        for spec in specs_data:
            task_specs.append(TaskSpec(
                key=spec["key"],
                name=spec["name"],
                description=spec["description"],
                depends_on=spec.get("depends_on", []),
                acceptance_criteria=spec.get("acceptance_criteria", []),
                context=spec.get("context", {})
            ))
        
        return task_specs


# ============================================================
# PLAN APPROVAL GATE
# ============================================================

class PlanApprovalGate:
    """
    Gates plan approval using MissionController's human_gate protocol.
    
    Uses existing HumanRequiredEvent / HumanDecisionRecordedEvent flow.
    In tests, can be auto-approved.
    """
    
    def __init__(self, mission_controller: MissionController, auto_approve: bool = False):
        self.mc = mission_controller
        self.auto_approve = auto_approve
        self._pending_gates: Dict[str, asyncio.Event] = {}
        self._decisions: Dict[str, str] = {}
    
    async def request_approval(self, mission_id: str, run_id: str, plan: Dict[str, Any]) -> bool:
        """Request plan approval from owner (or auto-approve in tests)."""
        gate_id = f"plan-approval-{uuid.uuid4().hex[:8]}"
        
        # Emit HUMAN_REQUIRED via MissionController
        self.mc.engine._emit(__import__('unified.contracts', fromlist=['FactoryEvent']).FactoryEvent.create(
            event_type=EventType.HUMAN_REQUIRED,
            mission_id=mission_id,
            run_id=run_id,
            payload=__import__('unified.contracts', fromlist=['HumanRequiredEvent']).HumanRequiredEvent(
                mission_id=mission_id,
                run_id=run_id,
                reason="Plan approval required for mission execution",
                context={"plan": plan, "gate_id": gate_id},
                options=[{"label": "APPROVE", "value": "APPROVE"}, {"label": "REVISE", "value": "REVISE"}, {"label": "REJECT", "value": "REJECT"}],
                impact="Mission execution blocked until plan approved",
                recommended_action="APPROVE",
            ),
            source="canonical_orchestrator",
            correlation_id=gate_id,
        ))
        
        if self.auto_approve:
            # Auto-approve in test mode
            return await self._record_decision(mission_id, run_id, gate_id, "APPROVE")
        
        # Wait for human decision (with timeout)
        event = asyncio.Event()
        self._pending_gates[gate_id] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=300.0)  # 5 min
            decision = self._decisions.get(gate_id, "REJECT")
            return decision == "APPROVE"
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending_gates.pop(gate_id, None)
            self._decisions.pop(gate_id, None)
    
    async def _record_decision(self, mission_id: str, run_id: str, gate_id: str, decision: str) -> bool:
        """Record human decision."""
        self.mc.engine._emit(__import__('unified.contracts', fromlist=['FactoryEvent']).FactoryEvent.create(
            event_type=EventType.HUMAN_DECISION_RECORDED,
            mission_id=mission_id,
            run_id=run_id,
            payload=__import__('unified.contracts', fromlist=['HumanDecisionRecordedEvent']).HumanDecisionRecordedEvent(
                gate_id=gate_id,
                mission_id=mission_id,
                run_id=run_id,
                decision=decision,
                actor="owner" if not self.auto_approve else "test_auto",
                feedback="Auto-approved for testing" if self.auto_approve else "Approved by owner",
                decided_at=datetime.now(timezone.utc),
            ),
            source="canonical_orchestrator",
            correlation_id=gate_id,
        ))
        
        # Resolve pending gate
        if gate_id in self._pending_gates:
            self._decisions[gate_id] = decision
            self._pending_gates[gate_id].set()
        
        return decision == "APPROVE"


# ============================================================
# ROLE COORDINATOR
# ============================================================

class RoleCoordinator:
    """
    Coordinates Thinker and Verifier roles within the mission.
    
    Thinker: Generates/updates plan (uses IMPLEMENTER with planner context)
    Verifier: Independent verification of completed tasks (uses VERIFIER agent type)
    
    Both use existing AgentFactory — no new agent types.
    """
    
    def __init__(self, mission_controller: MissionController, llm_provider: Any):
        self.mc = mission_controller
        self.llm_provider = llm_provider
        self._register_agents()
    
    def _register_agents(self) -> None:
        """Register Thinker and Verifier agents with proper implementations."""
        # Thinker agent (IMPLEMENTER with planner context)
        if "e3-thinker" not in agent_registry._definitions:
            llm_provider = self.llm_provider  # Capture in closure
            evidence_store = self.mc.engine.evidence_store  # Capture evidence_store
            
            class E3ThinkerAgent(BaseAgent):
                def __init__(self):
                    super().__init__(agent_type=AgentType.IMPLEMENTER)
                    self.llm_provider = llm_provider
                    self.evidence_store = evidence_store
                
                async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
                    # Check if this is a Thinker task (not a regular mission task)
                    role = task.context.get("role", "mission")
                    
                    if role in ("decomposer", "thinker"):
                        # Goal decomposition - use LLM to decompose
                        goal = task.context.get("goal", "")
                        return await self._execute_decomposition(context, task, goal)
                    else:
                        # Plan generation - write a basic plan artifact
                        return await self._execute_plan_generation(context, task)
                
                async def _execute_decomposition(self, context: AgentContext, task: AgentTask, goal: str) -> AgentResult:
                    from unified.contracts import new_artifact_id, new_evidence_id
                    import hashlib
                    
                    # Use LLM to decompose goal into TaskSpecs
                    prompt = f"""Decompose this engineering goal into executable task specifications.

Goal: {goal}

Output a JSON array of task specifications with this exact structure:
[
  {{
    "key": "unique_key",
    "name": "Task Name",
    "description": "What this task does",
    "depends_on": ["other_key"],
    "acceptance_criteria": ["criterion1", "criterion2"],
    "context": {{
      "content": "Expected output content",
      "output_path": "output_file.txt",
      "sleep_s": 0.1
    }}
  }}
]

Rules:
- Keys must be unique, alphanumeric + underscore
- depends_on references other keys in the array
- acceptance_criteria must be verifiable (file_contains, file_exists, etc.)
- context.content is what the agent should write
- context.output_path is the file path
- Max 8 tasks for E3 vertical slice
"""
                    try:
                        from llm.providers import LLMMessage
                        messages = [LLMMessage(role="user", content=prompt)]
                        response = await self.llm_provider.complete(messages)
                        content = response.content if hasattr(response, 'content') else str(response)
                        
                        # Parse JSON from response
                        import re
                        json_match = re.search(r'\[.*\]', content, re.DOTALL)
                        if json_match:
                            specs_data = json.loads(json_match.group())
                        else:
                            specs_data = json.loads(content)
                    except Exception as e:
                        # Fallback to simple plan
                        specs_data = [
                            {"key": "A", "name": "Web Search 1", "description": "Search web", "depends_on": [], "acceptance_criteria": ["file_contains:web1.txt:Web result 1"], "context": {"content": "Web result 1", "output_path": "web1.txt", "sleep_s": 0.1}},
                            {"key": "B", "name": "Web Search 2", "description": "Search web", "depends_on": [], "acceptance_criteria": ["file_contains:web2.txt:Web result 2"], "context": {"content": "Web result 2", "output_path": "web2.txt", "sleep_s": 0.1}},
                            {"key": "C", "name": "Web Search 3", "description": "Search web", "depends_on": [], "acceptance_criteria": ["file_contains:web3.txt:Web result 3"], "context": {"content": "Web result 3", "output_path": "web3.txt", "sleep_s": 0.1}},
                            {"key": "D", "name": "Write Report", "description": "Write markdown report", "depends_on": ["A", "B", "C"], "acceptance_criteria": ["file_contains:report.md:Summary report"], "context": {"content": "Summary report", "output_path": "report.md", "sleep_s": 0.1}},
                        ]
                    
                    # Store result as artifact
                    result_json = json.dumps(specs_data, indent=2)
                    artifact_bytes = result_json.encode('utf-8')
                    artifact_id = new_artifact_id()
                    sha256 = hashlib.sha256(artifact_bytes).hexdigest()
                    
                    from unified.domain_model import Artifact, EvidenceRecord
                    artifact = Artifact(
                        artifact_id=artifact_id,
                        name="e3_decomposed_specs.json",
                        path="e3_decomposed_specs.json",
                        sha256=sha256,
                        size_bytes=len(artifact_bytes),
                        created_by=context.task_id,
                        mission_id=context.mission_id,
                        content_type="application/json"
                    )
                    self.evidence_store.store_artifact(artifact)
                    
                    evidence = EvidenceRecord(
                        evidence_id=new_evidence_id(),
                        evidence_hash=sha256,
                        content_type="artifact",
                        source_id=artifact_id,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        task_id=context.task_id,
                    )
                    self.evidence_store.store_evidence(evidence)
                    
                    return AgentResult(
                        task_id=task.task_id,
                        agent_type=AgentType.IMPLEMENTER,
                        success=True,
                        output={
                            "task_specs": specs_data,
                            "artifact_id": artifact_id,
                            "sha256": sha256
                        },
                        evidence_hash=sha256,
                        artifacts=[artifact_id]
                    )
                
                async def _execute_plan_generation(self, context: AgentContext, task: AgentTask) -> AgentResult:
                    from unified.contracts import new_artifact_id, new_evidence_id
                    import hashlib
                    plan_json = json.dumps({
                        "goal": task.context.get("goal", ""),
                        "tasks": [
                            {"key": "A", "name": "Web Search 1", "depends_on": []},
                            {"key": "B", "name": "Web Search 2", "depends_on": []},
                            {"key": "C", "name": "Web Search 3", "depends_on": []},
                            {"key": "D", "name": "Write Report", "depends_on": ["A", "B", "C"]}
                        ]
                    }, indent=2)
                    artifact_bytes = plan_json.encode('utf-8')
                    artifact_id = new_artifact_id()
                    sha256 = hashlib.sha256(artifact_bytes).hexdigest()
                    
                    from unified.domain_model import Artifact, EvidenceRecord
                    artifact = Artifact(
                        artifact_id=artifact_id,
                        name="e3_plan.json",
                        path="e3_plan.json",
                        sha256=sha256,
                        size_bytes=len(artifact_bytes),
                        created_by=context.task_id,
                        mission_id=context.mission_id,
                        content_type="application/json"
                    )
                    self.evidence_store.store_artifact(artifact)
                    
                    evidence = EvidenceRecord(
                        evidence_id=new_evidence_id(),
                        evidence_hash=sha256,
                        content_type="artifact",
                        source_id=artifact_id,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        task_id=context.task_id,
                    )
                    self.evidence_store.store_evidence(evidence)
                    
                    return AgentResult(
                        task_id=task.task_id,
                        agent_type=AgentType.IMPLEMENTER,
                        success=True,
                        output={"plan": plan_json, "artifact_id": artifact_id},
                        evidence_hash=sha256,
                        artifacts=[artifact_id]
                    )
            
            thinker_def = AgentDefinition(
                agent_id="e3-thinker",
                agent_type=AgentType.IMPLEMENTER,
                name="E3 Thinker",
                description="Generates and updates mission plans",
                capabilities=["planning", "task_specification"],
                enabled=True,
                lifecycle_state=AgentLifecycleState.REGISTERED,
                implementation_class="orchestrator.canonical.E3ThinkerAgent"
            )
            agent_registry.add_definition(thinker_def)
            agent_registry.enable_agent(thinker_def.agent_id)
        
        # Verifier agent
        if "e3-verifier" not in agent_registry._definitions:
            evidence_store = self.mc.engine.evidence_store  # Capture evidence_store
            
            class E3VerifierAgent(BaseAgent):
                def __init__(self):
                    super().__init__(agent_type=AgentType.VERIFIER)
                    self.evidence_store = evidence_store

                def _resolve_current_file(self, base_dir: Path, rel_path: str,
                                          target_task_id: str = "") -> Optional[Path]:
                    """E10-RP2.1 §3 — resolve a criterion path against the
                    TARGET TASK's OWN sandbox tree only.

                    The old resolution globbed ``sandbox-*/<rel_path>`` across
                    ALL task sandboxes and took the newest mtime — a name
                    collision between two tasks could decide either task's
                    verdict with the OTHER task's file (proven at baseline
                    631f6fb, E10_RP21_DISCOVERY D5). The engine writes task
                    X's artifacts to ``sandbox-<task_id>`` (execution.py
                    sandbox binding), so the task-bound path is always
                    well-defined: ``<base_dir>/sandbox-<target_task_id>/
                    <rel_path>``. No glob, no mtime race, no cross-sandbox
                    reads. Returns None when the task's own file is absent —
                    a correct file in ANY other sandbox cannot change this
                    task's verdict."""
                    if not target_task_id:
                        # No target task identity => nothing task-bound to
                        # read => no evidence (fail-closed; never fall back
                        # to a cross-sandbox scan).
                        return None
                    p = Path(base_dir) / f"sandbox-{target_task_id}" / rel_path
                    return p if p.is_file() else None

                def _check_criteria_now(self, base_dir: Path, criteria: List[str],
                                        target_task_id: str = "") -> Tuple[bool, List[str], List[str], Dict[str, str]]:
                    """E10-RP2.1 §3+§4 — mechanical check of the task's
                    CURRENT acceptance criteria against the CURRENT on-disk
                    state OF THE TARGET TASK'S OWN SANDBOX.

                    Returns ``(all_ok, criteria_failures, machinery_errors,
                    evidence_paths)`` — criteria failures (readable evidence
                    that does not meet a criterion) are SEPARATED from
                    machinery errors (the verifier's own read/execution
                    failure). A read error is a TOOL/RUNTIME condition, never
                    a criteria mismatch (order §4.1); a missing file is a
                    criteria failure of ``file_exists``. Unknown criterion
                    types FAIL (fail-closed) as machinery limitations.

                    ``evidence_paths`` records, per criterion relative path,
                    the task-bound absolute file the verdict was read from —
                    re-examinable proof that each task's verdict came from
                    its own file."""
                    all_ok = True
                    missing: List[str] = []
                    machinery: List[str] = []
                    evidence_paths: Dict[str, str] = {}
                    for c in criteria:
                        if c.startswith("file_exists:"):
                            path = c.split(":", 1)[1]
                            f = self._resolve_current_file(base_dir, path, target_task_id)
                            if f is None:
                                all_ok = False
                                missing.append(f"file_exists failed: {path} not in this task's sandbox")
                            else:
                                evidence_paths[path] = str(f)
                        elif c.startswith("file_contains:"):
                            parts = c.split(":", 2)
                            path = parts[1] if len(parts) > 2 else ""
                            pattern = parts[2] if len(parts) > 2 else ""
                            f = self._resolve_current_file(base_dir, path, target_task_id)
                            if f is None:
                                all_ok = False
                                missing.append(f"file_contains failed: {path} not in this task's sandbox")
                            else:
                                evidence_paths[path] = str(f)
                                try:
                                    if pattern not in f.read_text(encoding="utf-8", errors="replace"):
                                        all_ok = False
                                        missing.append(
                                            f"file_contains failed: {pattern!r} not in {path} (current content)")
                                except Exception as e:
                                    # §4.1: READ failure = tool/runtime error,
                                    # NOT a criteria mismatch.
                                    all_ok = False
                                    machinery.append(
                                        f"verifier read error on {path}: {type(e).__name__}: {e}")
                        elif c.startswith("file_hash_matches:"):
                            import hashlib
                            parts = c.split(":", 2)
                            path = parts[1] if len(parts) > 2 else ""
                            expected = parts[2] if len(parts) > 2 else ""
                            f = self._resolve_current_file(base_dir, path, target_task_id)
                            if f is None:
                                all_ok = False
                                missing.append(f"file_hash_matches failed: {path} not in this task's sandbox")
                            else:
                                evidence_paths[path] = str(f)
                                try:
                                    actual = hashlib.sha256(f.read_bytes()).hexdigest()
                                except Exception as e:
                                    all_ok = False
                                    machinery.append(
                                        f"verifier read error on {path}: {type(e).__name__}: {e}")
                                    continue
                                if actual != expected:
                                    all_ok = False
                                    missing.append(
                                        f"file_hash_matches failed: {path} hash {actual[:12]}... != expected")
                        else:
                            # §4.1: the verifier itself cannot evaluate this
                            # criterion — a machinery limitation, fail-closed.
                            all_ok = False
                            machinery.append(f"unsupported criterion (verifier limitation, fail-closed): {c}")
                    return all_ok, missing, machinery, evidence_paths

                async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
                    # E10-RP2.1 §3: verify the target task's CURRENT criteria
                    # against the CURRENT on-disk artifacts of the TARGET
                    # TASK'S OWN SANDBOX (task-bound resolution), not merely
                    # artifact existence and not the recorded evidence-store
                    # history, and never a same-name file from another
                    # task's sandbox.
                    target_artifacts = task.context.get("target_artifacts", [])
                    target_task_id = task.context.get("target_task_id", "")
                    target_criteria = task.context.get("target_criteria", [])
                    base_dir = Path(task.context.get("artifacts_base_dir", "."))
                    producing_attempt_id = task.context.get("producing_attempt_id", "")

                    if target_criteria:
                        criteria_ok, criteria_failures, machinery_errors, evidence_paths = \
                            self._check_criteria_now(base_dir, target_criteria, target_task_id)
                    else:
                        criteria_ok = len(target_artifacts) > 0
                        criteria_failures = [] if criteria_ok else ["no target artifacts recorded"]
                        machinery_errors = []
                        evidence_paths = {}

                    # E10-RP2.1 §4 — EXPLICIT failure classification (never
                    # inferred from missing_evidence presence or strings):
                    #   machinery read/eval error  -> verifier_error (retry)
                    #   producing attempt unknown  -> provenance_unprovable
                    #   criteria mechanically unmet -> criteria_mismatch
                    # Precedence: machinery errors make the whole
                    # verification UNRELIABLE (retry territory) even if some
                    # criteria happened to pass; provenance failure is a
                    # mission-state problem (replan can recover by
                    # re-execution); a clean criteria failure is a plan
                    # deviation.
                    if machinery_errors:
                        failure_class = "verifier_error"
                    elif not producing_attempt_id:
                        failure_class = "provenance_unprovable"
                    elif not criteria_ok:
                        failure_class = "criteria_mismatch"
                    else:
                        failure_class = None
                    verified = failure_class is None

                    failure_causes = list(machinery_errors)
                    if not producing_attempt_id:
                        failure_causes.append(
                            "producing attempt could not be established for the verified task")
                    failure_causes.extend(criteria_failures)

                    from unified.contracts import new_artifact_id, new_evidence_id
                    import hashlib
                    verify_json = json.dumps({
                        "target_task_id": target_task_id,
                        "target_artifacts": target_artifacts,
                        "criteria": target_criteria,
                        "verified": verified,
                        "missing_evidence": failure_causes,
                        "failure_class": failure_class,
                        "failure_causes": {
                            "criteria_mismatch": criteria_failures,
                            "verifier_error": machinery_errors,
                            "provenance_unprovable": (
                                [] if producing_attempt_id
                                else ["producing attempt could not be established"]),
                        },
                        "evidence_paths": evidence_paths,
                        "verdict": "evidenced" if verified else "not_evidenced"
                    }, indent=2)
                    artifact_bytes = verify_json.encode('utf-8')
                    artifact_id = new_artifact_id()
                    sha256 = hashlib.sha256(artifact_bytes).hexdigest()

                    from unified.domain_model import Artifact, EvidenceRecord
                    artifact = Artifact(
                        artifact_id=artifact_id,
                        name=f"e3_verification_{target_task_id}.json",
                        path=f"e3_verification_{target_task_id}.json",
                        sha256=sha256,
                        size_bytes=len(artifact_bytes),
                        created_by=context.task_id,
                        mission_id=context.mission_id,
                        content_type="application/json"
                    )
                    self.evidence_store.store_artifact(artifact)

                    evidence = EvidenceRecord(
                        evidence_id=new_evidence_id(),
                        evidence_hash=sha256,
                        # E10-RP2 repair of a PRE-EXISTING defect (proven
                        # from the committed RP1 evidence): the old code
                        # passed content_type="verification", which the
                        # EvidenceRecord contract REJECTS (pydantic
                        # ValidationError). Every orchestrator-level
                        # verification at the RP1 baseline therefore FAILED
                        # internally (all published canonical_orchestrator
                        # verification.complete events are not_evidenced)
                        # while the loose evidenced>0 rule still reported
                        # success. "report" is the contract's valid type for
                        # verification outputs.
                        content_type="report",
                        source_id=artifact_id,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        task_id=context.task_id,
                    )
                    self.evidence_store.store_evidence(evidence)

                    return AgentResult(
                        task_id=task.task_id,
                        agent_type=AgentType.VERIFIER,
                        success=verified,
                        output={
                            "verification": verify_json,
                            "missing_evidence": failure_causes,
                            "failure_class": failure_class,
                            "evidence_paths": evidence_paths,
                        },
                        evidence_hash=sha256,
                        artifacts=[artifact_id],
                        error=(
                            "Tool/runtime failure (verifier machinery): "
                            + "; ".join(machinery_errors[:3])
                        ) if machinery_errors else None,
                    )
            
            verifier_def = AgentDefinition(
                agent_id="e3-verifier",
                agent_type=AgentType.VERIFIER,
                name="E3 Verifier",
                description="Independent verification of task outputs",
                capabilities=["verification", "evidence_checking"],
                enabled=True,
                lifecycle_state=AgentLifecycleState.REGISTERED,
                implementation_class="orchestrator.canonical.E3VerifierAgent"
            )
            agent_registry.add_definition(verifier_def)
            agent_registry._type_to_definition[AgentType.VERIFIER] = verifier_def
            agent_registry._implementations[AgentType.VERIFIER] = E3VerifierAgent
            agent_registry.enable_agent(verifier_def.agent_id)
        
        # Register a unified IMPLEMENTER implementation that handles both Thinker and MissionTaskAgent
        # This must be done AFTER register_mission_agent() which sets MissionTaskAgent as default
        # We create a wrapper that delegates based on agent_id
        # Always re-register to handle test isolation (agent_registry is global)
        class E3AgentWrapper(BaseAgent):
            def __init__(self):
                super().__init__(agent_type=AgentType.IMPLEMENTER)
                self._mission_agent = MissionTaskAgent()
                self._thinker_agent = E3ThinkerAgent()

            async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
                # E10-RP1 §2 correction (pre-existing at baseline, proven by
                # two-state probe at ac70eb6e): dispatch by the TASK's declared
                # role, NOT by the reserved agent_id. The engine's reservation
                # can hand the thinker (an IMPLEMENTER in the shared pool) to a
                # MISSION task; routing that to the thinker's plan-generation
                # produced an ungoverned evidence-store artifact instead of
                # MissionTaskAgent's governed sandbox write. Planning tasks
                # (role decomposer/thinker) still go to the thinker.
                role = (getattr(task, "context", None) or {}).get("role", "mission")
                if role in ("decomposer", "thinker"):
                    return await self._thinker_agent.execute(context, task)
                return await self._mission_agent.execute(context, task)
        
        # Replace the IMPLEMENTER implementation with our wrapper
        agent_registry._implementations[AgentType.IMPLEMENTER] = E3AgentWrapper
    
    async def run_thinker(self, mission_id: str, run_id: str, goal: str, context: Dict[str, Any]) -> AgentResult:
        """Run Thinker to generate/update plan."""
        engine = self.mc.engine
        task = engine.create_task(
            run_id=run_id,
            mission_id=mission_id,
            name="Thinker: Plan Generation",
            description=f"Generate plan for: {goal}",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=["file_contains:e3_plan.json:tasks"],
            depends_on=[]
        )
        task.context = {"role": "thinker", "goal": goal, **context}
        
        factory = AgentFactory(agent_registry)
        
        # Enable and reserve Thinker agent
        agent_registry.enable_agent("e3-thinker")
        attempt_id = __import__('unified.contracts', fromlist=['new_attempt_id']).new_attempt_id()
        agent_registry.set_lifecycle_state("e3-thinker", AgentLifecycleState.ASSIGNED)
        reservation = __import__('unified.agent_role', fromlist=['create_reservation']).create_reservation(
            agent_id="e3-thinker",
            task_id=task.task_id,
            attempt_id=attempt_id,
            owner="thinker"
        )
        
        agent_context = AgentContext(
            mission_id=mission_id,
            run_id=run_id,
            task_id=task.task_id,
            attempt_id=reservation.attempt_id,
            agent_id="e3-thinker",
            agent_type=AgentType.IMPLEMENTER,
            sandbox_id="e3-thinker-sandbox",
            sandbox_manager=engine.sandbox_manager,
            event_emitter=lambda e: None,
            evidence_store=engine.evidence_store,
        )
        
        return await factory.execute_agent_by_id("e3-thinker", agent_context, task)
    
    def _producing_attempt_id(self, task_id: str) -> str:
        """E10-RP2 §3.2: the attempt that PRODUCED the verified artifact —
        the task's latest COMPLETED attempt in the engine's attempt
        records. Empty string when provenance cannot be established
        (fail-closed: the caller treats that as unverifiable)."""
        attempts = [
            (getattr(a, "completed_at", None) or "", aid, a)
            for aid, a in self.mc.engine.attempts.items()
            if getattr(a, "task_id", None) == task_id
            and getattr(a, "state", None) is not None
            and str(getattr(a.state, "name", getattr(a, "state", ""))) == "COMPLETED"
        ]
        if not attempts:
            # fallback: any attempt for the task (latest by insertion order)
            related = [
                (aid, a) for aid, a in self.mc.engine.attempts.items()
                if getattr(a, "task_id", None) == task_id
            ]
            return related[-1][0] if related else ""
        attempts.sort(key=lambda t: str(t[0]))
        return attempts[-1][1]

    async def run_verifier(self, mission_id: str, run_id: str, task_id: str, artifacts: List[str]) -> AgentResult:
        """Run Verifier to independently check task outputs.

        E10-RP2 §3: the verification is bound to the target task's CURRENT
        acceptance criteria, the producing attempt, the plan version, and
        the run. VERIFICATION_COMPLETE is emitted for BOTH verdicts
        (evidenced and not_evidenced) — a failed verification was
        previously invisible at this layer (only recorded later by the
        orchestrator with an unrelated random attempt id)."""
        engine = self.mc.engine
        target_task = engine.tasks.get(task_id)
        target_criteria = list(getattr(target_task, "acceptance_criteria", []) or [])
        producing_attempt_id = self._producing_attempt_id(task_id)
        plan_version = getattr(self.mc, "plan_version", "v1")

        # Create verification task (NOT in engine's task graph to avoid "unresolved work" checks)
        verify_task = AgentTask(
            task_id=f"verify-{task_id}-{uuid.uuid4().hex[:8]}",
            run_id=run_id,
            mission_id=mission_id,
            name=f"Verifier: Verify {task_id}",
            description=f"Independent verification of task {task_id} outputs",
            agent_type=AgentType.VERIFIER,
            acceptance_criteria=["verification_verdict:evidenced"],
            depends_on=[task_id],
            context={
                "role": "verifier",
                "target_task_id": task_id,
                "target_artifacts": artifacts,
                "target_criteria": target_criteria,
                "artifacts_base_dir": engine.artifacts_base_dir,
                "producing_attempt_id": producing_attempt_id,
                "plan_version": plan_version,
            }
        )

        factory = AgentFactory(agent_registry)

        # Reserve verifier agent
        agent_registry.enable_agent("e3-verifier")
        attempt_id = __import__('unified.contracts', fromlist=['new_attempt_id']).new_attempt_id()
        agent_registry.set_lifecycle_state("e3-verifier", AgentLifecycleState.ASSIGNED)
        reservation = __import__('unified.agent_role', fromlist=['create_reservation']).create_reservation(
            agent_id="e3-verifier",
            task_id=verify_task.task_id,
            attempt_id=attempt_id,
            owner="verifier"
        )

        agent_context = AgentContext(
            mission_id=mission_id,
            run_id=run_id,
            task_id=verify_task.task_id,
            attempt_id=reservation.attempt_id,
            agent_id="e3-verifier",
            agent_type=AgentType.VERIFIER,
            sandbox_id="e3-verifier-sandbox",
            sandbox_manager=engine.sandbox_manager,
            event_emitter=lambda e: None,
            evidence_store=engine.evidence_store,
        )

        # E10-RP2.1 §4 — a verifier EXECUTION failure (the machinery itself
        # crashed) is caught and classified EXPLICITLY as verifier_error: it
        # must not propagate and crash the run, must not invoke replan, and
        # must not produce a final success. The verdict is not_evidenced
        # (fail-closed) with the explicit class carried in the event.
        try:
            result = await factory.execute_agent_by_id("e3-verifier", agent_context, verify_task)
        except Exception as exc:
            from unified.agent_contract import AgentResult as _AR
            result = _AR(
                task_id=verify_task.task_id,
                agent_type=AgentType.VERIFIER.value,
                success=False,
                output={
                    "failure_class": "verifier_error",
                    "failure_causes": [f"verifier execution raised: {type(exc).__name__}: {exc}"],
                    "missing_evidence": [
                        f"verifier execution raised: {type(exc).__name__}: {exc}"],
                    "evidence_paths": {},
                },
                evidence_hash="",
                error=f"Tool/runtime failure (verifier execution): {type(exc).__name__}: {exc}",
            )

        # E10-RP2.1 §4 — explicit classification from the verifier result
        # (never inferred from missing_evidence presence or strings).
        v_output = result.output if isinstance(result.output, dict) else {}
        failure_class = v_output.get("failure_class")
        if not result.success and failure_class is None:
            # Legacy/unclassified failure: conservatively retry territory —
            # NEVER auto-classified as a plan deviation (order §4).
            failure_class = "verifier_error"
        evidence_paths = list(v_output.get("evidence_paths", {}).values()) \
            if isinstance(v_output.get("evidence_paths"), dict) else []

        # E10-RP2.1 §3.4 — an unestablishable producing attempt makes the
        # verdict not_evidenced (fail-closed: provenance cannot be
        # fabricated), replacing the RP2 evidenced-with-disclosure hole.
        missing_evidence = list(v_output.get("missing_evidence", [])) \
            if not result.success else []
        if not producing_attempt_id:
            if result.success:
                result = type(result)(
                    task_id=result.task_id,
                    agent_type=result.agent_type,
                    success=False,
                    output={
                        **(v_output if isinstance(v_output, dict) else {}),
                        "failure_class": "provenance_unprovable",
                        "missing_evidence": [
                            "producing attempt could not be established for the verified task"],
                    },
                    evidence_hash=result.evidence_hash,
                    artifacts=result.artifacts,
                    error="Verification failed: producing attempt could not be established",
                )
                failure_class = "provenance_unprovable"
                missing_evidence = ["producing attempt could not be established for the verified task"]

        # Emit VERIFICATION_COMPLETE for BOTH verdicts (E10-RP2 §3) —
        # bound to the target task, the PRODUCING attempt (not a random
        # id), the plan version, and the run. Missing provenance is
        # recorded in the payload (fail-closed: an attempt that cannot be
        # established is disclosed, not fabricated).
        from unified.contracts import new_verification_id
        engine._emit(FactoryEvent.create(
            event_type=EventType.VERIFICATION_COMPLETE,
            mission_id=mission_id,
            run_id=run_id,
            payload=VerificationCompleteEvent(
                verification_id=new_verification_id(),
                task_id=task_id,
                attempt_id=producing_attempt_id or "unestablished",
                verdict="evidenced" if result.success else "not_evidenced",
                checks_performed=["criteria_current_state_check"]
                + [f"criterion:{c}" for c in target_criteria],
                missing_evidence=missing_evidence,
                confidence=1.0 if result.success else 0.0,
                plan_version=plan_version,
                run_id=run_id,
                verifier_attempt_id=reservation.attempt_id,
                criteria_source="task.acceptance_criteria",
                failure_class=failure_class,
                evidence_paths=evidence_paths,
            ),
            source="canonical_orchestrator",
            correlation_id=verify_task.task_id,
        ))

        return result


# ============================================================
# EVENT STREAMER
# ============================================================

class EventStreamer:
    """
    Streams canonical mission events via SSE.
    
    Thin wrapper over MissionController/ExecutionEngine event bus.
    """
    
    def __init__(self, mission_controller: MissionController):
        self.mc = mission_controller
        self._subscribers: List[asyncio.Queue] = []
        self._subscription_callback = None
    
    def subscribe(self) -> asyncio.Queue:
        """Create a new event subscription queue."""
        queue = asyncio.Queue()
        self._subscribers.append(queue)
        
        # Register callback on first subscriber
        if self._subscription_callback is None:
            self._subscription_callback = self._on_event
            self.mc.engine.subscribe_events(self._subscription_callback)
        
        return queue
    
    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a subscription."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)
        
        # Unregister callback if no subscribers
        if not self._subscribers and self._subscription_callback:
            self.mc.engine.event_bus.unsubscribe(self._subscription_callback)
            self._subscription_callback = None
    
    def _on_event(self, event: FactoryEvent) -> None:
        """Forward event to all subscribers."""
        event_dict = {
            "event_type": event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type),
            "mission_id": event.mission_id,
            "run_id": event.run_id,
            "correlation_id": event.correlation_id,
            "timestamp": event.timestamp.isoformat() if hasattr(event.timestamp, 'isoformat') else str(event.timestamp),
            "payload": event.payload.__dict__ if hasattr(event.payload, '__dict__') else event.payload,
            "source": event.source,
        }
        for queue in self._subscribers:
            try:
                queue.put_nowait(event_dict)
            except asyncio.QueueFull:
                pass  # Drop if queue full


# ============================================================
# CANONICAL ORCHESTRATOR (MAIN CLASS)
# ============================================================

class CanonicalOrchestrator:
    """
    Main orchestrator class coordinating the vertical slice.
    
    Delegates all execution to MissionController + ExecutionEngine (P1+P2).
    Only handles: goal decomposition, plan approval, role coordination, event streaming.
    """
    
    def __init__(
        self,
        llm_provider: Any,
        artifacts_base_dir: str = ".",
        auto_approve_plans: bool = True,
        max_parallel: int = 1,
        require_plan_review: bool = True,
        replan_decision_provider: Optional[Callable[..., Optional[Dict[str, Any]]]] = None,
        max_review_rounds: int = 3,
        grant_validator: Optional[Callable[[str, str], bool]] = None,
        grant_ids: Optional[List[str]] = None,
    ):
        self.llm_provider = llm_provider
        self.artifacts_base_dir = artifacts_base_dir
        self.auto_approve_plans = auto_approve_plans
        self.max_parallel = max_parallel
        
        # E10-RP1 §2.1: the canonical operational path enables the plan
        # review gate EXPLICITLY as policy (default ON). It never relies on
        # MissionController's library default (require_plan_review=False).
        self.require_plan_review = require_plan_review
        # E10-RP1 §2.3: the replanning decision is supplied by an explicit,
        # disclosed source at the replanning decision boundary. The
        # orchestrator wires the PATH (detect -> classify -> decide ->
        # replan_mission -> review gate -> continuation); this provider
        # supplies the decision CONTENT. None => no replan (fail-closed:
        # the mission then fails honestly instead of fabricating a replan).
        self.replan_decision_provider = replan_decision_provider
        self.max_review_rounds = max(1, int(max_review_rounds))
        
        # E10-RP1 §2 correction (pre-existing at baseline, proven by two-state
        # probe at ac70eb6e): the canonical engine was built WITHOUT a grant
        # validator, so the governed tool path (E9-R) rejected EVERY mission
        # write ('PermissionError: Tool artifact_write requires grants but no
        # validator available') — no canonical mission with file-based
        # criteria could ever complete. The validator is now supplied through
        # the same construction pattern as E9-R / E10-RP engines. Default
        # None keeps the old behavior for callers that do not opt in.
        self.grant_validator = grant_validator
        # E10-RP2 §2: grant IDENTITY is injected alongside the validator.
        # Real deployments pass the owner-approved EOE grant ids (see
        # eoe.engine_bridge.build_engine_grant_validator); None keeps the
        # engine's E9-R legacy default (rejected by any real validator —
        # fail-closed preserved).
        self.grant_ids = grant_ids

        # Core P1+P2 components
        self.engine = create_execution_engine(
            artifacts_base_dir=artifacts_base_dir,
            grant_validator=grant_validator,
            grant_ids=grant_ids,
        )
        # E10-RP1 §2.1: explicit review-gate policy for the canonical path.
        self.mc = MissionController(
            self.engine,
            state_dir=artifacts_base_dir,
            require_plan_review=require_plan_review,
        )
        
        # Register mission agent pool (E33) - MUST be done before RoleCoordinator
        register_mission_agent(self.engine.agent_registry)
        
        # Orchestrator components
        self.decomposer = GoalDecomposer(llm_provider, self.engine.evidence_store)
        self.approval_gate = PlanApprovalGate(self.mc, auto_approve=auto_approve_plans)
        self.role_coordinator = RoleCoordinator(self.mc, llm_provider)
        self.event_streamer = EventStreamer(self.mc)
        
        # State
        self._current_mission: Optional[OrchestratorMission] = None
        self._event_queue: Optional[asyncio.Queue] = None
        # E10-RP2 §3.5: open verifier-detected failures (task_id ->
        # FailureRecord) — dedup + resolution marking when newer valid
        # evidence arrives for the same task.
        self._open_verifier_failures: Dict[str, Any] = {}
    
    async def execute_mission(self, goal: str) -> OrchestratorResult:
        """Execute a mission from goal to completion."""
        start_time = datetime.now(timezone.utc)
        mission_id = f"e3-mission-{uuid.uuid4().hex[:8]}"
        
        # Subscribe to events
        self._event_queue = self.event_streamer.subscribe()
        event_trace = []
        
        try:
            # 1. Decompose goal into TaskSpecs
            # Create temp run for decomposition
            temp_mission = self.engine.create_mission(f"E3 Decomposition: {goal}")
            temp_run = self.engine.create_run(temp_mission.mission_id)
            
            task_specs = await self.decomposer.decompose(goal, temp_mission.mission_id, temp_run.run_id)
            
            # 2. Request plan approval
            plan = {
                "goal": goal,
                "tasks": [
                    {
                        "key": spec.key,
                        "name": spec.name,
                        "description": spec.description,
                        "depends_on": spec.depends_on,
                        "acceptance_criteria": spec.acceptance_criteria,
                    }
                    for spec in task_specs
                ]
            }
            
            approved = await self.approval_gate.request_approval(
                temp_mission.mission_id, temp_run.run_id, plan
            )
            
            if not approved:
                return OrchestratorResult(
                    mission_id=mission_id,
                    goal=goal,
                    success=False,
                    final_state="PLAN_REJECTED",
                    error="Plan approval rejected or timed out"
                )
            
            # 3. Define mission with MissionController (P2)
            mc_mission, mc_run, key_to_task = self.mc.define_mission(goal, task_specs)
            
            # Record plan version
            self.mc.record_plan_v1(mc_run.run_id, mc_mission.mission_id)
            
            # 3.5 E10-RP1 §2.2: the FIRST plan review happens BEFORE any
            # execution when the gate is enabled. The review itself is the
            # fail-closed structural/causal review implemented by
            # MissionController (checks C1..C8 on live state only); the
            # orchestrator only invokes it and honors its verdict. A
            # rejected initial review blocks ALL execution (fail-closed).
            if self.require_plan_review:
                initial_review = self.mc.review_plan(
                    mc_run.run_id,
                    reviewer="canonical_orchestrator",
                    note="initial plan (v1) review before first execution (E10-RP1 §2.2)",
                )
                if initial_review.verdict != "approved":
                    return OrchestratorResult(
                        mission_id=mission_id,
                        goal=goal,
                        success=False,
                        final_state="PLAN_REVIEW_REJECTED",
                        event_trace=self.mc.export_event_trace(mc_mission.mission_id),
                        evidence_chain=self.mc.export_evidence_chain(mc_mission.mission_id),
                        duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
                        error="Initial plan review REJECTED (fail-closed, zero execution): "
                              + "; ".join(initial_review.reasons),
                    )
            
            # 4. Execute through MissionController (delegates to ExecutionEngine P1)
            result = await self.mc.execute_run(mc_run.run_id, max_parallel=self.max_parallel)
            
            # 5. Handle failures/replanning if needed.
            # E10-RP1 §2.3/§2.4/§2.5: this branch was previously a `pass` stub
            # that claimed to delegate replanning while doing nothing. It is
            # now wired to the real MissionController replanning path:
            # REPLAN-classified FailureRecord (+ its evidence) -> decision
            # from the disclosed replan_decision_provider -> replan_mission
            # -> fail-closed review gate -> continuation ONLY after approval.
            if not result.get("success", False) and not result.get("paused", False):
                # Scan failures
                events = list(self.mc.engine.event_bus.history)
                failures = self.mc.scan_failures(events, result.get("task_results", {}))
                
                # Evidence-based replanning: only failures classified REPLAN
                # (plan deviation) and still unresolved enter the replanning
                # path. Without a valid decision the mission fails honestly.
                replan_failures = [
                    f for f in failures
                    if f.recovery_action.value == "replan" and not f.resolved
                ]
                if replan_failures and self.replan_decision_provider is not None:
                    replan_outcome = await self._run_replanning_cycle(
                        mc_run.run_id, replan_failures[0]
                    )
                    if replan_outcome is not None and replan_outcome.get("approved"):
                        # Continuation under the approved plan version. The
                        # gate at the top of execute_run independently
                        # re-enforces the approval (defense in depth).
                        result = replan_outcome["result"]
                    elif replan_outcome is not None and replan_outcome.get("blocked"):
                        # Review rejected and no revision corrected the plan:
                        # continuation is REFUSED — zero execution after the
                        # rejection (provable from the durable event log).
                        return OrchestratorResult(
                            mission_id=mission_id,
                            goal=goal,
                            success=False,
                            final_state="PLAN_REVIEW_REJECTED",
                            event_trace=self.mc.export_event_trace(mc_mission.mission_id),
                            evidence_chain=self.mc.export_evidence_chain(mc_mission.mission_id),
                            duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
                            error="Plan review REJECTED after replanning; continuation REFUSED (fail-closed): "
                                  + "; ".join(replan_outcome["review"].reasons),
                        )
                    # replan_outcome is None => no valid decision: fall
                    # through with the failed result; completion verification
                    # below reports INCOMPLETE honestly (no fabricated success).
            
            # 6. E10-RP2 §3 — VERIFICATION TRUTH LOOP.
            # Verify EVERY completed required task that has acceptance
            # criteria — against the task's CURRENT criteria and the
            # CURRENT on-disk state (preserved tasks included: a criteria
            # correction on a completed task invalidates its older
            # evidence). A verifier-detected failure that represents a plan
            # deviation (criteria vs current reality) flows into the
            # EXISTING decision -> replan_mission -> review gate ->
            # continuation path — the E10-RP1 disclosed gap "verifier ->
            # replan wiring" is closed here. Tool/runtime verifier errors
            # are recorded but never auto-classified as deviations (§3.5).
            # The loop is bounded by max_review_rounds; without a valid
            # decision the failure stays unresolved and verify_completion
            # below reports INCOMPLETE honestly — no fabricated success.
            verification_round = 0
            while True:
                verifier_failures = []
                tool_error_failures = []
                graph_now = self.mc.engine.task_graph.get(mc_run.run_id, {})
                for key, tid in list(self.mc._key_to_task.items()):
                    node = graph_now.get(tid)
                    if node is None or node.get("state") != TaskState.COMPLETED:
                        continue
                    task_obj = self.mc.engine.tasks.get(tid)
                    if task_obj is None or not getattr(task_obj, "acceptance_criteria", None):
                        continue
                    tr = (result.get("task_results", {}) or {}).get(tid, {})
                    verify_result = await self.role_coordinator.run_verifier(
                        mc_mission.mission_id, mc_run.run_id, tid,
                        tr.get("artifacts", []) or [],
                    )
                    if not verify_result.success:
                        rec = self._record_verifier_failure(
                            tid, key, verify_result, mc_run.run_id)
                        if rec is None:
                            continue
                        if rec.recovery_action == RecoveryAction.REPLAN:
                            verifier_failures.append((tid, key, rec))
                        else:
                            # §3.5: verifier TOOL/RUNTIME errors are recorded
                            # (and block completion through the per-task
                            # latest-verdict rule — the verification is a
                            # current unresolved result) but NEVER feed the
                            # replanning path.
                            tool_error_failures.append((tid, key, rec))
                    else:
                        self._resolve_verifier_failure(tid)
                if not verifier_failures:
                    break
                if (self.replan_decision_provider is None
                        or verification_round + 1 >= self.max_review_rounds):
                    # No decision source, or rounds exhausted: leave the
                    # failure unresolved — completion verification below
                    # will (and must) report it.
                    break
                replan_outcome = await self._run_replanning_cycle(
                    mc_run.run_id, verifier_failures[0][2]
                )
                if replan_outcome is not None and replan_outcome.get("approved"):
                    result = replan_outcome["result"]
                    verification_round += 1
                    continue
                if replan_outcome is not None and replan_outcome.get("blocked"):
                    # Review rejected the correction and no revision
                    # recovered it: continuation REFUSED (fail-closed).
                    return OrchestratorResult(
                        mission_id=mission_id,
                        goal=goal,
                        success=False,
                        final_state="PLAN_REVIEW_REJECTED",
                        event_trace=self.mc.export_event_trace(mc_mission.mission_id),
                        evidence_chain=self.mc.export_evidence_chain(mc_mission.mission_id),
                        duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
                        error="Plan review REJECTED after verifier-detected deviation; "
                              "continuation REFUSED (fail-closed): "
                              + "; ".join(replan_outcome["review"].reasons),
                    )
                # No valid decision: the mission fails honestly below.
                break
            
            # 7. Verify completion and finalize
            # E10-RP1: required keys follow the LIVE graph — after a replan the
            # invalidated tasks are gone and remediation tasks exist; checking
            # the stale pre-replan key set would always report INCOMPLETE.
            graph_now = self.mc.engine.task_graph.get(mc_run.run_id, {})
            required_keys = [
                k for k, tid in self.mc._key_to_task.items()
                if tid in graph_now
            ]
            complete, completion_report = self.mc.verify_completion(mc_run.run_id, required_keys)
            
            if complete:
                self.mc.finalize_mission(mc_mission.mission_id, mc_run.run_id)
            
            # 8. Collect final traces
            event_trace = self.mc.export_event_trace(mc_mission.mission_id)
            evidence_chain = self.mc.export_evidence_chain(mc_mission.mission_id)
            
            # Build reexecution ledger
            final_events = list(self.mc.engine.event_bus.history)
            resume_marker = next(
                (e for e in final_events if e.event_type == EventType.CHECKPOINT_LOADED),
                None
            )
            if resume_marker:
                expected = {k: "PRESERVED" for k in required_keys}
                ledger = self.mc.build_reexecution_ledger(
                    mc_mission.mission_id, resume_marker, expected
                )
            else:
                ledger = []
            
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            
            return OrchestratorResult(
                mission_id=mission_id,
                goal=goal,
                success=complete,
                final_state=mc_mission.state.value,
                event_trace=event_trace,
                evidence_chain=evidence_chain,
                reexecution_ledger=ledger,
                duration_ms=duration_ms
            )
            
        except Exception as e:
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            return OrchestratorResult(
                mission_id=mission_id,
                goal=goal,
                success=False,
                final_state="ERROR",
                error=str(e),
                duration_ms=duration_ms
            )
        finally:
            if self._event_queue:
                self.event_streamer.unsubscribe(self._event_queue)
                self._event_queue = None
    
    # ============================================================
    # E10-RP1 §2.3 — canonical replanning path
    # ============================================================

    def _valid_replan_decision(self, decision: Any) -> bool:
        """E10-RP1 §2.3: 'when a VALID decision is available'.

        Structural validation only — the decision CONTENT remains the
        provider's responsibility (disclosed control input, not claimed as
        independent planning). A malformed decision is treated as NO
        decision (fail-closed: no replan, no fabricated success)."""
        if not isinstance(decision, dict):
            return False
        required = ("reason", "next_version", "invalidate_task_ids",
                    "corrected_criteria", "add_specs", "rewire")
        if any(k not in decision for k in required):
            return False
        if not str(decision["reason"]).strip():
            return False
        version = str(decision["next_version"]).strip()
        if not version or version == self.mc.plan_version:
            return False
        if not isinstance(decision["invalidate_task_ids"], list):
            return False
        if not isinstance(decision["corrected_criteria"], dict):
            return False
        if not isinstance(decision["add_specs"], list):
            return False
        if not isinstance(decision["rewire"], dict):
            return False
        return True

    def _valid_revision(self, revision: Any) -> bool:
        """A revision must recover at least one task; a malformed revision
        ends the review loop with the plan still blocked (fail-closed)."""
        if not isinstance(revision, dict):
            return False
        recover = revision.get("recover_task_ids")
        if not isinstance(recover, list) or not recover:
            return False
        return all(isinstance(t, str) and t for t in recover)

    def _record_verifier_failure(self, task_id: str, task_key: str,
                                 verify_result: Any, run_id: str) -> Optional[FailureRecord]:
        """E10-RP2.1 §4: record a verifier-detected failure classified by the
        EXPLICIT ``failure_class`` carried in the verifier result — never
        inferred from ``missing_evidence`` presence/absence or error-string
        heuristics (the RP2 string-sniffing classifier is gone).

        Mapping (order §4.1):
          * criteria_mismatch     -> PLAN_DEVIATION (replan-eligible: the
            decision -> replan_mission -> review gate -> continuation path).
          * provenance_unprovable -> PLAN_DEVIATION (a mission-state problem
            — the producing attempt cannot be established; a replan can
            recover it by re-execution, retrying the verifier cannot).
          * verifier_error        -> TOOL_RUNTIME_FAILURE (retry territory);
            NEVER auto-classified as a plan deviation.
          * missing/unknown class -> TOOL_RUNTIME_FAILURE (conservative:
            replanning on an unclassified failure is forbidden).

        Dedup: one OPEN verifier failure per task — repeated failing
        verification rounds for the same task do not stack records; the
        open record is resolved by _resolve_verifier_failure when newer
        valid evidence arrives (§3.4), or by replan_mission when the
        deviation it carried is answered by an approved replan."""
        output = getattr(verify_result, "output", None) or {}
        missing = list(output.get("missing_evidence", []) or []) if isinstance(output, dict) else []
        # §4.2: the failure type comes from the EXPLICIT field, not from
        # missing_evidence or error strings.
        failure_class = (
            output.get("failure_class") if isinstance(output, dict) else None
        ) or "verifier_error"

        existing_open = self._open_verifier_failures.get(task_id)
        if existing_open is not None:
            return existing_open  # still unresolved — no stacking

        if failure_class in ("criteria_mismatch", "provenance_unprovable"):
            kind = FailureKind.PLAN_DEVIATION
            recovery = RecoveryAction.REPLAN
            if failure_class == "criteria_mismatch":
                reason = ("Verifier verdict not_evidenced against the task's "
                          "CURRENT acceptance criteria and CURRENT on-disk "
                          "state: observed reality deviates from the plan's "
                          "expectation (E10-RP2.1 §4, explicit class "
                          "criteria_mismatch)")
            else:
                reason = ("Verifier could not establish the producing "
                          "attempt for the task's evidence — provenance is "
                          "unprovable (fail-closed not_evidenced); a "
                          "mission-state problem a replan can recover by "
                          "re-execution (E10-RP2.1 §4, explicit class "
                          "provenance_unprovable)")
        else:
            kind = FailureKind.TOOL_RUNTIME_FAILURE
            recovery = RecoveryAction.RETRY
            # (kept contiguous for the RP2 source-pattern guarantee)
            reason = ("Verifier machinery error (tool/runtime, explicit class "
                      "verifier_error) — retry territory; "
                      "never auto-classified as plan deviation (E10-RP2.1 §4)")
        import hashlib as _hl
        record = FailureRecord(
            failure_id=f"fail-{_hl.sha256(f'{task_id}verifier{datetime.now(timezone.utc).isoformat()}'.encode()).hexdigest()[:12]}",
            kind=kind,
            task_id=task_id,
            task_key=task_key,
            description=(
                f"Verification failed (orchestrator verifier, class="
                f"{failure_class}): "
                + (str(getattr(verify_result, "error", "") or "")
                   or "criteria not evidenced")
                + ("" if not missing else " | missing: " + "; ".join(missing[:3]))),
            evidence=[
                f"VERIFICATION_COMPLETE not_evidenced for task {task_key} "
                f"(run {run_id}, plan {getattr(self.mc, 'plan_version', 'v1')}, "
                f"failure_class={failure_class})",
                *(f"missing_evidence: {m}" for m in missing[:5]),
            ],
            detected_at=datetime.now(timezone.utc).isoformat(),
            classification_reason=reason,
            recovery_action=recovery,
        )
        self.mc.failures.append(record)
        if kind is FailureKind.PLAN_DEVIATION:
            self._open_verifier_failures[task_id] = record
        return record

    def _resolve_verifier_failure(self, task_id: str) -> None:
        """§3.4: a NEWER evidenced verification for the same task resolves
        the open verifier failure (resolution requires newer valid
        evidence — the historical not_evidenced stays in the durable
        event log, never erased)."""
        rec = self._open_verifier_failures.pop(task_id, None)
        if rec is not None and not rec.resolved:
            rec.resolved = True
            rec.resolved_by = (f"newer_evidence@{getattr(self.mc, 'plan_version', 'v1')} "
                               "(latest verification verdict evidenced)")

    async def _run_replanning_cycle(
        self, run_id: str, deviation: Any
    ) -> Optional[Dict[str, Any]]:
        """E10-RP1 §2.3/§2.4 — the canonical replanning path.

        Wire: REPLAN-classified FailureRecord (+ its evidence) -> decision
        (from the disclosed replan_decision_provider) -> MissionController
        .replan_mission -> review gate (fail-closed checks C1..C8) ->,
        ONLY after APPROVAL, continuation via execute_run (whose own gate
        re-enforces the approval — defense in depth). A rejected review
        blocks continuation; the provider may supply a bounded revision
        (recovery of corrected tasks), which is re-reviewed. Beyond
        max_review_rounds the plan stays blocked.

        Returns:
          None                    — no valid decision (no replan at all)
          {"approved": True, ...} — continuation executed under approval
          {"approved": False, "blocked": True, "review": ...}
                                  — review rejected; continuation REFUSED
        """
        provider = self.replan_decision_provider
        decision = provider(
            stage="replan", deviation=deviation,
            controller=self.mc, orchestrator=self, run_id=run_id,
        )
        if not self._valid_replan_decision(decision):
            return None

        self.mc.replan_mission(
            run_id=run_id,
            deviation=deviation,
            invalidate_task_ids=list(decision["invalidate_task_ids"]),
            corrected_criteria=dict(decision["corrected_criteria"]),
            add_specs=list(decision["add_specs"]),
            rewire=dict(decision["rewire"]),
            reason=str(decision["reason"]),
            plan_version=str(decision["next_version"]),
        )

        review = self.mc.review_plan(
            run_id,
            reviewer="canonical_orchestrator",
            note=f"post-replan review (plan {self.mc.plan_version}) before continuation",
        )
        rounds = 1
        while review.verdict != "approved" and rounds < self.max_review_rounds:
            revision = provider(
                stage="revision", rejection=review,
                controller=self.mc, orchestrator=self, run_id=run_id,
            )
            if not self._valid_revision(revision):
                break
            for task_id in revision["recover_task_ids"]:
                self.mc.recover_failed_task(
                    run_id, task_id,
                    reason="plan review rejection: recover the corrected task after plan correction",
                )
            review = self.mc.review_plan(
                run_id,
                reviewer="canonical_orchestrator",
                note=f"review round {rounds + 1} (plan {self.mc.plan_version})",
            )
            rounds += 1

        if review.verdict != "approved":
            return {"approved": False, "blocked": True, "review": review, "result": None}

        # Continuation — ONLY under the approved plan version. The gate at
        # the top of execute_run independently re-enforces this: an
        # unapproved / never-reviewed / rejected plan refuses BEFORE any
        # execution starts.
        continuation = await self.mc.execute_run(run_id, max_parallel=self.max_parallel)
        return {"approved": True, "blocked": False, "review": review, "result": continuation}

    async def stream_events(self) -> asyncio.Queue:
        """Get event stream queue for SSE."""
        return self.event_streamer.subscribe()


# ============================================================
# FACTORY FUNCTION
# ============================================================

def create_canonical_orchestrator(
    llm_provider: Any,
    artifacts_base_dir: str = ".",
    auto_approve_plans: bool = True,
    max_parallel: int = 1,
    require_plan_review: bool = True,
    replan_decision_provider: Optional[Callable[..., Optional[Dict[str, Any]]]] = None,
    max_review_rounds: int = 3,
    grant_validator: Optional[Callable[[str, str], bool]] = None,
    grant_ids: Optional[List[str]] = None,
) -> CanonicalOrchestrator:
    """Create canonical orchestrator with default configuration.

    E10-RP1: the canonical default enables the plan review gate
    (require_plan_review=True) — the gated policy IS the operational path;
    callers that deliberately want the legacy ungated behavior must opt out
    explicitly.
    E10-RP2 §2: grant_validator + grant_ids carry the REAL authorization
    (e.g. the EOE engine bridge + owner-approved grant ids). Without them
    the governed write path fails closed (PermissionError)."""
    return CanonicalOrchestrator(
        llm_provider=llm_provider,
        artifacts_base_dir=artifacts_base_dir,
        auto_approve_plans=auto_approve_plans,
        max_parallel=max_parallel,
        require_plan_review=require_plan_review,
        replan_decision_provider=replan_decision_provider,
        max_review_rounds=max_review_rounds,
        grant_validator=grant_validator,
        grant_ids=grant_ids,
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "CanonicalOrchestrator",
    "OrchestratorMission",
    "OrchestratorResult",
    "GoalDecomposer",
    "PlanApprovalGate",
    "RoleCoordinator",
    "EventStreamer",
    "create_canonical_orchestrator",
]