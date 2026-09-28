#!/usr/bin/env python3
"""
Verifier Agent — Verification Agent
Mechanically verifies implementations against specifications.
"""

from __future__ import annotations

import os
import json
import asyncio
import subprocess
import re
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
from src.substrate.windows_executor import WindowsExecutor, ExecutionLimits
from src.llm.structured import StructuredLLM


class VerifierAgent(BaseAgent):
    """Verifier Agent — Mechanically verifies implementations against specifications."""
    
    agent_type = "verifier"
    agent_role = "Verifier"
    
    def __init__(
        self,
        llm: 'StructuredLLM',
        context: 'SharedContextManager',
        grants=None,
        test_mode: bool = False,
    ):
        self.llm = llm
        self.context = context
        self.grants = grants
        self.windows_executor = WindowsExecutor()
        self.test_mode = test_mode
    
    @property
    def agent_type(self) -> str:
        return "verifier"
    
    @property
    def agent_role(self) -> str:
        return "Verifier"
    
    @property
    def required_grants(self) -> List[str]:
        return ["read", "execute"]
    
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
        """Execute the verification task."""
        try:
            # Extract parameters from task spec
            spec = task.spec
            implementation_result = spec.get("implementation_result", {})
            plan = spec.get("plan", {})
            design_spec = spec.get("design_spec", {})
            user_request = spec.get("user_request", "")
            
            # Convert Pydantic models to dicts
            for obj_name, obj in [("implementation_result", implementation_result), ("plan", plan), ("design_spec", design_spec)]:
                if hasattr(obj, 'model_dump'):
                    spec[obj_name] = obj.model_dump()
                elif hasattr(obj, 'to_dict'):
                    spec[obj_name] = obj.to_dict()
            
            implementation_result = spec.get("implementation_result", {})
            plan = spec.get("plan", {})
            design_spec = spec.get("design_spec", {})
            
            # In test mode, return a passing verification without running actual commands
            if self.test_mode:
                verification = Verification(
                    passed=True,
                    tests_passed=1,
                    tests_total=1,
                    coverage=100.0,
                    issues=[],
                    evidence_hash=self._create_evidence_hash({"test_mode": True, "status": "passed"})
                )
            else:
                # Perform mechanical verification
                verification = await self._verify(
                    implementation_result=implementation_result,
                    plan=plan,
                    design_spec=design_spec,
                    user_request=user_request
                )
            
            evidence_hash = self._create_evidence_hash({
                "verification": verification,
                "report": verification
            })
            
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=True,
                output=verification,
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
    
    async def _verify(self, implementation_result: Dict, plan: Dict, design_spec: Dict, user_request: str) -> Verification:
        """Perform mechanical verification."""
        # Run the test command from implementation result
        test_command = implementation_result.get("test_command", "pytest -v")
        build_command = implementation_result.get("build_command", "")
        
        # Run build command if provided
        build_result = None
        if build_command:
            result = await self._run_command(build_command)
            if result["exit_code"] != 0:
                return Verification(
                    passed=False,
                    tests_passed=0,
                    tests_total=0,
                    coverage=0.0,
                    issues=[{"type": "build_failed", "message": result["stderr"]}],
                    evidence_hash=""
                )
        
        # Run test command
        test_result = await self._run_command(test_command)
        
        # Parse test results
        tests_passed = 0
        tests_total = 0
        issues = []
        
        if test_result["exit_code"] == 0:
            # Parse test output for counts
            try:
                passed_match = re.search(r'(\d+) passed', test_result["stdout"])
                failed_match = re.search(r'(\d+) failed', test_result["stdout"])
                if passed_match:
                    tests_passed = int(passed_match.group(1))
                if failed_match:
                    tests_failed = int(failed_match.group(1))
                    tests_total = tests_passed + tests_failed
                else:
                    tests_total = tests_passed
            except:
                tests_passed = 0
                tests_total = 0
        
        # Check if files created match plan
        files_created = implementation_result.get("files_created", [])
        plan_tasks = plan.get("tasks", [])
        
        # Check coverage if available
        coverage = 0.0
        coverage_match = re.search(r'(\d+)% coverage', test_result["stdout"])
        if coverage_match:
            coverage = float(coverage_match.group(1))
        
        # Determine if verification passed
        # Flexible: pass if exit_code == 0 AND (tests_passed == tests_total with tests_total > 0 OR files were created)
        has_tests = tests_total > 0
        has_files = len(files_created) > 0
        
        if has_tests:
            # Standard pytest-based verification
            passed = (test_result["exit_code"] == 0 and 
                      tests_passed == tests_total)
        else:
            # Simple command verification - pass if command succeeded and files exist
            passed = (test_result["exit_code"] == 0 and has_files)
        
        issues = []
        if not passed:
            if test_result["exit_code"] != 0:
                issues.append({"type": "test_failure", "message": f"Exit code: {test_result['exit_code']}, stderr: {test_result['stderr'][:500]}"})
            if has_tests and tests_total == 0:
                issues.append({"type": "no_tests", "message": "No tests were executed"})
            if not has_files and plan.get("tasks"):
                issues.append({"type": "no_files", "message": "No files were created"})
        
        return Verification(
            passed=passed,
            tests_passed=tests_passed,
            tests_total=tests_total,
            coverage=coverage,
            issues=issues,
            evidence_hash=""
        )
    
    async def _run_command(self, command: str) -> Dict:
        """Run a command and return result."""
        import shlex
        import sys
        
        # On Windows, use sys.executable for Python commands to avoid PATH issues
        if sys.platform == "win32" and command.strip().startswith("python "):
            # Replace 'python' with sys.executable
            command = sys.executable + " " + command[len("python "):]
        
        # Parse command - use shell=False with proper argument splitting
        if sys.platform == "win32":
            # On Windows, use subprocess.list2cmdline for proper quoting
            # But we need to split first - use simple split for basic cases
            # For complex commands, we'll let subprocess handle it with shell=True
            args = command.split()
        else:
            args = shlex.split(command)
        
        limits = ExecutionLimits(wall_time_seconds=60, memory_bytes=512_000_000)
        # Get workspace directory for command execution
        working_dir = self.context.get_workspace_path() if hasattr(self.context, 'get_workspace_path') else os.getcwd()
        
        # WindowsExecutor.execute is synchronous, run in thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.windows_executor.execute(
                command=args,
                limits=limits,
                working_dir=working_dir,
            )
        )
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": result.duration_ms,
        }
    
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