"""
Agent Contract — Unified Engineering Agents System

Defines the formal contracts for all agent roles.
Each agent implements the AgentRole protocol and has specific
input/output contracts with acceptance criteria.

Based on: EAS v2 roles (Thinker, Reviewer, Implementer, Verifier, Arbiter)
         AgentFactory agents (Explorer, Thinker, Planner, Designer, Reviewer, Implementer, Verifier, Security)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Literal, Protocol, runtime_checkable
from pydantic import BaseModel, Field, field_validator
from dataclasses import dataclass, field

from src.unified.domain_model import (
    AgentType,
    TaskState,
    MissionState,
    SubVerdict,
    VerifierVerdict,
    ArbiterDecision,
    HumanDecisionType,
    Grant,
    SandboxExecutionRecord,
    Artifact,
    EvidenceRecord,
    Verification,
    ArbiterRecord,
    HumanDecision,
    Checkpoint,
)


# ============================================================
# BASE AGENT PROTOCOL
# ============================================================

@runtime_checkable
class AgentRole(Protocol):
    """
    Unified protocol for all agent roles.
    Both AgentFactory agents and EAS roles must implement this.
    """

    # Identity
    agent_type: AgentType
    agent_role: str
    required_grants: List[str]

    # Lifecycle hooks
    async def on_start(self, task: "AgentTask") -> None: ...
    async def on_complete(self, task: "AgentTask", result: "AgentResult") -> None: ...
    async def on_failed(self, task: "AgentTask", error: Exception) -> None: ...

    # Main execution
    async def execute(self, task: "AgentTask") -> "AgentResult": ...


# ============================================================
# COMMON BASE CONTRACTS
# ============================================================

class AgentTask(BaseModel):
    """Task assigned to an agent."""
    task_id: str
    run_id: str
    mission_id: str
    name: str
    description: str
    agent_type: AgentType
    acceptance_criteria: List[str] = Field(default_factory=list)
    depends_on: List[str] = Field(default_factory=list)  # task_ids

    # Context from previous agents
    context: Dict[str, Any] = Field(default_factory=dict)

    # Grants
    grant_ids: List[str] = Field(default_factory=list)

    # Budget
    token_budget: int = 50000

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    priority: int = 1


class AgentResult(BaseModel):
    """Result of agent execution."""
    task_id: str
    agent_type: AgentType
    success: bool
    output: Optional[Any] = None

    # Evidence
    evidence_hash: str = ""
    artifacts: List[str] = Field(default_factory=list)  # artifact_ids
    evidence_ids: List[str] = Field(default_factory=list)

    # Error
    error: Optional[str] = None
    error_type: Optional[str] = None

    # Timing
    duration_ms: int = 0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime = Field(default_factory=datetime.utcnow)

    # Verification
    verification_id: Optional[str] = None
    verifier_verdict: Optional[VerifierVerdict] = None

    # Retry
    retry_count: int = 0
    max_retries: int = 2


# ============================================================
# EXPLORER CONTRACT
# ============================================================

class ExplorerInput(BaseModel):
    """Input for Explorer agent."""
    user_request: str
    codebase_path: str = "."
    focus_areas: List[str] = Field(default_factory=list)


class ExplorationReport(BaseModel):
    """Explorer output - structured codebase analysis."""
    project_overview: Dict[str, Any]
    dependencies: Dict[str, Any]
    similar_implementations: List[Dict[str, Any]]
    testing_conventions: Dict[str, Any]
    configuration_patterns: Dict[str, Any]
    risks_and_constraints: List[str]
    recommendations: List[str]
    unknown_areas: List[str]
    evidence_hash: str = ""

    # Acceptance criteria for verification
    acceptance_criteria: List[str] = Field(default_factory=lambda: [
        "project_overview contains project_type and key_files",
        "dependencies lists all package managers found",
        "similar_implementations has at least 1 entry or empty with reason",
        "testing_conventions describes test framework and patterns",
        "configuration_patterns lists config files found",
        "risks_and_constraints has at least 2 items",
        "recommendations has at least 1 item",
    ])


# ============================================================
# ANALYST (THINKER) CONTRACT
# ============================================================

class AnalystInput(BaseModel):
    """Input for Analyst agent."""
    user_request: str
    exploration_report: ExplorationReport
    codebase_path: str = "."


class Analysis(BaseModel):
    """Analyst output - root cause and impact analysis."""
    root_cause: str
    impact_assessment: Dict[str, Any]
    risks: List[str]
    constraints: List[str]
    assumptions: List[str]
    evidence_hash: str = ""

    acceptance_criteria: List[str] = Field(default_factory=lambda: [
        "root_cause is non-empty and specific",
        "impact_assessment has at least 2 dimensions",
        "risks has at least 2 items",
        "constraints includes technical and business constraints",
        "assumptions are explicit and testable",
    ])


# ============================================================
# PLANNER CONTRACT
# ============================================================

class PlanTask(BaseModel):
    """Single task in the plan."""
    id: str
    name: str
    description: str
    agent_type: AgentType
    acceptance_criteria: List[str] = Field(default_factory=list)
    depends_on: List[str] = Field(default_factory=list)
    estimated_tokens: int = 5000


class PlannerInput(BaseModel):
    """Input for Planner agent."""
    user_request: str
    exploration_report: ExplorationReport
    analysis: Analysis
    max_tasks: int = 10


class Plan(BaseModel):
    """Planner output - execution plan with task DAG."""
    tasks: List[PlanTask] = Field(default_factory=list)
    summary: str = ""
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    evidence_hash: str = ""

    acceptance_criteria: List[str] = Field(default_factory=lambda: [
        "tasks has at least 1 task",
        "each task has non-empty id, name, description",
        "each task has acceptance_criteria with at least 1 file-based criterion",
        "depends_on forms valid DAG (no cycles)",
        "agent_type matches task responsibility",
    ])


# ============================================================
# DESIGNER CONTRACT
# ============================================================

class DesignSpec(BaseModel):
    """Designer output - technical design specification."""
    interfaces: List[Dict[str, Any]] = Field(default_factory=list)
    data_models: List[Dict[str, Any]] = Field(default_factory=list)
    api_contracts: List[Dict[str, Any]] = Field(default_factory=list)
    protocols: List[Dict[str, Any]] = Field(default_factory=list)
    infrastructure: Dict[str, Any] = Field(default_factory=dict)
    security_considerations: List[str] = Field(default_factory=list)
    evidence_hash: str = ""

    acceptance_criteria: List[str] = Field(default_factory=lambda: [
        "interfaces has at least 1 entry or empty with reason",
        "data_models has at least 1 entry or empty with reason",
        "api_contracts has at least 1 entry or empty with reason",
        "security_considerations has at least 2 items",
        "evidence_hash is non-empty",
    ])


class DesignerInput(BaseModel):
    """Input for Designer agent."""
    plan: Plan
    analysis: Analysis
    exploration_report: ExplorationReport


# ============================================================
# REVIEWER CONTRACT
# ============================================================

class ReviewVerdict(str, Enum):
    APPROVED = "approved"
    REVISE = "revise"


class ReviewInput(BaseModel):
    """Input for Reviewer agent."""
    plan: Plan
    design_spec: Optional[DesignSpec] = None
    analysis: Optional[Analysis] = None
    previous_reviews: List[str] = Field(default_factory=list)
    review_round: int = 1


class Review(BaseModel):
    """Reviewer output - verdict with specific feedback."""
    verdict: ReviewVerdict
    issues: List[str] = Field(default_factory=list)
    required_changes: List[str] = Field(default_factory=list)
    score: float = Field(ge=0.0, le=10.0)
    evolution_score: float = Field(ge=0.0, le=10.0)
    evidence_hash: str = ""

    # Max 3 review cycles enforced by orchestrator
    max_cycles: int = 3

    acceptance_criteria: List[str] = Field(default_factory=lambda: [
        "verdict is either 'approved' or 'revise'",
        "if revise: issues and required_changes are non-empty",
        "if approved: issues and required_changes are empty",
        "score and evolution_score in range [0, 10]",
    ])


# ============================================================
# IMPLEMENTER CONTRACT
# ============================================================

class ImplementationResult(BaseModel):
    """Implementer output - artifacts produced in sandbox."""
    status: Literal["executed", "failed"] = "executed"
    artifacts: List[str] = Field(default_factory=list)  # artifact_ids
    stdout_reference: str = ""
    stderr_reference: str = ""
    evidence_refs: List[str] = Field(default_factory=list)  # sha256:hash:path

    # Failure detail (if failed)
    failure: Optional[Dict[str, Any]] = None

    acceptance_criteria: List[str] = Field(default_factory=lambda: [
        "artifacts list matches acceptance criteria from plan",
        "each artifact exists in sandbox /artifacts with matching sha256",
        "stdout_reference and stderr_reference point to bounded artifacts",
        "if failed: failure dict has class, stage, tool, reason",
    ])


class ImplementerInput(BaseModel):
    """Input for Implementer agent."""
    plan: Plan
    design_spec: Optional[DesignSpec] = None
    analysis: Optional[Analysis] = None
    exploration_report: Optional[ExplorationReport] = None
    task: PlanTask
    previous_attempts: List[str] = Field(default_factory=list)
    sandbox_root: str = "/artifacts"


# ============================================================
# VERIFIER CONTRACT
# ============================================================

class VerifierInput(BaseModel):
    """Input for Verifier agent."""
    task_acceptance_criteria: List[str]
    artifacts: List[str]  # artifact paths
    evidence_refs: List[str]


class VerificationResult(BaseModel):
    """Verifier output - evidence-based verdict."""
    verdict: VerifierVerdict
    checks_performed: List[str] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    # Sub-verdict for flow control
    sub_verdict: Optional[SubVerdict] = None

    acceptance_criteria: List[str] = Field(default_factory=lambda: [
        "verdict is either 'evidenced' or 'not_evidenced'",
        "checks_performed documents each acceptance criterion checked",
        "if not_evidenced: missing_evidence lists specific gaps",
        "confidence in range [0, 1]",
        "sub_verdict is NOT_EVIDENCED when verdict is not_evidenced",
    ])


# ============================================================
# ARBITER CONTRACT
# ============================================================

class ArbiterInput(BaseModel):
    """Input for Arbiter agent."""
    conflict_type: str
    parties: List[str]
    evidences: List[str]
    history: List[str]
    failure_context: Dict[str, Any] = Field(default_factory=dict)


class ArbiterResult(BaseModel):
    """Arbiter output - decision with retry budget."""
    decision: ArbiterDecision
    rationale: str
    escalation_to_human: bool = False
    max_retries_remaining: int = Field(ge=0)

    # Sub-verdict for flow control
    sub_verdict: Optional[SubVerdict] = None

    acceptance_criteria: List[str] = Field(default_factory=lambda: [
        "decision is one of: retry_with_constraints, terminate_stagnant, escalate_to_human",
        "rationale is non-empty and specific",
        "max_retries_remaining >= 0",
        "if terminate_stagnant: escalation_to_human is True",
        "if escalate_to_human: max_retries_remaining is 0",
    ])


# ============================================================
# AGENT FACTORY / REGISTRY
# ============================================================

class AgentContractRegistry:
    """Registry of all agent contracts for validation."""

    CONTRACTS: Dict[AgentType, Dict] = {
        AgentType.EXPLORER: {
            "input": ExplorerInput,
            "output": ExplorationReport,
            "acceptance": ExplorationReport.model_fields["acceptance_criteria"].default,
        },
        AgentType.ANALYST: {
            "input": AnalystInput,
            "output": Analysis,
            "acceptance": Analysis.model_fields["acceptance_criteria"].default,
        },
        AgentType.PLANNER: {
            "input": PlannerInput,
            "output": Plan,
            "acceptance": Plan.model_fields["acceptance_criteria"].default,
        },
        AgentType.DESIGNER: {
            "input": DesignerInput,
            "output": DesignSpec,
            "acceptance": DesignSpec.model_fields["acceptance_criteria"].default,
        },
        AgentType.REVIEWER: {
            "input": ReviewInput,
            "output": Review,
            "acceptance": Review.model_fields["acceptance_criteria"].default,
        },
        AgentType.IMPLEMENTER: {
            "input": ImplementerInput,
            "output": ImplementationResult,
            "acceptance": ImplementationResult.model_fields["acceptance_criteria"].default,
        },
        AgentType.VERIFIER: {
            "input": VerifierInput,
            "output": VerificationResult,
            "acceptance": VerificationResult.model_fields["acceptance_criteria"].default,
        },
        AgentType.ARBITER: {
            "input": ArbiterInput,
            "output": ArbiterResult,
            "acceptance": ArbiterResult.model_fields["acceptance_criteria"].default,
        },
    }

    @classmethod
    def get_contract(cls, agent_type: AgentType) -> Dict:
        """Get contract for agent type."""
        return cls.CONTRACTS.get(agent_type, {})

    @classmethod
    def validate_input(cls, agent_type: AgentType, input_data: Dict) -> bool:
        """Validate input against contract."""
        contract = cls.get_contract(agent_type)
        if not contract:
            return False
        try:
            contract["input"].model_validate(input_data)
            return True
        except Exception:
            return False

    @classmethod
    def validate_output(cls, agent_type: AgentType, output_data: Dict) -> bool:
        """Validate output against contract."""
        contract = cls.get_contract(agent_type)
        if not contract:
            return False
        try:
            contract["output"].model_validate(output_data)
            return True
        except Exception:
            return False

    @classmethod
    def check_acceptance(cls, agent_type: AgentType, output: BaseModel) -> List[str]:
        """Check acceptance criteria against output."""
        contract = cls.get_contract(agent_type)
        criteria = contract.get("acceptance", [])
        missing = []

        for criterion in criteria:
            # Simple heuristic checks - real implementation would be more sophisticated
            if "non-empty" in criterion.lower() and "evidence_hash" in criterion.lower():
                if not getattr(output, "evidence_hash", None):
                    missing.append(criterion)
            elif "at least" in criterion.lower():
                # Could parse number and check list lengths
                pass

        return missing


# ============================================================
# AGENT CAPABILITIES
# ============================================================

@dataclass
class AgentCapability:
    """Defines what an agent can do."""
    agent_type: AgentType
    tools: List[str]  # tool names
    permissions: List[str]  # grant types
    max_tokens: int
    timeout_seconds: int
    can_spawn_subtasks: bool = False


AGENT_CAPABILITIES: Dict[AgentType, AgentCapability] = {
    AgentType.EXPLORER: AgentCapability(
        agent_type=AgentType.EXPLORER,
        tools=["read_file", "list_dir", "grep", "find_files", "web_search"],
        permissions=["read"],
        max_tokens=50000,
        timeout_seconds=300,
    ),
    AgentType.ANALYST: AgentCapability(
        agent_type=AgentType.ANALYST,
        tools=["read_file", "llm"],
        permissions=["read"],
        max_tokens=50000,
        timeout_seconds=300,
    ),
    AgentType.PLANNER: AgentCapability(
        agent_type=AgentType.PLANNER,
        tools=["read_file", "llm"],
        permissions=["read"],
        max_tokens=50000,
        timeout_seconds=300,
    ),
    AgentType.DESIGNER: AgentCapability(
        agent_type=AgentType.DESIGNER,
        tools=["read_file", "llm"],
        permissions=["read"],
        max_tokens=50000,
        timeout_seconds=300,
    ),
    AgentType.REVIEWER: AgentCapability(
        agent_type=AgentType.REVIEWER,
        tools=["read_file", "llm"],
        permissions=["read"],
        max_tokens=50000,
        timeout_seconds=300,
    ),
    AgentType.IMPLEMENTER: AgentCapability(
        agent_type=AgentType.IMPLEMENTER,
        tools=["read_file", "write_file", "edit_file", "run_command", "llm"],
        permissions=["read", "write", "execute"],
        max_tokens=100000,
        timeout_seconds=600,
    ),
    AgentType.VERIFIER: AgentCapability(
        agent_type=AgentType.VERIFIER,
        tools=["read_file", "run_command", "grep", "llm"],
        permissions=["read", "execute"],
        max_tokens=50000,
        timeout_seconds=300,
    ),
    AgentType.ARBITER: AgentCapability(
        agent_type=AgentType.ARBITER,
        tools=["llm"],
        permissions=[],
        max_tokens=20000,
        timeout_seconds=120,
    ),
}


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Protocol
    "AgentRole",
    # Base
    "AgentTask",
    "AgentResult",
    # Explorer
    "ExplorerInput",
    "ExplorationReport",
    # Analyst
    "AnalystInput",
    "Analysis",
    # Planner
    "PlanTask",
    "PlannerInput",
    "Plan",
    # Designer
    "DesignerInput",
    "DesignSpec",
    # Reviewer
    "ReviewVerdict",
    "ReviewInput",
    "Review",
    # Implementer
    "ImplementerInput",
    "ImplementationResult",
    # Verifier
    "VerifierInput",
    "VerificationResult",
    # Arbiter
    "ArbiterInput",
    "ArbiterResult",
    # Registry
    "AgentContractRegistry",
    # Capabilities
    "AgentCapability",
    "AGENT_CAPABILITIES",
]