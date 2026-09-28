#!/usr/bin/env python3
"""
TaskDAG - Directed Acyclic Graph for task dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from enum import Enum


class TaskStatus(str, Enum):
    """Status of a task in the DAG."""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskNode:
    """Node in the task DAG."""
    task_id: str
    task_type: str
    spec: Dict[str, Any]
    acceptance_criteria: List[str]
    dependencies: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None


class TaskDAG:
    """Directed Acyclic Graph for task dependencies."""
    
    def __init__(self):
        self.nodes: Dict[str, TaskNode] = {}
        self.edges: Dict[str, Set[str]] = {}  # task_id -> set of dependent task_ids
    
    def add_task(self, task: TaskNode) -> None:
        """Add a task to the DAG."""
        self.nodes[task.task_id] = task
        self.edges[task.task_id] = set(task.dependencies)
        
        # Ensure all dependencies exist as nodes
        for dep_id in task.dependencies:
            if dep_id not in self.edges:
                self.edges[dep_id] = set()
    
    def get_ready_tasks(self) -> List[TaskNode]:
        """Get all tasks that are ready to execute (all dependencies completed)."""
        ready = []
        for task_id, node in self.nodes.items():
            if node.status == TaskStatus.PENDING:
                deps_completed = all(
                    self.nodes[dep_id].status == TaskStatus.COMPLETED
                    for dep_id in node.dependencies
                )
                if deps_completed:
                    ready.append(node)
        return ready
    
    def get_task(self, task_id: str) -> Optional[TaskNode]:
        """Get a task by ID."""
        return self.nodes.get(task_id)
    
    def mark_completed(self, task_id: str, result: Any = None) -> None:
        """Mark a task as completed."""
        if task_id in self.nodes:
            self.nodes[task_id].status = TaskStatus.COMPLETED
            self.nodes[task_id].result = result
    
    def mark_failed(self, task_id: str, error: str) -> None:
        """Mark a task as failed."""
        if task_id in self.nodes:
            self.nodes[task_id].status = TaskStatus.FAILED
            self.nodes[task_id].error = str(task_id)
    
    def get_ready_tasks(self) -> List[str]:
        """Get IDs of tasks ready to execute."""
        return [node.task_id for node in self.get_ready_tasks()]
    
    def is_complete(self) -> bool:
        """Check if all tasks are completed or failed."""
        return all(
            node.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED)
            for node in self.nodes.values()
        )
    
    def get_execution_order(self) -> List[str]:
        """Get a topological ordering of tasks."""
        # Kahn's algorithm for topological sort
        in_degree = {task_id: len(deps) for task_id, task in self.nodes.items() 
                     for deps in (task.dependencies,)}
        
        # Add nodes with no dependencies
        queue = [task_id for task_id, task in self.nodes.items() if not task.dependencies]
        
        # Build in-degree map
        in_degree = {}
        for task_id, node in self.nodes.items():
            in_degree[task_id] = len(node.dependencies)
        
        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        result = []
        
        while queue:
            task_id = queue.pop(0)
            result.append(task_id)
            
            # Decrease in-degree for dependents
            for dependent_id, dep_node in self.nodes.items():
                if task_id in dep_node.dependencies:
                    in_degree[dependent_id] -= 1
                    if in_degree[dependent_id] == 0:
                        queue.append(dependent_id)
        
        if len(result) != len(self.nodes):
            raise ValueError("Cycle detected in task DAG")
        
        return result


# Import required modules
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from enum import Enum