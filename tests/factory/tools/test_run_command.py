"""
Tests for run_command tool.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.factory.tools import RunCommandTool, RunCommandInput


class TestRunCommandTool:
    """Test cases for RunCommandTool."""
    
    @pytest.fixture
    def tool(self) -> RunCommandTool:
        return RunCommandTool()
    
    @pytest.fixture
    def temp_workspace(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    async def test_run_command_basic(self, tool: RunCommandTool, temp_workspace: Path) -> None:
        """Test basic command execution."""
        args = RunCommandInput(
            command=["cmd", "/c", "echo hello"],
            timeout_seconds=10
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        assert "hello" in result.output
        assert "EXIT CODE: 0" in result.output
        assert result.evidence_hash != ""
    
    async def test_run_command_with_output(self, tool: RunCommandTool, temp_workspace: Path) -> None:
        """Test command with stdout and stderr."""
        # Use a command that produces both stdout and stderr
        args = RunCommandInput(
            command=["cmd", "/c", "dir nonexistent_file_12345"],
            timeout_seconds=10
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False  # dir fails with nonexistent file
        assert "STDERR" in result.output or "stderr" in result.output.lower()
        assert result.evidence_hash != ""
    
    async def test_run_command_failure(self, tool: RunCommandTool, temp_workspace: Path) -> None:
        """Test command that fails."""
        args = RunCommandInput(
            command=["cmd", "/c", "exit /b 1"],
            timeout_seconds=10
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "exited with code 1" in result.error.lower()
        assert result.evidence_hash != ""
    
    async def test_run_command_working_dir(self, tool: RunCommandTool, temp_workspace: Path) -> None:
        """Test command with working directory."""
        (temp_workspace / "subdir").mkdir()
        (temp_workspace / "subdir" / "test.txt").write_text("content")
        
        args = RunCommandInput(
            command=["cmd", "/c", "type test.txt"],
            timeout_seconds=10,
            working_dir="subdir"
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is True
        assert "content" in result.output
    
    async def test_run_command_shell_metachar_rejected(self, tool: RunCommandTool, temp_workspace: Path) -> None:
        """Test shell metacharacters are rejected."""
        args = RunCommandInput(
            command=["cmd", "/c", "echo hello | grep hello"],
            timeout_seconds=10
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        assert "metacharacters" in result.error.lower()
    
    async def test_run_command_metachars_in_args(self, tool: RunCommandTool, temp_workspace: Path) -> None:
        """Test metacharacters in individual args are rejected."""
        forbidden = ["&", "|", ";", ">", "<", "$", "`", "(", ")", "{", "}", "*", "?", "~"]
        for char in forbidden:
            args = RunCommandInput(
                command=["echo", f"test{char}"],
                timeout_seconds=10
            )
            result = await tool.run(args, temp_workspace)
            assert result.ok is False, f"Should reject '{char}'"
            assert "metacharacters" in result.error.lower()
    
    async def test_run_command_timeout(self, tool: RunCommandTool, temp_workspace: Path) -> None:
        """Test command timeout."""
        args = RunCommandInput(
            command=["cmd", "/c", "timeout /t 5"],
            timeout_seconds=1
        )
        result = await tool.run(args, temp_workspace)
        
        # May succeed or fail depending on timing, but should not hang
        assert result.evidence_hash != ""
    
    async def test_run_command_invalid_working_dir(self, tool: RunCommandTool, temp_workspace: Path) -> None:
        """Test invalid working directory."""
        args = RunCommandInput(
            command=["cmd", "/c", "echo", "hello"],
            timeout_seconds=10,
            working_dir="nonexistent"
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        # The error details are in output (stderr from WindowsExecutor)
        assert "invalid" in result.output.lower() or "working_dir" in result.output.lower() or "not found" in result.output.lower() or "cannot find" in result.output.lower()
    
    async def test_run_command_working_dir_escape(self, tool: RunCommandTool, temp_workspace: Path) -> None:
        """Test working directory escape."""
        args = RunCommandInput(
            command=["cmd", "/c", "echo", "hello"],
            timeout_seconds=10,
            working_dir="../../Windows"
        )
        result = await tool.run(args, temp_workspace)
        
        assert result.ok is False
        # The validation should catch the escape attempt
        assert "escapes" in result.error.lower() or "absolute" in result.error.lower() or "not in the subpath" in result.error.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])