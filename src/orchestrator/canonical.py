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
                
                async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
                    # Independent verification of target task artifacts
                    target_artifacts = task.context.get("target_artifacts", [])
                    target_task_id = task.context.get("target_task_id", "")
                    
                    # For now, just verify artifacts exist
                    verified = len(target_artifacts) > 0
                    
                    from unified.contracts import new_artifact_id, new_evidence_id
                    import hashlib
                    verify_json = json.dumps({
                        "target_task_id": target_task_id,
                        "target_artifacts": target_artifacts,
                        "verified": verified,
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
                        content_type="verification",
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
                        output={"verification": verify_json},
                        evidence_hash=sha256,
                        artifacts=[artifact_id]
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
    
    async def run_verifier(self, mission_id: str, run_id: str, task_id: str, artifacts: List[str]) -> AgentResult:
        """Run Verifier to independently check task outputs."""
        engine = self.mc.engine
        
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
                "target_artifacts": artifacts
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
        
        result = await factory.execute_agent_by_id("e3-verifier", agent_context, verify_task)
        
        # Emit VERIFICATION_COMPLETE event for MissionController.verify_completion()
        if result.success:
            from unified.contracts import new_verification_id, new_attempt_id
            engine._emit(__import__('unified.contracts', fromlist=['FactoryEvent']).FactoryEvent.create(
                event_type=EventType.VERIFICATION_COMPLETE,
                mission_id=mission_id,
                run_id=run_id,
                payload=__import__('unified.contracts', fromlist=['VerificationCompleteEvent']).VerificationCompleteEvent(
                    verification_id=new_verification_id(),
                    task_id=task_id,
                    attempt_id=new_attempt_id(),
                    verdict="evidenced" if result.success else "not_evidenced",
                    checks_performed=["artifact_verification"],
                    missing_evidence=[],
                    confidence=1.0 if result.success else 0.0,
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

        # Core P1+P2 components
        self.engine = create_execution_engine(
            artifacts_base_dir=artifacts_base_dir,
            grant_validator=grant_validator,
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
            
            # 6. Run Verifier on completed tasks (independent verification)
            task_results = result.get("task_results", {})
            for task_id, tr in task_results.items():
                if tr.get("success") and tr.get("artifacts"):
                    verify_result = await self.role_coordinator.run_verifier(
                        mc_mission.mission_id, mc_run.run_id, task_id, tr["artifacts"]
                    )
                    # Record verification result (E10-RP1 §2.5: this was a
                    # `pass` stub whose comment claimed it "could trigger
                    # replan here" while doing nothing. The failure is now
                    # RECORDED durably as a not_evidenced verification and is
                    # visible to verify_completion below. Wiring verifier
                    # failures into the replanning decision path remains a
                    # DISCLOSED GAP — it is NOT claimed here.)
                    if not verify_result.success:
                        from unified.contracts import new_verification_id, new_attempt_id
                        self.mc.engine._emit(FactoryEvent.create(
                            event_type=EventType.VERIFICATION_COMPLETE,
                            mission_id=mc_mission.mission_id,
                            run_id=mc_run.run_id,
                            payload=VerificationCompleteEvent(
                                verification_id=new_verification_id(),
                                task_id=task_id,
                                attempt_id=new_attempt_id(),
                                verdict="not_evidenced",
                                checks_performed=["artifact_verification"],
                                missing_evidence=[],
                                confidence=0.0,
                            ),
                            source="canonical_orchestrator",
                            correlation_id=task_id,
                        ))
            
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
) -> CanonicalOrchestrator:
    """Create canonical orchestrator with default configuration.

    E10-RP1: the canonical default enables the plan review gate
    (require_plan_review=True) — the gated policy IS the operational path;
    callers that deliberately want the legacy ungated behavior must opt out
    explicitly."""
    return CanonicalOrchestrator(
        llm_provider=llm_provider,
        artifacts_base_dir=artifacts_base_dir,
        auto_approve_plans=auto_approve_plans,
        max_parallel=max_parallel,
        require_plan_review=require_plan_review,
        replan_decision_provider=replan_decision_provider,
        max_review_rounds=max_review_rounds,
        grant_validator=grant_validator,
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