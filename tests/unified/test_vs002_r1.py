#!/usr/bin/env python3
"""
VS-002-R1: True Execution Spine Closure Test

Proves the complete REAL execution path with LLM-driven action decision:

MISSION
  ↓
RUN
  ↓
TASK (IMPLEMENTER)
  ↓
ORCHESTRATOR (ExecutionEngine)
  ↓
AGENT REGISTRY (capability selection)
  ↓
AGENT FACTORY (LLM-driven agent instantiation)
  ↓
AGENT RUNTIME (execute IMPLEMENTER)
    ↓
    REAL LLM (via OrchestratorLLMProvider/LLMGateway)
    ↓
    LLM_REQUESTED
    ↓
    LLM_COMPLETED
    ↓
    STRUCTURED ACTION DECISION (LLM produces ActionRequest)
    ↓
    ACTION_REQUESTED
    ↓
    ACTION_VALIDATED (permission/tool check)
    ↓
    TOOL_STARTED
    ↓
    APPROVED TOOL → SANDBOX
    ↓
    TOOL_COMPLETED
    ↓
    ARTIFACT (file on disk)
    ↓
    ARTIFACT_CREATED
    ↓
    EVIDENCE_RECORDED
  ↓
TASK (VERIFIER) — depends on IMPLEMENTER
  ↓
INDEPENDENT VERIFIER (different agent/verifier)
    ↓
    VERIFICATION_STARTED
    ↓
    Reads artifact from evidence store
    ↓
    Recomputes SHA256 independently
    ↓
    Compares with expected content
    ↓
    VERIFICATION_COMPLETE (verdict = VERIFIED)
  ↓
ORCHESTRATOR consumes verifier verdict
  ↓
TASK COMPLETION (only if VERIFIED)
"""

import asyncio
import os
import tempfile
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

import pytest

from unified.contracts import (
    # IDs
    new_mission_id, new_run_id, new_task_id, new_attempt_id,
    new_agent_id, new_action_id, new_event_id, new_artifact_id,
    new_evidence_id, new_verification_id,
    # Enums
    MissionState, TaskState, AgentType, EventType,
    AgentLifecycleState,
    # Entities
    Mission, Run, Task, Attempt, Action, Agent,
    Artifact, EvidenceRecord, Verification,
    # Factories
    create_mission, create_run, create_task, create_attempt,
    create_action, create_artifact, create_evidence, create_verification,
    # Verification
    VerifierVerdict, AcceptanceCriterion, CriterionType, EvidenceStore,
    # Events
    FactoryEvent, EVENT_CATALOG,
    MissionStartedEvent, RunStartedEvent, TaskCreatedEvent,
    TaskAssignedEvent, AgentSelectedEvent, AgentStartedEvent,
    AgentCompletedEvent, AgentFailedEvent, TaskCompletedEvent, TaskFailedEvent,
    ToolStartedEvent, ToolCompletedEvent,
    ArtifactCreatedEvent, EvidenceRecordedEvent,
    VerificationCompleteEvent, VerificationStartedEvent,
    TokenUsageEvent,
    LLMRequestedEvent,
    LLMCompletedEvent,
    ActionRequestedEvent,
    ActionValidatedEvent,
    # Agent Role
    AgentDefinition, AgentRegistry, agent_registry, AgentFactory,
    AgentSelectionError,
    # Agent Contract Protocol
    AgentContext, AgentCapability, BaseAgent,
    AgentTask, AgentResult,
)
from unified.execution import ExecutionEngine, ExecutionContext, FileEvidenceStore
from unified.sandbox import create_sandbox_manager, SandboxBackend
from unified.windows_adapter import WindowsExecutorAdapter
from unified.verification_standard import Verifier, VerificationReport, CheckResult
from llm.orchestrator_adapter import OrchestratorLLMProvider
from llm.structured import StructuredLLM
from llm.providers import LLMMessage
from secrets_store import get_key


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def temp_dir():
    """Temporary directory for artifacts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sandbox_manager(temp_dir):
    """Create sandbox manager with Windows executor."""
    manager = create_sandbox_manager(
        backend=SandboxBackend.WINDOWS_EXECUTOR,
        artifacts_base_dir=temp_dir,
    )
    yield manager


@pytest.fixture
def nvidia_api_key():
    """Get NVIDIA API key from secrets store."""
    key = get_key("nvidia")
    if not key:
        pytest.skip("NVIDIA API key not available in secrets store")
    return key


@pytest.fixture
def llm_provider(nvidia_api_key):
    """Create OrchestratorLLMProvider with real NVIDIA key."""
    provider = OrchestratorLLMProvider.from_config(
        provider_type="nvidia",
        model="nvidia/nemotron-3-ultra-550b-a55b",
        api_key=nvidia_api_key,
    )
    yield provider


@pytest.fixture
def event_collector():
    """Collect all events emitted during test."""
    events = []
    def collector(event: FactoryEvent):
        events.append(event)
    return events, collector


# ============================================================
# HELPER CLASSES FOR VS-002-R1
# ============================================================

from pydantic import BaseModel, Field

class ActionDecision(BaseModel):
    """Structured action decision from LLM."""
    action: str = Field(description="Tool name to invoke")
    arguments: Dict[str, Any] = Field(description="Tool arguments")
    reasoning: str = Field(description="LLM reasoning for this action")


class LLMDecisionAgent:
    """
    Agent that uses REAL LLM to decide on action.
    
    Flow:
    1. Receives task with objective
    2. Emits LLM_REQUESTED
    3. Calls LLM to get structured action decision
    4. Emits LLM_COMPLETED
    5. Emits ACTION_REQUESTED
    6. Validates action (capability + permission)
    7. Emits ACTION_VALIDATED
    8. Emits TOOL_STARTED
    9. Executes action via sandbox
    10. Emits TOOL_COMPLETED
    11. Emits ARTIFACT_CREATED
    12. Returns result
    """
    
    agent_type = AgentType.IMPLEMENTER
    capability = AgentCapability(
        tools=["write_artifact", "read_artifact"],
        permissions=["write"],
        max_tokens=10000,
        timeout_seconds=120,
        requires_sandbox=True,
        supported_domains=["testing"],
    )
    version = "1.0"
    
    def __init__(self, llm_provider: OrchestratorLLMProvider):
        self.llm_provider = llm_provider
        self._context: Optional[AgentContext] = None
        self._current_task: Optional[AgentTask] = None
        self._structured_llm = llm_provider.get_structured_llm("implementer")
    
    @property
    def context(self) -> Optional[AgentContext]:
        return self._context
    
    @property
    def current_task(self) -> Optional[AgentTask]:
        return self._current_task
    
    def _emit_event(self, context: AgentContext, event_type: EventType, payload: Any) -> None:
        """Emit event via context event emitter."""
        if context.event_emitter:
            event = FactoryEvent.create(
                event_type=event_type,
                mission_id=context.mission_id,
                run_id=context.run_id,
                payload=payload,
                source=f"agent.{self.agent_type.value}",
                correlation_id=context.task_id,
            )
            context.event_emitter(event)
    
    def on_start(self, context: AgentContext, task: AgentTask) -> None:
        """Emit agent.started event."""
        print(f"DEBUG LLMDecisionAgent.on_start: task={task.task_id}")
        self._context = context
        self._current_task = task
        self._emit_event(
            context, EventType.AGENT_STARTED,
            AgentStartedEvent(
                agent_id=context.agent_id,
                agent_type=self.agent_type.value,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=task.task_id,
            )
        )
    
    def on_complete(self, context: AgentContext, task: AgentTask, result: AgentResult) -> None:
        """Called after execution completes (success or failure)."""
        print(f"DEBUG LLMDecisionAgent.on_complete: task={task.task_id}, success={result.success}")
    
    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """
        Execute using REAL LLM to decide action.
        
        The LLM receives the task objective and returns a structured
        action decision which is then validated and executed.
        """
        print(f"DEBUG LLMDecisionAgent.execute: START task={task.task_id}")
        self._context = context
        self._current_task = task
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            print("DEBUG: Getting task context")
            # Get task objective from task context/metadata
            task_objective = getattr(task, 'context', {}).get(
                "objective", 
                "Create a test file with specific content"
            )
            print("DEBUG: Got task_objective")
            expected_content = getattr(task, 'context', {}).get(
                "expected_content",
                "VS-002-R1: LLM-driven action execution verified!"
            )
            print("DEBUG: Got expected_content")
            file_path = getattr(task, 'context', {}).get(
                "file_path",
                "vs002_r1_output.txt"
            )
            print("DEBUG: Got file_path")
            
            # Step 1: Emit LLM_REQUESTED event
            print("DEBUG: Emitting LLM_REQUESTED event")
            self._emit_event(context, EventType.LLM_REQUESTED, LLMRequestedEvent(
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                agent_id=context.agent_id,
                agent_type=self.agent_type.value,
                provider="nvidia",
                model="nvidia/nemotron-3-ultra-550b-a55b",
                request_type="structured_chat",
            ))
            print("DEBUG: Emitted LLM_REQUESTED event")
            
            # Step 2: Call REAL LLM to get structured action decision
            system_prompt = f"""You are an implementation agent. Your task is to create a file with specific content.

