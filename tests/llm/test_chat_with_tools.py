"""Tests for chat_with_tools ReAct loop."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, patch
from pydantic import BaseModel

import pytest

from src.llm import MockLLMProvider, StructuredLLM, LLMMessage, LLMResponse, ToolCall
from src.llm.structured import ToolCallRecord, ToolChatResult, _tool_to_schema, _format_tool_result, _compute_trace_hash
from src.factory.tools import ReadFileTool, ListDirTool, BaseTool, ToolResult


class MockToolProvider(MockLLMProvider):
    """Mock provider that can return scripted tool calls."""
    
    def __init__(self):
        super().__init__()
        self._tool_call_sequence = []
        self._call_index = 0
    
    def set_tool_call_sequence(self, sequence: list[list[dict]]):
        """Set sequence of tool calls to return on each iteration."""
        self._tool_call_sequence = sequence
        self._call_index = 0
    
    async def chat(self, messages: list, tools: Optional[list] = None, **kwargs) -> LLMResponse:
        self._call_count += 1
        
        # Get next tool call sequence
        if self._call_index < len(self._tool_call_sequence):
            tool_calls = self._tool_call_sequence[self._call_index]
            self._call_index += 1
        else:
            tool_calls = []
        
        # Convert dict tool_calls to ToolCall objects
        tc_objects = [ToolCall.from_dict(tc) for tc in tool_calls]
        
        return LLMResponse(
            content="I'll use the tool." if tool_calls else "Done.",
            model="mock",
            usage=self._make_usage(),
            finish_reason="stop",
            tool_calls=tc_objects,
        )
    
    def _make_usage(self):
        from src.llm.provider import LLMUsage
        return LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)


class TestStructural:
    """Structural tests (no LLM calls)."""
    
    def test_tool_to_schema_format(self):
        """Test _tool_to_schema produces valid OpenAI schema."""
        tool = ReadFileTool()
        schema = _tool_to_schema(tool)
        
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "read_file"
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]
        # Should be a valid JSON schema
        assert "type" in schema["function"]["parameters"]
        assert schema["function"]["parameters"]["type"] == "object"
    
    def test_tool_to_schema_list_dir(self):
        """Test _tool_to_schema for list_dir."""
        tool = ListDirTool()
        schema = _tool_to_schema(tool)
        
        assert schema["function"]["name"] == "list_dir"
        assert "path" in schema["function"]["parameters"]["properties"]
    
    def test_format_tool_result_ok(self):
        """Test _format_tool_result for successful result."""
        result = ToolResult(ok=True, output="success output", error=None, evidence_hash="abc")
        formatted = _format_tool_result(result)
        assert formatted == "success output"
    
    def test_format_tool_result_error(self):
        """Test _format_tool_result for error result."""
        result = ToolResult(ok=False, output="", error="file not found", evidence_hash="")
        formatted = _format_tool_result(result)
        assert formatted == "ERROR: file not found"
    
    def test_format_tool_result_truncates(self):
        """Test _format_tool_result truncates long output."""
        long_output = "x" * 10000
        result = ToolResult(ok=True, output=long_output, error=None, evidence_hash="abc")
        formatted = _format_tool_result(result)
        assert len(formatted) == 8000
    
    def test_compute_trace_hash(self):
        """Test _compute_trace_hash produces SHA256."""
        records = [
            ToolCallRecord(iteration=0, name="tool1", arguments={}, ok=True, output="out", error=None, evidence_hash="h1"),
            ToolCallRecord(iteration=1, name="tool2", arguments={}, ok=False, output="", error="err", evidence_hash=""),
        ]
        hash_val = _compute_trace_hash(records)
        assert len(hash_val) == 64  # SHA256 hex
        # Verify it's actually SHA256 of the JSON
        trace_data = [{"iteration": 0, "name": "tool1", "arguments": {}, "ok": True, "output": "out", "error": None, "evidence_hash": "h1"},
                      {"iteration": 1, "name": "tool2", "arguments": {}, "ok": False, "output": "", "error": "err", "evidence_hash": ""}]
        expected = hashlib.sha256(json.dumps(trace_data, sort_keys=True, default=str).encode()).hexdigest()
        assert hash_val == expected


class TestLoopMechanics:
    """Tests using mock provider to verify loop mechanics."""
    
    @pytest.fixture
    def workspace(self) -> Path:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Create test files
            (root / "test.txt").write_text("hello world\npytest is great\n")
            (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\nasyncio_mode = "auto"')
            yield root
    
    @pytest.fixture
    def mock_provider(self) -> MockToolProvider:
        return MockToolProvider()
    
    @pytest.fixture
    def llm(self, mock_provider: MockToolProvider) -> StructuredLLM:
        return StructuredLLM(mock_provider)
    
    async def test_single_tool_call_then_final(self, llm: StructuredLLM, mock_provider: MockToolProvider, workspace: Path):
        """Test 1 tool call, then final message."""
        # First call: tool call; Second call: no tool calls
        mock_provider.set_tool_call_sequence([
            [{"id": "call_1", "function": {"name": "read_file", "arguments": {"path": "test.txt"}}}],
            [],  # No tool calls on second call -> final
        ])
        
        messages = [LLMMessage(role="user", content="Read test.txt")]
        tools = [ReadFileTool()]
        
        result = await llm.chat_with_tools(messages, tools, workspace)
        
        assert result.ok is True
        assert result.iterations == 2
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[0].ok is True
        assert "hello world" in result.tool_calls[0].output
        assert "Done." in result.final_message
    
    async def test_two_sequential_tool_calls(self, llm: StructuredLLM, mock_provider: MockToolProvider, workspace: Path):
        """Test read_file then grep then final."""
        mock_provider.set_tool_call_sequence([
            [{"id": "call_1", "function": {"name": "read_file", "arguments": {"path": "pyproject.toml"}}}],
            [{"id": "call_2", "function": {"name": "grep", "arguments": {"pattern": "pytest", "path": "."}}}],
            [],  # Final
        ])
        
        messages = [LLMMessage(role="user", content="Find pytest in pyproject.toml")]
        tools = [ReadFileTool(), ListDirTool()]
        
        result = await llm.chat_with_tools(messages, tools, workspace)
        
        assert result.ok is True
        assert result.iterations == 3
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[1].name == "grep"
    
    async def test_tool_failure_does_not_crash(self, llm: StructuredLLM, mock_provider: MockToolProvider, workspace: Path):
        """Test tool returning ok=False continues loop."""
        mock_provider.set_tool_call_sequence([
            [{"id": "call_1", "function": {"name": "read_file", "arguments": {"path": "nonexistent.txt"}}}],
            [],  # Final
        ])
        
        messages = [LLMMessage(role="user", content="Read missing file")]
        tools = [ReadFileTool()]
        
        result = await llm.chat_with_tools(messages, tools, workspace)
        
        assert result.ok is True  # Loop continues, final message received
        assert result.iterations == 2
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].ok is False
        assert "not found" in result.tool_calls[0].error.lower()
    
    async def test_evidence_hash_of_trace(self, llm: StructuredLLM, mock_provider: MockToolProvider, workspace: Path):
        """Test evidence_hash is SHA256 of trace."""
        mock_provider.set_tool_call_sequence([
            [{"id": "call_1", "function": {"name": "read_file", "arguments": {"path": "test.txt"}}}],
            [],
        ])
        
        messages = [LLMMessage(role="user", content="Read test.txt")]
        tools = [ReadFileTool()]
        
        result = await llm.chat_with_tools(messages, tools, workspace)
        
        assert result.evidence_hash != ""
        assert len(result.evidence_hash) == 64
        # Verify it matches recomputed hash
        expected = _compute_trace_hash(result.tool_calls)
        assert result.evidence_hash == expected
    
    async def test_no_tools_returns_directly(self, llm: StructuredLLM, mock_provider: MockToolProvider, workspace: Path):
        """Test empty tools list -> 1 provider call, no loop."""
        mock_provider.set_tool_call_sequence([])
        
        messages = [LLMMessage(role="user", content="Hello")]
        tools = []
        
        result = await llm.chat_with_tools(messages, tools, workspace)
        
        assert result.ok is True
        assert result.iterations == 1
        assert len(result.tool_calls) == 0
        assert result.final_message != ""
        # Provider should only be called once
        assert mock_provider._call_count == 1
    
    async def test_max_iterations_enforced(self, llm: StructuredLLM, mock_provider: MockToolProvider, workspace: Path):
        """Test max_iterations limit is enforced."""
        # Always return tool calls - should hit max_iterations
        mock_provider.set_tool_call_sequence([
            [{"id": "call_1", "function": {"name": "read_file", "arguments": {"path": "test.txt"}}}],
            [{"id": "call_2", "function": {"name": "read_file", "arguments": {"path": "test.txt"}}}],
            [{"id": "call_3", "function": {"name": "read_file", "arguments": {"path": "test.txt"}}}],
            [{"id": "call_4", "function": {"name": "read_file", "arguments": {"path": "test.txt"}}}],
            [{"id": "call_5", "function": {"name": "read_file", "arguments": {"path": "test.txt"}}}],
        ])
        
        messages = [LLMMessage(role="user", content="Loop forever")]
        tools = [ReadFileTool()]
        
        # Use low max_iterations
        result = await llm.chat_with_tools(messages, tools, workspace, max_iterations=3)
        
        assert result.ok is False
        assert result.error == "max_iterations reached"
        assert result.iterations == 3
        assert len(result.tool_calls) == 3
    
    async def test_unknown_tool_recorded_as_error(self, llm: StructuredLLM, mock_provider: MockToolProvider, workspace: Path):
        """Test unknown tool name is recorded as error."""
        mock_provider.set_tool_call_sequence([
            [{"id": "call_1", "function": {"name": "nonexistent_tool", "arguments": {}}}],
            [],
        ])
        
        messages = [LLMMessage(role="user", content="Use unknown tool")]
        tools = [ReadFileTool()]
        
        result = await llm.chat_with_tools(messages, tools, workspace)
        
        assert result.ok is True  # Loop continues after error
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "nonexistent_tool"
        assert result.tool_calls[0].ok is False
        assert "unknown tool" in result.tool_calls[0].error.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])