"""
Tests for parse_python tool.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.factory.tools import ParsePythonTool, ParsePythonInput


class TestParsePythonTool:
    """Test cases for ParsePythonTool."""
    
    @pytest.fixture
    def tool(self) -> ParsePythonTool:
        return ParsePythonTool()
    
    @pytest.fixture
    def temp_workspace(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    async def test_parse_python_basic(self, tool: ParsePythonTool, temp_workspace: Path) -> None:
        """Test parsing a simple Python file."""
        code = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"

class Greeter:
    def __init__(self, prefix: str):
        self.prefix = prefix
    
    def greet(self, name: str) -> str:
        return f"{self.prefix} {name}"

import os
from pathlib import Path
from typing import List, Optional
'''
        (temp_workspace / "test.py").write_text(code)
        
        args = ParsePythonInput(path="test.py")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "hello" in output
        assert "Greeter" in output
        assert "__init__" in output
        assert "greet" in output
        assert "os" in output
        assert "Path" in output
        assert "List" in output
        assert "Optional" in output
        assert result.evidence_hash != ""
    
    async def test_parse_python_async_function(self, tool: ParsePythonTool, temp_workspace: Path) -> None:
        """Test parsing async functions."""
        code = '''
async def fetch_data(url: str) -> dict:
    return {"url": url}

async def process() -> None:
    await fetch_data("http://example.com")
'''
        (temp_workspace / "async_test.py").write_text(code)
        
        args = ParsePythonInput(path="async_test.py")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "fetch_data" in output
        assert "async" in output
        assert "process" in output
    
    async def test_parse_python_class_inheritance(self, tool: ParsePythonTool, temp_workspace: Path) -> None:
        """Test parsing class inheritance."""
        code = '''
class Base:
    pass

class Derived(Base):
    def method(self):
        pass

class Multi(Base, object):
    pass
'''
        (temp_workspace / "inherit.py").write_text(code)
        
        args = ParsePythonInput(path="inherit.py")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "Base" in output
        assert "Derived" in output
        assert "Base" in output  # base class
        assert "object" in output
    
    async def test_parse_python_syntax_error(self, tool: ParsePythonTool, temp_workspace: Path) -> None:
        """Test parsing file with syntax error."""
        code = '''
def broken(
    return "missing paren"
'''
        (temp_workspace / "syntax_error.py").write_text(code)
        
        args = ParsePythonInput(path="syntax_error.py")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "syntax error" in result.error.lower()
        assert result.evidence_hash != ""
    
    async def test_parse_python_empty_file(self, tool: ParsePythonTool, temp_workspace: Path) -> None:
        """Test parsing empty file."""
        (temp_workspace / "empty.py").write_text("")
        
        args = ParsePythonInput(path="empty.py")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "FUNCTIONS (0)" in output
        assert "CLASSES (0)" in output
        assert "IMPORTS (0)" in output
    
    async def test_parse_python_missing_file(self, tool: ParsePythonTool, temp_workspace: Path) -> None:
        """Test parsing non-existent file."""
        args = ParsePythonInput(path="nonexistent.py")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "not found" in result.error.lower()
    
    async def test_parse_python_not_python_file(self, tool: ParsePythonTool, temp_workspace: Path) -> None:
        """Test parsing non-Python file (should still work, just no functions/classes)."""
        (temp_workspace / "test.txt").write_text("not python")
        
        args = ParsePythonInput(path="test.txt")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "FUNCTIONS (0)" in output
        assert "CLASSES (0)" in output
        assert "IMPORTS (0)" in output
    
    async def test_parse_python_path_escape(self, tool: ParsePythonTool, temp_workspace: Path) -> None:
        """Test path escape rejection."""
        args = ParsePythonInput(path="../../etc/passwd")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "escapes" in result.error.lower() or "absolute" in result.error.lower()
    
    async def test_parse_python_absolute_path(self, tool: ParsePythonTool, temp_workspace: Path) -> None:
        """Test absolute path rejection."""
        args = ParsePythonInput(path=str(Path("C:/Windows/test.py")))
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "absolute" in result.error.lower()
    
    async def test_parse_python_evidence_hash(self, tool: ParsePythonTool, temp_workspace: Path) -> None:
        """Test evidence hash is SHA256 of output."""
        code = 'def test(): pass'
        (temp_workspace / "hash.py").write_text(code)
        
        args = ParsePythonInput(path="hash.py")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        import hashlib
        expected = hashlib.sha256(result.output.encode("utf-8")).hexdigest()
        assert result.evidence_hash == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])