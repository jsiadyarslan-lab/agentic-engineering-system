"""
Git tools for repository operations.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Literal

from .base import BaseTool, ToolResult


# Shared helper
def _run_git(workspace_root: Path, git_args: list[str]) -> tuple[int, str, str]:
    """Run git command and return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + git_args,
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Git command timed out"
    except Exception as e:
        return -1, "", str(e)


class GitStatusInput(BaseModel):
    """Input for git_status tool."""
    pass


class GitStatusTool(BaseTool):
    """Show git status in porcelain format."""
    
    name = "git_status"
    description = "Show git status (staged, unstaged, untracked files)."
    input_schema = GitStatusInput
    
    async def run(self, args: GitStatusInput, workspace_root: Path) -> ToolResult:
        workspace_root = workspace_root.resolve()
        
        exit_code, stdout, stderr = _run_git(workspace_root, ["status", "--porcelain=v1"])
        
        if exit_code != 0:
            return ToolResult.failure(f"git status failed: {stderr}")
        
        # Parse porcelain output - split by lines WITHOUT stripping (leading space matters)
        staged = []
        unstaged = []
        untracked = []
        
        for line in stdout.splitlines():
            if not line:
                continue
            if len(line) < 3:
                continue
            status_xy = line[:2]
            filepath = line[3:]
            
            if status_xy[0] != " " and status_xy[0] != "?":
                staged.append(filepath)
            if status_xy[1] != " " and status_xy[1] != "?":
                unstaged.append(filepath)
            if status_xy == "??":
                untracked.append(filepath)
        
        output = f"STAGED ({len(staged)}):\n" + "\n".join(f"  {f}" for f in staged)
        output += f"\n\nUNSTAGED ({len(unstaged)}):\n" + "\n".join(f"  {f}" for f in unstaged)
        output += f"\n\nUNTRACKED ({len(untracked)}):\n" + "\n".join(f"  {f}" for f in untracked)
        
        evidence_hash = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
        
        return ToolResult.success(output, evidence_hash)


class GitDiffInput(BaseModel):
    """Input for git_diff tool."""
    staged: bool = Field(default=False, description="Show staged changes instead of working tree")
    path: str | None = Field(default=None, description="Limit diff to specific path")
    max_bytes: int = Field(default=50000, ge=1000, le=1000000, description="Max output bytes")


class GitDiffTool(BaseTool):
    """Show git diff."""
    
    name = "git_diff"
    description = "Show git diff (staged or working tree)."
    input_schema = GitDiffInput
    
    async def run(self, args: GitDiffInput, workspace_root: Path) -> ToolResult:
        workspace_root = workspace_root.resolve()
        
        git_args = ["diff"]
        if args.staged:
            git_args.append("--staged")
        if args.path:
            git_args.extend(["--", args.path])
        
        exit_code, stdout, stderr = _run_git(workspace_root, git_args)
        
        if exit_code != 0:
            return ToolResult.failure(f"git diff failed: {stderr}")
        
        # Truncate if needed
        if len(stdout.encode("utf-8")) > args.max_bytes:
            stdout = stdout[:args.max_bytes] + "\n... (truncated)"
        
        evidence_hash = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
        
        if not stdout.strip():
            return ToolResult.success("(no changes)", evidence_hash)
        
        return ToolResult.success(stdout, evidence_hash)


class GitCommitInput(BaseModel):
    """Input for git_commit tool."""
    message: str = Field(..., description="Commit message")
    allow_empty: bool = Field(default=False, description="Allow empty commit")
    user_confirmation: str = Field(..., description="Must be 'CONFIRM' to proceed")


class GitCommitTool(BaseTool):
    """Create a git commit (requires explicit confirmation)."""
    
    name = "git_commit"
    description = "Create a git commit. Requires user_confirmation='CONFIRM'."
    input_schema = GitCommitInput
    
    async def run(self, args: GitCommitInput, workspace_root: Path) -> ToolResult:
        if args.user_confirmation != "CONFIRM":
            return ToolResult.failure("user_confirmation must be 'CONFIRM' to proceed")
        
        workspace_root = workspace_root.resolve()
        
        git_args = ["commit", "-m", args.message]
        if args.allow_empty:
            git_args.append("--allow-empty")
        
        exit_code, stdout, stderr = _run_git(workspace_root, git_args)
        
        if exit_code != 0:
            return ToolResult.failure(f"git commit failed: {stderr}")
        
        output = stdout.strip()
        evidence_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
        
        return ToolResult.success(output, evidence_hash)


class GitBranchInput(BaseModel):
    """Input for git_branch tool."""
    action: Literal["list", "create", "switch"] = Field(..., description="Action to perform")
    branch_name: str | None = Field(default=None, description="Branch name for create/switch")
    start_point: str | None = Field(default=None, description="Start point for create")


class GitBranchTool(BaseTool):
    """List, create, or switch git branches."""
    
    name = "git_branch"
    description = "List, create, or switch git branches. Refuses force delete."
    input_schema = GitBranchInput
    
    async def run(self, args: GitBranchInput, workspace_root: Path) -> ToolResult:
        workspace_root = workspace_root.resolve()
        
        if args.action == "list":
            exit_code, stdout, stderr = _run_git(workspace_root, ["branch", "-a"])
            if exit_code != 0:
                return ToolResult.failure(f"git branch failed: {stderr}")
            output = stdout.strip() or "(no branches)"
            evidence_hash = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
            return ToolResult.success(output, evidence_hash)
        
        if args.action == "create":
            if not args.branch_name:
                return ToolResult.failure("branch_name required for create")
            git_args = ["branch"]
            if args.start_point:
                git_args.extend([args.branch_name, args.start_point])
            else:
                git_args.append(args.branch_name)
            
            exit_code, stdout, stderr = _run_git(workspace_root, git_args)
            if exit_code != 0:
                return ToolResult.failure(f"git branch create failed: {stderr}")
            output = f"Created branch '{args.branch_name}'"
            evidence_hash = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
            return ToolResult.success(output, evidence_hash)
        
        if args.action == "switch":
            if not args.branch_name:
                return ToolResult.failure("branch_name required for switch")
            exit_code, stdout, stderr = _run_git(workspace_root, ["switch", args.branch_name])
            if exit_code != 0:
                return ToolResult.failure(f"git switch failed: {stderr}")
            output = f"Switched to branch '{args.branch_name}'"
            evidence_hash = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
            return ToolResult.success(output, evidence_hash)
        
        return ToolResult.failure(f"Unknown action: {args.action}")