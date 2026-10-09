"""
Event Catalog — Unified Engineering Agents System
Complete catalog of all events in the system with schemas, triggers, and consumers.
Based on EAS v2 event model + AgentFactory FactoryEvent.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field
from dataclasses import dataclass
# ============================================================
# EVENT TYPES
# ============================================================
class EventType(str, Enum):
    """All event types in the system."""
    # Mission lifecycle
    MISSION_STARTED = "mission.started"
    MISSION_COMPLETED = "mission.completed"
    MISSION_ABORTED = "mission.aborted"
    MISSION_STATE_CHANGED = "mission.state_changed"
    # Run lifecycle
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_RESUMED = "run.resumed"
    # Plan/Section lifecycle
    PLAN_CREATED = "plan.created"
    PLAN_REVISED = "plan.revised"
    PLAN_APPROVED = "plan.approved"
    SECTION_START = "section.start"
    SECTION_COMPLETE = "section.complete"
    SECTION_FAILED = "section.failed"
    # Agent lifecycle
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    AGENT_SELECTED = "agent.selected"
    # Task lifecycle
    TASK_CREATED = "task.created"
    TASK_ASSIGNED = "task.assigned"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_RETRY = "task.retry"
    # LLM interactions
    LLM_REQUESTED = "llm.requested"
    LLM_COMPLETED = "llm.completed"
    # Action boundaries
    ACTION_REQUESTED = "action.requested"
    ACTION_VALIDATED = "action.validated"
    # Tool execution
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    # Artifacts & Evidence
    ARTIFACT_CREATED = "artifact.created"
    ARTIFACT_RECONCILED = "artifact.reconciled"
    ARTIFACT_VERIFIED = "artifact.verified"
    EVIDENCE_RECORDED = "evidence.recorded"
    # Verification
    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_COMPLETE = "verification.complete"
    # State transitions
    STATE_TRANSITION = "state.transition"
    CHECKPOINT_CREATED = "checkpoint.created"
    CHECKPOINT_LOADED = "checkpoint.loaded"
    VERIFICATION_FAILED = "verification.failed"
    # Arbiter
    ARBITER_CALLED = "arbiter.called"
    ARBITER_DECIDED = "arbiter.decided"
    # Human interaction
    HUMAN_REQUIRED = "human.required"
    HUMAN_DECISION = "human.decision"
    # Replan
    REPLAN_REQUESTED = "replan.requested"
    REPLAN_APPLIED = "replan.applied"
    # Grants
    GRANT_ISSUED = "grant.issued"
    GRANT_VALIDATED = "grant.validated"
    GRANT_REVOKED = "grant.revoked"
    # Sandbox
    SANDBOX_STARTED = "sandbox.started"
    SANDBOX_COMPLETED = "sandbox.completed"
    SANDBOX_FAILED = "sandbox.failed"
    # Push/Repository
    PUSH_INITIATED = "push.initiated"
    PUSH_COMPLETED = "push.completed"
    PUSH_FAILED = "push.failed"
    # Hard stops (EAS v2)
    HARD_STOP_FIRED = "hard_stop.fired"
    # Metrics/Cost
    TOKEN_USAGE = "token.usage"
    BUDGET_WARNING = "budget.warning"
    BUDGET_EXCEEDED = "budget.exceeded"
    # System
    SYSTEM_ERROR = "system.error"
    SYSTEM_WARNING = "system.warning"
    # E11: Human Mission Control
    MISSION_PAUSE_REQUESTED = "mission.pause_requested"
    MISSION_PAUSED = "mission.paused"
    MISSION_RESUME_REQUESTED = "mission.resume_requested"
    MISSION_RESUMED = "mission.resumed"
    MISSION_CANCEL_REQUESTED = "mission.cancel_requested"
    MISSION_CANCELLED = "mission.cancelled"
    HUMAN_GATE_CREATED = "human.gate_created"
    HUMAN_DECISION_RECORDED = "human.decision_recorded"
    HUMAN_DECISION_REJECTED = "human.decision_rejected"
# ============================================================
# EVENT SCHEMAS (Pydantic Models)
# ============================================================
class EventMetadata(BaseModel):
    """Common metadata for all events."""
    event_id: str
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    correlation_id: Optional[str] = None  # Links related events
    causation_id: Optional[str] = None    # Event that caused this one
    source: str = "orchestrator"          # Component that emitted
    tags: List[str] = Field(default_factory=list)
class MissionStartedEvent(BaseModel):
    mission_id: str
    user_request: str
    provider: Optional[str] = None
    model: Optional[str] = None
class MissionCompletedEvent(BaseModel):
    mission_id: str
    final_state: str
    duration_seconds: float
    total_tokens: int
    artifact_count: int
    verification_result: str
class MissionStateChangedEvent(BaseModel):
    mission_id: str
    run_id: str
    from_state: str
    to_state: str
    actor: str
    reason: str
class RunStartedEvent(BaseModel):
    run_id: str
    mission_id: str
    run_number: int
    parent_run_id: Optional[str] = None
class PlanCreatedEvent(BaseModel):
    mission_id: str
    run_id: str
    plan_summary: str
    task_count: int
class PlanRevisedEvent(BaseModel):
    mission_id: str
    run_id: str
    revision_number: int
    changes: List[str]
class SectionStartEvent(BaseModel):
    section_id: str
    mission_id: str
    run_id: str
    section_name: str
    command: List[str]
    grants_required: List[str]
class SectionCompleteEvent(BaseModel):
    section_id: str
    mission_id: str
    run_id: str
    artifacts_produced: List[str]
    evidence_hashes: List[str]
class AgentStartedEvent(BaseModel):
    agent_id: str
    agent_type: str
    mission_id: str
    run_id: str
    task_id: str
class AgentCompletedEvent(BaseModel):
    agent_id: str
    agent_type: str
    mission_id: str
    run_id: str
    task_id: str
    success: bool
    output_summary: str
    evidence_hash: str
    duration_ms: int
class AgentFailedEvent(BaseModel):
    agent_id: str
    agent_type: str
    mission_id: str
    run_id: str
    task_id: str
    error: str
    error_type: str
class AgentSelectedEvent(BaseModel):
    agent_id: str
    agent_type: str
    mission_id: str
    run_id: str
    task_id: str
    selection_method: str
class TaskCreatedEvent(BaseModel):
    task_id: str
    mission_id: str
    run_id: str
    name: str
    agent_type: str
    acceptance_criteria: List[str]
    depends_on: List[str]
class TaskAssignedEvent(BaseModel):
    task_id: str
    agent_id: str
    # E33: full traceability — the engine already passes these; they were
    # previously dropped silently by pydantic.
    mission_id: Optional[str] = None
    run_id: Optional[str] = None
    agent_type: Optional[str] = None
    attempt_id: Optional[str] = None
class TaskCompletedEvent(BaseModel):
    task_id: str
    mission_id: str
    run_id: str
    success: bool
    artifacts: List[str]
    evidence_hashes: List[str]
    duration_ms: int
class TaskFailedEvent(BaseModel):
    task_id: str
    mission_id: str
    run_id: str
    error: str
    retry_count: int
    max_retries: int
class TaskRetryEvent(BaseModel):
    task_id: str
    mission_id: str
    run_id: str
    attempt_id: str
    retry_count: int
    max_retries: int
    error: str
class ToolStartedEvent(BaseModel):
    tool_name: str
    action_id: str
    attempt_id: str
    sandbox_id: Optional[str] = None
    args_summary: str
class ToolCompletedEvent(BaseModel):
    tool_name: str
    action_id: str
    attempt_id: str
    success: bool
    output_summary: str
    evidence_id: Optional[str] = None
    duration_ms: int
class ToolFailedEvent(BaseModel):
    tool_name: str
    action_id: str
    attempt_id: str
    error: str
    sandbox_id: Optional[str] = None
class LLMRequestedEvent(BaseModel):
    """LLM request initiated by agent."""
    mission_id: str
    run_id: str
    task_id: str
    agent_id: str
    agent_type: str
    provider: str
    model: str
    request_type: str  # "chat" or "structured_chat"
class LLMCompletedEvent(BaseModel):
    """LLM request completed."""
    mission_id: str
    run_id: str
    task_id: str
    agent_id: str
    agent_type: str
    provider: str
    model: str
    request_type: str
    success: bool
    tokens_used: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None
class ActionRequestedEvent(BaseModel):
    """Action requested by agent (after LLM decision)."""
    mission_id: str
    run_id: str
    task_id: str
    agent_id: str
    action_id: str
    attempt_id: str
    tool_name: str
    tool_args: Dict[str, Any]
class ActionValidatedEvent(BaseModel):
    """Action validated (capability/permission check passed)."""
    mission_id: str
    run_id: str
    task_id: str
    agent_id: str
    action_id: str
    attempt_id: str
    tool_name: str
    valid: bool
    reason: Optional[str] = None
class ArtifactCreatedEvent(BaseModel):
    artifact_id: str
    name: str
    path: str
    sha256: str
    size_bytes: int
    created_by: str  # action_id or sandbox_id
    mission_id: str
    run_id: str
    task_id: Optional[str] = None
class ArtifactReconciledEvent(BaseModel):
    """E10-CW1-R1: a prior side effect was reconciled/adopted across process
    lives WITHOUT re-performing the physical write. Semantically DISTINCT from
    ARTIFACT_CREATED: it never claims a new artifact came into existence — it
    claims an EXISTING effect (identified durably pre-effect by its intent
    record, or post-effect by its performed record) was validated and adopted
    by the resuming process."""
    artifact_id: str
    name: str
    path: str
    sha256: str
    size_bytes: int
    created_by: str
    mission_id: str
    run_id: str
    task_id: Optional[str] = None
    mode: str  # "performed_record" (reconciled from a durable performed record) | "intent_adoption" (adopted after intent-only crash)
    no_physical_rewrite: bool
    observed_mtime_ns: int
    observed_inode: int
    original_artifact_id: str

class EvidenceRecordedEvent(BaseModel):
    evidence_id: str
    evidence_hash: str
    content_type: str
    source_id: str
    mission_id: str
    run_id: str
    task_id: Optional[str] = None
class VerificationCompleteEvent(BaseModel):
    verification_id: str
    task_id: str
    attempt_id: str
    verdict: str  # VerifierVerdict
    checks_performed: List[str]
    missing_evidence: List[str]
    confidence: float
    # E10-RP2 §3 — verification truth bindings (all optional + backward
    # compatible): a verification result is bound to the task it verified,
    # the ATTEMPT that produced the verified artifact (not a fresh random
    # id), the plan version it was performed under, and the run. Older
    # emitters (engine verify_task) leave them None; MissionController
    # .verify_completion derives the plan version by timestamp for those.
    plan_version: Optional[str] = None
    run_id: Optional[str] = None
    verifier_attempt_id: Optional[str] = None
    criteria_source: Optional[str] = None  # "task.acceptance_criteria" | "engine.verify_task" | ...
    # E10-RP2.1 §4 — EXPLICIT failure classification (no inference from
    # missing_evidence presence or error-string heuristics):
    #   criteria_mismatch    — evidence read OK, criteria mechanically unmet
    #                         (replan-eligible plan deviation)
    #   provenance_unprovable — the producing attempt cannot be established
    #                         (fail-closed not_evidenced; mission-state problem)
    #   verifier_error       — read/execution/verifier-machinery failure
    #                         (retry territory; NEVER auto-replan)
    # None on success; absent for legacy emitters.
    failure_class: Optional[str] = None
    # E10-RP2.1 §3 — the task-bound evidence sources the verdict was read
    # from (sandbox of the TARGET task), for re-examination.
    evidence_paths: Optional[List[str]] = None


class VerificationStartedEvent(BaseModel):
    """Verification process started by verifier agent."""
    verification_id: str
    mission_id: str
    run_id: str
    task_id: str
    attempt_id: str
    status: str = "started"
class ArbiterCalledEvent(BaseModel):
    mission_id: str
    conflict_type: str
    parties: List[str]
    evidence_summary: str
class ArbiterDecidedEvent(BaseModel):
    mission_id: str
    decision: str  # ArbiterDecision
    rationale: str
    escalation_to_human: bool
    max_retries_remaining: int
class HumanRequiredEvent(BaseModel):
    mission_id: str
    run_id: str
    task_id: Optional[str] = None
    reason: str
    context: Dict[str, Any]
    options: List[Dict[str, str]]
    impact: str
    recommended_action: str
class HumanDecisionEvent(BaseModel):
    decision_id: str
    mission_id: str
    run_id: str
    task_id: Optional[str] = None
    decision_type: str  # HumanDecisionType
    approved: bool
    feedback: str
    reviewer: str
class ReplanRequestedEvent(BaseModel):
    run_id: str
    failed_task_id: str
    reason: str
    proposed_changes: List[Dict[str, Any]]
    actor: str
    graph_version_before: int
    timestamp: str
class ReplanAppliedEvent(BaseModel):
    run_id: str
    replan_id: str
    applied_changes: List[Dict[str, Any]]
    actor: str
    graph_version_before: int
    graph_version_after: int
    timestamp: str
# E11: Human Mission Control events
class MissionPauseRequestedEvent(BaseModel):
    mission_id: str
    run_id: str
    actor: str
    reason: str
class MissionPausedEvent(BaseModel):
    mission_id: str
    run_id: str
    checkpoint_id: Optional[str] = None
    paused_at_task: Optional[str] = None
class MissionResumeRequestedEvent(BaseModel):
    mission_id: str
    run_id: str
    actor: str
    reason: str
class MissionResumedEvent(BaseModel):
    mission_id: str
    run_id: str
    resumed_from_state: str
class MissionCancelRequestedEvent(BaseModel):
    mission_id: str
    run_id: str
    actor: str
    reason: str
class MissionCancelledEvent(BaseModel):
    mission_id: str
    run_id: str
    cancelled_at_state: str
    tasks_affected: int
class HumanGateCreatedEvent(BaseModel):
    gate_id: str
    mission_id: str
    run_id: str
    task_id: Optional[str] = None
    reason: str
    context: Dict[str, Any]
    options: List[Dict[str, str]]
    impact: str
    required_action: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
class HumanDecisionRecordedEvent(BaseModel):
    gate_id: str
    mission_id: str
    run_id: str
    decision: str  # continue, cancel
    actor: str
    feedback: str
    decided_at: datetime = Field(default_factory=datetime.utcnow)
class HumanDecisionRejectedEvent(BaseModel):
    gate_id: str
    mission_id: str
    run_id: str
    attempted_decision: str
    actor: str
    feedback: str
    reason: str
    existing_decision: Optional[str] = None
    existing_actor: Optional[str] = None
    existing_decided_at: Optional[datetime] = None
class GrantIssuedEvent(BaseModel):
    grant_id: str
    grantor: str
    subject: str
    permission_class: str
    domains: List[str]
    resources: List[str]
    expires_at: datetime
class GrantValidatedEvent(BaseModel):
    grant_id: str
    subject: str
    valid: bool
    reason: Optional[str] = None
class SandboxStartedEvent(BaseModel):
    sandbox_id: str
    mission_id: str
    run_id: str
    task_id: Optional[str] = None
    command: List[str]
    image: str
class SandboxCompletedEvent(BaseModel):
    sandbox_id: str
    mission_id: str
    run_id: str
    exit_code: Optional[int]
    termination: str
    duration_ms: int
    artifacts: List[str]
class CheckpointCreatedEvent(BaseModel):
    checkpoint_id: str
    mission_id: str
    run_id: str
    step: int
    state: str
    task_count: int
    artifact_count: int
    hash: str
class HardStopFiredEvent(BaseModel):
    reason: str
    detail: str
    mission_id: Optional[str] = None
    section_id: Optional[str] = None
class TokenUsageEvent(BaseModel):
    mission_id: str
    run_id: Optional[str] = None
    agent_type: Optional[str] = None
    tokens_used: int
    cost_usd: float
    scope: str  # agent, mission, project, global
class BudgetWarningEvent(BaseModel):
    mission_id: str
    scope: str
    utilization: float
    threshold: float
    remaining: int
class SystemErrorEvent(BaseModel):
    component: str
    error: str
    severity: str
    recoverable: bool
# ============================================================
# EVENT UNION & WRAPPER
# ============================================================
# Map event types to their payload models
EVENT_PAYLOAD_MODELS: Dict[EventType, type] = {
    EventType.MISSION_STARTED: MissionStartedEvent,
    EventType.MISSION_COMPLETED: MissionCompletedEvent,
    EventType.MISSION_STATE_CHANGED: MissionStateChangedEvent,
    EventType.RUN_STARTED: RunStartedEvent,
    EventType.PLAN_CREATED: PlanCreatedEvent,
    EventType.PLAN_REVISED: PlanRevisedEvent,
    EventType.SECTION_START: SectionStartEvent,
    EventType.SECTION_COMPLETE: SectionCompleteEvent,
    EventType.AGENT_STARTED: AgentStartedEvent,
    EventType.AGENT_COMPLETED: AgentCompletedEvent,
    EventType.AGENT_FAILED: AgentFailedEvent,
    EventType.AGENT_SELECTED: AgentSelectedEvent,
    EventType.TASK_CREATED: TaskCreatedEvent,
    EventType.TASK_ASSIGNED: TaskAssignedEvent,
    EventType.TASK_COMPLETED: TaskCompletedEvent,
    EventType.TASK_FAILED: TaskFailedEvent,
    EventType.TASK_RETRY: TaskRetryEvent,
    EventType.LLM_REQUESTED: LLMRequestedEvent,
    EventType.LLM_COMPLETED: LLMCompletedEvent,
    EventType.ACTION_REQUESTED: ActionRequestedEvent,
    EventType.ACTION_VALIDATED: ActionValidatedEvent,
    EventType.TOOL_STARTED: ToolStartedEvent,
    EventType.TOOL_COMPLETED: ToolCompletedEvent,
    EventType.TOOL_FAILED: ToolFailedEvent,
    EventType.ARTIFACT_CREATED: ArtifactCreatedEvent,
    EventType.ARTIFACT_RECONCILED: ArtifactReconciledEvent,
    EventType.EVIDENCE_RECORDED: EvidenceRecordedEvent,
    EventType.VERIFICATION_STARTED: VerificationStartedEvent,
    EventType.VERIFICATION_COMPLETE: VerificationCompleteEvent,
    EventType.ARBITER_CALLED: ArbiterCalledEvent,
    EventType.ARBITER_DECIDED: ArbiterDecidedEvent,
    EventType.HUMAN_REQUIRED: HumanRequiredEvent,
    EventType.HUMAN_DECISION: HumanDecisionEvent,
    EventType.GRANT_ISSUED: GrantIssuedEvent,
    EventType.GRANT_VALIDATED: GrantValidatedEvent,
    EventType.SANDBOX_STARTED: SandboxStartedEvent,
    EventType.SANDBOX_COMPLETED: SandboxCompletedEvent,
    EventType.CHECKPOINT_CREATED: CheckpointCreatedEvent,
    EventType.HARD_STOP_FIRED: HardStopFiredEvent,
    EventType.TOKEN_USAGE: TokenUsageEvent,
    EventType.BUDGET_WARNING: BudgetWarningEvent,
    EventType.SYSTEM_ERROR: SystemErrorEvent,
    # E11: Human Mission Control events
    EventType.MISSION_PAUSE_REQUESTED: MissionPauseRequestedEvent,
    EventType.MISSION_PAUSED: MissionPausedEvent,
    EventType.MISSION_RESUME_REQUESTED: MissionResumeRequestedEvent,
    EventType.MISSION_RESUMED: MissionResumedEvent,
    EventType.MISSION_CANCEL_REQUESTED: MissionCancelRequestedEvent,
    EventType.MISSION_CANCELLED: MissionCancelledEvent,
    EventType.HUMAN_GATE_CREATED: HumanGateCreatedEvent,
    EventType.HUMAN_DECISION_RECORDED: HumanDecisionRecordedEvent,
    EventType.HUMAN_DECISION_REJECTED: HumanDecisionRejectedEvent,
    # E13: Replan events
    EventType.REPLAN_REQUESTED: ReplanRequestedEvent,
    EventType.REPLAN_APPLIED: ReplanAppliedEvent,
}
class FactoryEvent(BaseModel):
    """
    Unified event envelope - matches AgentFactory FactoryEvent
    with EAS v2 event model extensions.
    """
    mission_id: str
    run_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    event_type: EventType
    payload: Dict[str, Any] = Field(default_factory=dict)
    evidence_hash: Optional[str] = None
    source: str = "orchestrator"
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    @classmethod
    def create(
        cls,
        event_type: EventType,
        mission_id: str,
        payload: BaseModel,
        run_id: Optional[str] = None,
        evidence_hash: Optional[str] = None,
        source: str = "orchestrator",
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
    ) -> "FactoryEvent":
        """Create a FactoryEvent with validated payload."""
        model = EVENT_PAYLOAD_MODELS.get(event_type)
        if model:
            # Validate payload against model
            if isinstance(payload, BaseModel):
                payload_dict = payload.model_dump()
            elif isinstance(payload, dict):
                payload_dict = payload
            else:
                payload_dict = {}
            validated = model.model_validate(payload_dict)
            payload_dict = validated.model_dump()
        else:
            payload_dict = payload.model_dump() if isinstance(payload, BaseModel) else payload
        return cls(
            mission_id=mission_id,
            run_id=run_id,
            event_type=event_type,
            payload=payload_dict,
            evidence_hash=evidence_hash,
            source=source,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
    def get_payload_model(self) -> Optional[type]:
        """Get the Pydantic model for this event's payload."""
        return EVENT_PAYLOAD_MODELS.get(self.event_type)
    def get_typed_payload(self) -> Optional[BaseModel]:
        """Parse payload into typed model."""
        model = self.get_payload_model()
        if model:
            return model.model_validate(self.payload)
        return None
