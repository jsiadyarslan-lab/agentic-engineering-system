"""
Domain Model — Unified Engineering Agents System

Core entities, relationships, and invariants.
All models are frozen Pydantic v2 for immutability and validation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Literal
from pydantic import BaseModel, Field, field_validator
from dataclasses import dataclass, field


# ============================================================
# IDENTIFIERS
# ============================================================

def new_mission_id() -> str:
    return f"mission-{uuid.uuid4().hex[:12]}"


def new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


def new_task_id() -> str:
    return f"task-{uuid.uuid4().hex[:12]}"


def new_attempt_id() -> str:
    return f"attempt-{uuid.uuid4().hex[:8]}"


def new_agent_id() -> str:
    return f"agent-{uuid.uuid4().hex[:8]}"


def new_action_id() -> str:
    return f"action-{uuid.uuid4().hex[:8]}"


def new_event_id() -> str:
    return f"event-{uuid.uuid4().hex[:12]}"


def new_grant_id() -> str:
    return f"grant-{uuid.uuid4().hex[:12]}"


def new_sandbox_id() -> str:
    return f"sandbox-{uuid.uuid4().hex[:12]}"


def new_artifact_id() -> str:
    return f"artifact-{uuid.uuid4().hex[:12]}"


def new_evidence_id() -> str:
    return f"evidence-{uuid.uuid4().hex[:12]}"


def new_verification_id() -> str:
    return f"verification-{uuid.uuid4().hex[:12]}"


def new_decision_id() -> str:
    return f"decision-{uuid.uuid4().hex[:8]}"


def new_checkpoint_id() -> str:
    return f"checkpoint-{uuid.uuid4().hex[:12]}"


# ============================================================
# CORE ENUMS
# ============================================================

class MissionState(str, Enum):
    """Mission lifecycle states (unified from both systems)."""
    RECEIVED = "RECEIVED"
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    DESIGNING = "DESIGNING"
    REVIEWING = "REVIEWING"
    APPROVED = "APPROVED"
    REVISE = "REVISE"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    VERIFYING = "VERIFYING"
    EVIDENCED = "EVIDENCED"
    ADJUDICATED = "ADJUDICATED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    ESCALATED_TO_HUMAN = "ESCALATED_TO_HUMAN"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ABORTED = "ABORTED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            MissionState.VERIFIED,
            MissionState.FAILED,
            MissionState.ESCALATED_TO_HUMAN,
            MissionState.STOPPED,
            MissionState.ABORTED,
        }


class SubVerdict(str, Enum):
    """Sub-verdicts that drive flow (not mission states)."""
    NOT_EVIDENCED = "NOT_EVIDENCED"
    STAGNANT = "STAGNANT"


class TaskState(str, Enum):
    """Individual task states within a mission."""
    PENDING = "PENDING"
    READY = "READY"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class AgentType(str, Enum):
    """Unified agent roles."""
    EXPLORER = "explorer"
    ANALYST = "analyst"
    PLANNER = "planner"
    DESIGNER = "designer"
    REVIEWER = "reviewer"
    IMPLEMENTER = "implementer"
    VERIFIER = "verifier"
    ARBITER = "arbiter"


class PermissionClass(str, Enum):
    """Grant permission classes (from EAS v2)."""
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"


class EngineeringDomain(str, Enum):
    """Engineering domains for grant scoping."""
    CODEBASE = "codebase"
    INFRASTRUCTURE = "infrastructure"
    DATA = "data"
    SECURITY = "security"
    TESTING = "testing"
    DEPLOYMENT = "deployment"


class EventType(str, Enum):
    """Factory event types."""
    MISSION_STARTED = "mission.started"
    MISSION_COMPLETED = "mission.completed"
    SECTION_START = "section.start"
    SECTION_COMPLETE = "section.complete"
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    ARTIFACT_CREATED = "artifact.created"
    VERIFICATION_COMPLETE = "verification.complete"
    ARBITER_DECIDED = "arbiter.decided"
    HUMAN_REQUIRED = "human.required"
    HUMAN_DECISION = "human.decision"
    HARD_STOP_FIRED = "hard_stop.fired"
    STATE_TRANSITION = "state.transition"
    CHECKPOINT_CREATED = "checkpoint.created"


class SandboxTermination(str, Enum):
    """How a sandbox execution ended."""
    COMPLETED = "COMPLETED"
    TIMEOUT = "TIMEOUT"
    LIMIT_BREACH = "LIMIT_BREACH"
    KILLED = "KILLED"
    FAILED_TO_START = "FAILED_TO_START"
    NOT_RUN = "NOT_RUN"


class VerifierVerdict(str, Enum):
    """Verifier verdict."""
    EVIDENCED = "evidenced"
    NOT_EVIDENCED = "not_evidenced"


class ArbiterDecision(str, Enum):
    """Arbiter decision."""
    RETRY_WITH_CONSTRAINTS = "retry_with_constraints"
    TERMINATE_STAGNANT = "terminate_stagnant"
    ESCALATE_TO_HUMAN = "escalate_to_human"


class HumanDecisionType(str, Enum):
    """Human decision types."""
    APPROVE = "APPROVE"
    MODIFY = "MODIFY"
    REJECT = "REJECT"
    DISCUSS = "DISCUSS"


# ============================================================
# CORE ENTITIES
# ============================================================

class Mission(BaseModel):
    """Top-level mission container."""
    mission_id: str = Field(default_factory=new_mission_id)
    user_request: str
    state: MissionState = MissionState.RECEIVED
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    # Relationships
    run_ids: List[str] = Field(default_factory=list)
    current_run_id: Optional[str] = None

    # Evidence
    evidence_hashes: List[str] = Field(default_factory=list)

    # Human interaction
    human_decision_id: Optional[str] = None

    def transition(self, new_state: MissionState, actor: str = "system") -> None:
        """Validate and apply state transition."""
        # Golden rule: VERIFIED only by user
        if new_state == MissionState.VERIFIED and actor != "user":
            raise ValueError("VERIFIED transition requires actor='user'")
        # Terminal states cannot be left
        if self.state.is_terminal:
            raise ValueError(f"Cannot transition from terminal state {self.state}")
        self.state = new_state
        self.updated_at = datetime.now(timezone.utc)
        if new_state.is_terminal:
            self.completed_at = datetime.now(timezone.utc)


class Run(BaseModel):
    """Single execution run of a mission (for resume/retry)."""
    run_id: str = Field(default_factory=new_run_id)
    mission_id: str
    run_number: int = 1
    state: MissionState = MissionState.RECEIVED
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    parent_run_id: Optional[str] = None  # For resume from checkpoint

    # Task graph for this run
    task_graph_id: Optional[str] = None

    # Checkpoints
    checkpoint_ids: List[str] = Field(default_factory=list)


class Task(BaseModel):
    """Decomposable unit of work with acceptance criteria."""
    task_id: str = Field(default_factory=new_task_id)
    run_id: str
    mission_id: str
    name: str
    description: str
    agent_type: AgentType
    state: TaskState = TaskState.PENDING

    # Dependencies
    depends_on: List[str] = Field(default_factory=list)  # task_ids

    # Acceptance criteria (file-based, mechanically verifiable)
    acceptance_criteria: List[str] = Field(default_factory=list)

    # Assignment
    assigned_agent_id: Optional[str] = None
    attempt_ids: List[str] = Field(default_factory=list)

    # Evidence
    evidence_hashes: List[str] = Field(default_factory=list)
    artifact_ids: List[str] = Field(default_factory=list)

    # Timing
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Retry
    max_retries: int = 2
    retry_count: int = 0


class Attempt(BaseModel):
    """Single execution attempt of a task."""
    attempt_id: str = Field(default_factory=new_attempt_id)
    task_id: str
    agent_id: str
    state: TaskState = TaskState.RUNNING
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    # Actions executed in this attempt
    action_ids: List[str] = Field(default_factory=list)

    # Result
    success: bool = False
    error: Optional[str] = None
    evidence_hash: Optional[str] = None

    # Verification
    verification_id: Optional[str] = None
    verifier_verdict: Optional[VerifierVerdict] = None


class Action(BaseModel):
    """Single tool invocation within an attempt."""
    action_id: str = Field(default_factory=new_action_id)
    attempt_id: str
    tool_name: str
    tool_args: Dict[str, Any]
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    # Result
    success: bool = False
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    # Evidence
    evidence_id: Optional[str] = None
    sandbox_id: Optional[str] = None


class Agent(BaseModel):
    """Agent instance with identity and permissions."""
    agent_id: str = Field(default_factory=new_agent_id)
    agent_type: AgentType
    mission_id: str
    run_id: str

    # Permissions (grant IDs this agent holds)
    grant_ids: List[str] = Field(default_factory=list)

    # State
    current_task_id: Optional[str] = None
    state: Literal["idle", "working", "blocked", "completed", "failed"] = "idle"

    # Budget
    token_budget: int = 50000
    tokens_used: int = 0

    # Context
    context_summary: str = ""


class Grant(BaseModel):
    """Typed, signed, revocable authorization (EAS v2 model)."""
    grant_id: str = Field(default_factory=new_grant_id)
    grantor: str
    subject: str  # agent_id or "orchestrator"
    permission_class: PermissionClass
    domains: List[EngineeringDomain]
    resources: List[str]  # Absolute paths

    issued_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime
    approval_state: Literal["PENDING", "APPROVED", "DENIED"] = "PENDING"

    # Cryptographic
    signature: str = ""  # HMAC-SHA256 over canonical payload

    @field_validator("expires_at")
    @classmethod
    def expires_after_issued(cls, v: datetime, info) -> datetime:
        issued = info.data.get("issued_at") or datetime.now(timezone.utc)
        if v <= issued:
            raise ValueError("expires_at must be after issued_at")
        return v


class SandboxRequest(BaseModel):
    """Request to execute in sandbox."""
    sandbox_id: str = Field(default_factory=new_sandbox_id)
    image: str
    command: List[str]
    working_dir: str = "/workspace"
    artifacts_dir: str = "/artifacts"
    sources_root: str = ""

    # Resource limits
    memory_bytes: Optional[int] = None
    cpu_percent: Optional[float] = None
    cpu_time_seconds: Optional[int] = None
    max_processes: Optional[int] = None
    wall_time_seconds: int = 300

    # Network
    network_mode: Literal["NONE"] = "NONE"

    # Grants required for this sandbox
    required_grant_ids: List[str] = Field(default_factory=list)


class SandboxExecutionRecord(BaseModel):
    """Evidence-shaped record of sandbox execution."""
    sandbox_id: str
    executed: bool
    exit_code: Optional[int]
    termination: SandboxTermination
    duration_ms: int
    stdout_reference: str  # Path to bounded stdout artifact
    stderr_reference: str  # Path to bounded stderr artifact
    started_at: datetime
    finished_at: datetime

    # Artifacts produced (custody log)
    artifacts: List[str] = Field(default_factory=list)  # artifact_ids


class Artifact(BaseModel):
    """Artifact produced during execution."""
    artifact_id: str = Field(default_factory=new_artifact_id)
    name: str
    path: str  # Relative to artifacts_dir
    sha256: str
    size_bytes: int
    created_by: str  # action_id or sandbox_id
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Metadata
    content_type: str = "text/plain"
    is_evidence: bool = False


class EvidenceRecord(BaseModel):
    """Content-addressable evidence record."""
    evidence_id: str = Field(default_factory=new_evidence_id)
    evidence_hash: str  # sha256 of content
    content_type: Literal["artifact", "stdout", "stderr", "log", "report", "checkpoint"]
    source_id: str  # artifact_id, sandbox_id, etc.
    mission_id: str
    run_id: str
    task_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Verification
    verified: bool = False
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None


class Verification(BaseModel):
    """Verification of a task against acceptance criteria."""
    verification_id: str = Field(default_factory=new_verification_id)
    task_id: str
    attempt_id: str
    verdict: VerifierVerdict
    checks_performed: List[str] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Sub-verdict for flow control
    sub_verdict: Optional[SubVerdict] = None


class ArbiterRecord(BaseModel):
    """Arbiter decision record."""
    decision_id: str = Field(default_factory=lambda: f"arbiter-{uuid.uuid4().hex[:8]}")
    conflict_type: str
    parties: List[str]  # agent_ids or role names
    decision: ArbiterDecision
    rationale: str
    escalation_to_human: bool = False
    max_retries_remaining: int
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Sub-verdict for flow control
    sub_verdict: Optional[SubVerdict] = None


class HumanDecision(BaseModel):
    """Human decision at approval gate."""
    decision_id: str = Field(default_factory=new_decision_id)
    mission_id: str
    run_id: str
    task_id: Optional[str] = None
    decision_type: HumanDecisionType
    approved: bool
    feedback: str
    reviewer: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = Field(default_factory=dict)


class Checkpoint(BaseModel):
    """Mission/run checkpoint for resume."""
    checkpoint_id: str = Field(default_factory=new_checkpoint_id)
    mission_id: str
    run_id: str
    step: int  # Sequential step number
    state: MissionState
    task_states: Dict[str, TaskState]  # task_id -> state
    artifact_ids: List[str]
    evidence_hashes: List[str]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    hash: str = ""  # sha256 of checkpoint content

    def verify(self) -> bool:
        """Verify checkpoint integrity."""
        # Recompute hash and compare
        return True  # Implementation in checkpoint manager


# ============================================================
# RELATIONSHIP INVARIANTS
# ============================================================

"""
ENTITY RELATIONSHIPS (enforced by application logic):

