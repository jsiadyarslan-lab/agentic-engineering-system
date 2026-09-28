#!/usr/bin/env python3
"""
AgentFactory Orchestrator Core
Main coordinator that manages the 7 agents and orchestrates the mission lifecycle.
"""

from __future__ import annotations

import asyncio
import uuid
import time
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pathlib import Path
import sqlite3
import json

from src.factory.agents.base import BaseAgent, AgentTask, AgentResult
from src.factory.agents.explorer import ExplorerAgent
from src.factory.agents.thinker import ThinkerAgent
from src.factory.agents.planner import PlannerAgent
from src.factory.agents.designer import DesignerAgent
from src.factory.agents.reviewer import ReviewerAgent
from src.factory.agents.implementer import ImplementerAgent
from src.factory.agents.verifier import VerifierAgent
from src.factory.agents.security import SecurityAgent
from src.factory.human.gate import HumanApprovalGate, HumanDecision
from src.factory.human.chat import ChatInterface
from src.factory.contracts.agent_protocol import (
    AgentTask, AgentResult, Handoff, 
    ExplorationReport, Analysis, Plan, DesignSpec, 
    Review, ImplementationResult, Verification, SecurityReport
)
from src.factory.context.memory import SharedContextManager
from src.factory.context.knowledge import KnowledgeGraph
from src.factory.context.artifacts import ArtifactRegistry
from src.factory.context.decisions import DecisionLog
from src.factory.context.memory import SharedContextManager
from src.factory.workflow.dag import TaskDAG
from src.factory.workflow.engine import WorkflowEngine
from src.factory.workflow.checkpoint import CheckpointManager
from src.factory.contracts.agent_protocol import (
    AgentTask, AgentResult, Handoff,
    ExplorationReport, Analysis, Plan, DesignSpec,
    Review, ImplementationResult, Verification, SecurityReport
)
from src.factory.events import EventBus, FactoryEvent, EventType
from src.substrate.windows_executor import WindowsExecutor, ExecutionResult
from src.llm.budget import TokenBudget, get_global_budget
from src.llm import LLMProvider, StructuredLLM


class MissionState(str, Enum):
    """Mission lifecycle states."""
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    EXPLORING = "EXPLORING"
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    DESIGNING = "DESIGNING"
    REVIEWING = "REVIEWING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SECURITY_CHECK = "SECURITY_CHECK"
    COMPLETED = "COMPLETED"
    REVISING = "REVISING"
    BLOCKED = "BLOCKED"
    ABORTED = "ABORTED"
    ESCALATED = "ESCALATED"


@dataclass
class Mission:
    """Complete mission tracking with full history."""
    mission_id: str
    user_request: str
    state: MissionState = MissionState.IDLE
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    # Agent outputs
    exploration_report: Optional[ExplorationReport] = None
    analysis: Optional[Analysis] = None
    plan: Optional[Plan] = None
    design_spec: Optional[DesignSpec] = None
    review: Optional[Review] = None
    human_decision: Optional[HumanDecision] = None
    implementation_result: Optional[ImplementationResult] = None
    verification: Optional[Verification] = None
    security_report: Optional[SecurityReport] = None
    
    # Execution tracking
    current_agent: Optional[str] = None
    current_task: Optional[str] = None
    checkpoints: List[Dict[str, Any]] = field(default_factory=list)
    evidence_hashes: List[str] = field(default_factory=list)
    
    # Error tracking
    error_count: int = 0
    last_error: Optional[str] = None
    retry_count: int = 0
    
    def add_checkpoint(self, agent: str, task: str, output: Any, evidence_hash: str):
        """Add a checkpoint for potential resume."""
        checkpoint = {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": agent,
            "task": task,
            "output_summary": str(output)[:500],
            "evidence_hash": evidence_hash,
            "state": self.state.value
        }
        self.checkpoints.append(checkpoint)
        self.evidence_hashes.append(evidence_hash)
    
    def transition(self, new_state: MissionState, actor: str = "orchestrator"):
        """Transition to new state with logging."""
        old_state = self.state
        self.state = new_state
        self.updated_at = datetime.utcnow()
        
        # Log transition
        transition_log = {
            "timestamp": datetime.utcnow().isoformat(),
            "from_state": old_state.value,
            "to_state": new_state.value,
            "actor": actor,
            "mission_id": self.mission_id
        }
        
        # Append to decision log (would be persisted to DecisionLog)
        return transition_log


