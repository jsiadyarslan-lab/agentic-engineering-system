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


class EditFileInput(BaseModel):
    """Input for edit_file tool."""
    path: str = Field(..., description="Relative path to file within workspace_root")
    old_text: str = Field(..., description="Exact text to replace (must appear exactly once)")
    new_text: str = Field(..., description="Replacement text")


class EditFileTool(BaseTool):
    """Replace exact old_text with new_text in a UTF-8 file."""
    
    name = "edit_file"
    description = "Replace exact old_text with new_text in a UTF-8 file."
    input_schema = EditFileInput
    
    async def run(self, args: EditFileInput, workspace_root: Path) -> ToolResult:
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
        
        # 7. Check old_text exists exactly once
        count = content.count(args.old_text)
        if count == 0:
            return ToolResult.failure(f"old_text not found in file: {args.path}")
        if count > 1:
            return ToolResult.failure(f"old_text appears {count} times (must be unique): {args.path}")
        
        # 8. Replace and write atomically
        new_content = content.replace(args.old_text, args.new_text)
        
        # Write to temp file then rename for atomicity
        import tempfile
        import os
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=requested_path.parent,
                delete=False,
                prefix=f".{requested_path.name}.tmp.",
                suffix='.tmp'
            ) as tmp:
                tmp.write(new_content)
                tmp_path = Path(tmp.name)
            
            # Atomic rename
            os.replace(tmp_path, requested_path)
        except Exception as e:
            # Cleanup temp file on failure
            if 'tmp_path' in locals() and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return ToolResult.failure(f"Failed to write file: {e}")
        
        # 9. Compute evidence hash of NEW content
        evidence_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
        
        return ToolResult.success(new_content, evidence_hash)