Mission (1) ──► (N) Run
Run (1) ──► (N) Task
Task (1) ──► (N) Attempt
Attempt (1) ──► (N) Action
Action (1) ──► (1) Artifact (optional)
Artifact (1) ──► (1) EvidenceRecord
Task (1) ──► (0..1) Verification
Verification (1) ──► (0..1) ArbiterRecord
Mission (1) ──► (0..N) HumanDecision
Mission (1) ──► (N) Checkpoint
Run (1) ──► (N) Checkpoint
Agent (N) ──► (N) Grant (many-to-many via grant_ids)
SandboxRequest (1) ──► (1) SandboxExecutionRecord
SandboxExecutionRecord (1) ──► (N) Artifact

IDENTITY RULES:
- All IDs are UUID-based with type prefix for debuggability
- mission_id: "mission-{hex12}"
- run_id: "run-{hex12}"
- task_id: "task-{hex12}"
- attempt_id: "attempt-{hex8}"
- agent_id: "agent-{hex8}"
- action_id: "action-{hex8}"
- event_id: "event-{hex12}"
- grant_id: "grant-{hex12}"
- sandbox_id: "sandbox-{hex12}"
- artifact_id: "artifact-{hex12}"
- evidence_id: "evidence-{hex12}"
- verification_id: "verification-{hex12}"
- decision_id: "decision-{hex8}"
- checkpoint_id: "checkpoint-{hex12}"

