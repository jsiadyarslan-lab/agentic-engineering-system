"""
Tests for edit_file tool.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from pathlib import Path

import sys

import pytest

from src.factory.tools import EditFileTool, EditFileInput, ReadFileTool, ReadFileInput, ToolRegistry


class TestEditFileTool:
    """Test cases for EditFileTool."""
    
    @pytest.fixture
    def tool(self) -> EditFileTool:
        return EditFileTool()
    
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
    
    async def test_edit_unique_match_ok(self, tool: EditFileTool, temp_workspace: Path) -> None:
        """Test editing with unique match succeeds."""
        original = "hello world\nthis is a test"
        self._create_test_file(temp_workspace, "edit_test.txt", original)
        
        args = EditFileInput(
            path="edit_test.txt",
            old_text="hello world",
            new_text="hello universe"
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        assert result.output == "hello universe\nthis is a test"
        assert result.error is None
        # Verify file was actually changed
        new_content = (temp_workspace / "edit_test.txt").read_text(encoding="utf-8")
        assert new_content == "hello universe\nthis is a test"
        # Verify evidence hash is SHA256 of new content
        expected_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
        assert result.evidence_hash == expected_hash
    
    async def test_edit_missing_file_returns_error(self, tool: EditFileTool, temp_workspace: Path) -> None:
        """Test editing non-existent file returns error."""
        args = EditFileInput(
            path="nonexistent.txt",
            old_text="foo",
            new_text="bar"
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert result.output == ""
        assert result.error is not None
        assert "not found" in result.error.lower()
        assert result.evidence_hash == ""
    
    async def test_edit_old_text_not_found(self, tool: EditFileTool, temp_workspace: Path) -> None:
        """Test editing with old_text not in file returns error."""
        self._create_test_file(temp_workspace, "edit_test.txt", "hello world")
        
        args = EditFileInput(
            path="edit_test.txt",
            old_text="not in file",
            new_text="replacement"
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert result.error is not None
        assert "not found" in result.error.lower()
        assert result.evidence_hash == ""
        # Verify file unchanged
        content = (temp_workspace / "edit_test.txt").read_text(encoding="utf-8")
        assert content == "hello world"
    
    async def test_edit_old_text_not_unique(self, tool: EditFileTool, temp_workspace: Path) -> None:
        """Test editing with old_text appearing multiple times returns error."""
        self._create_test_file(temp_workspace, "edit_test.txt", "foo bar foo")
        
        args = EditFileInput(
            path="edit_test.txt",
            old_text="foo",
            new_text="baz"
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert result.error is not None
        assert "appears" in result.error.lower() or "unique" in result.error.lower()
        assert result.evidence_hash == ""
        # Verify file unchanged
        content = (temp_workspace / "edit_test.txt").read_text(encoding="utf-8")
        assert content == "foo bar foo"
    
    async def test_path_escape_rejected(self, tool: EditFileTool, temp_workspace: Path) -> None:
        """Test that path traversal is rejected."""
        args = EditFileInput(
            path="../../etc/passwd",
            old_text="foo",
            new_text="bar"
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert result.error is not None
        assert "escapes" in result.error.lower() or "absolute" in result.error.lower()
        assert result.evidence_hash == ""
    
    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="(AES-EXP-04) دلالات مسار ويندوز حصراً: سياسة المنتج ترفض "
               "المسارات المطلقة فعلاً (is_absolute في filesystem.py) لكن "
               "'C:/...' ليست مطلقة على POSIX — الفحص غير قابل للتطبيق هنا",
    )
    async def test_absolute_path_rejected(self, tool: EditFileTool, temp_workspace: Path) -> None:
        """Test that absolute paths are rejected."""
        args = EditFileInput(
            path=str(Path("C:/Windows/System32/drivers/etc/hosts")),
            old_text="foo",
            new_text="bar"
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert result.error is not None
        assert "absolute" in result.error.lower()
        assert result.evidence_hash == ""
    
    async def test_evidence_hash_is_sha256_of_new_content(self, tool: EditFileTool, temp_workspace: Path) -> None:
        """Test that evidence_hash is SHA256 of NEW file content."""
        original = "old content"
        new_content = "new content"
        self._create_test_file(temp_workspace, "hash_test.txt", original)
        
        args = EditFileInput(
            path="hash_test.txt",
            old_text="old content",
            new_text=new_content
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        expected_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
        assert result.evidence_hash == expected_hash
        # Verify output matches new content
        assert result.output == new_content
    
    async def test_edit_atomicity_original_unchanged_on_failure(self, tool: EditFileTool, temp_workspace: Path) -> None:
        """Test that file remains unchanged if write fails mid-operation."""
        # This test simulates a failure by making the file read-only temporarily
        # (not easily done on Windows), so we test the logic by checking
        # that old_text not found leaves file unchanged
        original = "original content"
        self._create_test_file(temp_workspace, "atomic_test.txt", original)
        
        # Try to edit with non-matching old_text
        args = EditFileInput(
            path="atomic_test.txt",
            old_text="not present",
            new_text="new content"
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        # Verify file unchanged
        content = (temp_workspace / "atomic_test.txt").read_text(encoding="utf-8")
        assert content == original


class TestReadFileRegression:
    """Regression tests for read_file tool."""
    
    @pytest.fixture
    def tool(self) -> ReadFileTool:
        return ReadFileTool()
    
    @pytest.fixture
    def temp_workspace(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def _create_test_file(self, workspace: Path, rel_path: str, content: str) -> Path:
        file_path = workspace / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return file_path
    
    async def test_read_existing_file_ok(self, tool: ReadFileTool, temp_workspace: Path) -> None:
        content = "hello world\nthis is a test"
        self._create_test_file(temp_workspace, "test.txt", content)
        
        args = ReadFileInput(path="test.txt")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        assert result.output == content
        assert result.error is None
        assert result.evidence_hash == hashlib.sha256(content.encode("utf-8")).hexdigest()
    
    async def test_read_missing_file_returns_error(self, tool: ReadFileTool, temp_workspace: Path) -> None:
        args = ReadFileInput(path="nonexistent.txt")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert result.output == ""
        assert result.error is not None
        assert "not found" in result.error.lower()
        assert result.evidence_hash == ""
    
    async def test_path_escape_rejected(self, tool: ReadFileTool, temp_workspace: Path) -> None:
        args = ReadFileInput(path="../../etc/passwd")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert result.error is not None
        assert "escapes" in result.error.lower() or "absolute" in result.error.lower()
        assert result.evidence_hash == ""
    
    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="(AES-EXP-04) دلالات مسار ويندوز حصراً: سياسة المنتج ترفض "
               "المسارات المطلقة فعلاً (is_absolute في filesystem.py) لكن "
               "'C:/...' ليست مطلقة على POSIX — الفحص غير قابل للتطبيق هنا",
    )
    async def test_absolute_path_rejected(self, tool: ReadFileTool, temp_workspace: Path) -> None:
        args = ReadFileInput(path=str(Path("C:/Windows/System32/drivers/etc/hosts")))
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert result.error is not None
        assert "absolute" in result.error.lower()
        assert result.evidence_hash == ""
    
    async def test_evidence_hash_is_sha256_of_content(self, tool: ReadFileTool, temp_workspace: Path) -> None:
        content = "test content for hashing"
        self._create_test_file(temp_workspace, "hash_test.txt", content)
        
        args = ReadFileInput(path="hash_test.txt")
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert result.evidence_hash == expected_hash
    
    async def test_file_too_large_rejected(self, tool: ReadFileTool, temp_workspace: Path) -> None:
        large_content = "x" * (1024 * 1024 + 100)
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
        from src.factory.tools import ReadFileTool, EditFileTool
        read_tool = ReadFileTool()
        edit_tool = EditFileTool()
        
        registry.register(read_tool)
        registry.register(edit_tool)
        
        assert "read_file" in registry.list()
        assert "edit_file" in registry.list()
        assert registry.get("read_file") is read_tool
        assert registry.get("edit_file") is edit_tool
    
    def test_duplicate_registration_raises(self) -> None:
        registry = ToolRegistry()
        from src.factory.tools import ReadFileTool
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