"""
Tests for grep tool.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import sys

import pytest

from src.factory.tools import GrepTool, GrepInput


class TestGrepTool:
    """Test cases for GrepTool."""
    
    @pytest.fixture
    def tool(self) -> GrepTool:
        return GrepTool()
    
    @pytest.fixture
    def temp_workspace(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def _create_files(self, workspace: Path) -> None:
        """Create test files for grepping."""
        (workspace / "test1.py").write_text("def hello():\n    print('hello world')\n    return 42")
        (workspace / "test2.py").write_text("def goodbye():\n    print('goodbye world')\n    return 0")
        (workspace / "test3.txt").write_text("hello there\njust text\nno match here")
        (workspace / "subdir").mkdir()
        (workspace / "subdir" / "test4.py").write_text("HELLO WORLD\ncase test")
        (workspace / ".git").mkdir()
        (workspace / ".git" / "config").write_text("hello = world")
        (workspace / "__pycache__").mkdir()
        (workspace / "__pycache__" / "test.pyc").write_bytes(b"")
    
    async def test_grep_basic(self, tool: GrepTool, temp_workspace: Path) -> None:
        """Test basic grep."""
        self._create_files(temp_workspace)
        
        args = GrepInput(pattern=r"hello", path=".")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "test1.py" in output
        assert "test3.txt" in output
        assert ".git/config" not in output  # skipped
        assert "hello world" in output
        assert result.evidence_hash != ""
    
    async def test_grep_case_insensitive(self, tool: GrepTool, temp_workspace: Path) -> None:
        """Test case-insensitive grep."""
        self._create_files(temp_workspace)
        
        args = GrepInput(pattern=r"HELLO", path=".", ignore_case=True)
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "test1.py" in output
        assert "test3.txt" in output
        assert "subdir/test4.py" in output
        assert "HELLO WORLD" in output
    
    async def test_grep_glob_filter(self, tool: GrepTool, temp_workspace: Path) -> None:
        """Test glob filter."""
        self._create_files(temp_workspace)
        
        args = GrepInput(pattern=r"world", path=".", glob="*.py", ignore_case=True)
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "test1.py" in output
        assert "test2.py" in output
        assert "test3.txt" not in output  # filtered by glob
        assert "subdir/test4.py" in output
    
    async def test_grep_specific_path(self, tool: GrepTool, temp_workspace: Path) -> None:
        """Test grep in specific directory."""
        self._create_files(temp_workspace)
        
        args = GrepInput(pattern=r"hello", path="subdir", ignore_case=True)
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        output = result.output
        assert "subdir/test4.py" in output
        assert "test1.py" not in output
    
    async def test_grep_no_matches(self, tool: GrepTool, temp_workspace: Path) -> None:
        """Test grep with no matches."""
        self._create_files(temp_workspace)
        
        args = GrepInput(pattern=r"nonexistent", path=".")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        assert result.output == "(no matches)"
        assert result.evidence_hash != ""
    
    async def test_grep_missing_path(self, tool: GrepTool, temp_workspace: Path) -> None:
        """Test grep with missing path."""
        args = GrepInput(pattern=r"hello", path="nonexistent")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "not found" in result.error.lower()
    
    async def test_grep_invalid_regex(self, tool: GrepTool, temp_workspace: Path) -> None:
        """Test grep with invalid regex."""
        args = GrepInput(pattern=r"[invalid", path=".")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "invalid regex" in result.error.lower()
    
    async def test_grep_path_escape(self, tool: GrepTool, temp_workspace: Path) -> None:
        """Test path escape rejection."""
        args = GrepInput(pattern=r"hello", path="../../etc")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "escapes" in result.error.lower() or "absolute" in result.error.lower()
    
    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="(AES-EXP-04) دلالات مسار ويندوز حصراً: سياسة المنتج ترفض "
               "المسارات المطلقة فعلاً (is_absolute في filesystem.py) لكن "
               "'C:/...' ليست مطلقة على POSIX — الفحص غير قابل للتطبيق هنا",
    )
    async def test_grep_absolute_path(self, tool: GrepTool, temp_workspace: Path) -> None:
        """Test absolute path rejection."""
        args = GrepInput(pattern=r"hello", path=str(Path("C:/Windows")))
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "absolute" in result.error.lower()
    
    async def test_grep_max_matches(self, tool: GrepTool, temp_workspace: Path) -> None:
        """Test max_matches limit."""
        for i in range(10):
            (temp_workspace / f"file{i}.txt").write_text("hello\n" * 5)
        
        args = GrepInput(pattern=r"hello", path=".", max_matches=3)
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        lines = result.output.strip().split("\n")
        assert len(lines) == 3
    
    async def test_grep_evidence_hash(self, tool: GrepTool, temp_workspace: Path) -> None:
        """Test evidence hash is SHA256 of output."""
        (temp_workspace / "test.txt").write_text("hello world")
        
        args = GrepInput(pattern=r"hello", path=".")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        import hashlib
        expected = hashlib.sha256(result.output.encode("utf-8")).hexdigest()
        assert result.evidence_hash == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])