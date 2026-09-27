"""
Filesystem tools for reading files within workspace.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from pydantic import BaseModel, Field

from .base import BaseTool, ToolResult


class ReadFileInput(BaseModel):
    """Input for read_file tool."""
    path: str = Field(..., description="Relative path to file within workspace_root")


class ReadFileTool(BaseTool):
    """Read a UTF-8 file from the workspace."""
    
    name = "read_file"
    description = "Read a UTF-8 file. Path must be inside workspace_root."
    input_schema = ReadFileInput
    
    async def run(self, args: ReadFileInput, workspace_root: Path) -> ToolResult:
        # Resolve workspace root
        workspace_root = workspace_root.resolve()
        
        # Resolve the requested path
        try:
            requested_path = (workspace_root / args.path).resolve()
        except Exception as e:
            return ToolResult.failure(f"Invalid path: {e}")
        
        # Security checks
        # 1. Reject absolute paths (args.path should be relative)
        if Path(args.path).is_absolute():
            return ToolResult.failure("Absolute paths are not allowed. Use relative path from workspace_root.")
        
        # 2. Reject paths escaping workspace_root
        try:
            requested_path.relative_to(workspace_root)
        except ValueError:
            return ToolResult.failure("Path escapes workspace_root")
        
        # 3. Check file exists
        if not requested_path.exists():
            return ToolResult.failure(f"File not found: {args.path}")
        
        # 4. Check it's a file (not directory)
        if not requested_path.is_file():
            return ToolResult.failure(f"Path is not a file: {args.path}")
        
        # 5. Check file size (1 MB limit)
        MAX_SIZE = 1024 * 1024  # 1 MB
        file_size = requested_path.stat().st_size
        if file_size > MAX_SIZE:
            return ToolResult.failure(f"File too large: {file_size} bytes (max {MAX_SIZE})")
        
        # 6. Read file content
        try:
            content = requested_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult.failure(f"File is not valid UTF-8: {args.path}")
        except Exception as e:
            return ToolResult.failure(f"Failed to read file: {e}")
        
        # 7. Compute evidence hash
        evidence_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        
        return ToolResult.success(content, evidence_hash)