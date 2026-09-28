#!/usr/bin/env python3
"""
Agent Contracts - Core protocol definitions for agent communication.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class AgentType(str, Enum):
    """Types of agents in the factory."""
    EXPLORER = "explorer"
    THINKER = "thinker"
    PLANNER = "planner"
    DESIGNER = "designer"
    REVIEWER = "reviewer"
    IMPLEMENTER = "implementer"
    VERIFIER = "verifier"
    SECURITY = "security"


class TaskType(str, Enum):
    """Types of tasks agents can perform."""
    EXPLORE = "explore"
    ANALYZE = "analyze"
    PLAN = "plan"
    DESIGN = "design"
    REVIEW = "review"
    IMPLEMENT = "implement"
    VERIFY = "verify"
    SECURITY_AUDIT = "security_audit"


class AgentTask(BaseModel):
    """Task assigned to an agent."""
    task_id: str
    task_type: str
    spec: Dict[str, Any]
    acceptance_criteria: List[str]
    dependencies: List[str] = Field(default_factory=list)
    timeout_seconds: int = 300
    priority: int = 1


class AgentResult(BaseModel):
    """Result of agent execution."""
    task_id: str
    agent_type: str
    success: bool
    output: Any
    evidence_hash: str
    error: Optional[str] = None
    artifacts: List[Dict] = Field(default_factory=list)
    duration_ms: int = 0
    evidence: Dict = Field(default_factory=dict)


class Handoff(BaseModel):
    """Handoff between agents with HMAC signature."""
    from_agent: str
    to_agent: str
    payload: Dict[str, Any]
    signature: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    handoff_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])


class ExplorationReport(BaseModel):
    """Report from Explorer agent."""
    summary: str
    codebase_structure: Dict[str, Any]
    entry_points: List[str]
    dependencies: Dict[str, List[str]]
    file_inventory: List[Dict[str, Any]]
    key_patterns: List[str]
    tech_stack: Dict[str, str]
    evidence_hash: str = ""


class Analysis(BaseModel):
    """Analysis from Thinker agent."""
    root_cause: str
    impact_assessment: str
    affected_components: List[str]
    risk_factors: List[str]
    recommendations: List[str]
    confidence: float
    evidence_hash: str = ""


class Plan(BaseModel):
    """Execution plan from Planner."""
    summary: str
    tasks: List[Dict[str, Any]]
    dependencies: Dict[str, List[str]]
    estimates: Dict[str, int]
    risks: List[str]
    evidence_hash: str = ""

    def to_dict(self) -> dict:
        return self.model_dump()


class DesignSpec(BaseModel):
    """Design specification from Designer."""
    summary: str
    architecture: Dict[str, Any]
    components: List[Dict[str, Any]]
    interfaces: List[Dict[str, Any]]
    data_models: List[Dict[str, Any]]
    api_contracts: List[Dict[str, Any]]
    evidence_hash: str = ""

    def to_dict(self) -> dict:
        return self.model_dump()


class Review(BaseModel):
    """Review from Reviewer agent."""
    approved: bool
    summary: str
    issues: List[Dict[str, Any]]
    suggestions: List[str]
    risk_assessment: str
    evidence_hash: str = ""


class ImplementationResult(BaseModel):
    """Result from Implementer agent."""
    files_created: List[str]
    files_modified: List[str]
    tests_added: List[str]
    tests_modified: List[str]
    build_command: str
    test_command: str
    artifacts: List[Dict[str, Any]]
    file_contents: Dict[str, str] = Field(default_factory=dict)
    evidence_hash: str = ""


class Verification(BaseModel):
    """Verification result from Verifier agent."""
    passed: bool
    tests_passed: int
    tests_total: int
    coverage: float
    issues: List[Dict[str, Any]]
    evidence_hash: str = ""


class SecurityReport(BaseModel):
    """Security audit report."""
    vulnerabilities_found: int
    secrets_found: int
    dependencies_checked: int
    issues: List[Dict[str, Any]]
    evidence_hash: str = ""


# Re-export for convenience
__all__ = [
    "AgentType",
    "TaskType",
    "AgentTask",
    "AgentResult",
    "Handoff",
    "ExplorationReport",
    "Analysis",
    "Plan",
    "DesignSpec",
    "Review",
    "ImplementationResult",
    "Verification",
    "SecurityReport",
]