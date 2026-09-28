#!/usr/bin/env python3
"""
Reviewer Agent — Review Agent
Reviews plans and design specifications for correctness and quality.
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


class ReviewerAgent(BaseAgent):
    """Reviewer Agent — Reviews plans and designs for correctness and quality."""
    
    agent_type = "reviewer"
    agent_role = "Code Reviewer"
    
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
        return "reviewer"
    
    @property
    def agent_role(self) -> str:
        return "Code Reviewer"
    
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
        """Execute the review task."""
        try:
            # Extract parameters from task spec
            spec = task.spec
            plan = spec.get("plan", {})
            design_spec = spec.get("design_spec", {})
            analysis = spec.get("analysis", {})
            user_request = spec.get("user_request", "")
            
            # Read the reviewer prompt template
            prompt_path = Path(__file__).parent.parent.parent / "llm" / "prompts" / "reviewer.yaml"
            
            # Perform review
            review = await self._perform_review(
                plan=spec.get("plan", {}),
                design_spec=spec.get("design_spec", {}),
                analysis=spec.get("analysis", {}),
                user_request=spec.get("user_request", "")
            )
            
            evidence_hash = self._create_evidence_hash({
                "review": review,
                "report": review
            })
            
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=True,
                output=review,
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
    
    async def _perform_review(self, plan: Dict, design_spec: Dict, analysis: Dict, user_request: str) -> Review:
        """Perform the review using LLM."""
        # Read the reviewer prompt template
        prompt_path = Path(__file__).parent.parent.parent / "llm" / "prompts" / "reviewer.yaml"
        
        # Convert plan to dict if it's a Pydantic model
        if hasattr(plan, 'model_dump'):
            plan = plan.model_dump()
        elif hasattr(plan, 'to_dict'):
            plan = plan.to_dict()
        
        # Convert design_spec to dict if it's a Pydantic model
        if hasattr(design_spec, 'model_dump'):
            design_spec = design_spec.model_dump()
        elif hasattr(design_spec, 'to_dict'):
            design_spec = design_spec.to_dict()
        
        # Convert analysis to dict if it's a Pydantic model
        if hasattr(analysis, 'model_dump'):
            analysis = analysis.model_dump()
        elif hasattr(analysis, 'to_dict'):
            analysis = analysis.to_dict()
        
        # Call LLM with structured output
        review = await self.llm.structured_chat(
            messages=[
                LLMMessage(role="system", content="You are an expert code reviewer. Review the plan and design for correctness, completeness, and quality."),
                LLMMessage(role="user", content=f"reviewer_agent: Review this plan and design:\n\nUser Request: {user_request}\n\nPlan: {json.dumps(plan, indent=2)}\n\nDesign Spec: {json.dumps(design_spec, indent=2)}\n\nAnalysis: {json.dumps(analysis, indent=2)}"),
            ],
            output_model=Review
        )
        
        return review
    
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
            task_id=task.task_id,
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