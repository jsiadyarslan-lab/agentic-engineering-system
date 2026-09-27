#!/usr/bin/env python3
"""
Agent Base Class
Abstract base class for all agents in the factory.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TypeVar, Generic

from src.factory.contracts.agent_protocol import (
    AgentTask, AgentResult, Handoff,
    ExplorationReport, Analysis, Plan, DesignSpec,
    Review, ImplementationResult, Verification, SecurityReport
)
from src.factory.context.memory import SharedContextManager
from src.factory.contracts.grants import GrantManager
from src.llm import StructuredLLM

T = TypeVar('T')


@dataclass
class AgentTask:
    """Task assigned to an agent."""
    task_id: str
    task_type: str
    spec: Dict[str, Any]
    acceptance_criteria: List[str]
    dependencies: List[str] = field(default_factory=list)
    timeout_seconds: int = 300
    priority: int = 1


@dataclass
class AgentResult:
    """Result of agent execution."""
    task_id: str
    agent_type: str
    success: bool
    output: Any
    evidence_hash: str
    error: Optional[str] = None
    artifacts: List[Dict] = field(default_factory=list)
    duration_ms: int = 0
    evidence: Dict = field(default_factory=dict)


class BaseAgent(ABC):
    """
    Abstract base class for all agents in the factory.
    
    Each agent implements the execute() method which is the single entry point.
    Agents must handle their own lifecycle: on_start -> execute -> on_complete/on_failed.
    """
    
    def __init__(
        self,
        llm: 'StructuredLLM',
        context: 'SharedContextManager',
        grants: Optional['GrantManager'] = None,
    ):
        self.llm = llm
        self.context = context
        self.grants = grants
        self.agent_type = self.__class__.__name__.replace('Agent', '').lower()
        self._running = False
    
    @property
    @abstractmethod
    def agent_type(self) -> str:
        """Unique identifier for this agent type."""
        pass
    
    @property
    @abstractmethod
    def agent_role(self) -> str:
        """Human-readable role description."""
        pass
    
    @property
    def required_grants(self) -> List[str]:
        """List of required grants for this agent."""
        return []
    
    async def on_start(self, task: 'AgentTask') -> None:
        """Called before task execution."""
        pass
    
    async def on_complete(self, task: 'AgentTask', result: 'AgentResult') -> None:
        """Called after successful completion."""
        pass
    
    async def on_failed(self, task: 'AgentTask', error: Exception) -> None:
        """Called on failure."""
        pass
    
    async def on_handoff_received(self, handoff: 'Handoff') -> None:
        """Called when receiving a handoff from another agent."""
        pass
    
    @abstractmethod
    async def execute(self, task: 'AgentTask') -> 'AgentResult':
        """Execute the task. Single entry point for agent execution."""
        pass
    
    def compact_context(self, budget: int) -> str:
        """Compact context to fit within token budget."""
        # Implementation would use LLM to summarize
        return self.context.summarize(budget)
    
    def prioritize_context(self, task: 'AgentTask') -> str:
        """Prioritize context elements for the given task."""
        return self.context.prioritize(task)
    
    async def _call_llm(
        self,
        prompt: str,
        output_model: Type[T],
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ) -> T:
        """Call LLM with structured output."""
        return await self.llm.structured_chat(
            prompt=prompt,
            output_model=output_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    
    def _create_evidence_hash(self, output: Any) -> str:
        """Create evidence hash for audit trail."""
        content = json.dumps(output, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()
    
    def _create_result(
        self,
        task_id: str,
        success: bool,
        output: Any,
        error: Optional[str] = None,
        artifacts: Optional[List[Dict]] = None,
        duration_ms: int = 0,
    ) -> 'AgentResult':
        """Create standardized agent result."""
        output_data = output if isinstance(output, dict) else {"result": output}
        evidence_hash = hashlib.sha256(
            json.dumps(output_data, sort_keys=True, default=str).encode()
        ).hexdigest()
        
        return AgentResult(
            task_id=task_id,
            agent_type=self.agent_type,
            success=success,
            output=output,
            evidence_hash=hashlib.sha256(
                json.dumps({"output": output_data, "error": str(error)}, sort_keys=True, default=str).encode()
            ).hexdigest(),
            error=error,
            artifacts=artifacts or [],
            duration_ms=0,
            evidence={"output_hash": hashlib.sha256(json.dumps(output_data, sort_keys=True, default=str).encode()).hexdigest()},
        )


# Missing imports
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Type, TypeVar, Generic
from abc import ABC, abstractmethod
import asyncio
import hashlib
import json
import uuid
from src.factory.contracts.agent_protocol import (
    AgentTask, AgentResult, Handoff,
    ExplorationReport, Analysis, Plan, DesignSpec,
    Review, ImplementationResult, Verification, SecurityReport
)
from src.factory.context.memory import SharedContextManager
from src.factory.contracts.grants import GrantManager
from src.llm import StructuredLLM