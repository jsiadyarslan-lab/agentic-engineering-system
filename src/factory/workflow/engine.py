#!/usr/bin/env python3
"""
Workflow Engine
Executes workflows defined as DAGs with retry logic and checkpointing.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Awaitable
from dataclasses import dataclass, field

from src.factory.workflow.dag import TaskDAG, TaskNode, TaskStatus
from src.factory.workflow.checkpoint import CheckpointManager
from src.factory.workflow.retry import RetryPolicy
from src.factory.contracts.agent_protocol import AgentTask, AgentResult


@dataclass
class WorkflowStep:
    """A step in the workflow execution."""
    task_id: str
    agent_type: str
    task_spec: Dict
    status: str = "pending"
    result: Any = None
    error: Optional[str] = None
    attempts: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class WorkflowEngine:
    """
    Executes workflows defined as DAGs with retry logic and checkpointing.
    """
    
    def __init__(
        self,
        dag: 'TaskDAG',
        agents: Dict[str, Any],
        checkpoint_manager: Optional['CheckpointManager'] = None,
        retry_policy: Optional['RetryPolicy'] = None,
    ):
        self.dag = dag
        self.agents = agents
        self.checkpoint_manager = checkpoint_manager or CheckpointManager()
        self.retry_policy = retry_policy or RetryPolicy()
        self._running = False
        self._steps: Dict[str, WorkflowStep] = {}
    
    async def execute(self, initial_context: Dict = None) -> Dict[str, Any]:
        """Execute the workflow DAG."""
        self._running = True
        
        # Initialize steps
        for task_id, node in self.dag.nodes.items():
            self._steps[task_id] = WorkflowStep(
                task_id=task_id,
                agent_type=self._get_agent_for_task(node.task_type),
                task_spec=node.spec,
            )
        
        while not self.dag.is_complete():
            # Get ready tasks
            ready_tasks = self.dag.get_ready_tasks()
            
            if not ready_tasks:
                # No ready tasks but not complete - might be a cycle or all failed
                break
            
            # Execute ready tasks in parallel
            tasks = []
            for node in ready_tasks:
                task = asyncio.create_task(self._execute_task(node))
                tasks.append(task)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        
        # Return final results
        return self._collect_results()
    
    def _get_agent_for_task(self, task_type: str) -> str:
        """Map task type to agent type."""
        mapping = {
            "explore": "explorer",
            "analyze": "thinker",
            "plan": "planner",
            "design": "designer",
            "review": "reviewer",
            "implement": "implementer",
            "verify": "verifier",
            "security": "security",
        }
        return self.agents.get(mapping.get(task_type, "implementer"))
    
    async def _execute_task(self, node: TaskNode) -> None:
        """Execute a single task with retry logic."""
        step = self._steps.get(node.task_id)
        if not step:
            return
        
        agent = self.agents.get(step.agent_type)
        if not agent:
            node.status = "failed"
            return
        
        step.status = "running"
        step.started_at = datetime.utcnow().isoformat()
        
        for attempt in range(self.retry_policy.max_retries + 1):
            try:
                # Create agent task
                task = AgentTask(
                    task_id=node.task_id,
                    task_type=node.task_type,
                    spec=node.spec,
                    acceptance_criteria=node.acceptance_criteria,
                )
                
                # Execute agent
                result = await agent.execute(AgentTask(
                    task_id=node.task_id,
                    task_type=node.task_type,
                    spec=node.spec,
                    acceptance_criteria=node.acceptance_criteria,
                ))
                
                if result.success:
                    node.status = "completed"
                    node.result = result.output
                    self.dag.mark_completed(node.task_id, result.output)
                    step.status = "completed"
                    step.result = result.output
                    step.completed_at = datetime.utcnow().isoformat()
                    break
                else:
                    node.error = result.error
                    if attempt < self.retry_policy.max_retries:
                        await asyncio.sleep(self.retry_policy.base_delay * (2 ** attempt))
                    else:
                        node.status = "failed"
                        node.error = result.error
                        
            except Exception as e:
                if attempt < self.retry_policy.max_retries:
                    await asyncio.sleep(self.retry_policy.base_delay * (2 ** attempt))
                else:
                    node.status = "failed"
                    node.error = str(e)
                    break
        
        step.completed_at = datetime.utcnow().isoformat()
        step.status = "completed" if node.status == "completed" else "failed"
    
    def _collect_results(self) -> Dict[str, Any]:
        """Collect results from all steps."""
        return {
            task_id: {
                "status": step.status,
                "result": step.result,
                "error": step.error,
                "attempts": step.attempts,
                "started_at": step.started_at,
                "completed_at": step.completed_at,
            }
            for task_id, step in self._steps.items()
        }


# Import required modules
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import asyncio