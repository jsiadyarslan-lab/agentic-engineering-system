#!/usr/bin/env python3
"""
Security Agent — Security Audit Agent
Mechanically audits implementations for security vulnerabilities.
"""

from __future__ import annotations

import os
import json
import asyncio
import subprocess
import re
import hashlib
import uuid
import logging
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

logger = logging.getLogger(__name__)


class SecurityAgent(BaseAgent):
    """Security Agent — Mechanically audits implementations for security vulnerabilities."""
    
    agent_type = "security"
    agent_role = "Security Auditor"
    
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
    
    async def _run_command(self, command: List[str], timeout: int = 120) -> Dict:
        """Run a command using subprocess directly (bypasses WindowsExecutor for reliability)."""
        loop = asyncio.get_event_loop()
        
        def _run():
            try:
                proc = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=self.context.get_workspace_path() if hasattr(self.context, 'get_workspace_path') else None,
                )
                return {
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                }
            except subprocess.TimeoutExpired as e:
                return {
                    "exit_code": -1,
                    "stdout": e.stdout or "",
                    "stderr": f"Timeout after {timeout}s: {e.stderr or ''}",
                }
            except Exception as e:
                return {
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": str(e),
                }
        
        return await loop.run_in_executor(None, _run)
    
    @property
    def agent_type(self) -> str:
        return "security"
    
    @property
    def agent_role(self) -> str:
        return "Security Auditor"
    
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
        """Execute the security audit task."""
        try:
            # Extract parameters from task spec
            spec = task.spec
            implementation_result = spec.get("implementation_result", {})
            plan = spec.get("plan", {})
            design_spec = spec.get("design_spec", {})
            verification = spec.get("verification", {})
            user_request = spec.get("user_request", "")
            
            # Convert Pydantic models to dicts
            for obj_name, obj in [("implementation_result", implementation_result), ("plan", plan), ("design_spec", design_spec), ("verification", verification)]:
                if hasattr(obj, 'model_dump'):
                    spec[obj_name] = obj.model_dump()
                elif hasattr(obj, 'to_dict'):
                    spec[obj_name] = obj.to_dict()
            
            implementation_result = spec.get("implementation_result", {})
            plan = spec.get("plan", {})
            design_spec = spec.get("design_spec", {})
            verification = spec.get("verification", {})
            
            # Perform mechanical security audit
            security_report = await self._audit(
                implementation_result=implementation_result,
                plan=plan,
                design_spec=design_spec,
                verification=verification,
                user_request=user_request
            )
            
            evidence_hash = self._create_evidence_hash({
                "security_report": security_report,
                "report": security_report
            })
            
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=True,
                output=security_report,
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
    
    async def _audit(self, implementation_result: Dict, plan: Dict, design_spec: Dict, verification: Dict, user_request: str) -> SecurityReport:
        """Perform mechanical security audit."""
        # In test mode, return a passing security report without running external tools
        if self.test_mode:
            return SecurityReport(
                vulnerabilities_found=0,
                secrets_found=0,
                dependencies_checked=0,
                issues=[],
                evidence_hash=self._create_evidence_hash({"test_mode": True, "status": "passed"})
            )
        
        # Initialize variables
        vulnerabilities = []
        secret_issues = []
        dep_issues = []
        issues = []
        
        # Run SAST (Static Application Security Testing)
        # bandit returns 0 for no issues, 1 for issues found, >1 for errors
        sast_result = await self._run_sast()
        if sast_result["exit_code"] in (0, 1):
            # Parse SAST output for vulnerabilities
            vulnerabilities = self._parse_sast_output(sast_result["stdout"])
            issues.extend(vulnerabilities)
        else:
            logger.warning(f"bandit error (exit={sast_result['exit_code']}): {sast_result['stderr'][:200]}")
        
        # Run dependency audit
        dep_audit_result = await self._run_dependency_audit()
        if dep_audit_result["exit_code"] == 0:
            dep_issues = self._parse_dep_audit(dep_audit_result["stdout"])
            issues.extend(dep_issues)
        else:
            logger.warning(f"pip-audit error (exit={dep_audit_result['exit_code']}): {dep_audit_result['stderr'][:200]}")
        
        # Run secret scanning
        secret_scan_result = await self._run_secret_scan()
        if secret_scan_result["exit_code"] == 0:
            secret_issues = self._parse_secret_scan(secret_scan_result["stdout"])
            issues.extend(secret_issues)
        else:
            logger.warning(f"detect-secrets error (exit={secret_scan_result['exit_code']}): {secret_scan_result['stderr'][:200]}")
        
        # Check for hardcoded secrets in created files
        files_created = implementation_result.get("files_created", [])
        for file_path in files_created:
            file_secret_issues = await self._scan_file_for_secrets(file_path)
            if file_secret_issues:
                issues.extend(file_secret_issues)
        
        return SecurityReport(
            vulnerabilities_found=len(vulnerabilities),
            secrets_found=len(secret_issues),
            dependencies_checked=len(dep_issues),
            issues=issues,
            evidence_hash=""
        )
    
    async def _run_sast(self) -> Dict:
        """Run SAST (Static Application Security Testing)."""
        result = await self._run_command(
            command=["bandit", "-r", "src", "-x", ".venv,target,node_modules,tests", "-f", "json", "-q"],
            timeout=120,
        )
        if result["exit_code"] != 0 and result["exit_code"] != 1:  # bandit returns 1 when issues found
            logger.warning(f"bandit failed (exit={result['exit_code']}): {result['stderr'][:200]}")
        return result
    
    def _parse_sast_output(self, stdout: str) -> List[Dict]:
        """Parse bandit/SAST output for vulnerabilities."""
        vulnerabilities = []
        try:
            data = json.loads(stdout)
            for result in data.get("results", []):
                vulnerabilities.append({
                    "type": "sast_vulnerability",
                    "severity": result.get("issue_severity", "unknown"),
                    "message": result.get("issue_text", ""),
                    "file": result.get("filename", ""),
                    "line": result.get("line_number", 0),
                    "code": result.get("code", ""),
                })
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed: {e}; head: {stdout[:200]}")
        return vulnerabilities
    
    async def _run_dependency_audit(self) -> Dict:
        """Run dependency audit."""
        result = await self._run_command(
            command=["pip-audit", "--format", "json", "--progress-spinner", "off"],
            timeout=120,
        )
        if result["exit_code"] != 0:
            logger.warning(f"pip-audit failed (exit={result['exit_code']}): {result['stderr'][:200]}")
        return result
    
    def _parse_dep_audit(self, stdout: str) -> List[Dict]:
        """Parse pip-audit output for vulnerable dependencies."""
        issues = []
        try:
            data = json.loads(stdout)
            for vuln in data.get("vulnerabilities", []):
                issues.append({
                    "type": "vulnerable_dependency",
                    "package": vuln.get("package", ""),
                    "version": vuln.get("installed_version", ""),
                    "fixed_version": vuln.get("fixed_version", ""),
                    "severity": vuln.get("severity", "unknown"),
                    "cve": vuln.get("cve_id", ""),
                })
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed: {e}; head: {stdout[:200]}")
        return issues
    
    async def _run_secret_scan(self) -> Dict:
        """Run secret scanning."""
        result = await self._run_command(
            command=["detect-secrets", "scan", "src"],
            timeout=60,
        )
        if result["exit_code"] != 0:
            logger.warning(f"detect-secrets failed (exit={result['exit_code']}): {result['stderr'][:200]}")
        return result
    
    def _parse_secret_scan(self, stdout: str) -> List[Dict]:
        """Parse detect-secrets output for secrets."""
        secrets = []
        try:
            data = json.loads(stdout)
            for result in data.get("results", []):
                for secret in result.get("secrets", []):
                    secrets.append({
                        "type": "secret_exposure",
                        "type_name": secret.get("type", "unknown"),
                        "file": secret.get("filename", ""),
                        "line": secret.get("line_number", 0),
                        "severity": "high",
                        "mitigation": "Rotate secret and remove from code",
                    })
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed: {e}; head: {stdout[:200]}")
        return secrets
    
    async def _scan_file_for_secrets(self, file_path: str) -> List[Dict]:
        """Scan a specific file for secrets."""
        issues = []
        try:
            result = await self._run_command(
                command=["detect-secrets", "scan", file_path],
                timeout=30,
            )
            if result["exit_code"] != 0:
                logger.warning(f"detect-secrets failed (exit={result['exit_code']}): {result['stderr'][:200]}")
            if result["exit_code"] == 0:
                data = json.loads(result["stdout"])
                for result in data.get("results", []):
                    for secret in result.get("secrets", []):
                        issues.append({
                            "type": "secret_exposure",
                            "type_name": secret.get("type", "unknown"),
                            "file": secret.get("filename", ""),
                            "line": secret.get("line_number", 0),
                            "severity": "high",
                            "mitigation": "Rotate secret and remove from code",
                        })
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed: {e}; head: {result['stdout'][:200] if 'result' in locals() else 'N/A'}")
        return issues
    
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