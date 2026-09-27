"""
Tests for read_file tool.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from pathlib import Path

import pytest

from src.factory.tools import ReadFileTool, ReadFileInput, ToolRegistry


class TestReadFileTool:
    """Test cases for ReadFileTool."""
    
    @pytest.fixture
    def tool(self) -> ReadFileTool:
        return ReadFileTool()
    
    @pytest.fixture
    def temp_workspace(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def _create_test_file(self, workspace: Path, rel_path: str, content: str) -> Path:
        """Helper to create a test file."""
        file_path = workspace / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return file_path
    
    async def test_read_existing_file_ok(self, tool: ReadFileTool, temp_workspace: Path) -> None:
        """Test reading an existing file returns content."""
        content = "hello world\nthis is a test"
        self._create_test_file(temp_workspace, "test.txt", content)
        
        args = ReadFileInput(path="test.txt")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        assert result.output == content
        assert result.error is None
        assert result.evidence_hash == hashlib.sha256(content.encode("utf-8")).hexdigest()
    
    async def test_read_missing_file_returns_error(self, tool: ReadFileTool, temp_workspace: Path) -> None:
        """Test reading non-existent file returns error."""
        args = ReadFileInput(path="nonexistent.txt")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert result.output == ""
        assert result.error is not None
        assert "not found" in result.error.lower()
        assert result.evidence_hash == ""
    
    async def test_path_escape_rejected(self, tool: ReadFileTool, temp_workspace: Path) -> None:
        """Test that path traversal is rejected."""
        args = ReadFileInput(path="../../etc/passwd")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert result.error is not None
        assert "escapes" in result.error.lower() or "absolute" in result.error.lower()
        assert result.evidence_hash == ""
    
    async def test_absolute_path_rejected(self, tool: ReadFileTool, temp_workspace: Path) -> None:
        """Test that absolute paths are rejected."""
        # Use an absolute path
        args = ReadFileInput(path=str(Path("C:/Windows/System32/drivers/etc/hosts")))
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert result.error is not None
        assert "absolute" in result.error.lower()
        assert result.evidence_hash == ""
    
    async def test_evidence_hash_is_sha256_of_content(self, tool: ReadFileTool, temp_workspace: Path) -> None:
        """Test that evidence_hash is SHA256 of file content."""
        content = "test content for hashing"
        self._create_test_file(temp_workspace, "hash_test.txt", content)
        
        args = ReadFileInput(path="hash_test.txt")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert result.evidence_hash == expected_hash
    
    async def test_file_too_large_rejected(self, tool: ReadFileTool, temp_workspace: Path) -> None:
        """Test that files > 1MB are rejected."""
        # Create a file larger than 1MB
        large_content = "x" * (1024 * 1024 + 100)  # 1MB + 100 bytes
        self._create_test_file(temp_workspace, "large.txt", large_content)
        
        args = ReadFileInput(path="large.txt")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert result.error is not None
        assert "too large" in result.error.lower()
        assert result.evidence_hash == ""


class TestToolRegistry:
    """Test cases for ToolRegistry."""
    
    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        tool = ReadFileTool()
        
        registry.register(tool)
        assert "read_file" in registry.list()
        assert registry.get("read_file") is tool
    
    def test_duplicate_registration_raises(self) -> None:
        registry = ToolRegistry()
        tool = ReadFileTool()
        
        registry.register(tool)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(tool)
    
    def test_get_missing_raises(self) -> None:
        registry = ToolRegistry()
        with pytest.raises(KeyError, match="not found"):
            registry.get("nonexistent")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])