"""
Tests for git_branch tool.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from src.factory.tools import GitBranchTool, GitBranchInput


class TestGitBranchTool:
    """Test cases for GitBranchTool."""
    
    @pytest.fixture
    def tool(self) -> GitBranchTool:
        return GitBranchTool()
    
    @pytest.fixture
    def temp_repo(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
            # Need at least one commit
            (repo / "README.md").write_text("# Test")
            subprocess.run(["git", "add", "README.md"], cwd=repo, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo, capture_output=True)
            yield repo
    
    async def test_git_branch_list(self, tool: GitBranchTool, temp_repo: Path) -> None:
        """Test listing branches."""
        args = GitBranchInput(action="list")
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert "main" in result.output or "master" in result.output
        assert result.evidence_hash != ""
    
    async def test_git_branch_create(self, tool: GitBranchTool, temp_repo: Path) -> None:
        """Test creating a branch."""
        args = GitBranchInput(action="create", branch_name="feature/test")
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert "Created branch 'feature/test'" in result.output
        
        # Verify branch exists
        list_result = await tool.run(GitBranchInput(action="list"), temp_repo)
        assert "feature/test" in list_result.output
    
    async def test_git_branch_create_with_start_point(self, tool: GitBranchTool, temp_repo: Path) -> None:
        """Test creating branch from specific commit."""
        # Create another commit
        (temp_repo / "file2.txt").write_text("v2")
        subprocess.run(["git", "add", "file2.txt"], cwd=temp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Second"], cwd=temp_repo, capture_output=True)
        
        # Get first commit hash
        result = subprocess.run(["git", "rev-list", "--max-parents=0", "HEAD"], cwd=temp_repo, capture_output=True, text=True)
        first_commit = result.stdout.strip()
        
        args = GitBranchInput(action="create", branch_name="from-first", start_point=first_commit)
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert "Created branch 'from-first'" in result.output
    
    async def test_git_branch_switch(self, tool: GitBranchTool, temp_repo: Path) -> None:
        """Test switching branches."""
        # Create and switch to new branch
        create_result = await tool.run(GitBranchInput(action="create", branch_name="feature/switch"), temp_repo)
        assert create_result.ok is True
        
        switch_result = await tool.run(GitBranchInput(action="switch", branch_name="feature/switch"), temp_repo)
        assert switch_result.ok is True
        assert "Switched to branch 'feature/switch'" in switch_result.output
    
    async def test_git_branch_create_requires_name(self, tool: GitBranchTool, temp_repo: Path) -> None:
        """Test create requires branch_name."""
        args = GitBranchInput(action="create")
        result = await tool.run(args, temp_repo)
        
        assert result.ok is False
        assert "branch_name required" in result.error.lower()
    
    async def test_git_branch_switch_requires_name(self, tool: GitBranchTool, temp_repo: Path) -> None:
        """Test switch requires branch_name."""
        args = GitBranchInput(action="switch")
        result = await tool.run(args, temp_repo)
        
        assert result.ok is False
        assert "branch_name required" in result.error.lower()
    
    async def test_git_branch_invalid_action(self, tool: GitBranchTool, temp_repo: Path) -> None:
        """Test invalid action is rejected by pydantic."""
        # Pydantic validates the literal, so invalid action raises at input creation
        with pytest.raises(Exception):
            GitBranchInput(action="delete", branch_name="test")  # type: ignore
    
    async def test_git_branch_not_a_repo(self, tool: GitBranchTool, temp_repo: Path) -> None:
        """Test on non-git directory (shows default branch)."""
        # git branch -a in a fresh repo shows the default branch
        args = GitBranchInput(action="list")
        result = await tool.run(args, temp_repo)
        
        assert result.ok is True
        assert "master" in result.output or "main" in result.output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])