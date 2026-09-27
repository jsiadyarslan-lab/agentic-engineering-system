"""
Tests for git_commit tool.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from src.factory.tools import GitCommitTool, GitCommitInput, GitStatusTool, GitStatusInput


class TestGitCommitTool:
    """Test cases for GitCommitTool."""
    
    @pytest.fixture
    def tool(self) -> GitCommitTool:
        return GitCommitTool()
    
    @pytest.fixture
    def status_tool(self) -> GitStatusTool:
        return GitStatusTool()
    
    @pytest.fixture
    def temp_repo(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
            yield repo
    
    async def test_git_commit_basic(self, tool: GitCommitTool, status_tool: GitStatusTool, temp_repo: Path) -> None:
        """Test basic commit."""
        (temp_repo / "file.txt").write_text("content")
        subprocess.run(["git", "add", "file.txt"], cwd=temp_repo, capture_output=True)
        
        args = GitCommitInput(message="Initial commit", user_confirmation="CONFIRM")
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert "commit" in result.output.lower() or "files changed" in result.output.lower()
        
        # Verify commit exists
        status = await status_tool.run(GitStatusInput(), temp_repo)
        assert status.ok is True
        assert "STAGED (0)" in status.output
    
    async def test_git_commit_requires_confirmation(self, tool: GitCommitTool, temp_repo: Path) -> None:
        """Test commit requires confirmation."""
        (temp_repo / "file.txt").write_text("content")
        subprocess.run(["git", "add", "file.txt"], cwd=temp_repo, capture_output=True)
        
        args = GitCommitInput(message="Test", user_confirmation="wrong")
        result = await tool.run(args, temp_repo)
        
        assert result.ok is False
        assert "confirm" in result.error.lower()
    
    async def test_git_commit_allow_empty(self, tool: GitCommitTool, temp_repo: Path) -> None:
        """Test empty commit."""
        subprocess.run(["git", "commit", "--allow-empty", "-m", "Initial"], cwd=temp_repo, capture_output=True)
        
        args = GitCommitInput(message="Empty commit", allow_empty=True, user_confirmation="CONFIRM")
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
    
    async def test_git_commit_no_changes_fails_without_allow_empty(self, tool: GitCommitTool, temp_repo: Path) -> None:
        """Test commit with no changes fails without allow_empty."""
        # Fresh repo with no commits
        args = GitCommitInput(message="No changes", user_confirmation="CONFIRM")
        result = await tool.run(args, temp_repo)
        
        # Git will fail because there's nothing to commit
        assert result.ok is False
    
    async def test_git_commit_evidence_hash(self, tool: GitCommitTool, temp_repo: Path) -> None:
        """Test evidence hash."""
        (temp_repo / "file.txt").write_text("content")
        subprocess.run(["git", "add", "file.txt"], cwd=temp_repo, capture_output=True)
        
        args = GitCommitInput(message="Test commit", user_confirmation="CONFIRM")
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert result.evidence_hash != ""
        import hashlib
        expected = hashlib.sha256(result.output.encode("utf-8")).hexdigest()
        assert result.evidence_hash == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])