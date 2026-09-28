#!/usr/bin/env python3
"""
Planner Agent — Planning Agent
Creates execution plans from analysis and exploration reports.
"""

from __future__ import annotations

import os
import json
import asyncio
import hashlib
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from abc import ABC, abstractmethod

from src.factory.agents.base import BaseAgent
from src.factory.contracts.agent_protocol import (
    AgentTask, AgentResult, Handoff,
    ExplorationReport, Analysis, Plan, DesignSpec,
    Review, ImplementationResult, Verification, SecurityReport
)
from src.factory.context.memory import SharedContextManager
from src.factory.contracts.grants import GrantManager
from src.llm.structured import StructuredLLM
from src.llm.provider import LLMMessage


class PlannerAgent(BaseAgent):
    """Planner Agent — Creates execution plans from analysis and exploration reports."""
    
    agent_type = "planner"
    agent_role = "Planner"
    
    def __init__(
        self,
        llm: 'StructuredLLM',
        context: 'SharedContextManager',
        grants=None,
    ):
        self.llm = llm
        self.context = context
        self.grants = grants
    
    @property
    def agent_type(self) -> str:
        return "planner"
    
    @property
    def agent_role(self) -> str:
        return "Planner"
    
    @property
    def required_grants(self) -> List[str]:
        return ["read"]
    
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
    
    async def execute(self, task: 'AgentTask') -> 'AgentResult':
        """Execute the planning task."""
        try:
            # Extract parameters from task spec
            spec = task.spec
            analysis = spec.get("analysis", {})
            exploration_report = spec.get("exploration_report", {})
            user_request = spec.get("user_request", "")
            
            # Read the planner prompt template
            prompt_path = Path(__file__).parent.parent.parent / "llm" / "prompts" / "planner.yaml"
            
            # Perform planning
            plan = await self._create_plan(
                analysis=spec.get("analysis", {}),
                exploration_report=spec.get("exploration_report", {}),
                user_request=spec.get("user_request", "")
            )
            
            evidence_hash = self._create_evidence_hash({
                "plan": plan,
                "report": plan
            })
            
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=True,
                output=plan,
                evidence_hash=evidence_hash
            )
            
        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=False,
                output=None,
                evidence_hash="",
                error=str(e)
            )
    
    async def _create_plan(self, analysis: Dict, exploration_report: Dict, user_request: str) -> Plan:
        """Create execution plan using LLM."""
        # Read the planner prompt template
        prompt_path = Path(__file__).parent.parent.parent / "llm" / "prompts" / "planner.yaml"
        
        # Convert analysis to dict if it's a Pydantic model
        if hasattr(analysis, 'model_dump'):
            analysis = analysis.model_dump()
        elif hasattr(analysis, 'to_dict'):
            analysis = analysis.to_dict()
        
        # Convert exploration_report to dict if it's a Pydantic model
        if hasattr(exploration_report, 'model_dump'):
            exploration_report = exploration_report.model_dump()
        elif hasattr(exploration_report, 'to_dict'):
            exploration_report = exploration_report.to_dict()
        
        # Call LLM with structured output
        plan = await self.llm.structured_chat(
            messages=[
                LLMMessage(role="system", content="You are an expert software planner. Create a detailed execution plan."),
                LLMMessage(role="user", content=f"planner_agent: Create an execution plan for this task:\n\nUser Request: {user_request}\n\nAnalysis: {json.dumps(analysis, indent=2)}\n\nExploration Report: {json.dumps(exploration_report, indent=2)}"),
            ],
            output_model=Plan
        )
        
        return plan
    
    def _create_evidence_hash(self, data: Any) -> str:
        """Create evidence hash for audit trail."""
        content = json.dumps(data, sort_keys=True, default=str)
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