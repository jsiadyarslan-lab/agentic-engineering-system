#!/usr/bin/env python3
"""
Implementer Agent — Implementation Agent
Implements code from design specifications using WindowsExecutor.
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
from src.factory.contracts.grants import Grant
from src.factory.context.memory import SharedContextManager
from src.factory.contracts.grants import GrantManager
from src.substrate.windows_executor import WindowsExecutor, ExecutionLimits
from src.llm.structured import StructuredLLM
from src.llm.provider import LLMMessage


class ImplementerAgent(BaseAgent):
    """Implementer Agent — Implements code from design specifications."""
    
    agent_type = "implementer"
    agent_role = "Implementer"
    
    def __init__(
        self,
        llm: 'StructuredLLM',
        context: 'SharedContextManager',
        grants: Optional['GrantManager'] = None,
        windows_executor: Optional['WindowsExecutor'] = None,
    ):
        self.llm = llm
        self.context = context
        self.grants = grants
        self.windows_executor = windows_executor or WindowsExecutor()
    
    @property
    def agent_type(self) -> str:
        return "implementer"
    
    @property
    def agent_role(self) -> str:
        return "Implementer"
    
    @property
    def required_grants(self) -> List[str]:
        return ["read", "write"]
    
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
        """Execute the implementation task."""
        try:
            # Extract parameters from task spec
            spec = task.spec
            plan = spec.get("plan", {})
            design_spec = spec.get("design_spec", {})
            analysis = spec.get("analysis", {})
            exploration_report = spec.get("exploration_report", {})
            user_request = spec.get("user_request", "")
            
            # Read the implementer prompt template
            prompt_path = Path(__file__).parent.parent.parent / "llm" / "prompts" / "implementer.yaml"
            
            # Perform implementation
            implementation_result = await self._implement(
                plan=spec.get("plan", {}),
                design_spec=spec.get("design_spec", {}),
                analysis=spec.get("analysis", {}),
                exploration_report=spec.get("exploration_report", {}),
                user_request=spec.get("user_request", "")
            )
            
            evidence_hash = self._create_evidence_hash({
                "implementation_result": implementation_result,
                "report": implementation_result
            })
            
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=True,
                output=implementation_result,
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
    
    async def _implement(self, plan: Dict, design_spec: Dict, analysis: Dict, exploration_report: Dict, user_request: str) -> ImplementationResult:
        """Implement the code using LLM and write files to disk."""
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
        
        # Call LLM with structured output to generate code
        implementation_result = await self.llm.structured_chat(
            messages=[
                LLMMessage(role="system", content="You are an expert software engineer. Implement the code according to the design specification. Return file contents in the file_contents field."),
                LLMMessage(role="user", content=f"implementer_agent: Implement the code for this task:\n\nUser Request: {user_request}\n\nPlan: {json.dumps(plan, indent=2)}\n\nDesign Spec: {json.dumps(design_spec, indent=2)}\n\nAnalysis: {json.dumps(analysis, indent=2)}"),
            ],
            output_model=ImplementationResult
        )
        
        # Write files to disk
        workspace = Path(self.context.get_workspace_path()) if hasattr(self.context, 'get_workspace_path') else Path.cwd()
        workspace.mkdir(parents=True, exist_ok=True)
        
        for file_path, content in implementation_result.file_contents.items():
            full_path = workspace / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding='utf-8')
            if file_path not in implementation_result.files_created:
                implementation_result.files_created.append(file_path)
        
        return implementation_result
    
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