"""
Execution tool for running commands via WindowsExecutor.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from pydantic import BaseModel, Field

from .base import BaseTool, ToolResult


class RunCommandInput(BaseModel):
    """Input for run_command tool."""
    command: list[str] = Field(..., description="Command as list of strings (no shell metacharacters)")
    timeout_seconds: int = Field(default=30, ge=1, le=300, description="Timeout in seconds")
    working_dir: str | None = Field(default=None, description="Working directory relative to workspace_root")


class RunCommandTool(BaseTool):
    """Run a command using WindowsExecutor (no shell)."""
    
    name = "run_command"
    description = "Run a command via WindowsExecutor. No shell metacharacters allowed."
    input_schema = RunCommandInput
    
    async def run(self, args: RunCommandInput, workspace_root: Path) -> ToolResult:
        # Import WindowsExecutor here to avoid circular imports
        from substrate.windows_executor import WindowsExecutor, ExecutionLimits
        
        # Resolve workspace root
        workspace_root = workspace_root.resolve()
        
        # Resolve working directory
        if args.working_dir:
            try:
                working_dir = (workspace_root / args.working_dir).resolve()
                working_dir.relative_to(workspace_root)
            except Exception as e:
                return ToolResult.failure(f"Invalid working_dir: {e}")
        else:
            working_dir = workspace_root
        
        # Validate command - no shell metacharacters
        forbidden = {'|', '>', '<', '&', ';', '$', '`', '(', ')', '{', '}', '*', '?', '~'}
        for part in args.command:
            if any(c in part for c in forbidden):
                return ToolResult.failure(f"Shell metacharacters not allowed in command: {part}")
        
        # Execute via WindowsExecutor
        try:
            executor = WindowsExecutor()
            limits = ExecutionLimits(
                wall_time_seconds=args.timeout_seconds,
                memory_bytes=512 * 1024 * 1024,
                cpu_percent=50,
            )
            result = executor.execute(
                command=args.command,
                working_dir=str(working_dir),
                limits=limits,
            )
        except Exception as e:
            return ToolResult.failure(f"Execution failed: {e}")
        
        # Build output
        output_parts = []
        if result.stdout:
            output_parts.append(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            output_parts.append(f"STDERR:\n{result.stderr}")
        output_parts.append(f"EXIT CODE: {result.exit_code}")
        output = "\n\n".join(output_parts)
        
        # Compute evidence hash from stdout + stderr + exit_code
        evidence_data = f"{result.stdout}{result.stderr}{result.exit_code}"
        evidence_hash = hashlib.sha256(evidence_data.encode("utf-8")).hexdigest()
        
        if result.exit_code != 0:
            return ToolResult(
                ok=False,
                output=output,
                error=f"Command exited with code {result.exit_code}",
                evidence_hash=evidence_hash,
            )
        
        return ToolResult.success(output, evidence_hash)