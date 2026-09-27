"""
Tests for git_diff tool.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from src.factory.tools import GitDiffTool, GitDiffInput


class TestGitDiffTool:
    """Test cases for GitDiffTool."""
    
    @pytest.fixture
    def tool(self) -> GitDiffTool:
        return GitDiffTool()
    
    @pytest.fixture
    def temp_repo(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
            yield repo
    
    async def test_git_diff_working_tree(self, tool: GitDiffTool, temp_repo: Path) -> None:
        """Test diff of working tree changes."""
        (temp_repo / "file.txt").write_text("line 1\nline 2\nline 3")
        subprocess.run(["git", "add", "file.txt"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=temp_repo, capture_output=True)
        
        (temp_repo / "file.txt").write_text("line 1\nline 2 modified\nline 3\nline 4")
        
        args = GitDiffInput(staged=False)
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert "line 2 modified" in result.output
        assert "line 4" in result.output
        assert result.evidence_hash != ""
    
    async def test_git_diff_staged(self, tool: GitDiffTool, temp_repo: Path) -> None:
        """Test diff of staged changes."""
        (temp_repo / "file.txt").write_text("line 1\nline 2\nline 3")
        subprocess.run(["git", "add", "file.txt"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=temp_repo, capture_output=True)
        
        (temp_repo / "file.txt").write_text("line 1\nline 2 staged\nline 3")
        subprocess.run(["git", "add", "file.txt"], cwd=temp_repo, capture_output=True)
        
        args = GitDiffInput(staged=True)
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert "line 2 staged" in result.output
    
    async def test_git_diff_path_filter(self, tool: GitDiffTool, temp_repo: Path) -> None:
        """Test diff with path filter."""
        (temp_repo / "file1.txt").write_text("file1 original")
        (temp_repo / "file2.txt").write_text("file2 original")
        subprocess.run(["git", "add", "."], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=temp_repo, capture_output=True)
        
        (temp_repo / "file1.txt").write_text("file1 modified")
        (temp_repo / "file2.txt").write_text("file2 modified")
        
        args = GitDiffInput(staged=False, path="file1.txt")
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert "file1 modified" in result.output
        assert "file2" not in result.output
    
    async def test_git_diff_no_changes(self, tool: GitDiffTool, temp_repo: Path) -> None:
        """Test diff with no changes."""
        (temp_repo / "file.txt").write_text("content")
        subprocess.run(["git", "add", "file.txt"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=temp_repo, capture_output=True)
        
        args = GitDiffInput()
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert result.output == "(no changes)"
    
    async def test_git_diff_max_bytes(self, tool: GitDiffTool, temp_repo: Path) -> None:
        """Test diff output truncation."""
        large_content = "x" * 10000
        (temp_repo / "large.txt").write_text(large_content)
        subprocess.run(["git", "add", "large.txt"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=temp_repo, capture_output=True)
        
        (temp_repo / "large.txt").write_text("y" * 10000)
        
        args = GitDiffInput(max_bytes=1000)
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert len(result.output.encode("utf-8")) <= 2000  # some overhead
        assert "(truncated)" in result.output
    
    async def test_git_diff_not_a_repo(self, tool: GitDiffTool, temp_repo: Path) -> None:
        """Test diff on non-git directory (shows no changes)."""
        (temp_repo / "file.txt").write_text("content")
        
        args = GitDiffInput()
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert result.output == "(no changes)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])