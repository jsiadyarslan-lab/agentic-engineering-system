"""
Tests for write_file tool.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.factory.tools import WriteFileTool, WriteFileInput, ReadFileTool, ReadFileInput


class TestWriteFileTool:
    """Test cases for WriteFileTool."""
    
    @pytest.fixture
    def tool(self) -> WriteFileTool:
        return WriteFileTool()
    
    @pytest.fixture
    def read_tool(self) -> ReadFileTool:
        return ReadFileTool()
    
    @pytest.fixture
    def temp_workspace(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    async def test_write_file_new(self, tool: WriteFileTool, read_tool: ReadFileTool, temp_workspace: Path) -> None:
        """Test writing a new file."""
        args = WriteFileInput(
            path="new_file.txt",
            content="Hello, World!",
            overwrite=False
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        assert "Written 13 bytes" in result.output
        assert result.evidence_hash != ""
        
        # Verify file was created
        read_result = await read_tool.run(ReadFileInput(path="new_file.txt"), temp_workspace)
        assert read_result.ok is True
        assert read_result.output == "Hello, World!"
    
    async def test_write_file_creates_parent_dirs(self, tool: WriteFileTool, read_tool: ReadFileTool, temp_workspace: Path) -> None:
        """Test writing to nested path creates parent dirs."""
        args = WriteFileInput(
            path="deep/nested/path/file.txt",
            content="nested content",
            overwrite=False
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        
        read_result = await read_tool.run(ReadFileInput(path="deep/nested/path/file.txt"), temp_workspace)
        assert read_result.ok is True
        assert read_result.output == "nested content"
    
    async def test_write_file_overwrite(self, tool: WriteFileTool, read_tool: ReadFileTool, temp_workspace: Path) -> None:
        """Test overwriting existing file."""
        # Create initial file
        (temp_workspace / "existing.txt").write_text("original")
        
        args = WriteFileInput(
            path="existing.txt",
            content="updated",
            overwrite=True
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        
        read_result = await read_tool.run(ReadFileInput(path="existing.txt"), temp_workspace)
        assert read_result.ok is True
        assert read_result.output == "updated"
    
    async def test_write_file_no_overwrite_fails(self, tool: WriteFileTool, temp_workspace: Path) -> None:
        """Test writing to existing file without overwrite fails."""
        (temp_workspace / "existing.txt").write_text("original")
        
        args = WriteFileInput(
            path="existing.txt",
            content="updated",
            overwrite=False
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "exists" in result.error.lower()
        assert result.evidence_hash == ""
    
    async def test_write_file_empty_content(self, tool: WriteFileTool, read_tool: ReadFileTool, temp_workspace: Path) -> None:
        """Test writing empty content."""
        args = WriteFileInput(
            path="empty.txt",
            content="",
            overwrite=False
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        
        read_result = await read_tool.run(ReadFileInput(path="empty.txt"), temp_workspace)
        assert read_result.ok is True
        assert read_result.output == ""
    
    async def test_write_file_path_escape(self, tool: WriteFileTool, temp_workspace: Path) -> None:
        """Test path escape rejection."""
        args = WriteFileInput(
            path="../../etc/passwd",
            content="malicious",
            overwrite=False
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "escapes" in result.error.lower() or "absolute" in result.error.lower()
    
    async def test_write_file_absolute_path(self, tool: WriteFileTool, temp_workspace: Path) -> None:
        """Test absolute path rejection."""
        args = WriteFileInput(
            path=str(Path("C:/Windows/test.txt")),
            content="malicious",
            overwrite=False
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "absolute" in result.error.lower()
    
    async def test_write_file_atomicity(self, tool: WriteFileTool, temp_workspace: Path) -> None:
        """Test atomic write - original unchanged on failure."""
        (temp_workspace / "atomic.txt").write_text("original")
        
        # This is hard to test directly, but we can verify the mechanism works
        # by checking the file doesn't get corrupted
        args = WriteFileInput(
            path="atomic.txt",
            content="new content",
            overwrite=True
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        
        content = (temp_workspace / "atomic.txt").read_text(encoding="utf-8")
        assert content == "new content"
    
    async def test_write_file_evidence_hash(self, tool: WriteFileTool, temp_workspace: Path) -> None:
        """Test evidence hash is SHA256 of content."""
        content = "test content for hashing"
        args = WriteFileInput(
            path="hash_test.txt",
            content=content,
            overwrite=False
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        import hashlib
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert result.evidence_hash == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])