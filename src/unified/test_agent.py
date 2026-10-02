"""
E4 Test Agent - Simple agent for VS-003 vertical slice testing.

This agent demonstrates the complete agent lifecycle:
REGISTERED -> AVAILABLE -> ASSIGNED -> RUNNING -> COMPLETED/FAILED

It writes a test artifact to the sandbox and produces evidence.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from src.unified.contracts import (
    AgentType,
    AgentTask,
    AgentResult,
    AgentCapability,
    AgentContext,
    EventType,
    FactoryEvent,
    Artifact,
    EvidenceRecord,
    AgentStartedEvent,
    AgentCompletedEvent,
    AgentFailedEvent,
)


class E4TestAgent:
    """
    Simple test agent for VS-003.
    Writes a test file to sandbox and returns result.
    """
    
    agent_type = AgentType.IMPLEMENTER
    capability = AgentCapability(
        tools=["write_artifact", "read_artifact"],
        permissions=["write"],
        max_tokens=10000,
        timeout_seconds=60,
        requires_sandbox=True,
        supported_domains=["testing"],
    )
    version = "1.0"
    
    def __init__(self):
        self._context: Optional[AgentContext] = None
        self._current_task: Optional[AgentTask] = None
    
    @property
    def context(self) -> Optional[AgentContext]:
        return self._context
    
    @property
    def current_task(self) -> Optional[AgentTask]:
        return self._current_task
    
    def on_start(self, context: AgentContext, task: AgentTask) -> None:
        """Emit agent.started event."""
        self._context = context
        self._current_task = task
        self._emit_event(
            EventType.AGENT_STARTED,
            AgentStartedEvent(
                agent_id=context.agent_id,
                agent_type=self.agent_type.value,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=task.task_id,
            ),
        )
    
    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """Execute the test: write artifact to sandbox."""
        self._context = context
        self._current_task = task
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Get content from task metadata or use default
            # Task from domain_model doesn't have context, so use task.description or metadata
            content = getattr(task, 'context', {}).get("content", b"Hello, VS-003 from E4TestAgent!")
            if isinstance(content, str):
                content = content.encode()
            
            path = getattr(task, 'context', {}).get("path", "e4_test_output.txt")
            
            # Write artifact via sandbox manager
            if not context.sandbox_manager or not context.sandbox_id:
                raise RuntimeError("Sandbox manager or sandbox_id not available")
            
            artifact = await context.sandbox_manager.write_artifact(
                context.sandbox_id, path, content
            )
            
            # Store artifact in evidence store if available
            if hasattr(context, 'evidence_store') and context.evidence_store:
                context.evidence_store.store_artifact(artifact)
                # Also create evidence record
                import hashlib
                evidence = EvidenceRecord(
                    evidence_id=f"evidence-{hashlib.sha256(artifact.sha256.encode()).hexdigest()[:12]}",
                    evidence_hash=artifact.sha256,
                    content_type="artifact",
                    source_id=artifact.artifact_id,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    task_id=task.task_id,
                )
                context.evidence_store.store_evidence(evidence)
            
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=True,
                output={"artifact_id": artifact.artifact_id, "path": artifact.path},
                evidence_hash=artifact.sha256,
                artifacts=[artifact.artifact_id],
                duration_ms=duration_ms,
            )
            
        except Exception as e:
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=False,
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=duration_ms,
            )
    
    def on_complete(self, context: AgentContext, task: AgentTask, result: AgentResult) -> None:
        """Emit agent.completed event."""
        self._emit_event(
            EventType.AGENT_COMPLETED,
            AgentCompletedEvent(
                agent_id=context.agent_id,
                agent_type=self.agent_type.value,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=task.task_id,
                success=result.success,
                output_summary=f"Artifact: {result.artifacts[0] if result.artifacts else 'none'}",
                evidence_hash=result.evidence_hash,
                duration_ms=result.duration_ms,
            ),
        )
        self._context = None
        self._current_task = None
    
    def on_failed(self, context: AgentContext, task: AgentTask, error: Exception) -> None:
        """Emit agent.failed event."""
        self._emit_event(
            EventType.AGENT_FAILED,
            AgentFailedEvent(
                agent_id=context.agent_id,
                agent_type=self.agent_type.value,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=task.task_id,
                error=str(error),
                error_type=type(error).__name__,
            ),
        )
        self._context = None
        self._current_task = None
    
    def validate_input(self, task: AgentTask) -> List[str]:
        """Validate task input."""
        errors = []
        if not task.task_id:
            errors.append("task_id is required")
        return errors
    
    def validate_output(self, result: AgentResult) -> List[str]:
        """Validate agent output."""
        errors = []
        if result.success and not result.evidence_hash:
            errors.append("successful result must have evidence_hash")
        return errors
    
    def _emit_event(self, event_type: EventType, payload: Dict[str, Any]) -> None:
        """Emit event via context's event emitter."""
        if self._context and self._context.event_emitter:
            event = FactoryEvent.create(
                event_type=event_type,
                mission_id=self._context.mission_id,
                run_id=self._context.run_id,
                payload=payload,
                source=f"agent.{self.agent_type.value}",
                correlation_id=self._context.task_id,
            )
            self._context.event_emitter(event)
    
    def _check_tool_permission(self, tool_name: str) -> bool:
        return tool_name in self.capability.tools
    
    def _require_tool_permission(self, tool_name: str) -> None:
        if not self._check_tool_permission(tool_name):
            raise PermissionError(
                f"Agent {self.agent_type.value} not permitted to use tool: {tool_name}. "
                f"Allowed: {self.capability.tools}"
            )


# Also export a simple function to register the test agent
def register_e4_test_agent(registry) -> None:
    """Register E4TestAgent with the registry."""
    from src.unified.contracts import AgentDefinition, AgentLifecycleState
    
    # Register definition
    definition = AgentDefinition(
        agent_id="e4-test-agent-001",
        agent_type=AgentType.IMPLEMENTER,
        name="E4TestAgent",
        version="1.0",
        description="Simple test agent for VS-003 vertical slice",
        tools=["write_artifact", "read_artifact"],
        permissions=["write"],
        max_tokens=10000,
        timeout_seconds=60,
        requires_sandbox=True,
        supported_domains=["testing"],
        implementation_class="unified.test_agent.E4TestAgent",
        state=AgentLifecycleState.REGISTERED,
    )
    registry.register_definition(definition)
    registry.enable_agent(definition.agent_id)
    
    # Register implementation
    registry.register_implementation(AgentType.IMPLEMENTER, E4TestAgent)


__all__ = ["E4TestAgent", "register_e4_test_agent"]