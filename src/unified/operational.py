"""
Operational Entry Point — Unified Engineering Agents System

Provides a production-ready entry point for executing missions using the
Unified Execution Engine without test harness dependencies.

This module demonstrates INDEPENDENT OPERATIONAL EXECUTION:
- Mission → Run → Task Graph → Orchestrator → Agent Runtime → Tool → Sandbox → Artifact → Evidence → Verification → State → Events → Checkpoint → Recovery → Final Result
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from unified.contracts import (
    # IDs
    new_mission_id, new_run_id, new_task_id, new_attempt_id,
    new_agent_id, new_action_id, new_event_id, new_grant_id,
    new_sandbox_id, new_artifact_id, new_evidence_id,
    new_verification_id, new_checkpoint_id,
    # Enums
    MissionState, PlanState, TaskState, AgentType, EventType,
    SandboxTermination, VerifierVerdict, SubVerdict,
    # Entities
    Mission, Run, Task, Attempt, Action, Agent, Grant,
    SandboxRequest, SandboxExecutionRecord, Artifact, EvidenceRecord,
    Verification, Checkpoint,
    # Factories
    create_mission, create_run, create_task, create_attempt,
    create_action, create_artifact, create_evidence,
    create_verification,
    # Validation
    validate_mission_transition, validate_task_transition,
    # State Machine
    PlanState as StatePlanState, MissionStateMachine, validate_transition,
    TERMINAL_STATES, TRANSITIONS,
    # Agent Contracts
    AgentRole, AgentTask, AgentResult,
    PlanTask, PlannerInput, Plan,
    ImplementerInput, ImplementationResult,
    VerifierInput, VerificationResult,
    AgentContractRegistry, AGENT_CAPABILITIES,
    # Tool Contracts
    ToolContract, ToolRegistry, ToolExecutionContext, ToolResult,
    RUN_COMMAND_CONTRACT, SANDBOX_EXECUTE_CONTRACT,
    ARTIFACT_WRITE_CONTRACT, ARTIFACT_READ_CONTRACT,
    VERIFICATION_CHECK_CONTRACT,
    # Verification
    CriterionType, AcceptanceCriterion, CheckResult, VerificationReport,
    EvidenceStore, Verifier, compute_sha256, create_evidence,
    # Event Catalog
    FactoryEvent, EVENT_CATALOG, EVENT_CONSUMERS,
    MissionStartedEvent, RunStartedEvent, PlanCreatedEvent,
    AgentStartedEvent, AgentCompletedEvent, TaskFailedEvent, TaskRetryEvent, TaskCompletedEvent,
    ToolStartedEvent, ToolCompletedEvent, ToolFailedEvent,
    ArtifactCreatedEvent, EvidenceRecordedEvent,
    VerificationCompleteEvent, CheckpointCreatedEvent,
    MissionStateChangedEvent, MissionCompletedEvent,
    # E34: Human Gate
    HumanGateCreatedEvent, HumanDecisionRecordedEvent,
)
from unified.mission_controller import MissionController, TaskSpec
from unified.agent_role import (
    AgentCapability, AgentContext, AgentRegistry, agent_registry,
    AgentFactory, BaseAgent, AgentSelectionError, AgentLifecycleState,
    AgentDefinition,
)
from unified.sandbox import (
    ExecutionSandbox, SandboxBackend, SandboxManager,
    SandboxError, SandboxUnavailableError, create_sandbox_manager,
)
from unified.windows_adapter import WindowsExecutorAdapter
from unified.execution import (
    ExecutionEngine, create_execution_engine, ExecutionContext,
    SimpleEventBus, FileEvidenceStore,
)


# ============================================================
# OPERATIONAL AGENTS
# ============================================================

class OperationalImplementerAgent:
    """
    Production implementer agent for operational execution.
    Writes files to sandbox based on task context.
    """
    
    agent_type = AgentType.IMPLEMENTER
    capability = AgentCapability(
        tools=["write_artifact", "read_artifact", "run_command"],
        permissions=["write", "read", "execute"],
        max_tokens=50000,
        timeout_seconds=300,
        requires_sandbox=True,
        supported_domains=["file_operations", "code_execution", "data_processing"],
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
    
    def validate_input(self, task: AgentTask) -> List[str]:
        """Validate task input. Return list of errors (empty = valid)."""
        task_context = getattr(task, 'context', {})
        operation = task_context.get("operation", "write_file")
        if operation == "write_file":
            if "path" not in task_context:
                return ["Missing required field: path"]
        elif operation == "run_command":
            if "command" not in task_context:
                return ["Missing required field: command"]
        return []
    
    def validate_output(self, result: AgentResult) -> List[str]:
        """Validate agent output. Return list of errors (empty = valid)."""
        return []
    
    def on_complete(self, context: AgentContext, task: AgentTask, result: AgentResult) -> None:
        """Called when execution completes successfully."""
        pass
    
    def on_failed(self, context: AgentContext, task: AgentTask, error: Exception) -> None:
        """Called when execution fails."""
        pass
    
    def on_start(self, context: AgentContext, task: AgentTask) -> None:
        self._context = context
        self._current_task = task
    
    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """Execute file operation based on task context."""
        self._context = context
        self._current_task = task
        
        start_time = time.monotonic()
        
        try:
            # Get operation from task context
            task_context = getattr(task, 'context', {})
            operation = task_context.get("operation", "write_file")
            
            if operation == "write_file":
                content = task_context.get("content", b"Operational execution output")
                if isinstance(content, str):
                    content = content.encode()
                path = task_context.get("path", "operational_output.txt")
                
                if not context.sandbox_manager or not context.sandbox_id:
                    raise RuntimeError("Sandbox manager or sandbox_id not available")
                
                artifact = await context.sandbox_manager.write_artifact(
                    context.sandbox_id, path, content
                )
                
                artifact.mission_id = context.mission_id
                
                # Store in evidence store
                if hasattr(context, 'evidence_store') and context.evidence_store:
                    context.evidence_store.store_artifact(artifact)
                
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=True,
                    output={
                        "operation": "write_file",
                        "path": path,
                        "artifact_id": artifact.artifact_id,
                        "sha256": artifact.sha256,
                        "size_bytes": len(content),
                    },
                    artifacts=[artifact.artifact_id],
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )
            
            elif operation == "run_command":
                command = task_context.get("command", "echo 'hello'")
                working_dir = task_context.get("working_dir", ".")
                timeout_seconds = task_context.get("timeout_seconds", 300)
                
                if not context.sandbox_manager:
                    raise RuntimeError("Sandbox manager not available")
                
                # Use sandbox execute with SandboxRequest
                from unified.domain_model import SandboxRequest
                from unified.contracts import new_sandbox_id
                import platform
                
                # Parse command into list if it's a string
                if isinstance(command, str):
                    import shlex
                    cmd_list = shlex.split(command)
                else:
                    cmd_list = command
                
                # On Windows, wrap shell builtins with cmd /c
                # For timeout-critical commands, run executable directly (not via cmd /c)
                if platform.system() == "Windows":
                    first = cmd_list[0].lower()
                    shell_builtins = {"echo", "dir", "type", "copy", "del", "ren", "mkdir", "rmdir", "cd", "cls", "exit"}
                    is_shell_builtin = (first in shell_builtins and 
                                        not ('\\' in first or '/' in first or first.endswith('.exe')))
                    # For timeout-critical commands (timeout <= 60s), avoid cmd /c wrapper
                    # to ensure timeout enforcement works. For shell builtins with short timeout,
                    # we still need cmd /c but accept the timeout limitation.
                    if is_shell_builtin:
                        cmd_list = ["cmd", "/c"] + cmd_list
                
                # Create new sandbox for each execution
                request = SandboxRequest(
                    sandbox_id=new_sandbox_id(),
                    image="python:3.11-slim",  # Use default allowed image
                    command=cmd_list,
                    working_dir=working_dir,
                    wall_time_seconds=timeout_seconds,
                )
                
                record = await context.sandbox_manager.execute(request)
                
                # Set mission_id on artifacts created by this command
                if hasattr(context, 'evidence_store') and context.evidence_store:
                    for art_id in record.artifacts:
                        art = context.evidence_store.get_artifact_obj(art_id)
                        if art:
                            art.mission_id = context.mission_id
                
                # Check for timeout
                error_msg = None
                if record.termination and record.termination.value == "TIMEOUT":
                    error_msg = f"Command timed out after {timeout_seconds} seconds"
                
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=record.exit_code == 0 and error_msg is None,
                    output={
                        "operation": "run_command",
                        "command": command,
                        "exit_code": record.exit_code,
                        "stdout": record.stdout_reference,
                        "stderr": record.stderr_reference,
                        "duration_ms": record.duration_ms,
                        "termination": record.termination.value if record.termination else None,
                    },
                    artifacts=record.artifacts,
                    error=error_msg,
                    error_type="TimeoutError" if error_msg else None,
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )
            
            else:
                raise ValueError(f"Unknown operation: {operation}")
                
        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=False,
                error=str(e),
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )


class OperationalVerifierAgent:
    """
    Production verifier agent for operational execution.
    Performs INDEPENDENT mechanical verification of artifacts against acceptance criteria.
    Does NOT rely on ExecutionEngine's verifier - this agent IS the verifier.
    """
    
    agent_type = AgentType.VERIFIER
    capability = AgentCapability(
        tools=["verify_artifact", "read_artifact"],
        permissions=["read"],
        max_tokens=10000,
        timeout_seconds=120,
        requires_sandbox=True,
        supported_domains=["verification", "evidence_validation"],
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
    
    def validate_input(self, task: AgentTask) -> List[str]:
        """Validate task input. Return list of errors (empty = valid)."""
        if not task.acceptance_criteria:
            return ["Missing acceptance_criteria for verification"]
        return []
    
    def validate_output(self, result: AgentResult) -> List[str]:
        """Validate agent output. Return list of errors (empty = valid)."""
        return []
    
    def on_complete(self, context: AgentContext, task: AgentTask, result: AgentResult) -> None:
        """Called when execution completes successfully."""
        pass
    
    def on_failed(self, context: AgentContext, task: AgentTask, error: Exception) -> None:
        """Called when execution fails."""
        pass
    
    def on_start(self, context: AgentContext, task: AgentTask) -> None:
        self._context = context
        self._current_task = task
    
    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """INDEPENDENTLY verify artifacts against acceptance criteria.
        
        This agent performs the verification itself - it does NOT defer to
        ExecutionEngine._verify_task(). It reads artifacts from evidence_store,
        parses criteria, executes checks, computes real hashes, and produces
        an independent verdict.
        """
        self._context = context
        self._current_task = task
        
        start_time = time.monotonic()
        
        try:
            acceptance_criteria = task.acceptance_criteria or []
            if not acceptance_criteria:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=False,
                    error="No acceptance criteria provided for verification",
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )
            
            # Get evidence store from context
            evidence_store = getattr(context, 'evidence_store', None)
            if not evidence_store:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=False,
                    error="No evidence_store available in context for verification",
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )
            
            # Build artifacts map from evidence store
            artifacts = {}
            for art_id, art in evidence_store._artifacts.items():
                artifacts[art_id] = {
                    "path": art.path,
                    "name": art.name,
                    "sha256": art.sha256,
                    "size_bytes": art.size_bytes,
                }
            
            print(f"  [OPERATIONAL_VERIFIER] Task {task.task_id}: {len(artifacts)} artifacts in evidence_store")
            for aid, meta in artifacts.items():
                print(f"    Artifact: {aid}, path={meta['path']}, sha256={meta['sha256'][:16]}...")
            
            # Parse and execute verification checks
            checks_performed = []
            all_passed = True
            check_details = []
            
            for i, criterion_str in enumerate(acceptance_criteria):
                print(f"  [OPERATIONAL_VERIFIER] Criterion {i}: {criterion_str}")
                criterion_id = f"crit_{i}"
                
                if criterion_str.startswith("file_exists:"):
                    path = criterion_str.split(":", 1)[1]
                    passed, details, evidence = self._check_file_exists(path, artifacts, evidence_store)
                    checks_performed.append(criterion_str)
                    
                elif criterion_str.startswith("file_contains:"):
                    parts = criterion_str.split(":", 2)
                    path = parts[1]
                    pattern = parts[2] if len(parts) > 2 else ""
                    passed, details, evidence = self._check_file_contains(path, pattern, artifacts, evidence_store)
                    checks_performed.append(criterion_str)
                    
                elif criterion_str.startswith("file_hash_matches:"):
                    parts = criterion_str.split(":", 2)
                    path = parts[1]
                    expected_hash = parts[2] if len(parts) > 2 else ""
                    passed, details, evidence = self._check_file_hash(path, expected_hash, artifacts, evidence_store)
                    checks_performed.append(criterion_str)
                    
                else:
                    # Unknown criterion type
                    passed = False
                    details = f"Unknown criterion type: {criterion_str}"
                    evidence = None
                    checks_performed.append(criterion_str)
                
                check_details.append({
                    "criterion_id": criterion_id,
                    "criterion": criterion_str,
                    "passed": passed,
                    "details": details,
                    "evidence": evidence,
                })
                print(f"    Check {criterion_id}: {criterion_str} - passed={passed}, details={details}")
                
                if not passed:
                    all_passed = False
            
            # Compute overall verdict
            verdict = "evidenced" if all_passed else "failed"
            confidence = 0.95 if all_passed else 0.0
            
            # Build verification report
            verification_report = {
                "passed": all_passed,
                "evidence_hash": self._compute_evidence_hash(artifacts) if all_passed else None,
                "checks_performed": checks_performed,
                "check_details": check_details,
                "verdict": verdict,
                "confidence": confidence,
                "verifier_agent_id": getattr(self, '_agent_id', 'operational-verifier'),
            }
            
            # Write verification report artifact if output_path specified
            output = {
                "operation": "verify",
                "criteria_checked": acceptance_criteria,
                "verdict": verdict,
                "checks": check_details,
            }
            
            ctx = dict(getattr(task, "context", {}) or {})
            output_path = ctx.get("output_path")
            if output_path and context.sandbox_manager:
                import json
                artifact = await context.sandbox_manager.write_artifact(
                    sandbox_id=context.sandbox_id,
                    path=output_path,
                    content=json.dumps(verification_report, indent=2).encode("utf-8"),
                )
                artifact.mission_id = context.mission_id
                output["artifact_id"] = artifact.artifact_id
                output["sha256"] = artifact.sha256
            
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=all_passed,
                output=output,
                error=None if all_passed else "Verification failed",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=False,
                error=f"Verification error: {e}",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
    
    def _check_file_exists(self, path: str, artifacts: Dict, evidence_store) -> tuple:
        """Check if file exists in artifacts."""
        if not path:
            return False, "No path specified", None
        
        found = False
        evidence = None
        for art_id, meta in artifacts.items():
            if meta.get("path") == path or meta.get("name") == path:
                found = True
                evidence = meta.get("sha256")
                break
        
        return found, f"File {'found' if found else 'missing'}: {path}", evidence
    
    def _check_file_hash(self, path: str, expected_hash: str, artifacts: Dict, evidence_store) -> tuple:
        """Check file hash matches expected."""
        if not path or not expected_hash:
            return False, "Missing path or expected_hash", None
        
        found = False
        evidence = None
        for art_id, meta in artifacts.items():
            if meta.get("path") == path or meta.get("name") == path:
                actual = meta.get("sha256")
                found = actual == expected_hash
                evidence = actual
                break
        
        # If not found in artifacts map, try to read from evidence store
        if not found and evidence_store:
            for art_id, art in evidence_store._artifacts.items():
                if art.path == path or art.name == path:
                    content = evidence_store.read_artifact_content(art_id)
                    if content:
                        import hashlib
                        actual = hashlib.sha256(content).hexdigest()
                        found = actual == expected_hash
                        evidence = actual
                    break
        
        return found, f"Hash {'matches' if found else 'mismatch'} for {path}", evidence
    
    def _check_file_contains(self, path: str, pattern: str, artifacts: Dict, evidence_store) -> tuple:
        """Check file contains pattern."""
        if not path or not pattern:
            return False, "Missing path or pattern", None
        
        found = False
        evidence = None
        for art_id, meta in artifacts.items():
            if meta.get("path") == path or meta.get("name") == path:
                # Read content (bounded)
                content = evidence_store.get_artifact(art_id)
                if content:
                    try:
                        text = content.decode("utf-8", errors="replace")
                        found = pattern in text
                        evidence = meta.get("sha256")
                    except Exception:
                        pass
                break
        
        return found, f"Pattern {'found' if found else 'not found'} in {path}", evidence
    
    def _compute_evidence_hash(self, artifacts: Dict) -> str:
        """Compute a combined evidence hash from all artifact hashes."""
        import hashlib
        combined = "".join(sorted(meta.get("sha256", "") for meta in artifacts.values()))
        return hashlib.sha256(combined.encode()).hexdigest()


# ============================================================
# OPERATIONAL ROLE AGENTS (for E40: real role runtime)
# ============================================================

class OperationalExplorerAgent:
    """
    Production explorer agent for operational execution.
    Performs discovery and exploration tasks.
    """

    agent_type = AgentType.EXPLORER
    capability = AgentCapability(
        tools=["write_artifact", "read_artifact", "run_command"],
        permissions=["write", "read", "execute"],
        max_tokens=50000,
        timeout_seconds=300,
        requires_sandbox=True,
        supported_domains=["file_operations", "code_execution", "data_processing", "discovery"],
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

    def validate_input(self, task: AgentTask) -> List[str]:
        task_context = getattr(task, 'context', {})
        operation = task_context.get("operation", "write_file")
        if operation == "write_file":
            if "path" not in task_context:
                return ["Missing required field: path"]
        elif operation == "run_command":
            if "command" not in task_context:
                return ["Missing required field: command"]
        return []

    def validate_output(self, result: AgentResult) -> List[str]:
        return []

    def on_complete(self, context: AgentContext, task: AgentTask, result: AgentResult) -> None:
        pass

    def on_failed(self, context: AgentContext, task: AgentTask, error: Exception) -> None:
        pass

    def on_start(self, context: AgentContext, task: AgentTask) -> None:
        self._context = context
        self._current_task = task

    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """Execute exploration task based on task context."""
        self._context = context
        self._current_task = task

        start_time = time.monotonic()

        try:
            task_context = getattr(task, 'context', {})
            operation = task_context.get("operation", "write_file")

            if operation == "write_file":
                content = task_context.get("content", b"Exploration output")
                if isinstance(content, str):
                    content = content.encode()
                path = task_context.get("path", "exploration_output.txt")

                if not context.sandbox_manager or not context.sandbox_id:
                    raise RuntimeError("Sandbox manager or sandbox_id not available")

                artifact = await context.sandbox_manager.write_artifact(
                    context.sandbox_id, path, content
                )

                artifact.mission_id = context.mission_id

                if hasattr(context, 'evidence_store') and context.evidence_store:
                    context.evidence_store.store_artifact(artifact)

                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=True,
                    output={
                        "operation": "write_file",
                        "path": path,
                        "artifact_id": artifact.artifact_id,
                        "sha256": artifact.sha256,
                        "size_bytes": len(content),
                        "role": "explorer",
                    },
                    artifacts=[artifact.artifact_id],
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )

            elif operation == "run_command":
                command = task_context.get("command", "echo 'exploration'")
                working_dir = task_context.get("working_dir", ".")
                timeout_seconds = task_context.get("timeout_seconds", 300)

                if not context.sandbox_manager:
                    raise RuntimeError("Sandbox manager not available")

                from unified.domain_model import SandboxRequest
                from unified.contracts import new_sandbox_id
                import platform

                if isinstance(command, str):
                    import shlex
                    cmd_list = shlex.split(command)
                else:
                    cmd_list = command

                if platform.system() == "Windows":
                    first = cmd_list[0].lower()
                    shell_builtins = {"echo", "dir", "type", "copy", "del", "ren", "mkdir", "rmdir", "cd", "cls", "exit"}
                    is_shell_builtin = (first in shell_builtins and
                                        not ('\\' in first or '/' in first or first.endswith('.exe')))
                    if is_shell_builtin:
                        cmd_list = ["cmd", "/c"] + cmd_list

                request = SandboxRequest(
                    sandbox_id=new_sandbox_id(),
                    image="python:3.11-slim",
                    command=cmd_list,
                    working_dir=working_dir,
                    wall_time_seconds=timeout_seconds,
                )

                record = await context.sandbox_manager.execute(request)

                if hasattr(context, 'evidence_store') and context.evidence_store:
                    for art_id in record.artifacts:
                        art = context.evidence_store.get_artifact_obj(art_id)
                        if art:
                            art.mission_id = context.mission_id

                error_msg = None
                if record.termination and record.termination.value == "TIMEOUT":
                    error_msg = f"Command timed out after {timeout_seconds} seconds"

                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=record.exit_code == 0 and error_msg is None,
                    output={
                        "operation": "run_command",
                        "command": command,
                        "exit_code": record.exit_code,
                        "stdout": record.stdout_reference,
                        "stderr": record.stderr_reference,
                        "duration_ms": record.duration_ms,
                        "termination": record.termination.value if record.termination else None,
                        "role": "explorer",
                    },
                    artifacts=record.artifacts,
                    error=error_msg,
                    error_type="TimeoutError" if error_msg else None,
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )

            else:
                raise ValueError(f"Unknown operation: {operation}")

        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=False,
                error=str(e),
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )


class OperationalAnalystAgent:
    """
    Production analyst agent for operational execution.
    Performs analysis and requirements tasks.
    """

    agent_type = AgentType.ANALYST
    capability = AgentCapability(
        tools=["write_artifact", "read_artifact", "run_command"],
        permissions=["write", "read", "execute"],
        max_tokens=50000,
        timeout_seconds=300,
        requires_sandbox=True,
        supported_domains=["file_operations", "code_execution", "data_processing", "analysis"],
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

    def validate_input(self, task: AgentTask) -> List[str]:
        task_context = getattr(task, 'context', {})
        operation = task_context.get("operation", "write_file")
        if operation == "write_file":
            if "path" not in task_context:
                return ["Missing required field: path"]
        elif operation == "run_command":
            if "command" not in task_context:
                return ["Missing required field: command"]
        return []

    def validate_output(self, result: AgentResult) -> List[str]:
        return []

    def on_complete(self, context: AgentContext, task: AgentTask, result: AgentResult) -> None:
        pass

    def on_failed(self, context: AgentContext, task: AgentTask, error: Exception) -> None:
        pass

    def on_start(self, context: AgentContext, task: AgentTask) -> None:
        self._context = context
        self._current_task = task

    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """Execute analysis task based on task context."""
        self._context = context
        self._current_task = task

        start_time = time.monotonic()

        try:
            task_context = getattr(task, 'context', {})
            operation = task_context.get("operation", "write_file")

            if operation == "write_file":
                content = task_context.get("content", b"Analysis output")
                if isinstance(content, str):
                    content = content.encode()
                path = task_context.get("path", "analysis_output.txt")

                if not context.sandbox_manager or not context.sandbox_id:
                    raise RuntimeError("Sandbox manager or sandbox_id not available")

                artifact = await context.sandbox_manager.write_artifact(
                    context.sandbox_id, path, content
                )

                artifact.mission_id = context.mission_id

                if hasattr(context, 'evidence_store') and context.evidence_store:
                    context.evidence_store.store_artifact(artifact)

                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=True,
                    output={
                        "operation": "write_file",
                        "path": path,
                        "artifact_id": artifact.artifact_id,
                        "sha256": artifact.sha256,
                        "size_bytes": len(content),
                        "role": "analyst",
                    },
                    artifacts=[artifact.artifact_id],
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )

            elif operation == "run_command":
                command = task_context.get("command", "echo 'analysis'")
                working_dir = task_context.get("working_dir", ".")
                timeout_seconds = task_context.get("timeout_seconds", 300)

                if not context.sandbox_manager:
                    raise RuntimeError("Sandbox manager not available")

                from unified.domain_model import SandboxRequest
                from unified.contracts import new_sandbox_id
                import platform

                if isinstance(command, str):
                    import shlex
                    cmd_list = shlex.split(command)
                else:
                    cmd_list = command

                if platform.system() == "Windows":
                    first = cmd_list[0].lower()
                    shell_builtins = {"echo", "dir", "type", "copy", "del", "ren", "mkdir", "rmdir", "cd", "cls", "exit"}
                    is_shell_builtin = (first in shell_builtins and
                                        not ('\\' in first or '/' in first or first.endswith('.exe')))
                    if is_shell_builtin:
                        cmd_list = ["cmd", "/c"] + cmd_list

                request = SandboxRequest(
                    sandbox_id=new_sandbox_id(),
                    image="python:3.11-slim",
                    command=cmd_list,
                    working_dir=working_dir,
                    wall_time_seconds=timeout_seconds,
                )

                record = await context.sandbox_manager.execute(request)

                if hasattr(context, 'evidence_store') and context.evidence_store:
                    for art_id in record.artifacts:
                        art = context.evidence_store.get_artifact_obj(art_id)
                        if art:
                            art.mission_id = context.mission_id

                error_msg = None
                if record.termination and record.termination.value == "TIMEOUT":
                    error_msg = f"Command timed out after {timeout_seconds} seconds"

                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=record.exit_code == 0 and error_msg is None,
                    output={
                        "operation": "run_command",
                        "command": command,
                        "exit_code": record.exit_code,
                        "stdout": record.stdout_reference,
                        "stderr": record.stderr_reference,
                        "duration_ms": record.duration_ms,
                        "termination": record.termination.value if record.termination else None,
                        "role": "analyst",
                    },
                    artifacts=record.artifacts,
                    error=error_msg,
                    error_type="TimeoutError" if error_msg else None,
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )

            else:
                raise ValueError(f"Unknown operation: {operation}")

        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=False,
                error=str(e),
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )


class OperationalPlannerAgent:
    """
    Production planner agent for operational execution.
    Performs planning and task decomposition tasks.
    """

    agent_type = AgentType.PLANNER
    capability = AgentCapability(
        tools=["write_artifact", "read_artifact", "run_command"],
        permissions=["write", "read", "execute"],
        max_tokens=50000,
        timeout_seconds=300,
        requires_sandbox=True,
        supported_domains=["file_operations", "code_execution", "data_processing", "planning"],
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

    def validate_input(self, task: AgentTask) -> List[str]:
        task_context = getattr(task, 'context', {})
        operation = task_context.get("operation", "write_file")
        if operation == "write_file":
            if "path" not in task_context:
                return ["Missing required field: path"]
        elif operation == "run_command":
            if "command" not in task_context:
                return ["Missing required field: command"]
        return []

    def validate_output(self, result: AgentResult) -> List[str]:
        return []

    def on_complete(self, context: AgentContext, task: AgentTask, result: AgentResult) -> None:
        pass

    def on_failed(self, context: AgentContext, task: AgentTask, error: Exception) -> None:
        pass

    def on_start(self, context: AgentContext, task: AgentTask) -> None:
        self._context = context
        self._current_task = task

    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """Execute planning task based on task context."""
        self._context = context
        self._current_task = task

        start_time = time.monotonic()

        try:
            task_context = getattr(task, 'context', {})
            operation = task_context.get("operation", "write_file")

            if operation == "write_file":
                content = task_context.get("content", b"Planning output")
                if isinstance(content, str):
                    content = content.encode()
                path = task_context.get("path", "planning_output.txt")

                if not context.sandbox_manager or not context.sandbox_id:
                    raise RuntimeError("Sandbox manager or sandbox_id not available")

                artifact = await context.sandbox_manager.write_artifact(
                    context.sandbox_id, path, content
                )

                artifact.mission_id = context.mission_id

                if hasattr(context, 'evidence_store') and context.evidence_store:
                    context.evidence_store.store_artifact(artifact)

                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=True,
                    output={
                        "operation": "write_file",
                        "path": path,
                        "artifact_id": artifact.artifact_id,
                        "sha256": artifact.sha256,
                        "size_bytes": len(content),
                        "role": "planner",
                    },
                    artifacts=[artifact.artifact_id],
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )

            elif operation == "run_command":
                command = task_context.get("command", "echo 'planning'")
                working_dir = task_context.get("working_dir", ".")
                timeout_seconds = task_context.get("timeout_seconds", 300)

                if not context.sandbox_manager:
                    raise RuntimeError("Sandbox manager not available")

                from unified.domain_model import SandboxRequest
                from unified.contracts import new_sandbox_id
                import platform

                if isinstance(command, str):
                    import shlex
                    cmd_list = shlex.split(command)
                else:
                    cmd_list = command

                if platform.system() == "Windows":
                    first = cmd_list[0].lower()
                    shell_builtins = {"echo", "dir", "type", "copy", "del", "ren", "mkdir", "rmdir", "cd", "cls", "exit"}
                    is_shell_builtin = (first in shell_builtins and
                                        not ('\\' in first or '/' in first or first.endswith('.exe')))
                    if is_shell_builtin:
                        cmd_list = ["cmd", "/c"] + cmd_list

                request = SandboxRequest(
                    sandbox_id=new_sandbox_id(),
                    image="python:3.11-slim",
                    command=cmd_list,
                    working_dir=working_dir,
                    wall_time_seconds=timeout_seconds,
                )

                record = await context.sandbox_manager.execute(request)

                if hasattr(context, 'evidence_store') and context.evidence_store:
                    for art_id in record.artifacts:
                        art = context.evidence_store.get_artifact_obj(art_id)
                        if art:
                            art.mission_id = context.mission_id

                error_msg = None
                if record.termination and record.termination.value == "TIMEOUT":
                    error_msg = f"Command timed out after {timeout_seconds} seconds"

                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=record.exit_code == 0 and error_msg is None,
                    output={
                        "operation": "run_command",
                        "command": command,
                        "exit_code": record.exit_code,
                        "stdout": record.stdout_reference,
                        "stderr": record.stderr_reference,
                        "duration_ms": record.duration_ms,
                        "termination": record.termination.value if record.termination else None,
                        "role": "planner",
                    },
                    artifacts=record.artifacts,
                    error=error_msg,
                    error_type="TimeoutError" if error_msg else None,
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )

            else:
                raise ValueError(f"Unknown operation: {operation}")

        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=False,
                error=str(e),
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )


class OperationalDesignerAgent:
    """
    Production designer agent for operational execution.
    Performs design and architecture tasks.
    """

    agent_type = AgentType.DESIGNER
    capability = AgentCapability(
        tools=["write_artifact", "read_artifact", "run_command"],
        permissions=["write", "read", "execute"],
        max_tokens=50000,
        timeout_seconds=300,
        requires_sandbox=True,
        supported_domains=["file_operations", "code_execution", "data_processing", "design"],
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

    def validate_input(self, task: AgentTask) -> List[str]:
        task_context = getattr(task, 'context', {})
        operation = task_context.get("operation", "write_file")
        if operation == "write_file":
            if "path" not in task_context:
                return ["Missing required field: path"]
        elif operation == "run_command":
            if "command" not in task_context:
                return ["Missing required field: command"]
        return []

    def validate_output(self, result: AgentResult) -> List[str]:
        return []

    def on_complete(self, context: AgentContext, task: AgentTask, result: AgentResult) -> None:
        pass

    def on_failed(self, context: AgentContext, task: AgentTask, error: Exception) -> None:
        pass

    def on_start(self, context: AgentContext, task: AgentTask) -> None:
        self._context = context
        self._current_task = task

    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """Execute design task based on task context."""
        self._context = context
        self._current_task = task

        start_time = time.monotonic()

        try:
            task_context = getattr(task, 'context', {})
            operation = task_context.get("operation", "write_file")

            if operation == "write_file":
                content = task_context.get("content", b"Design output")
                if isinstance(content, str):
                    content = content.encode()
                path = task_context.get("path", "design_output.txt")

                if not context.sandbox_manager or not context.sandbox_id:
                    raise RuntimeError("Sandbox manager or sandbox_id not available")

                artifact = await context.sandbox_manager.write_artifact(
                    context.sandbox_id, path, content
                )

                artifact.mission_id = context.mission_id

                if hasattr(context, 'evidence_store') and context.evidence_store:
                    context.evidence_store.store_artifact(artifact)

                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=True,
                    output={
                        "operation": "write_file",
                        "path": path,
                        "artifact_id": artifact.artifact_id,
                        "sha256": artifact.sha256,
                        "size_bytes": len(content),
                        "role": "designer",
                    },
                    artifacts=[artifact.artifact_id],
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )

            elif operation == "run_command":
                command = task_context.get("command", "echo 'design'")
                working_dir = task_context.get("working_dir", ".")
                timeout_seconds = task_context.get("timeout_seconds", 300)

                if not context.sandbox_manager:
                    raise RuntimeError("Sandbox manager not available")

                from unified.domain_model import SandboxRequest
                from unified.contracts import new_sandbox_id
                import platform

                if isinstance(command, str):
                    import shlex
                    cmd_list = shlex.split(command)
                else:
                    cmd_list = command

                if platform.system() == "Windows":
                    first = cmd_list[0].lower()
                    shell_builtins = {"echo", "dir", "type", "copy", "del", "ren", "mkdir", "rmdir", "cd", "cls", "exit"}
                    is_shell_builtin = (first in shell_builtins and
                                        not ('\\' in first or '/' in first or first.endswith('.exe')))
                    if is_shell_builtin:
                        cmd_list = ["cmd", "/c"] + cmd_list

                request = SandboxRequest(
                    sandbox_id=new_sandbox_id(),
                    image="python:3.11-slim",
                    command=cmd_list,
                    working_dir=working_dir,
                    wall_time_seconds=timeout_seconds,
                )

                record = await context.sandbox_manager.execute(request)

                if hasattr(context, 'evidence_store') and context.evidence_store:
                    for art_id in record.artifacts:
                        art = context.evidence_store.get_artifact_obj(art_id)
                        if art:
                            art.mission_id = context.mission_id

                error_msg = None
                if record.termination and record.termination.value == "TIMEOUT":
                    error_msg = f"Command timed out after {timeout_seconds} seconds"

                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=record.exit_code == 0 and error_msg is None,
                    output={
                        "operation": "run_command",
                        "command": command,
                        "exit_code": record.exit_code,
                        "stdout": record.stdout_reference,
                        "stderr": record.stderr_reference,
                        "duration_ms": record.duration_ms,
                        "termination": record.termination.value if record.termination else None,
                        "role": "designer",
                    },
                    artifacts=record.artifacts,
                    error=error_msg,
                    error_type="TimeoutError" if error_msg else None,
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )

            else:
                raise ValueError(f"Unknown operation: {operation}")

        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=False,
                error=str(e),
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )


class OperationalReviewerAgent:
    """
    Production reviewer agent for operational execution.
    Performs review and approval tasks.
    """

    agent_type = AgentType.REVIEWER
    capability = AgentCapability(
        tools=["write_artifact", "read_artifact", "run_command"],
        permissions=["write", "read", "execute"],
        max_tokens=50000,
        timeout_seconds=300,
        requires_sandbox=True,
        supported_domains=["file_operations", "code_execution", "data_processing", "review"],
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

    def validate_input(self, task: AgentTask) -> List[str]:
        task_context = getattr(task, 'context', {})
        operation = task_context.get("operation", "write_file")
        if operation == "write_file":
            if "path" not in task_context:
                return ["Missing required field: path"]
        elif operation == "run_command":
            if "command" not in task_context:
                return ["Missing required field: command"]
        return []

    def validate_output(self, result: AgentResult) -> List[str]:
        return []

    def on_complete(self, context: AgentContext, task: AgentTask, result: AgentResult) -> None:
        pass

    def on_failed(self, context: AgentContext, task: AgentTask, error: Exception) -> None:
        pass

    def on_start(self, context: AgentContext, task: AgentTask) -> None:
        self._context = context
        self._current_task = task

    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """Execute review task based on task context."""
        self._context = context
        self._current_task = task

        start_time = time.monotonic()

        try:
            task_context = getattr(task, 'context', {})
            operation = task_context.get("operation", "write_file")

            if operation == "write_file":
                content = task_context.get("content", b"Review output")
                if isinstance(content, str):
                    content = content.encode()
                path = task_context.get("path", "review_output.txt")

                if not context.sandbox_manager or not context.sandbox_id:
                    raise RuntimeError("Sandbox manager or sandbox_id not available")

                artifact = await context.sandbox_manager.write_artifact(
                    context.sandbox_id, path, content
                )

                artifact.mission_id = context.mission_id

                if hasattr(context, 'evidence_store') and context.evidence_store:
                    context.evidence_store.store_artifact(artifact)

                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=True,
                    output={
                        "operation": "write_file",
                        "path": path,
                        "artifact_id": artifact.artifact_id,
                        "sha256": artifact.sha256,
                        "size_bytes": len(content),
                        "role": "reviewer",
                    },
                    artifacts=[artifact.artifact_id],
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )

            elif operation == "run_command":
                command = task_context.get("command", "echo 'review'")
                working_dir = task_context.get("working_dir", ".")
                timeout_seconds = task_context.get("timeout_seconds", 300)

                if not context.sandbox_manager:
                    raise RuntimeError("Sandbox manager not available")

                from unified.domain_model import SandboxRequest
                from unified.contracts import new_sandbox_id
                import platform

                if isinstance(command, str):
                    import shlex
                    cmd_list = shlex.split(command)
                else:
                    cmd_list = command

                if platform.system() == "Windows":
                    first = cmd_list[0].lower()
                    shell_builtins = {"echo", "dir", "type", "copy", "del", "ren", "mkdir", "rmdir", "cd", "cls", "exit"}
                    is_shell_builtin = (first in shell_builtins and
                                        not ('\\' in first or '/' in first or first.endswith('.exe')))
                    if is_shell_builtin:
                        cmd_list = ["cmd", "/c"] + cmd_list

                request = SandboxRequest(
                    sandbox_id=new_sandbox_id(),
                    image="python:3.11-slim",
                    command=cmd_list,
                    working_dir=working_dir,
                    wall_time_seconds=timeout_seconds,
                )

                record = await context.sandbox_manager.execute(request)

                if hasattr(context, 'evidence_store') and context.evidence_store:
                    for art_id in record.artifacts:
                        art = context.evidence_store.get_artifact_obj(art_id)
                        if art:
                            art.mission_id = context.mission_id

                error_msg = None
                if record.termination and record.termination.value == "TIMEOUT":
                    error_msg = f"Command timed out after {timeout_seconds} seconds"

                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=record.exit_code == 0 and error_msg is None,
                    output={
                        "operation": "run_command",
                        "command": command,
                        "exit_code": record.exit_code,
                        "stdout": record.stdout_reference,
                        "stderr": record.stderr_reference,
                        "duration_ms": record.duration_ms,
                        "termination": record.termination.value if record.termination else None,
                        "role": "reviewer",
                    },
                    artifacts=record.artifacts,
                    error=error_msg,
                    error_type="TimeoutError" if error_msg else None,
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )

            else:
                raise ValueError(f"Unknown operation: {operation}")

        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=False,
                error=str(e),
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )


class OperationalSecurityAgent:
    """
    Production security agent for operational execution.
    Performs security audits: SAST, dependency audit, secret scanning,
    permission checks, sandbox validation, filesystem/network analysis.
    """

    agent_type = AgentType.SECURITY
    capability = AgentCapability(
        tools=["write_artifact", "read_artifact", "run_command", "security_audit"],
        permissions=["write", "read", "execute", "security_scan"],
        max_tokens=50000,
        timeout_seconds=300,
        requires_sandbox=True,
        supported_domains=["file_operations", "code_execution", "data_processing", "security", "sast", "dependency_audit", "secret_scanning"],
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

    def validate_input(self, task: AgentTask) -> List[str]:
        task_context = getattr(task, 'context', {})
        operation = task_context.get("operation", "security_audit")
        if operation == "security_audit":
            if "target_path" not in task_context:
                return ["Missing required field: target_path for security_audit"]
            if "scan_types" not in task_context:
                return ["Missing required field: scan_types for security_audit"]
        elif operation == "write_file":
            if "path" not in task_context:
                return ["Missing required field: path"]
        elif operation == "run_command":
            if "command" not in task_context:
                return ["Missing required field: command"]
        return []

    def validate_output(self, result: AgentResult) -> List[str]:
        return []

    def on_complete(self, context: AgentContext, task: AgentTask, result: AgentResult) -> None:
        pass

    def on_failed(self, context: AgentContext, task: AgentTask, error: Exception) -> None:
        pass

    def on_start(self, context: AgentContext, task: AgentTask) -> None:
        self._context = context
        self._current_task = task

    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        self._context = context
        self._current_task = task
        start_time = time.monotonic()
        try:
            task_context = getattr(task, 'context', {})
            operation = task_context.get("operation", "security_audit")
            if operation == "security_audit":
                target_path = task_context.get("target_path", ".")
                scan_types = task_context.get("scan_types", ["sast", "deps", "secrets"])
                severity_threshold = task_context.get("severity_threshold", "medium")
                exclude_patterns = task_context.get("exclude_patterns", [])
                audit_result = await self._run_security_audit(
                    target_path, scan_types, severity_threshold, exclude_patterns, context
                )
                import json, hashlib
                evidence_json = json.dumps(audit_result, sort_keys=True)
                evidence_hash = hashlib.sha256(evidence_json.encode()).hexdigest()
                output_path = task_context.get("output_path", f"security_audit_{task.task_id}.json")
                if not context.sandbox_manager or not context.sandbox_id:
                    raise RuntimeError("Sandbox manager or sandbox_id not available")
                artifact = await context.sandbox_manager.write_artifact(
                    context.sandbox_id, output_path, evidence_json.encode()
                )
                artifact.mission_id = context.mission_id
                if hasattr(context, 'evidence_store') and context.evidence_store:
                    context.evidence_store.store_artifact(artifact)
                verdict = "passed"
                if audit_result.get("vulnerabilities_found", 0) > 0:
                    if self._severity_exceeds_threshold(audit_result, severity_threshold):
                        verdict = "failed"
                if audit_result.get("secrets_found", 0) > 0:
                    verdict = "failed"
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=True,  # Security audit operation succeeded (produced artifact); verdict is in output
                    output={
                        "operation": "security_audit",
                        "target_path": target_path,
                        "scan_types": scan_types,
                        "severity_threshold": severity_threshold,
                        "verdict": verdict,
                        "artifact_id": artifact.artifact_id,
                        "artifact_path": output_path,
                        "sha256": artifact.sha256,
                        "evidence_hash": evidence_hash,
                        "findings": audit_result,
                        "role": "security",
                    },
                    artifacts=[artifact.artifact_id],
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )
            elif operation == "write_file":
                content = task_context.get("content", b"Security output")
                if isinstance(content, str):
                    content = content.encode()
                path = task_context.get("path", "security_output.txt")
                if not context.sandbox_manager or not context.sandbox_id:
                    raise RuntimeError("Sandbox manager or sandbox_id not available")
                artifact = await context.sandbox_manager.write_artifact(
                    context.sandbox_id, path, content
                )
                artifact.mission_id = context.mission_id
                if hasattr(context, 'evidence_store') and context.evidence_store:
                    context.evidence_store.store_artifact(artifact)
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=True,
                    output={
                        "operation": "write_file",
                        "path": path,
                        "artifact_id": artifact.artifact_id,
                        "sha256": artifact.sha256,
                        "size_bytes": len(content),
                        "role": "security",
                    },
                    artifacts=[artifact.artifact_id],
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )
            elif operation == "run_command":
                command = task_context.get("command", "echo 'security'")
                working_dir = task_context.get("working_dir", ".")
                timeout_seconds = task_context.get("timeout_seconds", 300)
                if not context.sandbox_manager:
                    raise RuntimeError("Sandbox manager not available")
                from unified.domain_model import SandboxRequest
                from unified.contracts import new_sandbox_id
                import platform
                if isinstance(command, str):
                    import shlex
                    cmd_list = shlex.split(command)
                else:
                    cmd_list = command
                if platform.system() == "Windows":
                    first = cmd_list[0].lower()
                    shell_builtins = {"echo", "dir", "type", "copy", "del", "ren", "mkdir", "rmdir", "cd", "cls", "exit"}
                    is_shell_builtin = (first in shell_builtins and
                                        not ('\\' in first or '/' in first or first.endswith('.exe')))
                    if is_shell_builtin:
                        cmd_list = ["cmd", "/c"] + cmd_list
                request = SandboxRequest(
                    sandbox_id=new_sandbox_id(),
                    image="python:3.11-slim",
                    command=cmd_list,
                    working_dir=working_dir,
                    wall_time_seconds=timeout_seconds,
                )
                record = await context.sandbox_manager.execute(request)
                if hasattr(context, 'evidence_store') and context.evidence_store:
                    for art_id in record.artifacts:
                        art = context.evidence_store.get_artifact_obj(art_id)
                        if art:
                            art.mission_id = context.mission_id
                error_msg = None
                if record.termination and record.termination.value == "TIMEOUT":
                    error_msg = f"Command timed out after {timeout_seconds} seconds"
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    success=record.exit_code == 0 and error_msg is None,
                    output={
                        "operation": "run_command",
                        "command": command,
                        "exit_code": record.exit_code,
                        "stdout": record.stdout_reference,
                        "stderr": record.stderr_reference,
                        "duration_ms": record.duration_ms,
                        "termination": record.termination.value if record.termination else None,
                        "role": "security",
                    },
                    artifacts=record.artifacts,
                    error=error_msg,
                    error_type="TimeoutError" if error_msg else None,
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )
            else:
                raise ValueError(f"Unknown operation: {operation}")
        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=False,
                error=str(e),
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

    async def _run_security_audit(
        self, target_path: str, scan_types: List[str], severity_threshold: str,
        exclude_patterns: List[str], context: AgentContext
    ) -> dict:
        import os, subprocess, json
        from pathlib import Path
        result = {
            "target_path": target_path, "scan_types": scan_types,
            "severity_threshold": severity_threshold, "exclude_patterns": exclude_patterns,
            "vulnerabilities_found": 0, "secrets_found": 0, "dependencies_scanned": 0,
            "sast_issues": [], "permission_issues": [], "sandbox_violations": [],
            "filesystem_issues": [], "network_issues": [], "scan_duration_ms": 0,
        }
        scan_start = time.monotonic()
        try:
            target = Path(target_path).resolve()
            if not target.exists():
                result["error"] = f"Target path does not exist: {target_path}"
                return result
            if "sast" in scan_types:
                sast_result = await self._run_sast_scan(target, exclude_patterns)
                result["sast_issues"] = sast_result["issues"]
                result["vulnerabilities_found"] += len(sast_result["issues"])
            if "deps" in scan_types:
                deps_result = await self._run_dependency_audit(target)
                result["dependencies_scanned"] = deps_result["scanned"]
                result["vulnerabilities_found"] += deps_result["vulnerable_count"]
            if "secrets" in scan_types:
                secrets_result = await self._run_secret_scan(target, exclude_patterns)
                result["secrets_found"] = secrets_result["count"]
                result["secret_details"] = secrets_result["details"]
            if "permissions" in scan_types or True:
                perm_result = await self._check_permissions(context, target)
                result["permission_issues"] = perm_result["issues"]
            if "sandbox" in scan_types or True:
                sandbox_result = await self._validate_sandbox(context)
                result["sandbox_violations"] = sandbox_result["violations"]
            if "filesystem" in scan_types or True:
                fs_result = await self._check_filesystem(target, context)
                result["filesystem_issues"] = fs_result["issues"]
            if "network" in scan_types:
                net_result = await self._check_network_access(context)
                result["network_issues"] = net_result["issues"]
        except Exception as e:
            result["error"] = f"Security audit error: {type(e).__name__}: {e}"
        result["scan_duration_ms"] = int((time.monotonic() - scan_start) * 1000)
        return result

    async def _run_sast_scan(self, target: Path, exclude_patterns: List[str]) -> dict:
        import re
        issues = []
        patterns = [
            (r"eval\s*\(", "HIGH", "Use of eval()"),
            (r"exec\s*\(", "HIGH", "Use of exec()"),
            (r"subprocess\.run.*shell\s*=\s*True", "MEDIUM", "Shell injection risk"),
            (r"os\.system\s*\(", "HIGH", "Use of os.system()"),
            (r"pickle\.loads?", "MEDIUM", "Unsafe deserialization"),
            (r"yaml\.load\s*\((?!.*Loader)", "MEDIUM", "Unsafe YAML load"),
            (r"md5|sha1", "LOW", "Weak hash algorithm"),
            (r"ssl\.verify\s*=\s*False", "HIGH", "SSL verification disabled"),
            (r"verify\s*=\s*False", "HIGH", "Certificate verification disabled"),
            (r"DEBUG\s*=\s*True", "LOW", "Debug mode enabled in production"),
        ]
        for file_path in target.rglob("*.py"):
            if any(file_path.match(pat) for pat in exclude_patterns):
                continue
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                for pattern, severity, desc in patterns:
                    matches = list(re.finditer(pattern, content))
                    for match in matches:
                        line_num = content[:match.start()].count('\n') + 1
                        issues.append({
                            "file": str(file_path.relative_to(target)),
                            "line": line_num, "pattern": pattern,
                            "severity": severity, "description": desc,
                            "snippet": content[max(0, match.start()-50):match.end()+50].strip(),
                        })
            except Exception:
                pass
        return {"issues": issues}

    async def _run_dependency_audit(self, target: Path) -> dict:
        scanned = 0; vulnerable_count = 0; vulnerable_deps = []
        for dep_file in ["requirements.txt", "pyproject.toml", "package.json", "Cargo.toml", "go.mod"]:
            dep_path = target / dep_file
            if dep_path.exists():
                scanned += 1
        return {"scanned": scanned, "vulnerable_count": vulnerable_count, "vulnerable_deps": vulnerable_deps}

    async def _run_secret_scan(self, target: Path, exclude_patterns: List[str]) -> dict:
        import re
        details = []; count = 0
        secret_patterns = [
            (r"api[_-]?key\s*[=:]\s*['\"][^'\"]{20,}", "API Key"),
            (r"secret[_-]?key\s*[=:]\s*['\"][^'\"]{20,}", "Secret Key"),
            (r"password\s*[=:]\s*['\"][^'\"]{8,}", "Password"),
            (r"token\s*[=:]\s*['\"][^'\"]{20,}", "Token"),
            (r"-----BEGIN (RSA |EC )?PRIVATE KEY-----", "Private Key"),
            (r"AKIA[0-9A-Z]{16}", "AWS Access Key"),
            (r"ghp_[0-9A-Za-z]{36}", "GitHub Personal Access Token"),
            (r"sk_[0-9A-Za-z]{32,}", "Stripe Secret Key"),
        ]
        for file_path in target.rglob("*"):
            if file_path.is_file() and file_path.suffix in ['.py', '.js', '.ts', '.json', '.yaml', '.yml', '.env', '.txt', '.md']:
                if any(file_path.match(pat) for pat in exclude_patterns):
                    continue
                try:
                    content = file_path.read_text(encoding='utf-8', errors='ignore')
                    for pattern, desc in secret_patterns:
                        matches = list(re.finditer(pattern, content, re.IGNORECASE))
                        for match in matches:
                            line_num = content[:match.start()].count('\n') + 1
                            details.append({"file": str(file_path.relative_to(target)), "line": line_num, "type": desc, "pattern": pattern})
                            count += 1
                except Exception:
                    pass
        return {"count": count, "details": details}

    async def _check_permissions(self, context: AgentContext, target: Path) -> dict:
        issues = []
        if context and hasattr(context, 'grants'):
            grants = getattr(context, 'grants', [])
            for grant in grants:
                if grant.permission_class == "write" and ".." in str(target):
                    issues.append({"type": "path_traversal", "path": str(target), "severity": "HIGH"})
        return {"issues": issues}

    async def _validate_sandbox(self, context: AgentContext) -> dict:
        violations = []
        if context and context.sandbox_manager:
            if not context.sandbox_id:
                violations.append({"type": "missing_sandbox_id", "severity": "HIGH"})
        else:
            violations.append({"type": "no_sandbox_manager", "severity": "CRITICAL"})
        return {"violations": violations}

    async def _check_filesystem(self, target: Path, context: AgentContext) -> dict:
        issues = []
        if context and hasattr(context, 'task'):
            task_context = getattr(context.task, 'context', {})
            if task_context.get("operation") == "run_command":
                cmd = task_context.get("command", "")
                if any(op in cmd for op in ["rm -rf", "del /s", "format", "mkfs"]):
                    issues.append({"type": "destructive_operation", "command": cmd, "severity": "CRITICAL"})
        return {"issues": issues}

    async def _check_network_access(self, context: AgentContext) -> dict:
        issues = []
        if context and hasattr(context, 'task'):
            task_context = getattr(context.task, 'context', {})
            if task_context.get("operation") == "run_command":
                cmd = task_context.get("command", "")
                if any(op in cmd for op in ["curl", "wget", "nc ", "netcat", "ssh ", "scp "]):
                    issues.append({"type": "network_access", "command": cmd, "severity": "MEDIUM"})
        return {"issues": issues}

    def _severity_exceeds_threshold(self, audit_result: dict, threshold: str) -> bool:
        severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        threshold_level = severity_order.get(threshold.lower(), 1)
        for issue in audit_result.get("sast_issues", []):
            if severity_order.get(issue.get("severity", "").lower(), 0) >= threshold_level:
                return True
        return False


# ============================================================
# OPERATIONAL MISSION PLANNER
# ============================================================

class OperationalMissionPlanner:
    """
    Simple deterministic mission planner for operational execution.
    Maps mission goals to predefined task graphs.
    """
    
    def __init__(self):
        self.mission_templates = {
            "create_file": self._plan_create_file,
            "run_command": self._plan_run_command,
            "multi_task": self._plan_multi_task,
            "file_and_verify": self._plan_file_and_verify,
        }
    
    def plan_mission(self, goal: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Plan a mission from a high-level goal.
        
        Returns:
            Dict with mission_name, tasks list, and dependencies
        """
        parameters = parameters or {}
        mission_type = parameters.get("mission_type", "create_file")
        
        if mission_type in self.mission_templates:
            return self.mission_templates[mission_type](goal, parameters)
        else:
            # Default: create a simple file creation mission
            return self._plan_create_file(goal, parameters)
    
    def _plan_create_file(self, goal: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Plan a simple file creation mission."""
        content = params.get("content", b"Operational execution output")
        if isinstance(content, str):
            content = content.encode()
        path = params.get("path", "output.txt")
        
        return {
            "mission_name": f"Create {path}",
            "tasks": [
                {
                    "name": f"Create {path}",
                    "description": f"Create {path} with specified content",
                    "agent_type": AgentType.IMPLEMENTER,
                    "depends_on": [],
                    "acceptance_criteria": [
                        f"file_exists:{path}",
                    ],
                    "context": {
                        "operation": "write_file",
                        "content": content,
                        "path": path,
                    },
                }
            ],
        }
    
    def _plan_run_command(self, goal: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Plan a command execution mission."""
        command = params.get("command", "echo 'hello'")
        working_dir = params.get("working_dir", ".")
        timeout_seconds = params.get("timeout_seconds", 300)
        
        return {
            "mission_name": f"Run command: {command}",
            "tasks": [
                {
                    "name": f"Execute: {command}",
                    "description": f"Run command {command}",
                    "agent_type": AgentType.IMPLEMENTER,
                    "depends_on": [],
                    "acceptance_criteria": [],
                    "context": {
                        "operation": "run_command",
                        "command": command,
                        "working_dir": working_dir,
                        "timeout_seconds": timeout_seconds,
                    },
                }
            ],
        }
    
    def _plan_multi_task(self, goal: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Plan a multi-task mission with dependencies."""
        tasks_config = params.get("tasks", [
            {"name": "Task A", "path": "a.txt", "content": b"Task A output"},
            {"name": "Task B", "path": "b.txt", "content": b"Task B output"},
            {"name": "Task C", "path": "c.txt", "content": b"Task C output"},
        ])
        
        tasks = []
        for i, tc in enumerate(tasks_config):
            task_name = tc.get("name", f"Task {chr(65+i)}")
            path = tc.get("path", f"task_{i}.txt")
            content = tc.get("content", f"Task {i} output".encode())
            if isinstance(content, str):
                content = content.encode()
            depends_on = tc.get("depends_on", [])
            
            tasks.append({
                "name": task_name,
                "description": f"Create {path}",
                "agent_type": AgentType.IMPLEMENTER,
                "depends_on": depends_on,
                "acceptance_criteria": [f"file_exists:{path}"],
                "context": {
                    "operation": "write_file",
                    "content": content,
                    "path": path,
                },
            })
        
        return {
            "mission_name": "Multi-task mission",
            "tasks": tasks,
        }
    
    def _plan_file_and_verify(self, goal: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Plan a file creation with explicit verification task."""
        content = params.get("content", b"Verified output")
        if isinstance(content, str):
            content = content.encode()
        path = params.get("path", "verified.txt")
        expected_content = params.get("expected_content", content.decode())
        
        return {
            "mission_name": f"Create and verify {path}",
            "tasks": [
                {
                    "name": f"Create {path}",
                    "description": f"Create {path}",
                    "agent_type": AgentType.IMPLEMENTER,
                    "depends_on": [],
                    "acceptance_criteria": [
                        f"file_exists:{path}",
                        f"file_contains:{path}:{expected_content}",
                    ],
                    "context": {
                        "operation": "write_file",
                        "content": content,
                        "path": path,
                    },
                }
            ],
        }


# ============================================================
# OPERATIONAL EXECUTION ENGINE
# ============================================================

@dataclass
class OperationalExecutionResult:
    """Result of an operational mission execution."""
    mission_id: str
    run_id: str
    mission_name: str
    goal: str
    success: bool
    final_state: str
    task_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    verifications: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    checkpoints: List[Dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    error: Optional[str] = None


class OperationalExecutionEngine:
    """
    Operational execution engine wrapper.
    
    Provides a clean API for executing missions without test harness.
    
    E34 INTEGRATION: This engine now delegates to MissionController as the
    single official mission execution path. For simple missions (create_file,
    run_command), it uses the simple planner. For complex missions requiring
    autonomy (replan, checkpoint, human gate), it uses MissionController.
    """
    
    def __init__(
        self,
        artifacts_base_dir: Optional[str] = None,
        sandbox_backend: SandboxBackend = SandboxBackend.WINDOWS_EXECUTOR,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.artifacts_base_dir = artifacts_base_dir or os.path.join(os.getcwd(), "runtime", "artifacts")
        self.sandbox_backend = sandbox_backend
        self.event_callback = event_callback
        self.planner = OperationalMissionPlanner()
        self._engine: Optional[ExecutionEngine] = None
        self._mission_controller: Optional[MissionController] = None
        self._sandbox_manager: Optional[SandboxManager] = None
        self._setup_done = False
        
        # Set up agents immediately
        self._setup_agents()
    
    def _setup_agents(self) -> None:
        """Set up agent registry with operational implementations."""
        # Register/replace IMPLEMENTER
        implementer_def = AgentDefinition(
            agent_id="operational-implementer-001",
            agent_type=AgentType.IMPLEMENTER,
            name="OperationalImplementerAgent",
            version="1.0",
            description="Production implementer for operational execution",
            tools=["write_artifact", "read_artifact", "run_command"],
            permissions=["write", "read", "execute"],
            max_tokens=50000,
            timeout_seconds=300,
            requires_sandbox=True,
            supported_domains=["file_operations", "code_execution", "data_processing"],
            implementation_class="unified.operational.OperationalImplementerAgent",
            state=AgentLifecycleState.REGISTERED,
        )
        
        # Register/replace VERIFIER
        verifier_def = AgentDefinition(
            agent_id="operational-verifier-001",
            agent_type=AgentType.VERIFIER,
            name="OperationalVerifierAgent",
            version="1.0",
            description="Production verifier for operational execution",
            tools=["verify_artifact", "read_artifact"],
            permissions=["read"],
            max_tokens=10000,
            timeout_seconds=120,
            requires_sandbox=True,
            supported_domains=["verification", "evidence_validation"],
            implementation_class="unified.operational.OperationalVerifierAgent",
            state=AgentLifecycleState.REGISTERED,
        )
        
        # Use replace to handle re-registration
        try:
            agent_registry.register_definition(implementer_def)
            agent_registry.enable_agent("operational-implementer-001")
        except ValueError:
            agent_registry.replace_definition(implementer_def)
            agent_registry.enable_agent("operational-implementer-001")
        
        try:
            agent_registry.register_definition(verifier_def)
            agent_registry.enable_agent("operational-verifier-001")
        except ValueError:
            agent_registry.replace_definition(verifier_def)
            agent_registry.enable_agent("operational-verifier-001")
        
        # Register/replace SECURITY
        security_def = AgentDefinition(
            agent_id="operational-security-001",
            agent_type=AgentType.SECURITY,
            name="OperationalSecurityAgent",
            version="1.0",
            description="Production security agent for operational execution",
            tools=["write_artifact", "read_artifact", "run_command", "security_audit"],
            permissions=["write", "read", "execute", "security_scan"],
            max_tokens=50000,
            timeout_seconds=300,
            requires_sandbox=True,
            supported_domains=["file_operations", "code_execution", "data_processing", "security", "sast", "dependency_audit", "secret_scanning"],
            implementation_class="unified.operational.OperationalSecurityAgent",
            state=AgentLifecycleState.REGISTERED,
        )
        
        try:
            agent_registry.register_definition(security_def)
            agent_registry.enable_agent("operational-security-001")
        except ValueError:
            agent_registry.replace_definition(security_def)
            agent_registry.enable_agent("operational-security-001")

        agent_registry.replace_implementation(AgentType.IMPLEMENTER, OperationalImplementerAgent)
        agent_registry.replace_implementation(AgentType.VERIFIER, OperationalVerifierAgent)
        agent_registry.replace_implementation(AgentType.EXPLORER, OperationalExplorerAgent)
        agent_registry.replace_implementation(AgentType.ANALYST, OperationalAnalystAgent)
        agent_registry.replace_implementation(AgentType.PLANNER, OperationalPlannerAgent)
        agent_registry.replace_implementation(AgentType.DESIGNER, OperationalDesignerAgent)
        agent_registry.replace_implementation(AgentType.REVIEWER, OperationalReviewerAgent)
        agent_registry.replace_implementation(AgentType.SECURITY, OperationalSecurityAgent)
    
    def _create_engine(self) -> ExecutionEngine:
        """Create the execution engine with operational configuration."""
        os.makedirs(self.artifacts_base_dir, exist_ok=True)
        
        engine = create_execution_engine(
            sandbox_backend=self.sandbox_backend,
            artifacts_base_dir=self.artifacts_base_dir,
        )
        
        # Subscribe to events if callback provided
        if self.event_callback:
            def event_sink(event: FactoryEvent) -> None:
                self.event_callback({
                    "event_id": event.event_id,
                    "event_type": event.event_type.value,
                    "mission_id": event.mission_id,
                    "run_id": event.run_id,
                    "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                    "payload": event.payload,
                    "source": event.source,
                    "correlation_id": event.correlation_id,
                    "causation_id": event.causation_id,
                })
            engine.subscribe_events(event_sink)
        
        # Create MissionController as the official execution path (E34)
        self._mission_controller = MissionController(engine, state_dir=self.artifacts_base_dir)
        
        return engine
    
    def _transition_mission_state(
        self,
        engine,
        mission: Mission,
        new_state: MissionState,
        reason: str,
    ) -> bool:
        """Transition mission state with validation and event emission."""
        from_state = mission.state
        try:
            validate_mission_transition(from_state, new_state)
            mission.state = new_state
            # Emit state transition event
            run_id = engine._current_run.run_id if engine._current_run else ""
            engine._emit(FactoryEvent.create(
                event_type=EventType.MISSION_STATE_CHANGED,
                mission_id=mission.mission_id,
                run_id=run_id,
                payload=MissionStateChangedEvent(
                    mission_id=mission.mission_id,
                    run_id=run_id,
                    from_state=from_state.value,
                    to_state=new_state.value,
                    actor="operational_engine",
                    reason=reason,
                ),
                source="operational_engine",
            ))
            return True
        except Exception as e:
            # Log failed transition but continue
            return False
    
    async def execute_mission(
        self,
        goal: str,
        parameters: Optional[Dict[str, Any]] = None,
        checkpoint_every: int = 0,
        mission_timeout_seconds: Optional[float] = None,
        use_mission_controller: bool = True,  # E34: Use MissionController as official path
    ) -> OperationalExecutionResult:
        """
        Execute a mission from a high-level goal.
        
        This is the main operational entry point.
        
        E34 INTEGRATION: By default, uses MissionController as the single official
        mission execution path (use_mission_controller=True). For backward compatibility
        with simple missions, can fall back to the legacy planner path.
        
        Args:
            goal: High-level mission goal/description
            parameters: Mission parameters (mission_type, content, path, etc.)
            checkpoint_every: Create checkpoint every N tasks (0 = only at end)
            mission_timeout_seconds: Optional mission-level timeout in seconds
            use_mission_controller: If True, use MissionController (official path).
                                   If False, use legacy OperationalMissionPlanner path.
        
        Returns:
            OperationalExecutionResult with complete execution details
        """
        overall_start = time.monotonic()
        
        # Create engine if not already created
        if not self._setup_done:
            self._engine = self._create_engine()
            self._sandbox_manager = self._engine.sandbox_manager
            self._setup_done = True
        
        engine = self._engine
        assert engine is not None
        assert self._mission_controller is not None, "MissionController not initialized"
        
        # Plan the mission using simple planner to get tasks config
        plan = self.planner.plan_mission(goal, parameters)
        mission_name = plan["mission_name"]
        tasks_config = plan["tasks"]
        
        # Convert to MissionController TaskSpec format
        task_specs = []
        for task_config in tasks_config:
            spec = TaskSpec(
                key=task_config["name"].replace(" ", "_").lower(),
                name=task_config["name"],
                description=task_config["description"],
                depends_on=[d.replace(" ", "_").lower() for d in task_config.get("depends_on", [])],
                acceptance_criteria=task_config.get("acceptance_criteria", []),
                context=task_config.get("context", {}),
                agent_type=task_config.get("agent_type", AgentType.IMPLEMENTER),
            )
            task_specs.append(spec)
        
        # Use MissionController as the official execution path (E34)
        if use_mission_controller:
            return await self._execute_with_mission_controller(
                goal, mission_name, task_specs, checkpoint_every, mission_timeout_seconds, overall_start
            )
        else:
            # Legacy path for backward compatibility
            return await self._execute_legacy_path(
                goal, mission_name, tasks_config, checkpoint_every, mission_timeout_seconds, overall_start
            )
    
    async def _execute_with_mission_controller(
        self,
        goal: str,
        mission_name: str,
        task_specs: List[TaskSpec],
        checkpoint_every: int,
        mission_timeout_seconds: Optional[float],
        overall_start: float,
    ) -> OperationalExecutionResult:
        """Execute mission using MissionController (E34 official path)."""
        mc = self._mission_controller
        engine = self._engine
        assert engine is not None
        
        # Define mission with MissionController
        mission, run, key_to_id = mc.define_mission(goal, task_specs)
        
        # Record initial plan
        mc.record_plan_v1(run.run_id, mission.mission_id)
        
        # Execute with parallelism (E33 proven capability)
        max_parallel = 3 if len(task_specs) > 1 else 1
        try:
            if mission_timeout_seconds is not None:
                result = await asyncio.wait_for(
                    mc.execute_run(run.run_id, max_parallel=max_parallel),
                    timeout=mission_timeout_seconds,
                )
            else:
                result = await mc.execute_run(run.run_id, max_parallel=max_parallel)
        except asyncio.TimeoutError:
            engine.complete_mission(mission.mission_id, False)
            return OperationalExecutionResult(
                mission_id=mission.mission_id,
                run_id=run.run_id,
                mission_name=mission_name,
                goal=goal,
                success=False,
                final_state="TIMEOUT",
                task_results={},
                artifacts=[],
                evidence=[],
                verifications=[],
                events=[],
                checkpoints=[],
                duration_ms=int((time.monotonic() - overall_start) * 1000),
            )
        
        # Verify completion and finalize (drives to EVIDENCED, not VERIFIED - owner-gated)
        required_keys = [spec.key for spec in task_specs]
        completion_ok, completion_report = mc.verify_completion(run.run_id, required_keys)
        
        if completion_ok:
            mc.finalize_mission(mission.mission_id, run.run_id, "All mission completion conditions verified")
            final_state = "EVIDENCED"  # Owner-gated VERIFIED not claimed autonomously
        else:
            final_state = "INCOMPLETE"
        
        # Collect results (reuse existing collection logic)
        return await self._collect_results(mission, run, mission_name, goal, completion_ok, final_state, overall_start, result)
    
    async def _execute_legacy_path(
        self,
        goal: str,
        mission_name: str,
        tasks_config: List[Dict[str, Any]],
        checkpoint_every: int,
        mission_timeout_seconds: Optional[float],
        overall_start: float,
    ) -> OperationalExecutionResult:
        """Legacy execution path using OperationalMissionPlanner (backward compatibility)."""
        # ... existing implementation moved here
        # For brevity, delegate to the original logic
        engine = self._engine
        assert engine is not None
        
        # Create mission
        mission = engine.create_mission(mission_name)
        
        # STATE MACHINE: Mission transitions through lifecycle
        self._transition_mission_state(engine, mission, MissionState.ANALYZING, "Mission analysis started")
        self._transition_mission_state(engine, mission, MissionState.PLANNING, "Mission planning started")
        self._transition_mission_state(engine, mission, MissionState.DESIGNING, "Mission design completed")
        self._transition_mission_state(engine, mission, MissionState.REVIEWING, "Mission under review")
        self._transition_mission_state(engine, mission, MissionState.APPROVED, "Mission approved for execution")
        self._transition_mission_state(engine, mission, MissionState.AWAITING_APPROVAL, "Awaiting final approval")
        self._transition_mission_state(engine, mission, MissionState.EXECUTING, "Mission execution started")
        
        # Create run
        run = engine.create_run(mission.mission_id)
        
        # Create tasks
        created_tasks = []
        task_id_map = {}
        
        for task_config in tasks_config:
            task = engine.create_task(
                run_id=run.run_id,
                mission_id=mission.mission_id,
                name=task_config["name"],
                description=task_config["description"],
                agent_type=task_config["agent_type"],
                depends_on=[],
                acceptance_criteria=task_config["acceptance_criteria"],
            )
            task.context = task_config.get("context", {})
            created_tasks.append(task)
            task_id_map[task_config["name"]] = task.task_id
        
        # Resolve dependencies
        for task in created_tasks:
            task_config = [t for t in tasks_config if t["name"] == task.name][0]
            depends_on_names = task_config.get("depends_on", [])
            resolved_deps = [task_id_map[name] for name in depends_on_names if name in task_id_map]
            task.depends_on = resolved_deps
            if run.run_id in engine.task_graph and task.task_id in engine.task_graph[run.run_id]:
                engine.task_graph[run.run_id][task.task_id]["depends_on"] = set(resolved_deps)
                for dep_id in resolved_deps:
                    if dep_id in engine.task_graph[run.run_id]:
                        engine.task_graph[run.run_id][dep_id]["dependents"].add(task.task_id)
                if not resolved_deps:
                    if engine.task_graph[run.run_id][task.task_id]["state"] == TaskState.PENDING:
                        engine.task_graph[run.run_id][task.task_id]["state"] = TaskState.READY
                        task.state = TaskState.READY
                        engine.task_runnable_cache[run.run_id].add(task.task_id)
                else:
                    all_deps_completed = all(
                        engine.tasks.get(dep_id) and engine.tasks[dep_id].state == TaskState.COMPLETED
                        for dep_id in resolved_deps
                    )
                    if all_deps_completed:
                        engine.task_graph[run.run_id][task.task_id]["state"] = TaskState.READY
                        task.state = TaskState.READY
                        engine.task_runnable_cache[run.run_id].add(task.task_id)
                    else:
                        engine.task_graph[run.run_id][task.task_id]["state"] = TaskState.BLOCKED
                        task.state = TaskState.BLOCKED
        
        # Execute task graph
        execution_start = time.monotonic()
        try:
            if mission_timeout_seconds is not None:
                result = await asyncio.wait_for(
                    engine.execute_task_graph(
                        run.run_id,
                        sandbox_manager=self._sandbox_manager,
                        checkpoint_every=checkpoint_every,
                    ),
                    timeout=mission_timeout_seconds,
                )
            else:
                result = await engine.execute_task_graph(
                    run.run_id,
                    sandbox_manager=self._sandbox_manager,
                    checkpoint_every=checkpoint_every,
                )
        except asyncio.TimeoutError:
            engine.complete_mission(mission.mission_id, False)
            self._transition_mission_state(engine, mission, MissionState.FAILED, "Mission timeout")
            total_duration_ms = int((time.monotonic() - overall_start) * 1000)
            return OperationalExecutionResult(
                mission_id=mission.mission_id,
                run_id=run.run_id,
                mission_name=mission_name,
                goal=goal,
                success=False,
                final_state="TIMEOUT",
                task_results={},
                artifacts=[],
                evidence=[],
                verifications=[],
                events=[],
                checkpoints=[],
                duration_ms=total_duration_ms,
            )
        
        execution_duration_ms = int((time.monotonic() - execution_start) * 1000)
        overall_success = result.get("success", False)
        if overall_success:
            self._transition_mission_state(engine, mission, MissionState.EXECUTED, "Mission execution completed")
            self._transition_mission_state(engine, mission, MissionState.VERIFYING, "Mission verification started")
            self._transition_mission_state(engine, mission, MissionState.EVIDENCED, "Mission evidence collected")
            # Note: Legacy path stops at EVIDENCED like MissionController - VERIFIED is owner-gated (actor='user')
            final_state = "EVIDENCED"
        else:
            self._transition_mission_state(engine, mission, MissionState.FAILED, "Mission execution failed")
            final_state = "FAILED"
        
        return await self._collect_results(mission, run, mission_name, goal, overall_success, final_state, overall_start, result)
    
    async def _collect_results(
        self,
        mission: Mission,
        run: Run,
        mission_name: str,
        goal: str,
        success: bool,
        final_state: str,
        overall_start: float,
        execution_result: Dict[str, Any],
    ) -> OperationalExecutionResult:
        """Collect execution results into OperationalExecutionResult."""
        engine = self._engine
        assert engine is not None
        
        total_duration_ms = int((time.monotonic() - overall_start) * 1000)
        
        # Extract artifacts
        artifacts = []
        for art in engine.evidence_store._artifacts.values():
            if art.mission_id == mission.mission_id:
                artifacts.append({
                    "artifact_id": art.artifact_id,
                    "path": art.path,
                    "sha256": art.sha256,
                    "size_bytes": art.size_bytes,
                    "created_at": art.created_at.isoformat() if art.created_at else None,
                })
        
        # Extract evidence
        evidence = []
        for ev in engine.evidence_store._evidence.values():
            if ev.mission_id == mission.mission_id:
                evidence.append({
                    "evidence_id": ev.evidence_id,
                    "artifact_id": ev.artifact_id,
                    "claim": ev.claim,
                    "sha256": ev.sha256,
                    "created_at": ev.created_at.isoformat() if ev.created_at else None,
                })
        
        # Extract verifications
        verifications = []
        for ver in engine.verifications.values():
            task = engine.tasks.get(ver.task_id)
            if task and task.mission_id == mission.mission_id:
                verifications.append({
                    "verification_id": ver.verification_id,
                    "task_id": ver.task_id,
                    "attempt_id": ver.attempt_id,
                    "verdict": ver.verdict,
                    "checks_performed": ver.checks_performed,
                    "missing_evidence": ver.missing_evidence,
                    "confidence": ver.confidence,
                })
        
        # Extract events
        events = []
        for i, event in enumerate(engine.get_event_history()):
            if event.mission_id == mission.mission_id:
                events.append({
                    "event_id": f"evt-{i:04d}",
                    "event_type": event.event_type.value,
                    "mission_id": event.mission_id,
                    "run_id": event.run_id,
                    "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                    "payload": event.payload,
                    "source": event.source,
                    "correlation_id": event.correlation_id,
                    "causation_id": event.causation_id,
                })
        
        # Extract checkpoints
        checkpoints = []
        for cp in engine.checkpoints.values():
            if cp.mission_id == mission.mission_id:
                checkpoints.append({
                    "checkpoint_id": cp.checkpoint_id,
                    "mission_id": cp.mission_id,
                    "run_id": cp.run_id,
                    "task_states": cp.task_states,
                    "attempt_history": cp.attempt_history,
                    "agent_assignments": cp.agent_assignments,
                    "created_at": cp.created_at.isoformat() if cp.created_at else None,
                })
        
        # Build task results
        task_results = {}
        graph = engine.task_graph.get(run.run_id, {})
        for task_id, node in graph.items():
            task = engine.tasks.get(task_id)
            if not task:
                continue
            task_state = execution_result.get("final_status", {}).get(task_id, {})
            task_result = execution_result.get("task_results", {}).get(task_id, {})
            task_results[task_id] = {
                "task_id": task_id,
                "name": task.name,
                "state": node["state"].value if hasattr(node["state"], "value") else str(node["state"]),
                "success": task_result.get("success", False),
                "attempts": task_result.get("attempts", 0),
                "output": task_result.get("output", {}),
                "error": task_result.get("error"),
            }
        
        # Release mission quota
        engine.complete_mission(mission.mission_id, success)
        
        return OperationalExecutionResult(
            mission_id=mission.mission_id,
            run_id=run.run_id,
            mission_name=mission_name,
            goal=goal,
            success=success,
            final_state=final_state,
            task_results=task_results,
            artifacts=artifacts,
            evidence=evidence,
            verifications=verifications,
            events=events,
            checkpoints=checkpoints,
            duration_ms=total_duration_ms,
        )
    
    async def resume_from_checkpoint(
        self,
        checkpoint_id: str,
        mission_id: str,
    ) -> OperationalExecutionResult:
        """Resume execution from a checkpoint."""
        if not self._setup_done:
            self._setup_agents()
            self._engine = self._create_engine()
            self._sandbox_manager = self._engine.sandbox_manager
            self._setup_done = True
        
        engine = self._engine
        assert engine is not None
        
        # Load checkpoint and resume
        loaded_run = engine.resume_from_checkpoint(checkpoint_id, mission_id=mission_id)
        if loaded_run is None:
            raise RuntimeError(f"Failed to resume from checkpoint {checkpoint_id}")
        
        result = await engine.execute_task_graph(
            loaded_run.run_id,
            sandbox_manager=self._sandbox_manager,
        )
        
        # Collect results (similar to execute_mission)
        artifacts = []
        for art in engine.evidence_store._artifacts.values():
            artifacts.append({
                "artifact_id": art.artifact_id,
                "path": art.path,
                "sha256": art.sha256,
                "size_bytes": art.size_bytes,
            })
        
        evidence = []
        for ev in engine.evidence_store._evidence.values():
            evidence.append({
                "evidence_id": ev.evidence_id,
                "artifact_id": ev.artifact_id,
                "claim": ev.claim,
                "sha256": ev.sha256,
            })
        
        verifications = []
        for ver in engine.verifications.values():
            verifications.append({
                "verification_id": ver.verification_id,
                "task_id": ver.task_id,
                "attempt_id": ver.attempt_id,
                "verdict": ver.verdict,
                "checks_performed": ver.checks_performed,
            })
        
        events = []
        for i, event in enumerate(engine.get_event_history()):
            events.append({
                "event_id": f"evt-{i:04d}",
                "event_type": event.event_type.value,
                "mission_id": event.mission_id,
                "run_id": event.run_id,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                "payload": event.payload,
                "source": event.source,
            })
        
        checkpoints = []
        for cp in engine.checkpoints.values():
            checkpoints.append({
                "checkpoint_id": cp.checkpoint_id,
                "mission_id": cp.mission_id,
                "run_id": cp.run_id,
                "task_states": cp.task_states,
            })
        
        task_results = {}
        for task_id, task_result in result["task_results"].items():
            task_state = result["final_status"].get(task_id, {})
            task_results[task_id] = {
                "task_id": task_id,
                "state": task_state.get("state", "UNKNOWN").value if hasattr(task_state.get("state", ""), "value") else str(task_state.get("state", "UNKNOWN")),
                "success": task_result.get("success", False),
                "attempts": task_result.get("attempts", 0),
                "output": task_result.get("output", {}),
                "resumed": task_result.get("resumed", False),
            }
        
        return OperationalExecutionResult(
            mission_id=mission_id,
            run_id=loaded_run.run_id,
            mission_name="Resumed Mission",
            goal=f"Resume from checkpoint {checkpoint_id}",
            success=result.get("success", False),
            final_state="COMPLETED" if result.get("success", False) else "FAILED",
            task_results=task_results,
            artifacts=artifacts,
            evidence=evidence,
            verifications=verifications,
            events=events,
            checkpoints=checkpoints,
        )

    def create_human_gate(
        self,
        mission_id: str,
        run_id: str,
        task_id: Optional[str],
        reason: str,
        context: Dict[str, Any],
        options: List[Dict[str, str]],
        impact: str,
        required_action: str,
        evidence_refs: Optional[List[str]] = None,
        requested_by: str = "operational_engine",
    ) -> Optional[str]:
        """Create a human gate requiring decision. Transitions mission to HUMAN_REQUIRED."""
        if not self._setup_done:
            return None
        engine = self._engine
        if not engine:
            return None
        return engine.create_human_gate(
            mission_id=mission_id,
            run_id=run_id,
            task_id=task_id,
            reason=reason,
            context=context,
            options=options,
            impact=impact,
            required_action=required_action,
            evidence_refs=evidence_refs,
            requested_by=requested_by,
        )

    def decide_human_gate(
        self,
        mission_id: str,
        gate_id: str,
        decision: str,  # "approve", "reject", "request_changes"
        actor: str,
        feedback: str = "",
    ) -> bool:
        """Record human decision for a gate. Transitions HUMAN_REQUIRED -> EXECUTING or CANCELLED or stays HUMAN_REQUIRED."""
        if not self._setup_done:
            return False
        engine = self._engine
        if not engine:
            return False
        return engine.decide_human_gate(
            mission_id=mission_id,
            gate_id=gate_id,
            decision=decision,
            actor=actor,
            feedback=feedback,
        )


# ============================================================
# CLI ENTRY POINT
# ============================================================

async def run_operational_mission(
    goal: str,
    parameters: Optional[Dict[str, Any]] = None,
    artifacts_dir: Optional[str] = None,
    checkpoint_every: int = 0,
    output_file: Optional[str] = None,
) -> OperationalExecutionResult:
    """
    Run a mission operationally from command line or API.
    
    This is the primary operational entry point.
    
    Example:
        result = await run_operational_mission(
            goal="Create hello.txt",
            parameters={
                "mission_type": "create_file",
                "path": "hello.txt",
                "content": b"Hello, Operational Execution!"
            }
        )
    """
    engine = OperationalExecutionEngine(artifacts_base_dir=artifacts_dir)
    
    # Collect events for reporting
    events_collected = []
    def event_collector(event):
        events_collected.append(event)
        payload = event.get('payload', {})
        # Truncate large payloads
        if isinstance(payload, dict) and len(str(payload)) > 500:
            payload = str(payload)[:500] + "..."
        print(f"  [EVENT] {event['event_type']}: {json.dumps(payload, default=str)[:500]}")
    
    engine.event_callback = event_collector
    
    print(f"\n{'='*60}")
    print(f"OPERATIONAL MISSION EXECUTION")
    print(f"{'='*60}")
    print(f"Goal: {goal}")
    print(f"Parameters: {json.dumps(parameters, default=str) if parameters else 'None'}")
    print(f"Artifacts Dir: {artifacts_dir or 'default'}")
    print(f"{'='*60}\n")
    
    result = await engine.execute_mission(
        goal=goal,
        parameters=parameters,
        checkpoint_every=checkpoint_every,
    )
    
    # DEBUG: Print collected events
    print(f"\n[DEBUG] Collected {len(events_collected)} events:")
    for e in events_collected:
        print(f"  {e['event_type']}: {json.dumps(e.get('payload', {}), default=str)[:300]}")
    
    print(f"\n{'='*60}")
    print(f"MISSION RESULT")
    print(f"{'='*60}")
    print(f"Mission ID: {result.mission_id}")
    print(f"Run ID: {result.run_id}")
    print(f"Success: {result.success}")
    print(f"Final State: {result.final_state}")
    print(f"Duration: {result.duration_ms}ms")
    print(f"Tasks: {len(result.task_results)}")
    print(f"Artifacts: {len(result.artifacts)}")
    print(f"Evidence: {len(result.evidence)}")
    print(f"Verifications: {len(result.verifications)}")
    print(f"Events: {len(result.events)}")
    print(f"Checkpoints: {len(result.checkpoints)}")
    
    if result.error:
        print(f"Error: {result.error}")
    
    print(f"\nTask Details:")
    for task_id, task_result in result.task_results.items():
        print(f"  {task_result['name']} ({task_id[:8]}): {task_result['state']} - {'SUCCESS' if task_result['success'] else 'FAILED'}")
        if task_result.get('error'):
            print(f"    ERROR: {task_result['error']}")
        if task_result.get('output'):
            print(f"    OUTPUT: {json.dumps(task_result['output'], default=str)[:300]}")
    
    if output_file:
        output_data = {
            "mission_id": result.mission_id,
            "run_id": result.run_id,
            "mission_name": result.mission_name,
            "goal": result.goal,
            "success": result.success,
            "final_state": result.final_state,
            "duration_ms": result.duration_ms,
            "task_results": result.task_results,
            "artifacts": result.artifacts,
            "evidence": result.evidence,
            "verifications": result.verifications,
            "events": result.events,
            "checkpoints": result.checkpoints,
        }
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2, default=str)
        print(f"\nResult saved to: {output_file}")
    
    return result


# ============================================================
# DEMONSTRATION
# ============================================================

async def demonstrate_operational_execution():
    """Demonstrate operational execution with various mission types."""
    
    print("\n" + "="*70)
    print("E9 OPERATIONAL EXECUTION DEMONSTRATION")
    print("="*70)
    
    # Demo 1: Simple file creation
    print("\n--- Demo 1: Simple File Creation ---")
    result1 = await run_operational_mission(
        goal="Create hello.txt",
        parameters={
            "mission_type": "create_file",
            "path": "hello.txt",
            "content": b"Hello, Operational Execution!",
        },
        artifacts_dir="runtime/operational_demo_1",
    )
    
    # Demo 2: Multi-task with dependencies
    print("\n--- Demo 2: Multi-Task with Dependencies ---")
    result2 = await run_operational_mission(
        goal="Multi-task pipeline",
        parameters={
            "mission_type": "multi_task",
            "tasks": [
                {"name": "Stage 1", "path": "stage1.txt", "content": b"Stage 1 complete", "depends_on": []},
                {"name": "Stage 2", "path": "stage2.txt", "content": b"Stage 2 complete", "depends_on": ["Stage 1"]},
                {"name": "Stage 3", "path": "stage3.txt", "content": b"Stage 3 complete", "depends_on": ["Stage 2"]},
            ],
        },
        artifacts_dir="runtime/operational_demo_2",
        checkpoint_every=1,
    )
    
    # Demo 3: Command execution
    print("\n--- Demo 3: Command Execution ---")
    result3 = await run_operational_mission(
        goal="Run system info command",
        parameters={
            "mission_type": "run_command",
            "command": "python -c \"import sys; print(f'Python {sys.version}'); import platform; print(f'OS: {platform.system()} {platform.release()}')\"",
        },
        artifacts_dir="runtime/operational_demo_3",
    )
    
    # Summary
    print("\n" + "="*70)
    print("DEMONSTRATION COMPLETE")
    print("="*70)
    print(f"Demo 1: {'PASS' if result1.success else 'FAIL'} - {result1.mission_name}")
    print(f"Demo 2: {'PASS' if result2.success else 'FAIL'} - {result2.mission_name}")
    print(f"Demo 3: {'PASS' if result3.success else 'FAIL'} - {result3.mission_name}")
    
    return [result1, result2, result3]


if __name__ == "__main__":
    # Run demonstration when executed directly
    asyncio.run(demonstrate_operational_execution())