# ============================================================
# EVENT CONSUMERS (Who listens to what)
# ============================================================
EVENT_CONSUMERS: Dict[EventType, List[str]] = {
    # Mission
    EventType.MISSION_STARTED: ["Dashboard", "EventStore", "Metrics"],
    EventType.MISSION_COMPLETED: ["Dashboard", "EventStore", "Metrics", "Notification"],
    EventType.MISSION_STATE_CHANGED: ["Dashboard", "EventStore", "Orchestrator"],
    # Run
    EventType.RUN_STARTED: ["EventStore", "Metrics"],
    EventType.RUN_COMPLETED: ["EventStore", "Metrics"],
    # Plan/Section
    EventType.PLAN_CREATED: ["Dashboard", "EventStore"],
    EventType.PLAN_REVISED: ["Dashboard", "EventStore"],
    EventType.PLAN_APPROVED: ["Dashboard", "EventStore", "HumanGate"],
    EventType.SECTION_START: ["Dashboard", "EventStore", "SandboxManager"],
    EventType.SECTION_COMPLETE: ["Dashboard", "EventStore", "Verifier"],
    # LLM
    EventType.LLM_REQUESTED: ["Dashboard", "EventStore", "Metrics", "TokenBudget"],
    EventType.LLM_COMPLETED: ["Dashboard", "EventStore", "Metrics", "TokenBudget"],
    # Action
    EventType.ACTION_REQUESTED: ["Dashboard", "EventStore", "SandboxManager", "Verifier"],
    EventType.ACTION_VALIDATED: ["Dashboard", "EventStore", "SandboxManager", "Orchestrator"],
    # Agent
    EventType.AGENT_STARTED: ["Dashboard", "EventStore"],
    EventType.AGENT_COMPLETED: ["Dashboard", "EventStore", "Orchestrator"],
    EventType.AGENT_FAILED: ["Dashboard", "EventStore", "Orchestrator"],
    # Task
    EventType.TASK_CREATED: ["Dashboard", "EventStore", "Scheduler"],
    EventType.TASK_ASSIGNED: ["Dashboard", "EventStore", "AgentRuntime"],
    EventType.TASK_COMPLETED: ["Dashboard", "EventStore", "Orchestrator", "Verifier"],
    EventType.TASK_FAILED: ["Dashboard", "EventStore", "Orchestrator"],
    EventType.TASK_RETRY: ["Dashboard", "EventStore", "Orchestrator"],
    # Tool
    EventType.TOOL_STARTED: ["Dashboard", "EventStore", "SandboxManager"],
    EventType.TOOL_COMPLETED: ["Dashboard", "EventStore", "SandboxManager"],
    EventType.TOOL_FAILED: ["Dashboard", "EventStore", "SandboxManager", "Orchestrator"],
    # Artifacts & Evidence
    EventType.ARTIFACT_CREATED: ["Dashboard", "EventStore", "ArtifactStore"],
    EventType.ARTIFACT_RECONCILED: ["EventStore", "ArtifactStore"],
    EventType.EVIDENCE_RECORDED: ["EventStore", "Verifier", "Metrics"],
    # Verification
    EventType.VERIFICATION_COMPLETE: ["Dashboard", "EventStore", "Orchestrator", "Arbiter"],
    EventType.VERIFICATION_FAILED: ["Dashboard", "EventStore", "Orchestrator"],
    # Arbiter
    EventType.ARBITER_CALLED: ["Dashboard", "EventStore", "Orchestrator"],
    EventType.ARBITER_DECIDED: ["Dashboard", "EventStore", "Orchestrator", "HumanGate"],
    # Human
    EventType.HUMAN_REQUIRED: ["Dashboard", "HumanGate", "EventStore"],
    EventType.HUMAN_DECISION: ["Dashboard", "EventStore", "Orchestrator", "HumanGate"],
    # Grants
    EventType.GRANT_ISSUED: ["EventStore", "AccessAdmission"],
    EventType.GRANT_VALIDATED: ["EventStore", "AccessAdmission", "SandboxManager"],
    # Sandbox
    EventType.SANDBOX_STARTED: ["EventStore", "SandboxManager"],
    EventType.SANDBOX_COMPLETED: ["Dashboard", "EventStore", "Verifier"],
    # Checkpoints
    EventType.CHECKPOINT_CREATED: ["EventStore", "CheckpointManager"],
    # Hard stops
    EventType.HARD_STOP_FIRED: ["Dashboard", "EventStore", "Orchestrator", "HumanGate"],
    # Metrics
    EventType.TOKEN_USAGE: ["Metrics", "TokenBudget", "Dashboard"],
    EventType.BUDGET_WARNING: ["Dashboard", "Metrics", "Orchestrator"],
    EventType.BUDGET_EXCEEDED: ["Orchestrator", "Dashboard", "HumanGate"],
    # System
    EventType.SYSTEM_ERROR: ["Dashboard", "EventStore", "Alerting"],
    EventType.SYSTEM_WARNING: ["Dashboard", "EventStore", "Metrics"],
}
# ============================================================
# EVENT BUS INTERFACE
# ============================================================
class EventBusInterface:
    """
    Abstract interface for event bus implementation.
    """
    async def publish(self, event: FactoryEvent) -> None:
        """Publish event to all subscribers."""
        raise NotImplementedError
    def subscribe(self, event_type: EventType, handler: callable) -> None:
        """Subscribe to event type."""
        raise NotImplementedError
    def unsubscribe(self, event_type: EventType, handler: callable) -> None:
        """Unsubscribe from event type."""
        raise NotImplementedError
    async def get_history(
        self,
        mission_id: Optional[str] = None,
        event_types: Optional[List[EventType]] = None,
        limit: int = 1000,
    ) -> List[FactoryEvent]:
        """Get event history with filters."""
        raise NotImplementedError
