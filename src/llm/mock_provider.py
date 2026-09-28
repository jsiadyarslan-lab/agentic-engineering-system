#!/usr/bin/env python3
"""Mock LLM Provider for testing without API keys."""

from __future__ import annotations

import json
from typing import Any, Optional, Type
from pydantic import BaseModel

from src.llm.provider import LLMProvider, LLMMessage, LLMResponse, LLMUsage, LLMProviderType


class MockLLMProvider(LLMProvider):
    """Mock provider that returns predefined responses for testing."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(model="mock", api_key="mock")
        self._responses = {}
        self._call_count = 0
        self._default_responses = {}
    
    def get_structured_llm(self, agent_type: str) -> "StructuredLLM":
        """Get a StructuredLLM wrapper for this provider."""
        from src.llm.structured import StructuredLLM
        return StructuredLLM(self)
    
    @property
    def provider_type(self) -> LLMProviderType:
        return LLMProviderType.LOCAL
    
    def set_response(self, prompt_contains: str, response: Any):
        """Set predefined response for prompts containing string."""
        self._responses[prompt_contains] = response
    
    async def chat(self, messages: list, **kwargs) -> LLMResponse:
        self._call_count += 1
        # Handle both dict and LLMMessage objects
        prompt_parts = []
        for m in messages:
            if hasattr(m, 'content'):
                prompt_parts.append(m.content)
            elif isinstance(m, dict) and 'content' in m:
                prompt_parts.append(m['content'])
        prompt = " ".join(prompt_parts).lower()
        
        # Check for predefined response (case-insensitive)
        for key, response in self._responses.items():
            if key.lower() in prompt:
                resp = LLMResponse(
                    content=response if isinstance(response, str) else json.dumps(response),
                    model="mock",
                    usage=LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
                    finish_reason="stop",
                )
                self._accumulate_usage(resp.usage)
                return resp
        
        # Check default responses
        for key, response in self._default_responses.items():
            if key in prompt:
                resp = LLMResponse(
                    content=response if isinstance(response, str) else json.dumps(response),
                    model="mock",
                    usage=LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
                    finish_reason="stop",
                )
                self._accumulate_usage(resp.usage)
                return resp
        
        # Default fallback response
        resp = LLMResponse(
            content='{"status": "mock_response"}',
            model="mock",
            usage=LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        )
        self._accumulate_usage(resp.usage)
        return resp
    
    async def structured_chat(self, messages: list, output_model: Type[BaseModel], **kwargs):
        """Return mock instance of output_model."""
        # Import locally to avoid circular import
        from .structured import parse_structured_output
        prompt_parts = []
        for m in messages:
            if hasattr(m, 'content'):
                prompt_parts.append(m.content)
            elif isinstance(m, dict) and 'content' in m:
                prompt_parts.append(m['content'])
        prompt = " ".join(prompt_parts).lower()
        
        # Check for predefined response (case-insensitive)
        for key, response in self._responses.items():
            if key.lower() in prompt:
                if isinstance(response, str):
                    return parse_structured_output(response, output_model)
                return parse_structured_output(json.dumps(response), output_model)
        
        for key, response in self._default_responses.items():
            if key in prompt:
                if isinstance(response, str):
                    return parse_structured_output(response, output_model)
                return parse_structured_output(json.dumps(response), output_model)
        
        # Generate mock data for the model based on model type
        model_name = output_model.__name__
        if model_name == "ExplorationReport":
            mock_data = self._get_exploration_report_mock()
        elif model_name == "Analysis":
            mock_data = self._get_analysis_mock()
        elif model_name == "Plan":
            mock_data = self._get_plan_mock()
        elif model_name == "DesignSpec":
            mock_data = self._get_design_spec_mock()
        elif model_name == "Review":
            mock_data = self._get_review_mock()
        elif model_name == "ImplementationResult":
            mock_data = self._get_implementation_result_mock()
        elif model_name == "Verification":
            mock_data = self._get_verification_mock()
        elif model_name == "SecurityReport":
            mock_data = self._get_security_report_mock()
        else:
            mock_data = self._get_mock_data(output_model)
        
        return parse_structured_output(json.dumps(mock_data), output_model)
    
    def _get_exploration_report_mock(self) -> dict:
        return {
            "summary": "Mock exploration of codebase",
            "codebase_structure": {"src": ["main.py", "utils.py"], "tests": ["test_main.py"]},
            "entry_points": ["src/main.py"],
            "dependencies": {"internal": ["utils"], "external": ["requests", "pydantic"]},
            "file_inventory": [
                {"path": "src/main.py", "type": "python", "size": 1024},
                {"path": "src/utils.py", "type": "python", "size": 512},
            ],
            "key_patterns": ["async/await", "dependency injection", "factory pattern"],
            "tech_stack": {"language": "Python", "framework": "None", "async": "True"},
            "evidence_hash": "mock_hash",
        }
    
    def _get_analysis_mock(self) -> dict:
        return {
            "root_cause": "Mock root cause analysis",
            "impact_assessment": "Low impact",
            "affected_components": ["src/main.py", "src/utils.py"],
            "risk_factors": ["none"],
            "recommendations": ["Add tests", "Improve documentation"],
            "confidence": 0.9,
            "evidence_hash": "mock_hash",
        }
    
    def _get_plan_mock(self) -> dict:
        return {
            "summary": "Mock execution plan",
            "tasks": [
                {"id": "1", "name": "Explore", "agent": "explorer", "depends_on": []},
                {"id": "2", "name": "Analyze", "agent": "thinker", "depends_on": ["1"]},
                {"id": "3", "name": "Plan", "agent": "planner", "depends_on": ["2"]},
                {"id": "4", "name": "Design", "agent": "designer", "depends_on": ["3"]},
                {"id": "5", "name": "Review", "agent": "reviewer", "depends_on": ["4"]},
                {"id": "6", "name": "Implement", "agent": "implementer", "depends_on": ["5"]},
                {"id": "7", "name": "Verify", "agent": "verifier", "depends_on": ["6"]},
                {"id": "8", "name": "Security", "agent": "security", "depends_on": ["7"]},
            ],
            "dependencies": {"1": [], "2": ["1"], "3": ["2"], "4": ["3"], "5": ["4"], "6": ["5"], "7": ["6"], "8": ["7"]},
            "estimates": {"1": 10, "2": 15, "3": 20, "4": 25, "5": 15, "6": 60, "7": 30, "8": 20},
            "risks": ["none"],
            "evidence_hash": "mock_hash",
        }
    
    def _get_design_spec_mock(self) -> dict:
        return {
            "summary": "Mock design specification",
            "architecture": {"pattern": "layered", "components": ["api", "service", "data"]},
            "components": [{"name": "api", "type": "rest"}, {"name": "service", "type": "business"}],
            "interfaces": [{"name": "api", "methods": ["get", "post"]}],
            "data_models": [{"name": "User", "fields": ["id", "name"]}],
            "api_contracts": [{"endpoint": "/api/users", "method": "GET"}],
            "evidence_hash": "mock_hash",
        }
    
    def _get_review_mock(self) -> dict:
        return {
            "summary": "Mock review",
            "approved": True,
            "issues": [{"type": "info", "message": "Good structure"}, {"type": "info", "message": "Well documented"}],
            "suggestions": ["Add more tests"],
            "risk_assessment": "Low risk",
            "evidence_hash": "mock_hash",
        }
    
    def _get_implementation_result_mock(self) -> dict:
        return {
            "files_created": ["hello.py"],
            "files_modified": [],
            "tests_added": ["test_hello.py"],
            "tests_modified": [],
            "build_command": "python -m py_compile hello.py",
            "test_command": "pytest test_hello.py -v",
            "artifacts": [{"type": "file", "path": "hello.py"}],
            "file_contents": {"hello.py": "print('Hello, World!')"},
            "evidence_hash": "mock_hash",
        }
    
    def _get_verification_mock(self) -> dict:
        return {
            "passed": True,
            "test_results": {"passed": 5, "failed": 0, "skipped": 0},
            "coverage": 0.85,
            "issues": [],
            "evidence_hash": "mock_hash",
        }
    
    def _get_security_report_mock(self) -> dict:
        return {
            "summary": "Mock security audit",
            "vulnerabilities": [],
            "secrets_found": [],
            "dependency_issues": [],
            "risk_level": "LOW",
            "evidence_hash": "mock_hash",
        }
    
    def _get_mock_data(self, model: Type[BaseModel]) -> dict:
        """Generate mock data for Pydantic model."""
        mock = {}
        for field_name, field_info in model.model_fields.items():
            annotation = field_info.annotation
            # Handle Optional types
            if hasattr(annotation, '__origin__'):
                origin = annotation.__origin__
                args = annotation.__args__
                if origin is type(None) or (hasattr(origin, '__name__') and origin.__name__ == 'Union' and type(None) in args):
                    # Optional field - make it non-None
                    annotation = [a for a in args if a is not type(None)][0]
            
            if annotation == str:
                mock[field_name] = f"mock_{field_name}"
            elif annotation == int:
                mock[field_name] = 1
            elif annotation == float:
                mock[field_name] = 1.0
            elif annotation == bool:
                mock[field_name] = True
            elif hasattr(annotation, '__origin__') and annotation.__origin__ == list:
                mock[field_name] = []
            elif hasattr(annotation, '__origin__') and annotation.__origin__ == dict:
                mock[field_name] = {}
            elif annotation == Any:
                mock[field_name] = "mock"
            else:
                mock[field_name] = "mock"
        return mock