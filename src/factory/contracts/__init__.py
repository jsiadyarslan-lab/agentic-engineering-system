# Factory Contracts Package
"""
Agent Contracts Package
Core protocol definitions for agent communication and coordination.
"""

from .agent_protocol import (
    AgentType,
    TaskType,
    AgentTask,
    AgentResult,
    Handoff,
    ExplorationReport,
    Analysis,
    Plan,
    DesignSpec,
    Review,
    ImplementationResult,
    Verification,
    SecurityReport,
    Handoff,
)

from .grants import (
    GrantType,
    Grant,
    GrantRequest,
    GrantManager,
    get_grant_manager,
    set_grant_manager,
)

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
    "Handoff",
    "GrantType",
    "Grant",
    "GrantRequest",
    "GrantManager",
    "get_grant_manager",
    "set_grant_manager",
]