"""
Tests for git_status tool.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from src.factory.tools import GitStatusTool, GitStatusInput


class TestGitStatusTool:
    """Test cases for GitStatusTool."""
    
    @pytest.fixture
    def tool(self) -> GitStatusTool:
        return GitStatusTool()
    
    @pytest.fixture
    def temp_repo(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            # Initialize git repo
            subprocess.run(["git", "init"], cwd=repo, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
            yield repo
    
    async def test_git_status_clean(self, tool: GitStatusTool, temp_repo: Path) -> None:
        """Test status on clean repo."""
        (temp_repo / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "README.md"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=temp_repo, capture_output=True)
        
        args = GitStatusInput()
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert "STAGED (0)" in result.output
        assert "UNSTAGED (0)" in result.output
        assert "UNTRACKED (0)" in result.output
        assert result.evidence_hash != ""
    
    async def test_git_status_staged(self, tool: GitStatusTool, temp_repo: Path) -> None:
        """Test status with staged files."""
        (temp_repo / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "README.md"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=temp_repo, capture_output=True)
        
        (temp_repo / "new.txt").write_text("new file")
        subprocess.run(["git", "add", "new.txt"], cwd=temp_repo, capture_output=True)
        
        args = GitStatusInput()
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert "STAGED (1)" in result.output
        assert "new.txt" in result.output
    
    async def test_git_status_unstaged(self, tool: GitStatusTool, temp_repo: Path) -> None:
        """Test status with unstaged changes."""
        (temp_repo / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "README.md"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=temp_repo, capture_output=True)
        
        (temp_repo / "README.md").write_text("# Updated")
        
        args = GitStatusInput()
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert "UNSTAGED (1)" in result.output
        assert "README.md" in result.output
    
    async def test_git_status_untracked(self, tool: GitStatusTool, temp_repo: Path) -> None:
        """Test status with untracked files."""
        (temp_repo / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "README.md"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=temp_repo, capture_output=True)
        
        (temp_repo / "untracked.txt").write_text("untracked")
        
        args = GitStatusInput()
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert "UNTRACKED (1)" in result.output
        assert "untracked.txt" in result.output
    
    async def test_git_status_mixed(self, tool: GitStatusTool, temp_repo: Path) -> None:
        """Test status with mixed changes."""
        (temp_repo / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "README.md"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=temp_repo, capture_output=True)
        
        (temp_repo / "staged.txt").write_text("staged")
        subprocess.run(["git", "add", "staged.txt"], cwd=temp_repo, capture_output=True)
        
        # Modify a tracked file to make it unstaged
        (temp_repo / "README.md").write_text("# Updated")
        
        (temp_repo / "untracked.txt").write_text("untracked")
        
        args = GitStatusInput()
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert "STAGED (1)" in result.output
        assert "UNSTAGED (1)" in result.output
        assert "UNTRACKED (1)" in result.output
        assert "staged.txt" in result.output
        assert "README.md" in result.output
        assert "untracked.txt" in result.output
    
    async def test_git_status_not_a_repo(self, tool: GitStatusTool, temp_repo: Path) -> None:
        """Test status on non-git directory (shows all as untracked)."""
        (temp_repo / "file.txt").write_text("content")
        
        args = GitStatusInput()
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert "UNTRACKED (1)" in result.output
        assert "file.txt" in result.output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])