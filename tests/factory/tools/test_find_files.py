"""
Tests for find_files tool.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.factory.tools import FindFilesTool, FindFilesInput


class TestFindFilesTool:
    """Test cases for FindFilesTool."""
    
    @pytest.fixture
    def tool(self) -> FindFilesTool:
        return FindFilesTool()
    
    @pytest.fixture
    def temp_workspace(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def _create_files(self, workspace: Path) -> None:
        """Create test files."""
        (workspace / "test1.py").write_text("print('hello')")
        (workspace / "test2.py").write_text("print('world')")
        (workspace / "test3.txt").write_text("text file")
        (workspace / "test4.md").write_text("# markdown")
        (workspace / "subdir").mkdir()
        (workspace / "subdir" / "test5.py").write_text("x=1")
        (workspace / "subdir" / "test6.txt").write_text("nested")
        (workspace / "subdir" / "nested").mkdir()
        (workspace / "subdir" / "nested" / "test7.py").write_text("y=2")
        (workspace / ".git").mkdir()
        (workspace / ".git" / "config").write_text("[core]")
        (workspace / "__pycache__").mkdir()
        (workspace / "__pycache__" / "test.pyc").write_bytes(b"")
        (workspace / ".venv").mkdir()
        (workspace / ".venv" / "lib").mkdir()
        (workspace / ".venv" / "lib" / "site.py").write_text("# venv")
    
    async def test_find_files_basic(self, tool: FindFilesTool, temp_workspace: Path) -> None:
        """Test basic find_files."""
        self._create_files(temp_workspace)
        
        args = FindFilesInput(pattern="*.py", path=".")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "test1.py" in output
        assert "test2.py" in output
        assert "subdir/test5.py" in output
        assert "subdir/nested/test7.py" in output
        assert "test3.txt" not in output
        assert ".git/config" not in output  # skipped
        assert "__pycache__/test.pyc" not in output  # skipped
        assert ".venv/lib/site.py" not in output  # skipped
        assert result.evidence_hash != ""
    
    async def test_find_files_recursive_glob(self, tool: FindFilesTool, temp_workspace: Path) -> None:
        """Test recursive glob pattern **/*.py."""
        self._create_files(temp_workspace)
        
        args = FindFilesInput(pattern="**/*.py", path=".")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "test1.py" in output
        assert "subdir/test5.py" in output
        assert "subdir/nested/test7.py" in output
    
    async def test_find_files_specific_path(self, tool: FindFilesTool, temp_workspace: Path) -> None:
        """Test find_files in specific directory."""
        self._create_files(temp_workspace)
        
        args = FindFilesInput(pattern="*.py", path="subdir")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "test5.py" in output
        assert "nested/test7.py" in output
        assert "test1.py" not in output
    
    async def test_find_files_no_matches(self, tool: FindFilesTool, temp_workspace: Path) -> None:
        """Test find_files with no matches."""
        self._create_files(temp_workspace)
        
        args = FindFilesInput(pattern="*.rs", path=".")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        assert result.output == "(no files found)"
    
    async def test_find_files_missing_path(self, tool: FindFilesTool, temp_workspace: Path) -> None:
        """Test find_files with missing path."""
        args = FindFilesInput(pattern="*.py", path="nonexistent")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "not found" in result.error.lower()
    
    async def test_find_files_not_directory(self, tool: FindFilesTool, temp_workspace: Path) -> None:
        """Test find_files on a file."""
        (temp_workspace / "file.txt").write_text("content")
        
        args = FindFilesInput(pattern="*.txt", path="file.txt")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "not a directory" in result.error.lower()
    
    async def test_find_files_path_escape(self, tool: FindFilesTool, temp_workspace: Path) -> None:
        """Test path escape rejection."""
        args = FindFilesInput(pattern="*.py", path="../../etc")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "escapes" in result.error.lower() or "absolute" in result.error.lower()
    
    async def test_find_files_absolute_path(self, tool: FindFilesTool, temp_workspace: Path) -> None:
        """Test absolute path rejection."""
        args = FindFilesInput(pattern="*.py", path=str(Path("C:/Windows")))
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "absolute" in result.error.lower()
    
    async def test_find_files_max_results(self, tool: FindFilesTool, temp_workspace: Path) -> None:
        """Test max_results limit."""
        for i in range(10):
            (temp_workspace / f"file{i}.py").write_text(f"# file{i}")
        
        args = FindFilesInput(pattern="*.py", path=".", max_results=5)
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        lines = result.output.strip().split("\n")
        assert len(lines) == 5
    
    async def test_find_files_evidence_hash(self, tool: FindFilesTool, temp_workspace: Path) -> None:
        """Test evidence hash is SHA256 of output."""
        (temp_workspace / "test.py").write_text("print('hello')")
        
        args = FindFilesInput(pattern="*.py", path=".")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        import hashlib
        expected = hashlib.sha256(result.output.encode("utf-8")).hexdigest()
        assert result.evidence_hash == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])