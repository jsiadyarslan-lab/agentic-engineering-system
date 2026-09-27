"""
Filesystem tools for reading, writing, and searching files within workspace.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import tempfile
from pathlib import Path
from pydantic import BaseModel, Field

from .base import BaseTool, ToolResult


# Shared constants
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "target", ".cargo", ".tracker"}
MAX_ENTRIES = 500
MAX_SIZE = 1024 * 1024  # 1 MB


def _resolve_and_validate(workspace_root: Path, rel_path: str, must_exist: bool = True, must_be_file: bool = False) -> tuple[Path | None, ToolResult | None]:
    """Resolve path and validate it's within workspace_root."""
    workspace_root = workspace_root.resolve()
    try:
        requested_path = (workspace_root / rel_path).resolve()
    except Exception as e:
        return None, ToolResult.failure(f"Invalid path: {e}")
    
    if Path(rel_path).is_absolute():
        return None, ToolResult.failure("Absolute paths are not allowed. Use relative path from workspace_root.")
    
    try:
        requested_path.relative_to(workspace_root)
    except ValueError:
        return None, ToolResult.failure("Path escapes workspace_root")
    
    if must_exist and not requested_path.exists():
        return None, ToolResult.failure(f"Path not found: {rel_path}")
    
    if must_be_file and not requested_path.is_file():
        return None, ToolResult.failure(f"Path is not a file: {rel_path}")
    
    return requested_path, None


class ReadFileInput(BaseModel):
    """Input for read_file tool."""
    path: str = Field(..., description="Relative path to file within workspace_root")


class ReadFileTool(BaseTool):
    """Read a UTF-8 file from the workspace."""
    
    name = "read_file"
    description = "Read a UTF-8 file. Path must be inside workspace_root."
    input_schema = ReadFileInput
    
    async def run(self, args: ReadFileInput, workspace_root: Path) -> ToolResult:
        requested_path, error = _resolve_and_validate(workspace_root, args.path, must_exist=True, must_be_file=True)
        if error:
            return error
        
        file_size = requested_path.stat().st_size
        if file_size > MAX_SIZE:
            return ToolResult.failure(f"File too large: {file_size} bytes (max {MAX_SIZE})")
        
        try:
            content = requested_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult.failure(f"File is not valid UTF-8: {args.path}")
        except Exception as e:
            return ToolResult.failure(f"Failed to read file: {e}")
        
        evidence_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return ToolResult.success(content, evidence_hash)


class ListDirInput(BaseModel):
    """Input for list_dir tool."""
    path: str = Field(default=".", description="Relative directory path within workspace_root")
    recursive: bool = Field(default=False, description="List recursively")
    max_entries: int = Field(default=MAX_ENTRIES, ge=1, le=5000, description="Max entries to return")


class ListDirTool(BaseTool):
    """List directory contents."""
    
    name = "list_dir"
    description = "List directory contents. Skips .git, __pycache__, .venv, node_modules."
    input_schema = ListDirInput
    
    async def run(self, args: ListDirInput, workspace_root: Path) -> ToolResult:
        requested_path, error = _resolve_and_validate(workspace_root, args.path, must_exist=True, must_be_file=False)
        if error:
            return error
        
        if not requested_path.is_dir():
            return ToolResult.failure(f"Path is not a directory: {args.path}")
        
        entries = []
        try:
            if args.recursive:
                for root, dirs, files in os.walk(requested_path):
                    # Filter out skip dirs
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                    for f in files:
                        full_path = Path(root) / f
                        rel = full_path.relative_to(workspace_root)
                        entries.append(str(rel).replace("\\", "/"))
                        if len(entries) >= args.max_entries:
                            break
                    if len(entries) >= args.max_entries:
                        break
            else:
                for entry in requested_path.iterdir():
                    if entry.name in SKIP_DIRS:
                        continue
                    rel = entry.relative_to(workspace_root)
                    entries.append(str(rel).replace("\\", "/"))
                    if len(entries) >= args.max_entries:
                        break
        except Exception as e:
            return ToolResult.failure(f"Failed to list directory: {e}")
        
        output = "\n".join(sorted(entries)) if entries else "(empty)"
        evidence_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
        return ToolResult.success(output, evidence_hash)


class GrepInput(BaseModel):
    """Input for grep tool."""
    pattern: str = Field(..., description="Regex pattern to search for")
    path: str = Field(default=".", description="Relative path to search in")
    glob: str | None = Field(default=None, description="Optional glob filter (e.g., '*.py')")
    max_matches: int = Field(default=200, ge=1, le=5000, description="Max matches to return")
    ignore_case: bool = Field(default=False, description="Case-insensitive search")


