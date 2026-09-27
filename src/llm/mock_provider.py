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
        
        # Generate mock data for the model
        mock_data = self._get_mock_data(output_model)
        return parse_structured_output(json.dumps(mock_data), output_model)
    
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