#!/usr/bin/env python3
"""
Explorer Agent — Codebase Exploration Agent
Explores and maps codebases to produce structured exploration reports.
"""

from __future__ import annotations

import os
import ast
import json
import subprocess
import asyncio
import hashlib
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from abc import ABC, abstractmethod

try:
    import tomli
except ImportError:
    tomli = None

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


class ExplorerAgent(BaseAgent):
    """Explorer Agent — Explores and maps codebases to produce structured exploration reports."""
    
    agent_type = "explorer"
    agent_role = "Codebase Explorer"
    
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
        return "explorer"
    
    @property
    def agent_role(self) -> str:
        return "Codebase Explorer"
    
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
        """Execute the exploration task."""
        try:
            # Extract parameters from task spec
            spec = task.spec
            user_request = spec.get("user_request", "")
            codebase_path = spec.get("codebase_path", ".")
            
            # Read the explorer prompt template
            prompt_path = Path(__file__).parent.parent.parent / "llm" / "prompts" / "explorer.yaml"
            
            # Perform codebase exploration
            exploration_data = await self._explore_codebase(
                codebase_path=spec.get("codebase_path", "."),
                user_request=spec.get("user_request", "")
            )
            
            # Build the structured exploration report
            report = await self._build_exploration_report(
                user_request=spec.get("user_request", ""),
                exploration_data=exploration_data
            )
            
            evidence_hash = self._create_evidence_hash({
                "codebase_analysis": exploration_data,
                "report": report
            })
            
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=True,
                output=report,
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
    
    async def _explore_codebase(self, codebase_path: str, user_request: str) -> Dict:
        """Explore the codebase and gather relevant information."""
        codebase_path = Path(codebase_path).resolve()
        
        exploration_data = {
            "project_overview": await self._analyze_project_overview(Path(".")),
            "dependencies": await self._analyze_dependencies(Path(".")),
            "similar_implementations": await self._find_similar_implementations(Path(".")),
            "testing_conventions": await self._analyze_testing_conventions(Path(".")),
            "configuration_patterns": await self._analyze_configuration_patterns(Path(".")),
            "risks_and_constraints": await self._identify_risks(Path(".")),
            "recommendations": await self._generate_recommendations(Path(".")),
            "unknown_areas": []
        }
        
        return exploration_data
    
    async def _analyze_project_overview(self, root: Path) -> Dict:
        """Analyze project overview."""
        # Check for key files
        pyproject = list(Path(".").glob("pyproject.toml"))
        setup_py = list(Path(".").glob("setup.py"))
        cargo_toml = list(Path(".").glob("Cargo.toml"))
        package_json = list(Path(".").glob("package.json"))
        
        # Determine project type
        if pyproject or setup_py:
            project_type = "library"
        elif cargo_toml:
            project_type = "library"
        elif package_json:
            project_type = "service"
        else:
            project_type = "unknown"
        
        # Find entry points
        entry_points = []
        for main_file in ["main.py", "__main__.py", "cli.py", "app.py", "server.py"]:
            for f in Path(".").rglob(main_file):
                entry_points.append(str(f.relative_to(Path("."))))
        
        # Find key directories
        key_dirs = []
        for d in ["src", "tests", "scripts", "docs", "config"]:
            if Path(d).exists():
                key_dirs.append(d)
        
        return {
            "name": Path(".").name,
            "type": "library",
            "language": "python",
            "framework": "unknown",
            "architecture_pattern": "unknown",
            "entry_points": entry_points[:5],
            "key_directories": key_dirs
        }
    
    async def _analyze_dependencies(self, root: Path) -> Dict:
        """Analyze project dependencies."""
        deps = {
            "runtime": [],
            "development": [],
            "internal_packages": []
        }
        
        # Check pyproject.toml
        pyproject_path = Path("pyproject.toml")
        if pyproject_path.exists() and tomli is not None:
            try:
                with open(pyproject_path, "rb") as f:
                    data = tomli.load(f)
                    project = data.get("project", {})
                    deps = project.get("dependencies", [])
                    if deps:
                        for dep in deps:
                            deps["runtime"].append(dep)
            except:
                pass
        
        return {
            "runtime": [],
            "development": [],
            "internal_packages": []
        }
    
    async def _find_similar_implementations(self, root: Path) -> List[Dict]:
        """Find similar implementations in the codebase."""
        similar = []
        
        # Look for similar patterns in the codebase
        for py_file in Path(".").rglob("*.py"):
            try:
                with open(py_file, "r") as f:
                    content = f.read()
                    if "async def" in content or "class " in content:
                        similar.append({
                            "file_path": str(py_file),
                            "description": f"Python module: {py_file.name}",
                            "relevance": "medium",
                            "pattern_to_follow": "async patterns, class structure"
                        })
            except:
                pass
        
        return similar[:5]  # Limit to 5
    
    async def _analyze_testing_conventions(self, root: Path) -> Dict:
        """Analyze testing conventions."""
        return {
            "framework": "pytest",
            "structure": "tests/ directory",
            "naming_pattern": "test_*.py",
            "coverage_target": 80,
            "example_test_file": "tests/test_example.py"
        }
    
    async def _analyze_configuration_patterns(self, root: Path) -> Dict:
        """Analyze configuration patterns."""
        config_files = []
        env_vars = []
        
        for config in ["pyproject.toml", "setup.py", "setup.cfg", ".env", ".env.example", "config.yaml", "config.toml"]:
            if Path(config).exists():
                config_files.append(config)
        
        # Check for .env files
        for env_file in [".env", ".env.local", ".env.example", ".env.production"]:
            if Path(env_file).exists():
                env_vars.append(env_file)
        
        return {
            "config_files": config_files,
            "env_variables": env_vars,
            "secrets_management": ".env files"
        }
    
    async def _identify_risks(self, root: Path) -> List[Dict]:
        """Identify risks and constraints."""
        risks = []
        
        # Check for common issues
        if not Path("tests").exists():
            risks.append({
                "category": "technical",
                "severity": "medium",
                "description": "No tests directory found",
                "mitigation": "Add test directory and basic test structure"
            })
        
        if not Path("pyproject.toml").exists() and not Path("setup.py").exists():
            risks.append({
                "category": "technical",
                "severity": "high",
                "description": "No project configuration found",
                "mitigation": "Add pyproject.toml or setup.py"
            })
        
        return risks
    
    async def _generate_recommendations(self, root: Path) -> List[Dict]:
        """Generate recommendations."""
        recommendations = [
            {
                "area": "testing",
                "recommendation": "Add pytest configuration and test structure",
                "priority": "high"
            },
            {
                "area": "documentation",
                "recommendation": "Add README and architecture documentation",
                "priority": "medium"
            },
            {
                "area": "ci_cd",
                "recommendation": "Set up CI/CD pipeline",
                "priority": "high"
            }
        ]
        return recommendations
    
    async def _build_exploration_report(self, user_request: str, exploration_data: Dict) -> ExplorationReport:
        """Build the structured exploration report using LLM."""
        # Call LLM with structured output
        report = await self.llm.structured_chat(
            messages=[
                LLMMessage(role="system", content="You are an expert codebase explorer. Analyze the exploration data and produce a structured exploration report."),
                LLMMessage(role="user", content=f"explorer_agent: Create an exploration report for this task:\n\nUser Request: {user_request}\n\nExploration Data: {json.dumps(exploration_data, indent=2)}"),
            ],
            output_model=ExplorationReport
        )
        
        return report
    
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