class GrepTool(BaseTool):
    """Search for regex pattern in files."""
    
    name = "grep"
    description = "Search for regex pattern in files within workspace."
    input_schema = GrepInput
    
    async def run(self, args: GrepInput, workspace_root: Path) -> ToolResult:
        requested_path, error = _resolve_and_validate(workspace_root, args.path, must_exist=True, must_be_file=False)
        if error:
            return error
        
        if not requested_path.is_dir():
            return ToolResult.failure(f"Path is not a directory: {args.path}")
        
        try:
            flags = re.IGNORECASE if args.ignore_case else 0
            regex = re.compile(args.pattern, flags)
        except re.error as e:
            return ToolResult.failure(f"Invalid regex pattern: {e}")
        
        matches = []
        try:
            for root, dirs, files in os.walk(requested_path):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for f in files:
                    if args.glob and not Path(f).match(args.glob):
                        continue
                    full_path = Path(root) / f
                    if full_path.stat().st_size > MAX_SIZE:
                        continue
                    try:
                        content = full_path.read_text(encoding="utf-8")
                    except (UnicodeDecodeError, PermissionError):
                        continue
                    for i, line in enumerate(content.splitlines(), 1):
                        if regex.search(line):
                            rel = full_path.relative_to(workspace_root)
                            matches.append(f"{str(rel).replace(os.sep, '/')}:{i}:{line.strip()}")
                            if len(matches) >= args.max_matches:
                                break
                    if len(matches) >= args.max_matches:
                        break
        except Exception as e:
            return ToolResult.failure(f"Search failed: {e}")
        
        output = "\n".join(matches) if matches else "(no matches)"
        evidence_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
        return ToolResult.success(output, evidence_hash)


class FindFilesInput(BaseModel):
    """Input for find_files tool."""
    pattern: str = Field(..., description="Glob pattern to match files (e.g., '**/*.py')")
    path: str = Field(default=".", description="Relative directory path within workspace_root")
    max_results: int = Field(default=MAX_ENTRIES, ge=1, le=5000, description="Max results to return")


class FindFilesTool(BaseTool):
    """Find files matching glob pattern."""
    
    name = "find_files"
    description = "Find files matching glob pattern. Skips .git, __pycache__, .venv."
    input_schema = FindFilesInput
    
    async def run(self, args: FindFilesInput, workspace_root: Path) -> ToolResult:
        requested_path, error = _resolve_and_validate(workspace_root, args.path, must_exist=True, must_be_file=False)
        if error:
            return error
        
        if not requested_path.is_dir():
            return ToolResult.failure(f"Path is not a directory: {args.path}")
        
        results = []
        try:
            # Use rglob for recursive matching (more intuitive for users)
            # If pattern doesn't contain **, treat as recursive
            if "**" in args.pattern:
                iterator = requested_path.glob(args.pattern)
            else:
                iterator = requested_path.rglob(args.pattern)
            
            for match in iterator:
                if not match.is_file():
                    continue
                # Check if any parent is in SKIP_DIRS
                if any(p.name in SKIP_DIRS for p in match.parents):
                    continue
                if match.stat().st_size > MAX_SIZE:
                    continue
                rel = match.relative_to(workspace_root)
                # Normalize path separators to forward slash
                results.append(str(rel).replace("\\", "/"))
                if len(results) >= args.max_results:
                    break
        except Exception as e:
            return ToolResult.failure(f"Find failed: {e}")
        
        output = "\n".join(sorted(results)) if results else "(no files found)"
        evidence_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
        return ToolResult.success(output, evidence_hash)


class WriteFileInput(BaseModel):
    """Input for write_file tool."""
    path: str = Field(..., description="Relative path to file within workspace_root")
    content: str = Field(..., description="Content to write")
    overwrite: bool = Field(default=False, description="Overwrite if file exists")


class WriteFileTool(BaseTool):
    """Write content to a file (creates parent dirs)."""
    
    name = "write_file"
    description = "Write content to a file. Creates parent directories. Requires overwrite=True to replace existing."
    input_schema = WriteFileInput
    
    async def run(self, args: WriteFileInput, workspace_root: Path) -> ToolResult:
        workspace_root = workspace_root.resolve()
        try:
            requested_path = (workspace_root / args.path).resolve()
        except Exception as e:
            return ToolResult.failure(f"Invalid path: {e}")
        
        if Path(args.path).is_absolute():
            return ToolResult.failure("Absolute paths are not allowed. Use relative path from workspace_root.")
        
        try:
            requested_path.relative_to(workspace_root)
        except ValueError:
            return ToolResult.failure("Path escapes workspace_root")
        
        if requested_path.exists() and not args.overwrite:
            return ToolResult.failure(f"File exists (use overwrite=True): {args.path}")
        
        # Create parent dirs
        requested_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Atomic write
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=requested_path.parent,
                delete=False,
                prefix=f".{requested_path.name}.tmp.",
                suffix='.tmp'
            ) as tmp:
                tmp.write(args.content)
                tmp_path = Path(tmp.name)
            os.replace(tmp_path, requested_path)
        except Exception as e:
            if 'tmp_path' in locals() and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return ToolResult.failure(f"Failed to write file: {e}")
        
        evidence_hash = hashlib.sha256(args.content.encode("utf-8")).hexdigest()
        return ToolResult.success(f"Written {len(args.content)} bytes to {args.path}", evidence_hash)


