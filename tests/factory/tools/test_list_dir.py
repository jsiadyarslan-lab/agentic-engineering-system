"""
Tests for list_dir tool.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.factory.tools import ListDirTool, ListDirInput


class TestListDirTool:
    """Test cases for ListDirTool."""
    
    @pytest.fixture
    def tool(self) -> ListDirTool:
        return ListDirTool()
    
    @pytest.fixture
    def temp_workspace(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def _create_structure(self, workspace: Path) -> None:
        """Create test directory structure."""
        (workspace / "file1.txt").write_text("content1")
        (workspace / "file2.py").write_text("print('hello')")
        (workspace / "subdir").mkdir()
        (workspace / "subdir" / "file3.txt").write_text("content3")
        (workspace / "subdir" / "nested").mkdir()
        (workspace / "subdir" / "nested" / "file4.py").write_text("x=1")
        (workspace / ".git").mkdir()
        (workspace / ".git" / "config").write_text("[core]")
        (workspace / "__pycache__").mkdir()
        (workspace / "__pycache__" / "test.pyc").write_bytes(b"")
        (workspace / ".venv").mkdir()
        (workspace / ".venv" / "bin").mkdir(parents=True)
        (workspace / ".venv" / "bin" / "python").write_text("#!")
    
    async def test_list_dir_flat(self, tool: ListDirTool, temp_workspace: Path) -> None:
        """Test listing directory non-recursively."""
        self._create_structure(temp_workspace)
        
        args = ListDirInput(path=".", recursive=False)
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "file1.txt" in output
        assert "file2.py" in output
        assert "subdir" in output
        assert ".git" not in output  # skipped
        assert "__pycache__" not in output  # skipped
        assert ".venv" not in output  # skipped
        assert result.evidence_hash != ""
    
    async def test_list_dir_recursive(self, tool: ListDirTool, temp_workspace: Path) -> None:
        """Test listing directory recursively."""
        self._create_structure(temp_workspace)
        
        args = ListDirInput(path=".", recursive=True)
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "file1.txt" in output
        assert "file2.py" in output
        assert "subdir/file3.txt" in output
        assert "subdir/nested/file4.py" in output
        assert ".git/config" not in output  # skipped
        assert result.evidence_hash != ""
    
    async def test_list_dir_specific_path(self, tool: ListDirTool, temp_workspace: Path) -> None:
        """Test listing specific subdirectory."""
        self._create_structure(temp_workspace)
        
        args = ListDirInput(path="subdir", recursive=True)
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "file3.txt" in output
        assert "nested/file4.py" in output
        assert "file1.txt" not in output
    
    async def test_list_dir_empty(self, tool: ListDirTool, temp_workspace: Path) -> None:
        """Test listing empty directory."""
        (temp_workspace / "empty").mkdir()
        
        args = ListDirInput(path="empty")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        assert result.output == "(empty)"
    
    async def test_list_dir_missing(self, tool: ListDirTool, temp_workspace: Path) -> None:
        """Test listing non-existent directory."""
        args = ListDirInput(path="nonexistent")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "not found" in result.error.lower()
    
    async def test_list_dir_not_a_directory(self, tool: ListDirTool, temp_workspace: Path) -> None:
        """Test listing a file as directory."""
        (temp_workspace / "file.txt").write_text("content")
        
        args = ListDirInput(path="file.txt")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "not a directory" in result.error.lower()
    
    async def test_list_dir_path_escape(self, tool: ListDirTool, temp_workspace: Path) -> None:
        """Test path escape rejection."""
        args = ListDirInput(path="../../etc")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "escapes" in result.error.lower() or "absolute" in result.error.lower()
    
    async def test_list_dir_absolute_path(self, tool: ListDirTool, temp_workspace: Path) -> None:
        """Test absolute path rejection."""
        args = ListDirInput(path=str(Path("C:/Windows")))
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "absolute" in result.error.lower()
    
    async def test_list_dir_max_entries(self, tool: ListDirTool, temp_workspace: Path) -> None:
        """Test max_entries limit."""
        for i in range(10):
            (temp_workspace / f"file{i}.txt").write_text(f"content{i}")
        
        args = ListDirInput(path=".", max_entries=5)
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        lines = result.output.strip().split("\n")
        assert len(lines) == 5
    
    async def test_list_dir_evidence_hash(self, tool: ListDirTool, temp_workspace: Path) -> None:
        """Test evidence hash is SHA256 of output."""
        (temp_workspace / "test.txt").write_text("content")
        
        args = ListDirInput(path=".")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        import hashlib
        expected = hashlib.sha256(result.output.encode("utf-8")).hexdigest()
        assert result.evidence_hash == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])