class AgentFactoryOrchestrator:
    """
    Main orchestrator that coordinates all 7 agents through the mission lifecycle.
    """
    
    def __init__(
        self,
        llm_provider: LLMProvider,
        context_manager: SharedContextManager,
        windows_executor: WindowsExecutor,
        human_gate: HumanApprovalGate,
        chat_interface: ChatInterface,
        token_budget: TokenBudget,
        test_mode: bool = False,
    ):
        self.llm_provider = llm_provider
        self.context_manager = context_manager
        self.windows_executor = windows_executor
        self.human_gate = human_gate
        self.chat_interface = chat_interface
        self.token_budget = token_budget
        self.test_mode = test_mode
        
        # Initialize agents
        self.agents = self._initialize_agents()
        self.agent_registry = {agent.agent_type: agent for agent in self.agents}
        
        # State management
        self.current_mission: Optional[Mission] = None
        self.mission_history: List[Mission] = []
        
        # Workflow engine - create DAG from agent dependencies
        from src.factory.workflow.dag import TaskDAG, TaskNode
        dag = TaskDAG()
        for agent in self.agents:
            dag.add_task(TaskNode(
                task_id=agent.agent_type,
                task_type=agent.agent_type,
                spec={},
                acceptance_criteria=[],
            ))
        self.workflow_engine = WorkflowEngine(dag=dag, agents=self.agent_registry)
        self.checkpoint_manager = CheckpointManager()
        
        # Decision log
        self.decision_log: List[Dict] = []
        
        # Event bus
        self.event_bus = EventBus()
        
        # Running state
        self._running = False
        self._shutdown_event = asyncio.Event()
    
    def _initialize_agents(self) -> List[BaseAgent]:
        """Initialize all 7 agents with their dependencies."""
        agents = [
            ExplorerAgent(
                llm=self.llm_provider.get_structured_llm("explorer"),
                context=self.context_manager,
                grants=None,  # Explorer needs read access
            ),
            ThinkerAgent(
                llm=self.llm_provider.get_structured_llm("thinker"),
                context=self.context_manager,
                grants=None,
            ),
            PlannerAgent(
                llm=self.llm_provider.get_structured_llm("planner"),
                context=self.context_manager,
                grants=None,
            ),
            DesignerAgent(
                llm=self.llm_provider.get_structured_llm("designer"),
                context=self.context_manager,
                grants=None,
            ),
            ReviewerAgent(
                llm=self.llm_provider.get_structured_llm("reviewer"),
                context=self.context_manager,
                grants=None,
            ),
            ImplementerAgent(
                llm=self.llm_provider.get_structured_llm("implementer"),
                context=self.context_manager,
                grants=None,  # Will get write grants after human approval
            ),
            VerifierAgent(
                llm=self.llm_provider.get_structured_llm("verifier"),
                context=self.context_manager,
                grants=None,
                test_mode=self.test_mode,
            ),
            SecurityAgent(
                llm=self.llm_provider.get_structured_llm("security"),
                context=self.context_manager,
                grants=None,
                test_mode=self.test_mode,
            ),
        ]
        return agents
    
    async def start_mission(self, user_request: str) -> Mission:
        """Start a new mission from user request."""
        mission_id = str(uuid.uuid4())[:8]
        mission = Mission(
            mission_id=mission_id,
            user_request=user_request,
        )
        
        self.current_mission = mission
        self._running = True
        self._shutdown_event.clear()
        
        # Initialize context for this mission
        await self.context_manager.initialize_mission(mission.mission_id, user_request)
        
        # Log mission start
        self._log_decision("mission_started", {
            "mission_id": mission.mission_id,
            "user_request": user_request,
        })
        
        # Start the mission loop
        asyncio.create_task(self._run_mission_loop())
        
        return mission
    
    async def _run_mission_loop(self):
        """Main mission execution loop."""
        mission = self.current_mission
        
        try:
            while self._running and not self._shutdown_event.is_set():
                # Check for shutdown
                if self._shutdown_event.is_set():
                    break
                
                # Execute current state logic
                await self._execute_current_state()
                
                # Small delay to prevent busy loop
                await asyncio.sleep(0.1)
                
        except Exception as e:
            await self._handle_mission_error(e)
        finally:
            self._running = False
    
    async def _execute_current_state(self):
        """Execute logic for current mission state."""
        mission = self.current_mission
        if not mission:
            return
        
        state_handlers = {
            MissionState.IDLE: self._handle_idle,
            MissionState.LISTENING: self._handle_listening,
            MissionState.EXPLORING: self._handle_exploring,
            MissionState.ANALYZING: self._handle_analyzing,
            MissionState.PLANNING: self._handle_planning,
            MissionState.DESIGNING: self._handle_designing,
            MissionState.REVIEWING: self._handle_reviewing,
            MissionState.AWAITING_APPROVAL: self._handle_awaiting_approval,
            MissionState.EXECUTING: self._handle_executing,
            MissionState.VERIFYING: self._handle_verifying,
            MissionState.SECURITY_CHECK: self._handle_security_check,
            MissionState.REVISING: self._handle_revising,
            MissionState.BLOCKED: self._handle_blocked,
            MissionState.ABORTED: self._handle_aborted,
        }
        
        handler = state_handlers.get(mission.state)
        if handler:
            await handler()
        else:
            await self._handle_unknown_state()
    
    async def _handle_idle(self):
        """IDLE -> LISTENING"""
        mission = self.current_mission
        old_state = mission.state
        mission.transition(MissionState.LISTENING, "orchestrator")
        await self._publish_state_transition(mission, old_state, MissionState.LISTENING, "orchestrator")
        # Wait for user input or external trigger
        await asyncio.sleep(0.5)
    
    async def _handle_listening(self):
        """LISTENING -> EXPLORING"""
        mission = self.current_mission
        if mission.user_request:
            old_state = mission.state
            mission.transition(MissionState.EXPLORING, "orchestrator")
            await self._publish_state_transition(mission, old_state, MissionState.EXPLORING, "orchestrator")
    
    async def _handle_exploring(self):
        """EXPLORING -> ANALYZING"""
        mission = self.current_mission
        
        # Delegate to Explorer
        explorer = self.agent_registry["explorer"]
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="explore",
            spec={"user_request": self.current_mission.user_request},
            acceptance_criteria=["codebase_mapped", "dependencies_identified", "entry_points_found"],
        )
        
        result = await explorer.execute(task)
        
        if result.success:
            mission.exploration_report = result.output
            mission.evidence_hashes.append(result.evidence_hash)
            mission.add_checkpoint("explorer", "explore", result.output, result.evidence_hash)
            await self._publish_agent_completion(mission, "explorer", result, True)
            old_state = mission.state
            mission.transition(MissionState.ANALYZING, "explorer")
            await self._publish_state_transition(mission, old_state, MissionState.ANALYZING, "explorer")
        else:
            await self._handle_agent_failure("explorer", result.error)
    
    async def _handle_analyzing(self):
        """ANALYZING -> PLANNING"""
        mission = self.current_mission
        
        thinker = self.agent_registry["thinker"]
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="analyze",
            spec={
                "exploration_report": mission.exploration_report,
                "user_request": mission.user_request,
            },
            acceptance_criteria=["root_cause_identified", "impact_assessed", "risks_identified"],
        )
        
        result = await thinker.execute(task)
        
        if result.success:
            mission.analysis = result.output
            mission.evidence_hashes.append(result.evidence_hash)
            mission.add_checkpoint("thinker", "analyze", result.output, result.evidence_hash)
            await self._publish_agent_completion(mission, "thinker", result, True)
            old_state = mission.state
            mission.transition(MissionState.PLANNING, "thinker")
            await self._publish_state_transition(mission, old_state, MissionState.PLANNING, "thinker")
        else:
            await self._handle_agent_failure("thinker", result.error)
    
    async def _handle_planning(self):
        """PLANNING -> DESIGNING"""
        mission = self.current_mission
        
        planner = self.agent_registry["planner"]
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="plan",
            spec={
                "analysis": mission.analysis,
                "exploration_report": mission.exploration_report,
                "user_request": mission.user_request,
            },
            acceptance_criteria=["tasks_defined", "dependencies_mapped", "estimates_provided"],
        )
        
        result = await planner.execute(task)
        
        if result.success:
            mission.plan = result.output
            mission.evidence_hashes.append(result.evidence_hash)
            mission.add_checkpoint("planner", "plan", result.output, result.evidence_hash)
            await self._publish_agent_completion(mission, "planner", result, True)
            old_state = mission.state
            mission.transition(MissionState.DESIGNING, "planner")
            await self._publish_state_transition(mission, old_state, MissionState.DESIGNING, "planner")
        else:
            await self._handle_agent_failure("planner", result.error)
    
    async def _handle_designing(self):
        """DESIGNING -> REVIEWING"""
        mission = self.current_mission
        
        designer = self.agent_registry["designer"]
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="design",
            spec={
                "plan": mission.plan,
                "analysis": mission.analysis,
            },
            acceptance_criteria=["spec_complete", "interfaces_defined", "data_models_defined"],
        )
        
        result = await designer.execute(task)
        
        if result.success:
            mission.design_spec = result.output
            mission.evidence_hashes.append(result.evidence_hash)
            mission.add_checkpoint("designer", "design", result.output, result.evidence_hash)
            await self._publish_agent_completion(mission, "designer", result, True)
            old_state = mission.state
            mission.transition(MissionState.REVIEWING, "designer")
            await self._publish_state_transition(mission, old_state, MissionState.REVIEWING, "designer")
        else:
            await self._handle_agent_failure("designer", result.error)
    
    async def _handle_reviewing(self):
        """REVIEWING -> AWAITING_APPROVAL"""
        mission = self.current_mission
        
        reviewer = self.agent_registry["reviewer"]
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="review",
            spec={
                "plan": mission.plan,
                "design_spec": mission.design_spec,
                "analysis": mission.analysis,
            },
            acceptance_criteria=["approves_or_requests_changes", "risks_identified"],
        )
        
        result = await reviewer.execute(task)
        
        if result.success:
            mission.review = result.output
            mission.evidence_hashes.append(result.evidence_hash)
            mission.add_checkpoint("reviewer", "review", result.output, result.evidence_hash)
            await self._publish_agent_completion(mission, "reviewer", result, True)
            
            if result.output.approved:
                old_state = mission.state
                mission.transition(MissionState.AWAITING_APPROVAL, "reviewer")
                await self._publish_state_transition(mission, old_state, MissionState.AWAITING_APPROVAL, "reviewer")
                # Publish human approval request
                await self._publish_human_approval_request(mission, {
                    "plan": mission.plan.to_dict() if mission.plan else {},
                    "design_spec": mission.design_spec.to_dict() if mission.design_spec else {},
                    "review_summary": mission.review.summary if mission.review else "",
                })
            else:
                old_state = mission.state
                mission.transition(MissionState.REVISING, "reviewer")
                await self._publish_state_transition(mission, old_state, MissionState.REVISING, "reviewer")
        else:
            await self._handle_agent_failure("reviewer", result.error)
    
    async def _handle_awaiting_approval(self):
        """AWAITING_APPROVAL -> EXECUTING or REVISING"""
        mission = self.current_mission
        
        # Request human approval via chat interface
        approval_request = {
            "plan": mission.plan.to_dict() if mission.plan else {},
            "design_spec": mission.design_spec.to_dict() if mission.design_spec else {},
            "review_summary": mission.review.summary if mission.review else "",
        }
        
        # Request human approval via chat interface
        decision = await self.human_gate.request_approval(mission.mission_id, approval_request)
        
        if decision.approved:
            mission.human_decision = decision
            old_state = mission.state
            mission.transition(MissionState.EXECUTING, "human")
            await self._publish_state_transition(mission, old_state, MissionState.EXECUTING, "human")
        else:
            mission.human_decision = decision
            old_state = mission.state
            mission.transition(MissionState.REVISING, "human")
            await self._publish_state_transition(mission, old_state, MissionState.REVISING, "human")
    
    async def _handle_executing(self):
        """EXECUTING -> VERIFYING"""
        mission = self.current_mission
        
        # Grant write permissions to implementer
        implementer = self.agent_registry["implementer"]
        # Grant write access for implementation
        # (Would integrate with grant system)
        
        implementer = self.agent_registry["implementer"]
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="implement",
            spec={
                "plan": mission.plan.to_dict() if mission.plan else {},
                "design_spec": mission.design_spec.to_dict() if mission.design_spec else {},
                "workspace": self.context_manager.get_workspace_path(),
            },
            acceptance_criteria=["all_tests_pass", "code_compiles", "implements_spec"],
        )
        
        result = await implementer.execute(task)
        
        if result.success:
            mission.implementation_result = result.output
            mission.evidence_hashes.append(result.evidence_hash)
            mission.add_checkpoint("implementer", "implement", result.output, result.evidence_hash)
            await self._publish_agent_completion(mission, "implementer", result, True)
            old_state = mission.state
            mission.transition(MissionState.VERIFYING, "implementer")
            await self._publish_state_transition(mission, old_state, MissionState.VERIFYING, "implementer")
        else:
            await self._handle_agent_failure("implementer", result.error)
    
    async def _handle_verifying(self):
        """VERIFYING -> SECURITY_CHECK"""
        mission = self.current_mission
        
        verifier = self.agent_registry["verifier"]
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="verify",
            spec={
                "implementation": mission.implementation_result,
                "plan": mission.plan,
                "design_spec": mission.design_spec,
            },
            acceptance_criteria=["all_tests_pass", "spec_compliance", "no_regressions"],
        )
        
        result = await verifier.execute(task)
        
        if result.success:
            mission.verification = result.output
            mission.evidence_hashes.append(result.evidence_hash)
            mission.add_checkpoint("verifier", "verify", result.output, result.evidence_hash)
            await self._publish_agent_completion(mission, "verifier", result, True)
            old_state = mission.state
            mission.transition(MissionState.SECURITY_CHECK, "verifier")
            await self._publish_state_transition(mission, old_state, MissionState.SECURITY_CHECK, "verifier")
        else:
            await self._handle_agent_failure("verifier", result.error)
    
    async def _handle_security_check(self):
        """SECURITY_CHECK -> COMPLETED"""
        mission = self.current_mission
        
        security = self.agent_registry["security"]
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="security_audit",
            spec={
                "implementation": mission.implementation_result,
                "verification": mission.verification,
            },
            acceptance_criteria=["no_vulnerabilities", "no_secrets", "dependencies_safe"],
        )
        
        result = await security.execute(task)
        
        if result.success:
            mission.security_report = result.output
            mission.evidence_hashes.append(result.evidence_hash)
            mission.add_checkpoint("security", "security_audit", result.output, result.evidence_hash)
            await self._publish_agent_completion(mission, "security", result, True)
            old_state = mission.state
            mission.transition(MissionState.COMPLETED, "security")
            await self._publish_state_transition(mission, old_state, MissionState.COMPLETED, "security")
            mission.completed_at = datetime.utcnow()
        else:
            await self._handle_agent_failure("security", result.error)
    
    async def _handle_revising(self):
        """REVISING -> back to PLANNING or DESIGNING"""
        mission = self.current_mission
        
        # Get revision feedback from human decision
        feedback = mission.human_decision.feedback if mission.human_decision else "Revision requested"
        
        # Determine where to go back based on feedback
        if "design" in (mission.human_decision.feedback or "").lower():
            old_state = mission.state
            mission.transition(MissionState.DESIGNING, "human")
            await self._publish_state_transition(mission, old_state, MissionState.DESIGNING, "human")
        else:
            old_state = mission.state
            mission.transition(MissionState.PLANNING, "human")
            await self._publish_state_transition(mission, old_state, MissionState.PLANNING, "human")
    
    async def _handle_blocked(self):
        """BLOCKED -> ESCALATED or ABORTED"""
        mission = self.current_mission
        mission.error_count += 1
        
        if mission.error_count >= 3:
            old_state = mission.state
            mission.transition(MissionState.ESCALATED, "orchestrator")
            await self._publish_state_transition(mission, old_state, MissionState.ESCALATED, "orchestrator")
        else:
            # Try to recover
            await asyncio.sleep(5)
            # Would implement recovery logic
    
    async def _handle_aborted(self):
        """ABORTED - mission terminated"""
        if self.current_mission:
            old_state = self.current_mission.state
            await self._publish_state_transition(self.current_mission, old_state, MissionState.ABORTED, "orchestrator")
        self._running = False
    
    async def _handle_unknown_state(self):
        """Unknown state - log and abort"""
        mission = self.current_mission
        self._log_decision("unknown_state", {
            "state": mission.state.value,
            "mission_id": mission.mission_id,
        })
        old_state = mission.state
        mission.transition(MissionState.ABORTED, "orchestrator")
        await self._publish_state_transition(mission, old_state, MissionState.ABORTED, "orchestrator")
    
    async def _handle_agent_failure(self, agent_name: str, error: str):
        """Handle agent execution failure."""
        mission = self.current_mission
        mission.error_count += 1
        mission.last_error = f"{agent_name}: {error}"
        
        self._log_decision("agent_failure", {
            "agent": agent_name,
            "error": error,
            "mission_id": self.current_mission.mission_id,
        })
        
        # Publish failed agent completion event
        await self._publish_agent_completion(mission, agent_name, None, False)
        
        if self.current_mission.error_count >= 3:
            old_state = self.current_mission.state
            self.current_mission.transition(MissionState.ESCALATED, "orchestrator")
            await self._publish_state_transition(self.current_mission, old_state, MissionState.ESCALATED, "orchestrator")
        else:
            # Retry logic would go here
            await asyncio.sleep(2)
            # Could implement retry with backoff
    
    async def _handle_mission_error(self, error: Exception):
        """Handle unexpected mission error."""
        if self.current_mission:
            old_state = self.current_mission.state
            self.current_mission.transition(MissionState.ABORTED, "orchestrator")
            await self._publish_state_transition(self.current_mission, old_state, MissionState.ABORTED, "orchestrator")
            self.current_mission.last_error = str(error)
        
        self._log_decision("mission_error", {
            "error": str(error),
            "mission_id": self.current_mission.mission_id if self.current_mission else None,
        })
    
    def _log_decision(self, decision_type: str, data: Dict):
        """Log decision to decision log."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "type": decision_type,
            "data": data,
        }
        self.decision_log.append(entry)
        # Would persist to DecisionLog in context
    
    async def _publish_state_transition(self, mission: Mission, old_state: MissionState, new_state: MissionState, actor: str = "orchestrator"):
        """Publish state transition event to event bus."""
        await self.event_bus.publish(FactoryEvent(
            event_type=EventType.STATE_TRANSITION,
            mission_id=mission.mission_id,
            timestamp=datetime.utcnow(),
            state_from=old_state.value,
            state_to=new_state.value,
            agent_type=actor,
            payload={"actor": actor},
            evidence_hash="",
            source="mock",
        ))
    
    async def _publish_agent_completion(self, mission: Mission, agent_type: str, result, success: bool):
        """Publish agent completion event to event bus."""
        evidence_hash = ""
        if result is not None and hasattr(result, 'evidence_hash'):
            evidence_hash = result.evidence_hash
        await self.event_bus.publish(FactoryEvent(
            event_type=EventType.AGENT_COMPLETION,
            mission_id=mission.mission_id,
            timestamp=datetime.utcnow(),
            state_from=mission.state.value,
            state_to=mission.state.value,
            agent_type=agent_type,
            payload={"success": success},
            evidence_hash=evidence_hash,
            source="mock",
        ))
    
    async def _publish_human_approval_request(self, mission: Mission, payload: Dict):
        """Publish human approval request event to event bus."""
        await self.event_bus.publish(FactoryEvent(
            event_type=EventType.HUMAN_APPROVAL_REQUEST,
            mission_id=mission.mission_id,
            timestamp=datetime.utcnow(),
            state_from=mission.state.value,
            state_to="AWAITING_APPROVAL",
            agent_type="reviewer",
            payload=payload,
            evidence_hash="",
            source="mock",
        ))
    
    async def request_human_approval(self, request: Dict) -> HumanDecision:
        """Request human approval via gate."""
        mission_id = request.get("mission_id", "")
        return await self.human_gate.request_approval(mission_id, request)
    
    async def shutdown(self):
        """Graceful shutdown."""
        self._running = False
        self._shutdown_event.set()
        await self._shutdown_event.wait()
    
    def get_mission_status(self, mission_id: str) -> Optional[Dict]:
        """Get current mission status."""
        if self.current_mission and self.current_mission.mission_id == mission_id:
            return self._serialize_mission(self.current_mission)
        
        for mission in self.mission_history:
            if mission.mission_id == mission_id:
                return self._serialize_mission(mission)
        return None
    
    def _serialize_mission(self, mission: Mission) -> Dict:
        return {
            "mission_id": mission.mission_id,
            "state": mission.state.value,
            "user_request": mission.user_request,
            "created_at": mission.created_at.isoformat(),
            "updated_at": mission.updated_at.isoformat(),
            "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
            "current_agent": mission.current_agent,
            "error_count": mission.error_count,
            "evidence_count": len(mission.evidence_hashes),
        }
    
    def get_decision_log(self) -> List[Dict]:
        return self.decision_log

    @classmethod
    async def create_for_test(cls, test_mode: bool = True) -> "AgentFactoryOrchestrator":
        """Create orchestrator for testing with mock components."""
        from src.llm import MockLLMProvider
        from src.factory.context.memory import SharedContextManager
        from src.factory.context.knowledge import KnowledgeGraph
        from src.factory.context.artifacts import ArtifactRegistry
        from src.factory.context.decisions import DecisionLog
        from src.factory.human.gate import HumanApprovalGate, HumanDecision
        from src.factory.human.chat import ChatInterface
        from src.llm.budget import TokenBudget
        from src.substrate.windows_executor import WindowsExecutor
        
        # Create mock LLM provider
        llm_provider = MockLLMProvider()
        
        # Create context manager (initialize mission first)
        context_manager = await SharedContextManager.initialize_mission(
            mission_id="test-mission",
            user_request="test request"
        )
        
        # Create windows executor
        windows_executor = WindowsExecutor()
        
        # Create human gate with test_mode for auto-approve
        human_gate = HumanApprovalGate(
            chat_interface=None,
            decision_log=None,
            test_mode=test_mode,
        )
        
        # Create chat interface (minimal for testing)
        chat_interface = ChatInterface(
            input_callback=lambda _: asyncio.sleep(0, result="A"),
            output_callback=print,
        )
        
        # Create token budget
        token_budget = TokenBudget()
        
        # Create orchestrator
        orchestrator = cls(
            llm_provider=llm_provider,
            context_manager=context_manager,
            windows_executor=windows_executor,
            human_gate=human_gate,
            chat_interface=chat_interface,
            token_budget=token_budget,
            test_mode=test_mode,
        )
        
        return orchestrator