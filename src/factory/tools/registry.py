"""
Tool registry for managing available tools.
"""

from __future__ import annotations

from typing import Any
from .base import BaseTool


class ToolRegistry:
    """Registry for managing tool instances."""
    
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
    
    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool
    
    def get(self, name: str) -> BaseTool:
        """Get a tool by name."""
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found")
        return self._tools[name]
    
    def list(self) -> list[str]:
        """List all registered tool names."""
        return sorted(self._tools.keys())
    
    def __contains__(self, name: str) -> bool:
        return name in self._tools