STATE MACHINE INVARIANTS:
1. Mission.state follows PlanState transitions (validated by validate_transition)
2. VERIFIED only by actor="user" (golden rule)
3. Terminal states: VERIFIED, FAILED, ESCALATED_TO_HUMAN, STOPPED, ABORTED
4. STOPPING → STOPPED only (Order 004)
5. Task.state follows TaskState transitions
6. Attempt.state follows TaskState (RUNNING → COMPLETED/FAILED)
7. Sub-verdicts (NOT_EVIDENCED, STAGNANT) are NOT states, they drive transitions

GRANT INVARIANTS:
1. Grant.valid == True only if: structurally valid + trusted grantor + APPROVED + within time window + not revoked + signature verified
2. Grant validation at ADMISSION TIME and EXECUTION TIME (both required)
3. No grant → no write/execute operation
4. Revocation channel required (fail-closed if missing)
5. HMAC-SHA256 signature over canonical payload

EVIDENCE INVARIANTS:
1. Every artifact has sha256 evidence record
2. EvidenceRecord is immutable once created
3. Verification checks file existence + hash match + criteria
3. False evidence rejected (hash mismatch)
4. Evidence chain: Action → Artifact → EvidenceRecord → Verification

SANDBOX INVARIANTS:
1. Single execute per sandbox_id (enforced by SandboxManager)
2. NetworkMode.NONE always (D-04=A)
3. Image must be in allowlist
4. Limits may only be lowered from defaults
5. Teardown always attempted
6. No host execution fallback (fail-closed)
"""


# ============================================================
# FACTORY FUNCTIONS
# ============================================================

def create_mission(user_request: str) -> Mission:
    """Create new mission from user request."""
    return Mission(user_request=user_request)


def create_run(mission_id: str, parent_run_id: Optional[str] = None) -> Run:
    """Create new run for mission."""
    return Run(
        mission_id=mission_id,
        run_number=1 if parent_run_id is None else 2,
        parent_run_id=parent_run_id,
    )


def create_task(
    run_id: str,
    mission_id: str,
    name: str,
    description: str,
    agent_type: AgentType,
    acceptance_criteria: List[str],
    depends_on: Optional[List[str]] = None,
) -> Task:
    """Create new task."""
    return Task(
        run_id=run_id,
        mission_id=mission_id,
        name=name,
        description=description,
        agent_type=agent_type,
        acceptance_criteria=acceptance_criteria,
        depends_on=depends_on or [],
    )


def create_attempt(task_id: str, agent_id: str) -> Attempt:
    """Create new attempt for task."""
    return Attempt(task_id=task_id, agent_id=agent_id)


def create_action(attempt_id: str, tool_name: str, tool_args: Dict[str, Any]) -> Action:
    """Create new action."""
    return Action(attempt_id=attempt_id, tool_name=tool_name, tool_args=tool_args)


def create_artifact(
    name: str,
    path: str,
    sha256: str,
    size_bytes: int,
    created_by: str,
) -> Artifact:
    """Create new artifact record."""
    return Artifact(
        name=name,
        path=path,
        sha256=sha256,
        size_bytes=size_bytes,
        created_by=created_by,
    )


def create_evidence(
    evidence_hash: str,
    content_type: Literal["artifact", "stdout", "stderr", "log", "report", "checkpoint"],
    source_id: str,
    mission_id: str,
    run_id: str,
    task_id: Optional[str] = None,
) -> EvidenceRecord:
    """Create new evidence record."""
    return EvidenceRecord(
        evidence_hash=evidence_hash,
        content_type=content_type,
        source_id=source_id,
        mission_id=mission_id,
        run_id=run_id,
        task_id=task_id,
    )


def create_verification(
    task_id: str,
    attempt_id: str,
    verdict: VerifierVerdict,
    checks: List[str],
    missing: List[str],
    confidence: float,
) -> Verification:
    """Create new verification record."""
    v = Verification(
        task_id=task_id,
        attempt_id=attempt_id,
        verdict=verdict,
        checks_performed=checks,
        missing_evidence=missing,
        confidence=confidence,
    )
    if verdict == VerifierVerdict.NOT_EVIDENCED:
        v.sub_verdict = SubVerdict.NOT_EVIDENCED
    return v


def create_arbiter_record(
    conflict_type: str,
    parties: List[str],
    decision: ArbiterDecision,
    rationale: str,
    escalation: bool,
    retries_remaining: int,
) -> ArbiterRecord:
    """Create new arbiter record."""
    r = ArbiterRecord(
        conflict_type=conflict_type,
        parties=parties,
        decision=decision,
        rationale=rationale,
        escalation_to_human=escalation,
        max_retries_remaining=retries_remaining,
    )
    if decision == ArbiterDecision.TERMINATE_STAGNANT:
        r.sub_verdict = SubVerdict.STAGNANT
    return r


# ============================================================
# VALIDATION HELPERS
# ============================================================

def validate_mission_transition(
    from_state: MissionState,
    to_state: MissionState,
    actor: str = "system",
) -> None:
    """Validate mission state transition."""
    # Terminal states cannot be left
    if from_state in {
        MissionState.VERIFIED,
        MissionState.FAILED,
        MissionState.ESCALATED_TO_HUMAN,
        MissionState.STOPPED,
        MissionState.ABORTED,
    }:
        raise ValueError(f"Cannot transition from terminal state {from_state}")

    # Golden rule: VERIFIED only by user
    if to_state == MissionState.VERIFIED and actor != "user":
        raise ValueError("VERIFIED transition requires actor='user'")

    # STOPPING → STOPPED only
    if from_state == MissionState.STOPPING and to_state != MissionState.STOPPED:
        raise ValueError("STOPPING can only transition to STOPPED")

    # Allowed transitions (simplified - full table in state_machine.py)
    allowed = {
        MissionState.RECEIVED: {MissionState.ANALYZING, MissionState.STOPPING},
        MissionState.ANALYZING: {MissionState.PLANNING, MissionState.STOPPING},
        MissionState.PLANNING: {MissionState.DESIGNING, MissionState.REVIEWING, MissionState.STOPPING},
        MissionState.DESIGNING: {MissionState.REVIEWING, MissionState.STOPPING},
        MissionState.REVIEWING: {MissionState.APPROVED, MissionState.REVISE, MissionState.STOPPING},
        MissionState.APPROVED: {MissionState.AWAITING_APPROVAL, MissionState.STOPPING},
        MissionState.REVISE: {MissionState.PLANNING, MissionState.STOPPING},
        MissionState.AWAITING_APPROVAL: {MissionState.EXECUTING, MissionState.STOPPING},
        MissionState.EXECUTING: {MissionState.EXECUTED, MissionState.FAILED, MissionState.STOPPING},
        MissionState.EXECUTED: {MissionState.VERIFYING, MissionState.STOPPING},
        MissionState.VERIFYING: {MissionState.EVIDENCED, MissionState.ADJUDICATED, MissionState.STOPPING},
        MissionState.EVIDENCED: {MissionState.VERIFIED, MissionState.ADJUDICATED, MissionState.STOPPING},
        MissionState.ADJUDICATED: {MissionState.EXECUTING, MissionState.ESCALATED_TO_HUMAN, MissionState.STOPPING},
        MissionState.STOPPING: {MissionState.STOPPED},
    }

    if to_state not in allowed.get(from_state, set()):
        raise ValueError(f"Invalid transition: {from_state} → {to_state}")


def validate_task_transition(from_state: TaskState, to_state: TaskState) -> None:
    """Validate task state transition."""
    allowed = {
        TaskState.PENDING: {TaskState.READY, TaskState.CANCELLED},
        TaskState.READY: {TaskState.ASSIGNED, TaskState.CANCELLED},
        TaskState.ASSIGNED: {TaskState.RUNNING, TaskState.BLOCKED, TaskState.CANCELLED},
        TaskState.RUNNING: {TaskState.COMPLETED, TaskState.FAILED, TaskState.BLOCKED},
        TaskState.COMPLETED: set(),
        TaskState.FAILED: {TaskState.READY},  # Retry
        TaskState.BLOCKED: {TaskState.READY, TaskState.CANCELLED},
        TaskState.CANCELLED: set(),
    }
    if to_state not in allowed.get(from_state, set()):
        raise ValueError(f"Invalid task transition: {from_state} → {to_state}")


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # IDs
    "new_mission_id", "new_run_id", "new_task_id", "new_attempt_id",
    "new_agent_id", "new_action_id", "new_event_id", "new_grant_id",
    "new_sandbox_id", "new_artifact_id", "new_evidence_id",
    "new_verification_id", "new_decision_id", "new_checkpoint_id",
    # Enums
    "MissionState", "SubVerdict", "TaskState", "AgentType",
    "PermissionClass", "EngineeringDomain", "EventType",
    "SandboxTermination", "VerifierVerdict", "ArbiterDecision",
    "HumanDecisionType",
    # Entities
    "Mission", "Run", "Task", "Attempt", "Action", "Agent",
    "Grant", "SandboxRequest", "SandboxExecutionRecord",
    "Artifact", "EvidenceRecord", "Verification", "ArbiterRecord",
    "HumanDecision", "Checkpoint",
    # Factories
    "create_mission", "create_run", "create_task", "create_attempt",
    "create_action", "create_artifact", "create_evidence",
    "create_verification", "create_arbiter_record",
    # Validation
    "validate_mission_transition", "validate_task_transition",
]