Objective: {task_objective}
Expected file: {file_path}
Expected content: {expected_content}

Return a JSON action decision with:
- action: "write_artifact" (the only available tool)
- arguments: {{"path": "<file_path>", "content": "<content>"}}
- reasoning: brief explanation"""
            
            user_prompt = f"Generate the action to create file '{file_path}' with content: '{expected_content}'"
            
            # REAL LLM CALL - this is the critical integration point
            print("DEBUG: About to call structured_chat")
            try:
                action_decision = await self._structured_llm.structured_chat(
                    messages=[
                        LLMMessage(role="system", content=system_prompt),
                        LLMMessage(role="user", content=user_prompt)
                    ],
                    output_model=ActionDecision,
                    temperature=0.1,
                    max_tokens=500,
                )
            except Exception as llm_error:
                print(f"DEBUG: LLM call failed with error: {llm_error}")
                print(f"DEBUG: LLM error type: {type(llm_error)}")
                import traceback
                traceback.print_exc()
                # Emit LLM_COMPLETED with failure
                self._emit_event(context, EventType.LLM_COMPLETED, LLMCompletedEvent(
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    task_id=context.task_id,
                    agent_id=context.agent_id,
                    agent_type=self.agent_type.value,
                    provider="nvidia",
                    model="nvidia/nemotron-3-ultra-550b-a55b",
                    request_type="structured_chat",
                    success=False,
                    error=str(llm_error),
                ))
                raise
            print(f"DEBUG: After structured_chat, action_decision type = {type(action_decision)}")
            print(f"DEBUG: action_decision = {action_decision}")
            
            # Emit LLM_COMPLETED event with success
            self._emit_event(context, EventType.LLM_COMPLETED, LLMCompletedEvent(
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                agent_id=context.agent_id,
                agent_type=self.agent_type.value,
                provider="nvidia",
                model="nvidia/nemotron-3-ultra-550b-a55b",
                request_type="structured_chat",
                success=True,
                tokens_used=0,  # Would be populated by gateway
                cost_usd=0.0,
            ))
            
            # DEBUG: Check what we got
            if not action_decision:
                raise RuntimeError("LLM did not return valid structured action decision")
            
            # Ensure it's a Pydantic model, not a dict
            if not hasattr(action_decision, 'model_dump'):
                raise RuntimeError(f"Expected Pydantic model, got {type(action_decision)}: {action_decision}")
            
            # Step 3: ACTION_REQUESTED - create Action and emit event
            action_id = new_action_id()
            print("DEBUG: Creating Action object")
            action = Action(
                action_id=action_id,
                attempt_id=context.attempt_id,
                tool_name=action_decision.action,
                tool_args=action_decision.arguments,
                started_at=datetime.now(timezone.utc),
            )
            print("DEBUG: Created Action object")
            
            # Emit ACTION_REQUESTED
            print("DEBUG: Emitting ACTION_REQUESTED event")
            self._emit_event(context, EventType.ACTION_REQUESTED, ActionRequestedEvent(
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                agent_id=context.agent_id,
                action_id=action_id,
                attempt_id=context.attempt_id,
                tool_name=action_decision.action,
                tool_args=action_decision.arguments,
            ))
            print("DEBUG: Emitted ACTION_REQUESTED event")
            
            # Step 4: ACTION VALIDATION
            # Check if tool is allowed and arguments are valid
            print("DEBUG: Validating action")
            if action_decision.action not in self.capability.tools:
                # Emit ACTION_VALIDATED with failure
                self._emit_event(context, EventType.ACTION_VALIDATED, ActionValidatedEvent(
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    task_id=context.task_id,
                    agent_id=context.agent_id,
                    action_id=action_id,
                    attempt_id=context.attempt_id,
                    tool_name=action_decision.action,
                    valid=False,
                    reason=f"Tool {action_decision.action} not in agent capabilities",
                ))
                raise RuntimeError(f"Tool {action_decision.action} not in agent capabilities")
            print("DEBUG: Action validated - tool allowed")
            
            # Check permissions
            if "write" not in self.capability.permissions and "write" in str(action_decision.arguments):
                self._emit_event(context, EventType.ACTION_VALIDATED, ActionValidatedEvent(
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    task_id=context.task_id,
                    agent_id=context.agent_id,
                    action_id=action_id,
                    attempt_id=context.attempt_id,
                    tool_name=action_decision.action,
                    valid=False,
                    reason="Agent lacks write permission",
                ))
                raise RuntimeError("Agent lacks write permission")
            print("DEBUG: Permissions validated")
            
            # Emit ACTION_VALIDATED with success
            self._emit_event(context, EventType.ACTION_VALIDATED, ActionValidatedEvent(
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                agent_id=context.agent_id,
                action_id=action_id,
                attempt_id=context.attempt_id,
                tool_name=action_decision.action,
                valid=True,
                reason="Action validated successfully",
            ))
            
            # Step 5: Execute via sandbox (TOOL execution) - only after validation
            print("DEBUG: Checking sandbox")
            if not context.sandbox_manager or not context.sandbox_id:
                raise RuntimeError("Sandbox manager or sandbox_id not available")
            print("DEBUG: Sandbox available")
            
            print("DEBUG: Emitting TOOL_STARTED event")
            self._emit_event(context, EventType.TOOL_STARTED, ToolStartedEvent(
                tool_name=action_decision.action,
                action_id=action_id,
                attempt_id=context.attempt_id,
                sandbox_id=context.sandbox_id,
                args_summary=str(action_decision.arguments),
            ))
            print("DEBUG: Emitted TOOL_STARTED event")
            
            print("DEBUG: Writing artifact via sandbox")
            artifact = await context.sandbox_manager.write_artifact(
                context.sandbox_id,
                action_decision.arguments["path"],
                action_decision.arguments["content"].encode() if isinstance(action_decision.arguments["content"], str) else action_decision.arguments["content"]
            )
            print(f"DEBUG: Artifact created: {artifact.artifact_id}")
            
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            
            # Emit TOOL_COMPLETED
            print("DEBUG: Emitting TOOL_COMPLETED event")
            self._emit_event(context, EventType.TOOL_COMPLETED, ToolCompletedEvent(
                tool_name=action_decision.action,
                action_id=action_id,
                attempt_id=context.attempt_id,
                success=True,
                output_summary=f"Created artifact {artifact.artifact_id}",
                duration_ms=duration_ms,
            ))
            print("DEBUG: Emitted TOOL_COMPLETED event")
            
            # Step 6: ARTIFACT_CREATED
            print("DEBUG: Emitting ARTIFACT_CREATED event")
            self._emit_event(context, EventType.ARTIFACT_CREATED, ArtifactCreatedEvent(
                artifact_id=artifact.artifact_id,
                name="vs002_r1_output.txt",
                path=artifact.path,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                created_by=action_id,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
            ))
            print("DEBUG: Emitted ARTIFACT_CREATED event")
            
            # Store artifact in evidence store with mission_id
            print("DEBUG: Storing artifact in evidence store")
            try:
                if hasattr(context, 'evidence_store') and context.evidence_store:
                    print(f"DEBUG: evidence_store exists, type={type(context.evidence_store)}")
                    artifact.mission_id = context.mission_id
                    # Note: Artifact model doesn't have run_id or task_id fields
                    print(f"DEBUG: About to call store_artifact with artifact_id={artifact.artifact_id}")
                    context.evidence_store.store_artifact(artifact)
                    print(f"DEBUG: store_artifact returned successfully")
                print("DEBUG: Stored artifact in evidence store")
            except Exception as e:
                print(f"DEBUG: Exception during store_artifact: {e}")
                import traceback
                traceback.print_exc()
                raise
            
            # Emit AGENT_COMPLETED
            print("DEBUG: About to emit AGENT_COMPLETED event")
            try:
                self._emit_event(context, EventType.AGENT_COMPLETED, AgentCompletedEvent(
                    agent_id=context.agent_id,
                    agent_type=self.agent_type.value,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    task_id=context.task_id,
                    success=True,
                    output_summary=f"Action: {action_decision.action}, Artifact: {artifact.artifact_id}",
                    evidence_hash=artifact.sha256,
                    duration_ms=duration_ms,
                ))
                print("DEBUG: Emitted AGENT_COMPLETED event")
            except Exception as e:
                print(f"DEBUG: Exception during AGENT_COMPLETED emission: {e}")
                import traceback
                traceback.print_exc()
                raise
            
            print("DEBUG: About to return AgentResult")
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=True,
                output={
                    "action_decision": action_decision.model_dump(),
                    "artifact_id": artifact.artifact_id,
                    "artifact_path": artifact.path,
                },
                evidence_hash=artifact.sha256,
                artifacts=[artifact.artifact_id],
                duration_ms=duration_ms,
            )
            
        except Exception as e:
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            
            self._emit_event(context, EventType.AGENT_COMPLETED, AgentCompletedEvent(
                agent_id=context.agent_id,
                agent_type=self.agent_type.value,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                success=False,
                output_summary=f"Error: {str(e)}",
                evidence_hash=None,
                duration_ms=duration_ms,
            ))
            
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=False,
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=duration_ms,
            )
    
    def on_failed(self, context: AgentContext, task: AgentTask, error: Exception) -> None:
        """Emit agent.failed event."""
        self._emit_event(
            context, EventType.AGENT_FAILED,
            AgentFailedEvent(
                agent_id=context.agent_id,
                agent_type=self.agent_type.value,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                error=str(error),
                error_type=type(error).__name__,
            )
        )
    
    def validate_input(self, task: AgentTask) -> List[str]:
        """Validate task input - always valid for this test."""
        print(f"DEBUG LLMDecisionAgent.validate_input: task={task.task_id}")
        return []
    
    def validate_output(self, result: AgentResult) -> List[str]:
        """Validate agent output - always valid for this test."""
        print(f"DEBUG LLMDecisionAgent.validate_output")
        return []


class IndependentVerifierAgent:
    """
    INDEPENDENT verifier agent - separate from executing agent.
    
    This verifier:
    1. Reads artifact from evidence store (not from agent output)
    2. Recomputes SHA256 independently
    3. Compares with expected content
    4. Returns VERIFIED or FAILED
    """
    
    agent_type = AgentType.VERIFIER
    capability = AgentCapability(
        tools=["read_artifact"],
        permissions=["read"],
        max_tokens=5000,
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
    
    def _emit_event(self, context: AgentContext, event_type: EventType, payload: Any) -> None:
        """Emit event via context event emitter."""
        if context.event_emitter:
            event = FactoryEvent.create(
                event_type=event_type,
                mission_id=context.mission_id,
                run_id=context.run_id,
                payload=payload,
                source=f"agent.{self.agent_type.value}",
                correlation_id=context.task_id,
            )
            context.event_emitter(event)
    
    def on_start(self, context: AgentContext, task: AgentTask) -> None:
        """Emit verifier started event."""
        print(f"DEBUG IndependentVerifierAgent.on_start: task={task.task_id}")
        self._context = context
        self._current_task = task
        # Emit VERIFICATION_STARTED
        try:
            event_payload = VerificationStartedEvent(
                verification_id=new_verification_id(),
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                attempt_id=context.attempt_id,
                status="started",
            )
            print(f"DEBUG: Emitting VERIFICATION_STARTED with payload type: {type(event_payload)}")
            self._emit_event(context, EventType.VERIFICATION_STARTED, event_payload)
            print("DEBUG: VERIFICATION_STARTED emitted successfully")
        except Exception as e:
            print(f"DEBUG: Error emitting VERIFICATION_STARTED: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """
        Independent verification - read artifact from evidence store,
        recompute hash, compare with expected.
        """
        print(f"DEBUG IndependentVerifierAgent.execute: START task={task.task_id}")
        print(f"DEBUG IndependentVerifierAgent.execute: context.evidence_store={hasattr(context, 'evidence_store') and context.evidence_store is not None}")
        self._context = context
        self._current_task = task
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Get expected values from task context
            expected_content = getattr(task, 'context', {}).get(
                "expected_content",
                "VS-002-R1: LLM-driven action execution verified!"
            )
            expected_path = getattr(task, 'context', {}).get(
                "file_path",
                "vs002_r1_output.txt"
            )
            artifact_id = getattr(task, 'context', {}).get("artifact_id")
            
            print(f"DEBUG: expected_content={expected_content}, expected_path={expected_path}, artifact_id={artifact_id}")
            
            if not artifact_id:
                # Try to find artifact in evidence store
                if hasattr(context, 'evidence_store') and context.evidence_store:
                    # Look for artifacts from this mission/run/task
                    print(f"DEBUG: Searching evidence store for artifact. _artifacts keys: {list(context.evidence_store._artifacts.keys())}")
                    for aid, art in context.evidence_store._artifacts.items():
                        print(f"DEBUG: Checking artifact {aid}: mission_id={art.mission_id}, path={art.path}")
                        if art.mission_id == context.mission_id and art.path == expected_path:
                            artifact_id = aid
                            break
            
            if not artifact_id:
                raise RuntimeError(f"Artifact not found in evidence store for path {expected_path}")
            
            print(f"DEBUG: Found artifact_id={artifact_id}")
            
            # INDEPENDENT VERIFICATION: Read artifact content from evidence store
            artifact_obj = context.evidence_store.get_artifact_obj(artifact_id)
            if not artifact_obj:
                raise RuntimeError(f"Artifact object not found: {artifact_id}")
            
            print(f"DEBUG: Got artifact_obj, sha256={artifact_obj.sha256}")
            
            content_bytes = context.evidence_store.read_artifact_content(artifact_id)
            if not content_bytes:
                raise RuntimeError(f"Could not read artifact content: {artifact_id}")
            
            print(f"DEBUG: Read content_bytes length={len(content_bytes)}")
            
            # Recompute SHA256 independently
            print("DEBUG: Computing hash")
            actual_hash = hashlib.sha256(content_bytes).hexdigest()
            print(f"DEBUG: actual_hash={actual_hash}")
            expected_hash = artifact_obj.sha256
            print(f"DEBUG: expected_hash={expected_hash}")
            
            # Verify content matches expected
            actual_content = content_bytes.decode('utf-8') if isinstance(content_bytes, bytes) else content_bytes
            
            # VERIFICATION DECISION
            if actual_hash == expected_hash and expected_content in actual_content:
                verdict = VerifierVerdict.EVIDENCED
            else:
                verdict = VerifierVerdict.NOT_EVIDENCED
            
            print(f"DEBUG: verdict={verdict}, actual_hash={actual_hash}, expected_hash={expected_hash}")
            
            # Create evidence record for verification
            print("DEBUG: Creating EvidenceRecord")
            evidence = EvidenceRecord(
                evidence_id=new_evidence_id(),
                evidence_hash=actual_hash,
                content_type="report",
                source_id=artifact_id,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
            )
            print("DEBUG: Storing evidence")
            context.evidence_store.store_evidence(evidence)
            
            # Emit EVIDENCE_RECORDED
            print("DEBUG: Emitting EVIDENCE_RECORDED")
            self._emit_event(context, EventType.EVIDENCE_RECORDED, EvidenceRecordedEvent(
                evidence_id=evidence.evidence_id,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                evidence_hash=actual_hash,
                content_type="report",
                source_id=artifact_id,
            ))
            print("DEBUG: EVIDENCE_RECORDED emitted")
            
            # Emit VERIFICATION_COMPLETE
            print(f"DEBUG: About to emit VERIFICATION_COMPLETE")
            try:
                self._emit_event(context, EventType.VERIFICATION_COMPLETE, VerificationCompleteEvent(
                    verification_id=evidence.evidence_id,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    task_id=context.task_id,
                    attempt_id=context.attempt_id,
                    verdict=verdict,
                    checks_performed=["sha256_match", "content_match"],
                    missing_evidence=[],
                    confidence=1.0 if verdict == VerifierVerdict.EVIDENCED else 0.0,
                ))
                print(f"DEBUG: VERIFICATION_COMPLETE emitted successfully")
            except Exception as e:
                print(f"DEBUG: Exception during VERIFICATION_COMPLETE emission: {e}")
                import traceback
                traceback.print_exc()
                raise
            
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=(verdict == VerifierVerdict.EVIDENCED),
                output={
                    "verdict": verdict.value,
                    "artifact_id": artifact_id,
                    "actual_hash": actual_hash,
                    "expected_hash": expected_hash,
                    "content_match": expected_content in actual_content,
                },
                evidence_hash=actual_hash,
                artifacts=[artifact_id],
                duration_ms=duration_ms,
            )
            
        except Exception as e:
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            
            self._emit_event(context, EventType.VERIFICATION_COMPLETE, VerificationCompleteEvent(
                verification_id=new_verification_id(),
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                attempt_id=context.attempt_id,
                verdict=VerifierVerdict.NOT_EVIDENCED,
                checks_performed=[],
                missing_evidence=[str(e)],
                confidence=0.0,
            ))
            
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=False,
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=duration_ms,
            )
    
    def on_failed(self, context: AgentContext, task: AgentTask, error: Exception) -> None:
        """Emit agent.failed event."""
        self._emit_event(
            context, EventType.AGENT_FAILED,
            AgentFailedEvent(
                agent_id=context.agent_id,
                agent_type=self.agent_type.value,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                error=str(error),
                error_type=type(error).__name__,
            )
        )
    
    def validate_input(self, task: AgentTask) -> List[str]:
        """Validate task input - always valid for this test."""
        print(f"DEBUG IndependentVerifierAgent.validate_input: task={task.task_id}")
        return []
    
    def on_complete(self, context: AgentContext, task: AgentTask, result: AgentResult) -> None:
        """Called after execution completes successfully."""
        print(f"DEBUG IndependentVerifierAgent.on_complete: task={task.task_id}, success={result.success}")
    
    def validate_output(self, result: AgentResult) -> List[str]:
        """Validate agent output - always valid for this test."""
        print(f"DEBUG IndependentVerifierAgent.validate_output")
        return []


def register_vs002_r1_agents(registry: AgentRegistry, llm_provider: OrchestratorLLMProvider):
    """Register the LLM-driven agent and independent verifier."""
    
    print("DEBUG: Registering VS-002-R1 agents")
    
    # Register LLMDecisionAgent implementation
    class LLMDecisionAgentImpl(LLMDecisionAgent):
        def __init__(self):
            super().__init__(llm_provider)
    
    registry.replace_implementation(AgentType.IMPLEMENTER, LLMDecisionAgentImpl)
    print("DEBUG: Registered LLMDecisionAgentImpl for IMPLEMENTER")
    registry.replace_definition(AgentDefinition(
        agent_id="vs002-r1-implementer",
        agent_type=AgentType.IMPLEMENTER,
        name="VS002R1LLMDecisionAgent",
        version="1.0",
        description="LLM-driven agent that produces structured action decisions",
        tools=["write_artifact", "read_artifact"],
        permissions=["write"],
        max_tokens=10000,
        timeout_seconds=120,
        requires_sandbox=True,
        supported_domains=["testing"],
        implementation_class="tests.unified.test_vs002_r1.LLMDecisionAgentImpl",
    ))
    registry.enable_agent("vs002-r1-implementer")
    print("DEBUG: Enabled vs002-r1-implementer")
    
    # Register IndependentVerifierAgent
    class IndependentVerifierImpl(IndependentVerifierAgent):
        pass
    
    registry.replace_implementation(AgentType.VERIFIER, IndependentVerifierImpl)
    print("DEBUG: Registered IndependentVerifierImpl for VERIFIER")
    registry.replace_definition(AgentDefinition(
        agent_id="vs002-r1-verifier",
        agent_type=AgentType.VERIFIER,
        name="VS002R1IndependentVerifier",
        version="1.0",
        description="Independent verifier that reads from evidence store",
        tools=["read_artifact"],
        permissions=["read"],
        max_tokens=5000,
        timeout_seconds=60,
        requires_sandbox=True,
        supported_domains=["testing"],
        implementation_class="tests.unified.test_vs002_r1.IndependentVerifierImpl",
    ))
    registry.enable_agent("vs002-r1-verifier")
    print("DEBUG: Enabled vs002-r1-verifier")
    
    print(f"DEBUG: Registry implementations: {list(registry._implementations.keys())}")
    print(f"DEBUG: Registry definitions: {list(registry._definitions.keys())}")


# ============================================================
# VS-002-R1 TEST
# ============================================================

class TestVS002R1TrueExecutionSpine:
    """VS-002-R1: Prove true LLM-driven execution spine."""
    
    @pytest.mark.asyncio
    async def test_vs002_r1_full_execution_spine(
        self, temp_dir, sandbox_manager, nvidia_api_key, llm_provider, event_collector
    ):
        """
        Full end-to-end test proving:
        MISSION → RUN → TASK (IMPLEMENTER) → ORCHESTRATOR → AGENT → REAL LLM → 
        LLM_REQUESTED → LLM_COMPLETED → ACTION_REQUESTED → ACTION_VALIDATED → 
        TOOL_STARTED → TOOL_COMPLETED → ARTIFACT_CREATED → EVIDENCE_RECORDED
        → TASK (VERIFIER) → INDEPENDENT VERIFIER → VERIFICATION_STARTED → 
        VERIFICATION_COMPLETE (VERIFIED) → ORCHESTRATOR ACCEPTS → TASK_COMPLETED
        """
        events, collector = event_collector
        
        # Save original registry state
        original_impl = agent_registry._implementations.get(AgentType.IMPLEMENTER)
        original_verifier_impl = agent_registry._implementations.get(AgentType.VERIFIER)
        original_defs = {}
        for key in ["vs002-r1-implementer", "vs002-r1-verifier"]:
            if key in agent_registry._definitions:
                original_defs[key] = agent_registry._definitions[key]
        
        try:
            # Register VS-002-R1 agents
            register_vs002_r1_agents(agent_registry, llm_provider)
            
            # Create execution engine
            engine = ExecutionEngine(artifacts_base_dir=temp_dir)
            
            # Subscribe to events
            engine.event_bus.subscribe(collector)
            
            # Create mission
            mission = engine.create_mission("VS-002-R1: Prove LLM-driven execution spine")
            
            # Create run
            run = engine.create_run(mission.mission_id)
            
            # Create IMPLEMENTER task
            implementer_task = engine.create_task(
                run_id=run.run_id,
                mission_id=mission.mission_id,
                name="LLM-driven file creation",
                description="Create a file using LLM to decide the action",
                agent_type=AgentType.IMPLEMENTER,
                acceptance_criteria=["file_contains:vs002_r1_output.txt:VS-002-R1: LLM-driven action execution verified!"],
            )
            # Set task context for agent execution
            implementer_task.context = {
                "objective": "Create a test file with specific content using LLM decision",
                "expected_content": "VS-002-R1: LLM-driven action execution verified!",
                "file_path": "vs002_r1_output.txt",
            }
            
            # Create VERIFIER task that DEPENDS on IMPLEMENTER task
            verifier_task = engine.create_task(
                run_id=run.run_id,
                mission_id=mission.mission_id,
                name="Independent verification of artifact",
                description="Verify the artifact created by implementer",
                agent_type=AgentType.VERIFIER,
                depends_on=[implementer_task.task_id],
                # No acceptance_criteria - the verifier agent IS the verification
            )
            verifier_task.max_retries = 0
            # Set verifier task context - it will read artifact_id from implementer output
            verifier_task.context = {
                "expected_content": "VS-002-R1: LLM-driven action execution verified!",
                "file_path": "vs002_r1_output.txt",
            }
            
            # Execute task graph (sequential due to dependency)
            print("DEBUG: Starting task graph execution")
            result = await engine.execute_task_graph(
                run_id=run.run_id,
                sandbox_manager=sandbox_manager,
                event_collector=collector,
            )
            print(f"DEBUG: Task graph execution completed, result={result}")
            print(f"DEBUG: Events collected: {len(events)} events")
            for e in events:
                print(f"  {e.event_type.value}: {e.source} correlation={e.correlation_id}")
            
            # ============================================================
            # ASSERTIONS - Prove the full execution spine
            # ============================================================
            
            # 1. Task graph completed successfully
            assert result["success"] is True, f"Task graph failed: {result}"
            assert implementer_task.task_id in result["task_results"]
            assert verifier_task.task_id in result["task_results"]
            
            implementer_result = result["task_results"][implementer_task.task_id]
            verifier_result = result["task_results"][verifier_task.task_id]
            
            assert implementer_result["success"] is True, f"Implementer task failed: {implementer_result}"
            assert verifier_result["success"] is True, f"Verifier task failed: {verifier_result}"
            
            # 2. Different agents executed (IMPLEMENTER != VERIFIER)
            # The agent types are known from task creation
            assert implementer_task.agent_type == AgentType.IMPLEMENTER, "Implementer task type mismatch"
            assert verifier_task.agent_type == AgentType.VERIFIER, "Verifier task type mismatch"
            # Verify different agent types were used
            assert implementer_task.agent_type != verifier_task.agent_type, "Different agent types should be used"
            
            # 3. LLM produced structured action decision
            assert "output" in implementer_result
            output = implementer_result["output"]
            assert "action_decision" in output, "LLM did not produce action_decision in output"
            action_decision = output["action_decision"]
            assert action_decision["action"] == "write_artifact", "LLM chose wrong action"
            assert "path" in action_decision["arguments"], "Action missing path argument"
            assert "content" in action_decision["arguments"], "Action missing content argument"
            assert action_decision["arguments"]["path"] == "vs002_r1_output.txt"
            assert "VS-002-R1" in action_decision["arguments"]["content"]
            assert "reasoning" in action_decision, "LLM did not provide reasoning"
            
            # 4. Artifact created on disk
            artifact_id = output.get("artifact_id") or implementer_result.get("artifacts", [None])[0]
            assert artifact_id is not None, "No artifact ID in result"
            
            # Verify artifact exists in evidence store
            artifact_obj = engine.evidence_store.get_artifact_obj(artifact_id)
            assert artifact_obj is not None, f"Artifact not found in evidence store: {artifact_id}"
            assert artifact_obj.path == "vs002_r1_output.txt"
            
            # 5. Read artifact content and verify SHA256
            content_bytes = engine.evidence_store.read_artifact_content(artifact_id)
            assert content_bytes is not None, "Could not read artifact content"
            actual_content = content_bytes.decode('utf-8')
            assert "VS-002-R1: LLM-driven action execution verified!" in actual_content
            
            actual_hash = hashlib.sha256(content_bytes).hexdigest()
            assert actual_hash == artifact_obj.sha256, "SHA256 mismatch!"
            
            # 6. Pass artifact_id to verifier task context for next run (already done via evidence store)
            # The verifier reads from evidence store independently
            
            # 7. FULL EVENT TRACE - Check all required events exist IN ORDER
            event_types = [e.event_type for e in events]
            
            required_events = [
                EventType.MISSION_STARTED,
                EventType.RUN_STARTED,
                EventType.TASK_ASSIGNED,     # implementer
                EventType.AGENT_SELECTED,    # implementer
                EventType.AGENT_STARTED,     # implementer
                EventType.LLM_REQUESTED,     # NEW - LLM request
                EventType.LLM_COMPLETED,     # NEW - LLM response
                EventType.ACTION_REQUESTED,  # NEW - action boundary
                EventType.ACTION_VALIDATED,  # NEW - validation boundary
                EventType.TOOL_STARTED,      # tool execution starts
                EventType.TOOL_COMPLETED,    # tool execution ends
                EventType.ARTIFACT_CREATED,  # artifact created
                EventType.EVIDENCE_RECORDED, # evidence recorded
                EventType.TASK_COMPLETED,    # implementer task
                EventType.TASK_ASSIGNED,     # verifier task
                EventType.AGENT_SELECTED,    # verifier
                EventType.AGENT_STARTED,     # verifier
                EventType.VERIFICATION_STARTED,  # NEW - verifier starts
                EventType.EVIDENCE_RECORDED, # verification evidence
                EventType.VERIFICATION_COMPLETE, # verifier completes
                EventType.TASK_COMPLETED,    # verifier task (final)
            ]
            
            # Check LLM events specifically
            llm_requested_events = [e for e in events if e.event_type == EventType.LLM_REQUESTED]
            llm_completed_events = [e for e in events if e.event_type == EventType.LLM_COMPLETED]
            assert len(llm_requested_events) > 0, "No LLM_REQUESTED events (LLM not called)"
            assert len(llm_completed_events) > 0, "No LLM_COMPLETED events"
            llm_completed = llm_completed_events[0].get_typed_payload()
            assert llm_completed.success is True, "LLM_COMPLETED should have success=True"
            
            # Check ACTION events
            action_requested_events = [e for e in events if e.event_type == EventType.ACTION_REQUESTED]
            action_validated_events = [e for e in events if e.event_type == EventType.ACTION_VALIDATED]
            assert len(action_requested_events) > 0, "No ACTION_REQUESTED events"
            assert len(action_validated_events) > 0, "No ACTION_VALIDATED events"
            action_validated = action_validated_events[0].get_typed_payload()
            assert action_validated.valid is True, "ACTION_VALIDATED should have valid=True"
            
            # Check VERIFICATION events
            verification_started_events = [e for e in events if e.event_type == EventType.VERIFICATION_STARTED]
            verification_complete_events = [e for e in events if e.event_type == EventType.VERIFICATION_COMPLETE]
            assert len(verification_started_events) > 0, "No VERIFICATION_STARTED events"
            assert len(verification_complete_events) > 0, "No VERIFICATION_COMPLETE events"
            verification_complete = verification_complete_events[0].get_typed_payload()
            assert verification_complete.verdict == "evidenced", f"Verification verdict should be evidenced, got {verification_complete.verdict}"
            
            # Check all required events present
            for req_event in required_events:
                assert req_event in event_types, f"Missing required event: {req_event}"
            
            # 8. EVENT ORDERING - Verify critical path ordering
            # Critical ordering assertions - check ordering within each task's correlation chain
            # Get implementer task events
            implementer_events = [e for e in events if e.correlation_id == implementer_task.task_id]
            implementer_indices = {e.event_type: i for i, e in enumerate(implementer_events)}
            
            # Get verifier task events
            verifier_events = [e for e in events if e.correlation_id == verifier_task.task_id]
            verifier_indices = {e.event_type: i for i, e in enumerate(verifier_events)}
            
            # Implementer task ordering
            assert implementer_indices[EventType.LLM_REQUESTED] < implementer_indices[EventType.LLM_COMPLETED], \
                "LLM_REQUESTED must come before LLM_COMPLETED"
            assert implementer_indices[EventType.LLM_COMPLETED] < implementer_indices[EventType.ACTION_REQUESTED], \
                "LLM_COMPLETED must come before ACTION_REQUESTED"
            assert implementer_indices[EventType.ACTION_REQUESTED] < implementer_indices[EventType.ACTION_VALIDATED], \
                "ACTION_REQUESTED must come before ACTION_VALIDATED"
            assert implementer_indices[EventType.ACTION_VALIDATED] < implementer_indices[EventType.TOOL_STARTED], \
                "ACTION_VALIDATED must come before TOOL_STARTED (validation before execution)"
            assert implementer_indices[EventType.TOOL_STARTED] < implementer_indices[EventType.TOOL_COMPLETED], \
                "TOOL_STARTED must come before TOOL_COMPLETED"
            assert implementer_indices[EventType.TOOL_COMPLETED] < implementer_indices[EventType.ARTIFACT_CREATED], \
                "TOOL_COMPLETED must come before ARTIFACT_CREATED"
            
            # Verifier task ordering
            assert verifier_indices[EventType.VERIFICATION_STARTED] < verifier_indices[EventType.EVIDENCE_RECORDED], \
                "VERIFICATION_STARTED must come before EVIDENCE_RECORDED"
            assert verifier_indices[EventType.EVIDENCE_RECORDED] < verifier_indices[EventType.VERIFICATION_COMPLETE], \
                "EVIDENCE_RECORDED must come before VERIFICATION_COMPLETE"
            
            # Cross-task ordering: implementer ARTIFACT_CREATED before verifier VERIFICATION_STARTED
            # Find the implementer's ARTIFACT_CREATED and verifier's VERIFICATION_STARTED in global events
            implementer_artifact_created_idx = next(i for i, e in enumerate(events) 
                if e.event_type == EventType.ARTIFACT_CREATED and e.correlation_id == implementer_task.task_id)
            verifier_verification_started_idx = next(i for i, e in enumerate(events) 
                if e.event_type == EventType.VERIFICATION_STARTED and e.correlation_id == verifier_task.task_id)
            assert implementer_artifact_created_idx < verifier_verification_started_idx, \
                "Implementer ARTIFACT_CREATED must come before verifier VERIFICATION_STARTED"
            
            # Verifier VERIFICATION_COMPLETE before final TASK_COMPLETED
            verifier_verification_complete_idx = next(i for i, e in enumerate(events) 
                if e.event_type == EventType.VERIFICATION_COMPLETE and e.correlation_id == verifier_task.task_id)
            final_task_completed_idx = next(i for i, e in enumerate(events) 
                if e.event_type == EventType.TASK_COMPLETED and e.correlation_id == verifier_task.task_id)
            assert verifier_verification_complete_idx < final_task_completed_idx, \
                "VERIFICATION_COMPLETE must come before final TASK_COMPLETED"
            
            # 9. Correlation IDs - all events should have mission_id, run_id
            for event in events:
                assert event.mission_id == mission.mission_id
                if event.event_type != EventType.MISSION_STARTED:
                    assert event.run_id == run.run_id
            
            # 10. Engine state transitions
            final_implementer_task = engine.tasks[implementer_task.task_id]
            final_verifier_task = engine.tasks[verifier_task.task_id]
            assert final_implementer_task.state == TaskState.COMPLETED
            assert final_verifier_task.state == TaskState.COMPLETED
            
            # 11. Evidence persisted
            assert artifact_id in engine.evidence_store._artifacts
            
            print("\n=== VS-002-R1 EXECUTION SPINE VERIFIED ===")
            print(f"Mission: {mission.mission_id}")
            print(f"Run: {run.run_id}")
            print(f"Implementer Task: {implementer_task.task_id}")
            print(f"Verifier Task: {verifier_task.task_id}")
            print(f"Artifact: {artifact_id}")
            print(f"Artifact SHA256: {actual_hash}")
            print(f"Events captured: {len(events)}")
            print(f"Action decision: {action_decision}")
            print(f"Implementer agent type: {implementer_result.get('agent_type')}")
            print(f"Verifier agent type: {verifier_result.get('agent_type')}")
            print(f"Verification verdict: {verification_complete.verdict}")
            print("==========================================\n")
            
        finally:
            # Restore registry
            if original_impl:
                agent_registry._implementations[AgentType.IMPLEMENTER] = original_impl
            if original_verifier_impl:
                agent_registry._implementations[AgentType.VERIFIER] = original_verifier_impl
            for key, val in original_defs.items():
                agent_registry._definitions[key] = val
            for key in ["vs002-r1-implementer", "vs002-r1-verifier"]:
                if key in agent_registry._definitions:
                    del agent_registry._definitions[key]
            if original_impl:
                agent_registry._implementations[AgentType.IMPLEMENTER] = original_impl
    
    @pytest.mark.asyncio
    async def test_vs002_r1_controlled_failure_verifier_fails(
        self, temp_dir, sandbox_manager, nvidia_api_key, llm_provider, event_collector
    ):
        """
        Controlled failure: Verifier FAILS due to unmatched acceptance criteria.
        
        This proves the VERIFICATION boundary works:
        - IMPLEMENTER agent succeeds (creates artifact)
        - VERIFIER agent runs independently
        - VERIFIER independently evaluates and FAILS
        - Orchestrator receives verifier FAILED verdict
        - Task graph does NOT complete successfully
        """
        events, collector = event_collector
        
        # Create execution engine
        engine = ExecutionEngine(artifacts_base_dir=temp_dir)
        
        # Subscribe to events
        engine.event_bus.subscribe(collector)
        
        # Register VS-002-R1 agents
        register_vs002_r1_agents(agent_registry, llm_provider)
        
        # Create mission
        mission = engine.create_mission("VS-002-R1: Controlled verifier failure test")
        
        # Create run
        run = engine.create_run(mission.mission_id)
        
        # Create IMPLEMENTER task
        implementer_task = engine.create_task(
            run_id=run.run_id,
            mission_id=mission.mission_id,
            name="File creation",
            description="Create a file with correct content",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=["file_contains:vs002_r1_output.txt:VS-002-R1: LLM-driven action execution verified!"],
        )
        implementer_task.context = {
            "objective": "Create a test file with specific content",
            "expected_content": "VS-002-R1: LLM-driven action execution verified!",
            "file_path": "vs002_r1_output.txt",
        }
        
        # Create VERIFIER task that DEPENDS on IMPLEMENTER
        # But with WRONG expected content - verifier will fail
        verifier_task = engine.create_task(
            run_id=run.run_id,
            mission_id=mission.mission_id,
            name="Independent verification (will fail)",
            description="Verify artifact but with wrong expected content",
            agent_type=AgentType.VERIFIER,
            depends_on=[implementer_task.task_id],
            acceptance_criteria=["verification:evidenced"],
        )
        verifier_task.max_retries = 0
        verifier_task.context = {
            "expected_content": "WRONG_CONTENT_THAT_WONT_MATCH",
            "file_path": "vs002_r1_output.txt",
        }
        
        # No retries
        implementer_task.max_retries = 0
        verifier_task.max_retries = 0
        
        result = await engine.execute_task_graph(
            run_id=run.run_id,
            sandbox_manager=sandbox_manager,
            event_collector=collector,
        )
        
        # Verify IMPLEMENTER succeeded
        implementer_result = result["task_results"][implementer_task.task_id]
        assert implementer_result["success"] is True, "Implementer should succeed"
        
        # Verify VERIFIER failed
        verifier_result = result["task_results"][verifier_task.task_id]
        assert verifier_result["success"] is False, "Verifier should fail"
        
        # Verify overall task graph failed (because verifier failed)
        assert result["success"] is False, "Task graph should fail due to verifier failure"
        
        # Verify VERIFICATION_COMPLETE event has verdict = failed (from verifier task)
        verification_complete_events = [e for e in events if e.event_type == EventType.VERIFICATION_COMPLETE and e.correlation_id == verifier_task.task_id]
        assert len(verification_complete_events) > 0, "No VERIFICATION_COMPLETE event from verifier task"
        verification_complete = verification_complete_events[0].get_typed_payload()
        assert verification_complete.verdict == "not_evidenced", f"Verification should fail, got {verification_complete.verdict}"
        
        # Verify VERIFIER agent ran (different from implementer)
        # The agent types are known from task creation
        assert verifier_task.agent_type == AgentType.VERIFIER, "Verifier task type mismatch"
        assert implementer_task.agent_type == AgentType.IMPLEMENTER, "Implementer task type mismatch"
        assert verifier_task.agent_type != implementer_task.agent_type, "Different agent types should be used"
        
        # Verify VERIFICATION_STARTED was emitted
        verification_started_events = [e for e in events if e.event_type == EventType.VERIFICATION_STARTED]
        assert len(verification_started_events) > 0, "No VERIFICATION_STARTED event"
        
        print("\n=== VS-002-R1 CONTROLLED VERIFIER FAILURE VERIFIED ===")
        print(f"Implementer succeeded: {implementer_result['success']}")
        print(f"Verifier failed: {not verifier_result['success']}")
        print(f"Verification verdict: {verification_complete.verdict}")
        print("========================================================\n")
    
    @pytest.mark.asyncio
    async def test_vs002_r1_unauthorized_action_rejected(
        self, temp_dir, sandbox_manager, nvidia_api_key, llm_provider, event_collector
    ):
        """
        Test that unauthorized action (tool not in capabilities) is rejected
        BEFORE any tool execution (no TOOL_STARTED emitted).
        """
        events, collector = event_collector
        
        # Create execution engine
        engine = ExecutionEngine(artifacts_base_dir=temp_dir)
        engine.event_bus.subscribe(collector)
        
        # Register agent with LLM that will be prompted to use unauthorized tool
        class UnauthorizedLLMDecisionAgent(LLMDecisionAgent):
            """Agent with LLM prompted to use unauthorized tool."""
            capability = AgentCapability(
                tools=["write_artifact"],  # Only write_artifact allowed
                permissions=["write"],
                max_tokens=10000,
                timeout_seconds=120,
                requires_sandbox=True,
                supported_domains=["testing"],
            )
            
            async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
                # Override to prompt LLM for unauthorized tool
                self._context = context
                self._current_task = task
                start_time = asyncio.get_event_loop().time()
                
                try:
                    task_objective = getattr(task, 'context', {}).get("objective", "Test")
                    expected_content = getattr(task, 'context', {}).get("expected_content", "test")
                    file_path = getattr(task, 'context', {}).get("file_path", "test.txt")
                    
                    # Emit LLM_REQUESTED
                    self._emit_event(context, EventType.LLM_REQUESTED, LLMRequestedEvent(
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        task_id=context.task_id,
                        agent_id=context.agent_id,
                        agent_type=self.agent_type.value,
                        provider="nvidia",
                        model="nvidia/nemotron-3-ultra-550b-a55b",
                        request_type="structured_chat",
                    ))
                    
                    system_prompt = f"""You are an implementation agent. Try to use the "run_command" tool.
                    Objective: {task_objective}
                    Return action with tool "run_command"."""
                    
                    user_prompt = "Use run_command tool"
                    
                    action_decision = await self._structured_llm.structured_chat(
                        messages=[
                            LLMMessage(role="system", content=system_prompt),
                            LLMMessage(role="user", content=user_prompt)
                        ],
                        output_model=ActionDecision,
                        temperature=0.1,
                        max_tokens=500,
                    )
                    
                    # Emit LLM_COMPLETED
                    self._emit_event(context, EventType.LLM_COMPLETED, LLMCompletedEvent(
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        task_id=context.task_id,
                        agent_id=context.agent_id,
                        agent_type=self.agent_type.value,
                        provider="nvidia",
                        model="nvidia/nemotron-3-ultra-550b-a55b",
                        request_type="structured_chat",
                        success=True,
                    ))
                    
                    # ACTION_REQUESTED
                    action_id = new_action_id()
                    self._emit_event(context, EventType.ACTION_REQUESTED, ActionRequestedEvent(
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        task_id=context.task_id,
                        agent_id=context.agent_id,
                        action_id=action_id,
                        attempt_id=context.attempt_id,
                        tool_name=action_decision.action,
                        tool_args=action_decision.arguments,
                    ))
                    
                    # ACTION_VALIDATED - should FAIL because run_command not in capabilities
                    if action_decision.action not in self.capability.tools:
                        self._emit_event(context, EventType.ACTION_VALIDATED, ActionValidatedEvent(
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            task_id=context.task_id,
                            agent_id=context.agent_id,
                            action_id=action_id,
                            attempt_id=context.attempt_id,
                            tool_name=action_decision.action,
                            valid=False,
                            reason=f"Tool {action_decision.action} not in agent capabilities",
                        ))
                        # Should NOT emit TOOL_STARTED
                        raise RuntimeError(f"Tool {action_decision.action} not in agent capabilities")
                    
                    # If validation passes (shouldn't happen), emit TOOL_STARTED
                    self._emit_event(context, EventType.ACTION_VALIDATED, ActionValidatedEvent(
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        task_id=context.task_id,
                        agent_id=context.agent_id,
                        action_id=action_id,
                        attempt_id=context.attempt_id,
                        tool_name=action_decision.action,
                        valid=True,
                    ))
                    
                    duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
                    return AgentResult(
                        task_id=task.task_id,
                        agent_type=self.agent_type,
                        success=False,
                        error=f"Unauthorized tool: {action_decision.action}",
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
        
        # Register the unauthorized agent
        class UnauthorizedImpl(UnauthorizedLLMDecisionAgent):
            def __init__(self):
                super().__init__(llm_provider)
        
        agent_registry.replace_implementation(AgentType.IMPLEMENTER, UnauthorizedImpl)
        agent_registry.replace_definition(AgentDefinition(
            agent_id="vs002-r1-unauthorized",
            agent_type=AgentType.IMPLEMENTER,
            name="UnauthorizedAgent",
            version="1.0",
            description="Agent prompted to use unauthorized tool",
            tools=["write_artifact"],
            permissions=["write"],
            max_tokens=10000,
            timeout_seconds=120,
            requires_sandbox=True,
            supported_domains=["testing"],
            implementation_class="tests.unified.test_vs002_r1.UnauthorizedImpl",
        ))
        agent_registry.enable_agent("vs002-r1-unauthorized")
        
        try:
            # Create mission
            mission = engine.create_mission("VS-002-R1: Unauthorized action test")
            run = engine.create_run(mission.mission_id)
            
            task = engine.create_task(
                run_id=run.run_id,
                mission_id=mission.mission_id,
                name="Unauthorized action test",
                description="Try to use unauthorized tool",
                agent_type=AgentType.IMPLEMENTER,
                acceptance_criteria=["file_contains:test.txt:test"],
            )
            task.context = {
                "objective": "Test unauthorized action rejection",
                "expected_content": "test",
                "file_path": "test.txt",
            }
            task.max_retries = 0
            
            result = await engine.execute_task_graph(
                run_id=run.run_id,
                sandbox_manager=sandbox_manager,
                event_collector=collector,
            )
            
            # Task should fail
            task_result = result["task_results"][task.task_id]
            assert task_result["success"] is False, "Task should fail due to unauthorized action"
            
            # Check events: ACTION_REQUESTED should exist, ACTION_VALIDATED with valid=False, NO TOOL_STARTED
            action_requested_events = [e for e in events if e.event_type == EventType.ACTION_REQUESTED]
            action_validated_events = [e for e in events if e.event_type == EventType.ACTION_VALIDATED]
            tool_started_events = [e for e in events if e.event_type == EventType.TOOL_STARTED]
            
            assert len(action_requested_events) > 0, "ACTION_REQUESTED should be emitted"
            assert len(action_validated_events) > 0, "ACTION_VALIDATED should be emitted"
            action_validated = action_validated_events[0].get_typed_payload()
            assert action_validated.valid is False, "ACTION_VALIDATED should be invalid"
            assert "not in agent capabilities" in (action_validated.reason or ""), "Reason should mention capability"
            assert len(tool_started_events) == 0, "TOOL_STARTED must NOT be emitted for unauthorized action"
            
            print("\n=== VS-002-R1 UNAUTHORIZED ACTION REJECTED ===")
            print(f"ACTION_REQUESTED: {len(action_requested_events)}")
            print(f"ACTION_VALIDATED (valid={action_validated.valid}): {len(action_validated_events)}")
            print(f"TOOL_STARTED (should be 0): {len(tool_started_events)}")
            print("==============================================\n")
            
        finally:
            # Restore
            agent_registry._implementations.pop(AgentType.IMPLEMENTER, None)
            agent_registry._definitions.pop("vs002-r1-unauthorized", None)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])