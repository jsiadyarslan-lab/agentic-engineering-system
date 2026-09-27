"""
Tool base classes and result types.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from pydantic import BaseModel


@dataclass
class ToolResult:
    """Result of a tool execution."""
    ok: bool
    output: str
    error: str | None
    evidence_hash: str

    @staticmethod
    def success(output: str, evidence_hash: str) -> ToolResult:
        return ToolResult(ok=True, output=output, error=None, evidence_hash=evidence_hash)

    @staticmethod
    def failure(error: str) -> ToolResult:
        return ToolResult(ok=False, output="", error=error, evidence_hash="")


class BaseTool(ABC):
    """Abstract base class for all tools."""
    
    name: str
    description: str
    input_schema: type[BaseModel]
    
    @abstractmethod
    async def run(self, args: BaseModel, workspace_root: Path) -> ToolResult:
        """Execute the tool with given arguments."""
        pass