class ParsePythonInput(BaseModel):
    """Input for parse_python tool."""
    path: str = Field(..., description="Relative path to Python file within workspace_root")


class ParsePythonTool(BaseTool):
    """Parse Python file with AST and extract functions, classes, imports."""
    
    name = "parse_python"
    description = "Parse Python file with AST. Returns functions, classes, imports, syntax errors."
    input_schema = ParsePythonInput
    
    async def run(self, args: ParsePythonInput, workspace_root: Path) -> ToolResult:
        requested_path, error = _resolve_and_validate(workspace_root, args.path, must_exist=True, must_be_file=True)
        if error:
            return error
        
        if requested_path.stat().st_size > MAX_SIZE:
            return ToolResult.failure(f"File too large: {requested_path.stat().st_size} bytes (max {MAX_SIZE})")
        
        try:
            content = requested_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult.failure(f"File is not valid UTF-8: {args.path}")
        except Exception as e:
            return ToolResult.failure(f"Failed to read file: {e}")
        
        try:
            tree = ast.parse(content, filename=args.path)
        except SyntaxError as e:
            error_msg = f"Syntax error at line {e.lineno}, col {e.offset}: {e.msg}"
            evidence_hash = hashlib.sha256(error_msg.encode("utf-8")).hexdigest()
            return ToolResult(
                ok=False,
                output=error_msg,
                error=error_msg,
                evidence_hash=evidence_hash,
            )
        
        functions = []
        classes = []
        imports = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append({
                    "name": node.name,
                    "line": node.lineno,
                    "args": [a.arg for a in node.args.args],
                    "returns": ast.unparse(node.returns) if node.returns else None,
                })
            elif isinstance(node, ast.AsyncFunctionDef):
                functions.append({
                    "name": node.name,
                    "line": node.lineno,
                    "args": [a.arg for a in node.args.args],
                    "returns": ast.unparse(node.returns) if node.returns else None,
                    "async": True,
                })
            elif isinstance(node, ast.ClassDef):
                classes.append({
                    "name": node.name,
                    "line": node.lineno,
                    "bases": [ast.unparse(b) for b in node.bases],
                    "methods": [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))],
                })
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append({"module": alias.name, "alias": alias.asname, "line": node.lineno})
                else:
                    module = node.module or ""
                    for alias in node.names:
                        imports.append({"module": module, "name": alias.name, "alias": alias.asname, "line": node.lineno})
        
        output_lines = []
        output_lines.append(f"FILE: {args.path}")
        output_lines.append(f"FUNCTIONS ({len(functions)}):")
        for f in functions:
            async_marker = " async" if f.get("async") else ""
            ret = f" -> {f['returns']}" if f.get("returns") else ""
            output_lines.append(f"  {f['name']}({', '.join(f['args'])}){ret}{async_marker}  [line {f['line']}]")
        output_lines.append(f"CLASSES ({len(classes)}):")
        for c in classes:
            bases = f"({', '.join(c['bases'])})" if c['bases'] else ""
            output_lines.append(f"  {c['name']}{bases}  [line {c['line']}]")
            for m in c['methods']:
                output_lines.append(f"    .{m}")
        output_lines.append(f"IMPORTS ({len(imports)}):")
        for imp in imports:
            if 'name' in imp:
                output_lines.append(f"  from {imp['module']} import {imp['name']}" + (f" as {imp['alias']}" if imp.get('alias') else "") + f"  [line {imp['line']}]")
            else:
                output_lines.append(f"  import {imp['module']}" + (f" as {imp['alias']}" if imp.get('alias') else "") + f"  [line {imp['line']}]")
        
        output = "\n".join(output_lines)
        evidence_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
        return ToolResult.success(output, evidence_hash)


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
        requested_path, error = _resolve_and_validate(workspace_root, args.path, must_exist=True, must_be_file=True)
        if error:
            return error
        
        file_size = requested_path.stat().st_size
        if file_size > MAX_SIZE:
            return ToolResult.failure(f"File too large: {file_size} bytes (max {MAX_SIZE})")
        
        try:
            content = requested_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult.failure(f"File is not valid UTF-8: {args.path}")
        except Exception as e:
            return ToolResult.failure(f"Failed to read file: {e}")
        
        count = content.count(args.old_text)
        if count == 0:
            return ToolResult.failure(f"old_text not found in file: {args.path}")
        if count > 1:
            return ToolResult.failure(f"old_text appears {count} times (must be unique): {args.path}")
        
        new_content = content.replace(args.old_text, args.new_text)
        
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
            os.replace(tmp_path, requested_path)
        except Exception as e:
            if 'tmp_path' in locals() and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return ToolResult.failure(f"Failed to write file: {e}")
        
        evidence_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
        return ToolResult.success(new_content, evidence_hash)