# ============================================================
# EVENT STORE (Persistence)
# ============================================================
class EventStoreInterface:
    """
    Interface for persistent event storage.
    """
    async def append(self, event: FactoryEvent) -> None:
        """Append event to store."""
        raise NotImplementedError
    async def get_events(
        self,
        mission_id: Optional[str] = None,
        run_id: Optional[str] = None,
        event_types: Optional[List[EventType]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[FactoryEvent]:
        """Query events with filters."""
        raise NotImplementedError
    async def get_mission_timeline(self, mission_id: str) -> List[FactoryEvent]:
        """Get complete event timeline for mission replay."""
        raise NotImplementedError
    async def get_correlation_chain(self, correlation_id: str) -> List[FactoryEvent]:
        """Get all events in a correlation chain."""
        raise NotImplementedError
# ============================================================
# EVENT CATALOG (Metadata for documentation)
# ============================================================
@dataclass
class EventCatalogEntry:
    """Documentation entry for an event type."""
    event_type: EventType
    description: str
    payload_model: str
    emitted_by: List[str]
    consumed_by: List[str]
    triggers: List[str]
    is_state_transition: bool = False
    is_terminal: bool = False
EVENT_CATALOG: Dict[EventType, EventCatalogEntry] = {
    EventType.MISSION_STARTED: EventCatalogEntry(
        event_type=EventType.MISSION_STARTED,
        description="New mission created from user request",
        payload_model="MissionStartedEvent",
        emitted_by=["Orchestrator.intake()"],
        consumed_by=["Dashboard", "EventStore", "Metrics"],
        triggers=["Agent assignment", "Plan creation"],
    ),
    EventType.MISSION_COMPLETED: EventCatalogEntry(
        event_type=EventType.MISSION_COMPLETED,
        description="Mission reached terminal state (VERIFIED/FAILED/ESCALATED)",
        payload_model="MissionCompletedEvent",
        emitted_by=["Orchestrator.complete()"],
        consumed_by=["Dashboard", "EventStore", "Metrics", "Notification"],
        triggers=["Report generation", "Cleanup"],
        is_terminal=True,
    ),
    EventType.MISSION_STATE_CHANGED: EventCatalogEntry(
        event_type=EventType.MISSION_STATE_CHANGED,
        description="Mission state transition occurred",
        payload_model="MissionStateChangedEvent",
        emitted_by=["MissionStateMachine.transition()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator"],
        triggers=["Next agent/task assignment"],
        is_state_transition=True,
    ),
    EventType.SECTION_START: EventCatalogEntry(
        event_type=EventType.SECTION_START,
        description="Engineering order section execution started",
        payload_model="SectionStartEvent",
        emitted_by=["TaskEngine.execute_section()"],
        consumed_by=["Dashboard", "EventStore", "SandboxManager"],
        triggers=["Grant validation", "Sandbox execution"],
    ),
    EventType.SECTION_COMPLETE: EventCatalogEntry(
        event_type=EventType.SECTION_COMPLETE,
        description="Section execution completed with artifacts",
        payload_model="SectionCompleteEvent",
        emitted_by=["ExecutionEngine.execute()"],
        consumed_by=["Dashboard", "EventStore", "Verifier"],
        triggers=["Verification", "Next section"],
    ),
    EventType.AGENT_STARTED: EventCatalogEntry(
        event_type=EventType.AGENT_STARTED,
        description="Agent began task execution",
        payload_model="AgentStartedEvent",
        emitted_by=["AgentRuntime.execute()"],
        consumed_by=["Dashboard", "EventStore"],
        triggers=["Tool calls", "LLM calls"],
    ),
    EventType.AGENT_COMPLETED: EventCatalogEntry(
        event_type=EventType.AGENT_COMPLETED,
        description="Agent finished task with result",
        payload_model="AgentCompletedEvent",
        emitted_by=["AgentRuntime.execute()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator"],
        triggers=["Next agent", "Verification"],
    ),
    EventType.LLM_REQUESTED: EventCatalogEntry(
        event_type=EventType.LLM_REQUESTED,
        description="Agent requested LLM structured output",
        payload_model="LLMRequestedEvent",
        emitted_by=["Agent.execute()"],
        consumed_by=["Dashboard", "EventStore", "Metrics", "TokenBudget"],
        triggers=["LLM API call"],
    ),
    EventType.LLM_COMPLETED: EventCatalogEntry(
        event_type=EventType.LLM_COMPLETED,
        description="LLM returned structured response",
        payload_model="LLMCompletedEvent",
        emitted_by=["Agent.execute()"],
        consumed_by=["Dashboard", "EventStore", "Metrics", "TokenBudget"],
        triggers=["Action decision", "Budget update"],
    ),
    EventType.ACTION_REQUESTED: EventCatalogEntry(
        event_type=EventType.ACTION_REQUESTED,
        description="Agent requested action execution after LLM decision",
        payload_model="ActionRequestedEvent",
        emitted_by=["Agent.execute()"],
        consumed_by=["Dashboard", "EventStore", "SandboxManager", "Verifier"],
        triggers=["Action validation", "Permission check"],
    ),
    EventType.ACTION_VALIDATED: EventCatalogEntry(
        event_type=EventType.ACTION_VALIDATED,
        description="Action validated (capability/permission check passed)",
        payload_model="ActionValidatedEvent",
        emitted_by=["Agent.execute()"],
        consumed_by=["Dashboard", "EventStore", "SandboxManager", "Orchestrator"],
        triggers=["Tool execution"],
    ),
    EventType.TASK_CREATED: EventCatalogEntry(
        event_type=EventType.TASK_CREATED,
        description="New task created in task graph",
        payload_model="TaskCreatedEvent",
        emitted_by=["Planner.decompose()", "TaskEngine.build_graph()"],
        consumed_by=["Dashboard", "EventStore", "Scheduler"],
        triggers=["Task scheduling", "Agent assignment"],
    ),
    EventType.TASK_COMPLETED: EventCatalogEntry(
        event_type=EventType.TASK_COMPLETED,
        description="Task completed successfully",
        payload_model="TaskCompletedEvent",
        emitted_by=["Orchestrator.on_task_complete()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator", "Verifier"],
        triggers=["Verification", "Dependent task ready"],
    ),
    EventType.VERIFICATION_COMPLETE: EventCatalogEntry(
        event_type=EventType.VERIFICATION_COMPLETE,
        description="Verifier completed evidence check",
        payload_model="VerificationCompleteEvent",
        emitted_by=["Verifier.verify()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator", "Arbiter"],
        triggers=["EVIDENCED → VERIFIED", "NOT_EVIDENCED → ARBITER"],
    ),
    EventType.ARBITER_DECIDED: EventCatalogEntry(
        event_type=EventType.ARBITER_DECIDED,
        description="Arbiter made decision on conflict",
        payload_model="ArbiterDecidedEvent",
        emitted_by=["Arbiter.decide()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator", "HumanGate"],
        triggers=["Retry", "Escalate", "Terminate"],
    ),
    EventType.HUMAN_REQUIRED: EventCatalogEntry(
        event_type=EventType.HUMAN_REQUIRED,
        description="System requires human decision",
        payload_model="HumanRequiredEvent",
        emitted_by=["HumanGate.request_approval()"],
        consumed_by=["Dashboard", "HumanGate", "EventStore"],
        triggers=["Human decision via Dashboard/CLI"],
    ),
    EventType.HUMAN_DECISION: EventCatalogEntry(
        event_type=EventType.HUMAN_DECISION,
        description="Human provided decision",
        payload_model="HumanDecisionEvent",
        emitted_by=["Dashboard.approve()", "CLI.approve()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator", "HumanGate"],
        triggers=["Mission continues", "Mission stops"],
    ),
    EventType.GRANT_ISSUED: EventCatalogEntry(
        event_type=EventType.GRANT_ISSUED,
        description="New grant issued by owner",
        payload_model="GrantIssuedEvent",
        emitted_by=["GrantorService.issue()"],
        consumed_by=["EventStore", "AccessAdmission"],
        triggers=["Grant validation at admission"],
    ),
    EventType.GRANT_VALIDATED: EventCatalogEntry(
        event_type=EventType.GRANT_VALIDATED,
        description="Grant validated for admission/execution",
        payload_model="GrantValidatedEvent",
        emitted_by=["AccessAdmission.validate()"],
        consumed_by=["EventStore", "AccessAdmission", "SandboxManager"],
        triggers=["Sandbox execution allowed/denied"],
    ),
    EventType.SANDBOX_STARTED: EventCatalogEntry(
        event_type=EventType.SANDBOX_STARTED,
        description="Sandbox execution started",
        payload_model="SandboxStartedEvent",
        emitted_by=["SandboxManager.execute()"],
        consumed_by=["EventStore", "SandboxManager"],
        triggers=["Process execution", "Resource monitoring"],
    ),
    EventType.SANDBOX_COMPLETED: EventCatalogEntry(
        event_type=EventType.SANDBOX_COMPLETED,
        description="Sandbox execution completed",
        payload_model="SandboxCompletedEvent",
        emitted_by=["SandboxManager.execute()"],
        consumed_by=["Dashboard", "EventStore", "Verifier"],
        triggers=["Artifact collection", "Verification"],
    ),
    EventType.HARD_STOP_FIRED: EventCatalogEntry(
        event_type=EventType.HARD_STOP_FIRED,
        description="EOE engine fired hard stop (fail-closed)",
        payload_model="HardStopFiredEvent",
        emitted_by=["EoeEngine.run_order()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator", "HumanGate"],
        triggers=["Partial report", "Mission abort"],
        is_terminal=True,
    ),
    EventType.TOKEN_USAGE: EventCatalogEntry(
        event_type=EventType.TOKEN_USAGE,
        description="LLM token usage recorded",
        payload_model="TokenUsageEvent",
        emitted_by=["LLMGateway.structured_chat()", "TokenBudget.consume()"],
        consumed_by=["Metrics", "TokenBudget", "Dashboard"],
        triggers=["Budget check", "Cost alert"],
    ),
    EventType.BUDGET_WARNING: EventCatalogEntry(
        event_type=EventType.BUDGET_WARNING,
        description="Token budget approaching limit",
        payload_model="BudgetWarningEvent",
        emitted_by=["TokenBudget.check()"],
        consumed_by=["Dashboard", "Metrics", "Orchestrator"],
        triggers=["Throttle", "Human notification"],
    ),
    EventType.BUDGET_EXCEEDED: EventCatalogEntry(
        event_type=EventType.BUDGET_EXCEEDED,
        description="Token budget exceeded - fail closed",
        payload_model="BudgetWarningEvent",
        emitted_by=["TokenBudget.consume()"],
        consumed_by=["Orchestrator", "Dashboard", "HumanGate"],
        triggers=["Mission abort", "Human notification"],
        is_terminal=True,
    ),
    # E11: Human Mission Control events
    EventType.MISSION_PAUSE_REQUESTED: EventCatalogEntry(
        event_type=EventType.MISSION_PAUSE_REQUESTED,
        description="Human requested mission pause",
        payload_model="MissionPauseRequestedEvent",
        emitted_by=["ControlPlane.pause_mission()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator"],
        triggers=["Checkpoint creation", "Execution pause"],
    ),
    EventType.MISSION_PAUSED: EventCatalogEntry(
        event_type=EventType.MISSION_PAUSED,
        description="Mission paused at safe checkpoint",
        payload_model="MissionPausedEvent",
        emitted_by=["ExecutionEngine.on_pause_complete()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator"],
        triggers=["Resume available", "Human notification"],
    ),
    EventType.MISSION_RESUME_REQUESTED: EventCatalogEntry(
        event_type=EventType.MISSION_RESUME_REQUESTED,
        description="Human requested mission resume",
        payload_model="MissionResumeRequestedEvent",
        emitted_by=["ControlPlane.resume_mission()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator"],
        triggers=["Execution resume"],
    ),
    EventType.MISSION_RESUMED: EventCatalogEntry(
        event_type=EventType.MISSION_RESUMED,
        description="Mission resumed from paused state",
        payload_model="MissionResumedEvent",
        emitted_by=["ExecutionEngine.on_resume_complete()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator"],
        triggers=["Task execution continues"],
    ),
    EventType.MISSION_CANCEL_REQUESTED: EventCatalogEntry(
        event_type=EventType.MISSION_CANCEL_REQUESTED,
        description="Human requested mission cancellation",
        payload_model="MissionCancelRequestedEvent",
        emitted_by=["ControlPlane.cancel_mission()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator"],
        triggers=["Execution cancellation", "Resource cleanup"],
    ),
    EventType.MISSION_CANCELLED: EventCatalogEntry(
        event_type=EventType.MISSION_CANCELLED,
        description="Mission cancelled and resources released",
        payload_model="MissionCancelledEvent",
        emitted_by=["ExecutionEngine.on_cancel_complete()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator"],
        triggers=["Resource release", "Final reporting"],
        is_terminal=True,
    ),
    EventType.HUMAN_GATE_CREATED: EventCatalogEntry(
        event_type=EventType.HUMAN_GATE_CREATED,
        description="Human gate created requiring decision",
        payload_model="HumanGateCreatedEvent",
        emitted_by=["HumanGate.create()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator", "HumanGate"],
        triggers=["Human decision required"],
    ),
    EventType.HUMAN_DECISION_RECORDED: EventCatalogEntry(
        event_type=EventType.HUMAN_DECISION_RECORDED,
        description="Human decision recorded for gate",
        payload_model="HumanDecisionRecordedEvent",
        emitted_by=["HumanGate.decide()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator", "HumanGate"],
        triggers=["Mission continues or cancels"],
    ),
    EventType.HUMAN_DECISION_REJECTED: EventCatalogEntry(
        event_type=EventType.HUMAN_DECISION_REJECTED,
        description="Duplicate human decision rejected for gate",
        payload_model="HumanDecisionRejectedEvent",
        emitted_by=["HumanGate.decide() - duplicate attempt"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator", "HumanGate"],
        triggers=["Audit trail", "Governance violation recorded"],
    ),
    # E13: Replan events
    EventType.REPLAN_REQUESTED: EventCatalogEntry(
        event_type=EventType.REPLAN_REQUESTED,
        description="Replan requested due to task failure or new requirements",
        payload_model="ReplanRequestedEvent",
        emitted_by=["ExecutionEngine.request_replan()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator"],
        triggers=["Graph mutation"],
    ),
    EventType.REPLAN_APPLIED: EventCatalogEntry(
        event_type=EventType.REPLAN_APPLIED,
        description="Replan changes applied to task graph",
        payload_model="ReplanAppliedEvent",
        emitted_by=["ExecutionEngine.apply_replan()"],
        consumed_by=["Dashboard", "EventStore", "Orchestrator"],
        triggers=["Graph version increment", "New task scheduling"],
    ),
}
# ============================================================
# UTILITY FUNCTIONS
# ============================================================
def get_event_payload_model(event_type: EventType) -> Optional[type]:
    """Get the Pydantic model for an event type."""
    return EVENT_PAYLOAD_MODELS.get(event_type)
def get_event_consumers(event_type: EventType) -> List[str]:
    """Get list of consumers for an event type."""
    return EVENT_CONSUMERS.get(event_type, [])
def get_event_catalog_entry(event_type: EventType) -> Optional[EventCatalogEntry]:
    """Get catalog documentation for event type."""
    return EVENT_CATALOG.get(event_type)
def validate_event_payload(event_type: EventType, payload: Dict[str, Any]) -> bool:
    """Validate event payload against its model."""
    model = get_event_payload_model(event_type)
    if model:
        try:
            model.model_validate(payload)
            return True
        except Exception:
            return False
    return True  # No model = no validation
def list_all_events() -> List[EventType]:
    """List all defined event types."""
    return list(EventType)
# ============================================================
# EXPORTS
# ============================================================
__all__ = [
    "EventType",
    "EventMetadata",
    "MissionStartedEvent",
    "MissionCompletedEvent",
    "MissionStateChangedEvent",
    "RunStartedEvent",
    "PlanCreatedEvent",
    "PlanRevisedEvent",
    "SectionStartEvent",
    "SectionCompleteEvent",
    "AgentStartedEvent",
    "AgentCompletedEvent",
    "TaskCreatedEvent",
    "TaskAssignedEvent",
    "TaskCompletedEvent",
    "TaskFailedEvent",
    "ToolStartedEvent",
    "ToolCompletedEvent",
    "ToolFailedEvent",
    "ArtifactCreatedEvent",
    "EvidenceRecordedEvent",
    "VerificationCompleteEvent",
    "LLMRequestedEvent",
    "LLMCompletedEvent",
    "ActionRequestedEvent",
    "ActionValidatedEvent",
    "ArbiterCalledEvent",
    "ArbiterDecidedEvent",
    "HumanRequiredEvent",
    "HumanDecisionEvent",
    "ReplanRequestedEvent",
    "ReplanAppliedEvent",
    "GrantIssuedEvent",
    "GrantValidatedEvent",
    "SandboxStartedEvent",
    "SandboxCompletedEvent",
    "CheckpointCreatedEvent",
    "HardStopFiredEvent",
    "TokenUsageEvent",
    "BudgetWarningEvent",
    "SystemErrorEvent",
    "VerificationStartedEvent",
    "EVENT_PAYLOAD_MODELS",
    "FactoryEvent",
    "EventBusInterface",
    "EventStoreInterface",
    "EventCatalogEntry",
    "EVENT_CATALOG",
    "EVENT_CONSUMERS",
    "get_event_payload_model",
    "get_event_consumers",
    "get_event_catalog_entry",
    "validate_event_payload",
    "list_all_events",
]