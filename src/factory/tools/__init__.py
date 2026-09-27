"""
Factory Tools Package

Provides base classes, registry, and built-in tools for agent execution.
"""

from .base import BaseTool, ToolResult
from .registry import ToolRegistry
from .filesystem import (
    ReadFileTool, ReadFileInput,
    EditFileTool, EditFileInput,
    ListDirTool, ListDirInput,
    GrepTool, GrepInput,
    FindFilesTool, FindFilesInput,
    WriteFileTool, WriteFileInput,
    ParsePythonTool, ParsePythonInput,
)
from .execution import RunCommandTool, RunCommandInput
from .git import GitStatusTool, GitStatusInput, GitDiffTool, GitDiffInput, GitCommitTool, GitCommitInput, GitBranchTool, GitBranchInput

__all__ = [
    "BaseTool",
    "ToolResult", 
    "ToolRegistry",
    "ReadFileTool",
    "ReadFileInput",
    "EditFileTool",
    "EditFileInput",
    "ListDirTool",
    "ListDirInput",
    "GrepTool",
    "GrepInput",
    "FindFilesTool",
    "FindFilesInput",
    "WriteFileTool",
    "WriteFileInput",
    "ParsePythonTool",
    "ParsePythonInput",
    "RunCommandTool",
    "RunCommandInput",
    "GitStatusTool",
    "GitStatusInput",
    "GitDiffTool",
    "GitDiffInput",
    "GitCommitTool",
    "GitCommitInput",
    "GitBranchTool",
    "GitBranchInput",
]