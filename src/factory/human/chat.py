#!/usr/bin/env python3
"""
Chat Interface for Human Interaction
CLI-based interactive chat for human-in-the-loop decisions.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Awaitable
import asyncio
import sys


class MessageType(str, Enum):
    """Type of chat message."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_RESPONSE = "approval_response"
    SYSTEM_MESSAGE = "system_message"


@dataclass
class ChatMessage:
    """Chat message."""
    message_id: str
    message_type: MessageType
    content: str
    metadata: Dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


class ChatInterface:
    """
    CLI-based chat interface for human interaction.
    Handles approval requests, discussions, and status updates.
    """
    
    def __init__(
        self,
        approval_callback: Optional[Callable] = None,
        input_callback: Optional[Callable[[str], Awaitable[str]]] = None,
        output_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        self._input_callback = input_callback or self._default_input
        self._output_callback = output_callback or self._default_output
        self._message_history: List[Dict] = []
        self._running = False
        self._pending_approvals: Dict[str, asyncio.Future] = {}
        self._approval_callback = None
    
    async def send_approval_request(self, request_data: Dict):
        """Send approval request to human via chat."""
        approval_id = str(uuid.uuid4())[:8]
        
        # Store future for response
        future = asyncio.get_event_loop().create_future()
        self._pending_approvals[request_data.get("mission_id")] = future
        
        # Send to output
        await self._output(f"\n{'='*60}")
        await self._output("🔔 APPROVAL REQUEST")
        await self._output(f"Mission: {request_data.get('mission_id')}")
        await self._output("-" * 60)
        
        # Show request details
        request_data = request_data.get("request_data", {})
        if "plan" in request_data:
            plan = request_data["plan"]
            self._output(f"\n📋 Plan: {plan.get('summary', 'N/A')}")
            if "tasks" in plan:
                for i, task in enumerate(plan["tasks"][:5], 1):
                    self._output(f"  {i}. {task.get('description', 'N/A')}")
                if len(plan.get("tasks", [])) > 5:
                    self._output(f"  ... and {len(plan['tasks']) - 5} more tasks")
        
        if "design_spec" in request_data:
            design = request_data["design_spec"]
            self._output(f"\n🎨 Design: {design.get('summary', 'N/A')}")
        
        if "review_summary" in request_data:
            self._output(f"\n📋 Review: {request_data['review_summary'][:200]}...")
        
        self._output(f"\n⏱️  Timeout: {request_data.get('timeout', 86400)/3600:.1f} hours")
        self._output("=" * 60)
        self._output("\nOptions:")
        self._output("  ✅ [A]pprove    - Approve and continue")
        self._output("  🔄 [M]odify     - Request changes")
        self._output("  ❌ [R]eject      - Reject and stop")
        self._output("  💬 [D]iscuss    - Ask questions / discuss")
        self._output("-" * 60)
        
        # Store the future for the decision
        future = asyncio.get_event_loop().create_future()
        self._pending_approvals[request_data.get("mission_id")] = future
        
        # Wait for user input in background
        asyncio.create_task(self._wait_for_decision())
    
    async def _wait_for_decision(self):
        """Wait for human decision input."""
        while True:
            try:
                user_input = await self._input_callback("Your decision [A/M/R/D]: ")
                user_input = user_input.strip().upper()
                
                if user_input in ['A', 'APPROVE']:
                    decision = {"type": "APPROVE", "approved": True, "feedback": "Approved"}
                    break
                elif user_input in ['M', 'MODIFY']:
                    feedback = await self._input_callback("What changes? ")
                    decision = {"type": "MODIFY", "approved": False, "feedback": feedback}
                    break
                elif user_input in ['R', 'REJECT']:
                    feedback = await self._input_callback("Reason for rejection: ")
                    decision = {"type": "REJECT", "approved": False, "feedback": feedback}
                    break
                elif user_input in ['D', 'DISCUSS']:
                    question = await self._input_callback("Your question: ")
                    self._output(f"💬 Question noted: {question}")
                    # Continue waiting for decision
                    continue
                else:
                    self._output("Invalid option. Use A/M/R/D")
                    continue
            except Exception as e:
                self._output(f"Error reading input: {e}")
                continue
            
            # Store decision and resolve future
            # Implementation depends on pending approval tracking
            break
    
    def submit_decision(self, decision_data: Dict) -> bool:
        """Submit a decision for the current pending approval."""
        # Find pending approval and resolve
        pass
    
    async def send_approval_request(self, request_data: Dict):
        """Send approval request to human via chat."""
        # This is a simplified version - real implementation would use the chat interface
        pass
    
    async def send_system_message(self, message: str, level: str = "info"):
        """Send system message to user."""
        prefix = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "success": "✅"}.get(level, "ℹ️")
        await self._output(f"{prefix} {message}")
    
    async def send_status_update(self, mission_id: str, status: str, details: str = ""):
        """Send mission status update."""
        message = f"📋 Mission {mission_id[:8]}: {status}"
        if details:
            message += f" - {details}"
        await self._output(message)
    
    async def start_interactive_session(self, mission_id: str):
        """Start interactive chat session for a mission."""
        self._output(f"\n{'='*60}")
        self._output(f"🤖 Factory Chat - Mission {mission_id[:8]}")
        self._output("Type 'help' for commands, 'exit' to leave")
        self._output("=" * 60)
        
        while True:
            try:
                user_input = await self._input_callback("\n> ")
                if not user_input.strip():
                    continue
                
                if user_input.lower() in ['exit', 'quit', 'exit()']:
                    self._output("👋 Exiting chat...")
                    break
                elif user_input.lower() == 'help':
                    self._show_help()
                elif user_input.lower().startswith('status'):
                    await self._show_status(user_input)
                elif user_input.lower().startswith('approve'):
                    await self._handle_approve(user_input)
                elif user_input.lower().startswith('modify'):
                    await self._handle_modify(user_input)
                elif user_input.lower().startswith('reject'):
                    await self._handle_reject(user_input)
                else:
                    # Treat as discussion/question
                    await self._handle_discussion(user_input)
                    
            except (KeyboardInterrupt, EOFError):
                self._output("\n👋 Exiting chat...")
                break
            except Exception as e:
                self._output(f"❌ Error: {e}")
    
    async def _show_status(self, cmd: str):
        """Show mission status."""
        self._output("📊 Status: [Would show mission status]")
    
    async def _handle_approve(self, cmd: str):
        """Handle approve command."""
        self._output("✅ Approved!")
        # Submit approval
    
    async def _handle_modify(self, cmd: str):
        """Handle modify request."""
        feedback = cmd[6:].strip() if len(cmd) > 6 else ""
        if not feedback:
            feedback = await self._input_callback("What changes? ")
        self._output(f"🔄 Modification requested: {feedback}")
    
    async def _handle_reject(self, cmd: str):
        """Handle reject command."""
        reason = cmd[6:].strip() if len(cmd) > 6 else ""
        if not reason:
            reason = await self._input_callback("Reason for rejection: ")
        self._output(f"❌ Rejected: {reason}")
    
    async def _handle_discussion(self, message: str):
        """Handle discussion/question."""
        self._output("💬 Discussion noted. Continuing...")
        # In a real implementation, this would go to the orchestrator
    
    def _show_help(self):
        """Show help message."""
        self._output("""
Available commands:
  help              - Show this help
  status            - Show mission status
  approve           - Approve current plan/design
  modify <reason>   - Request modifications
  reject <reason>   - Reject current plan
  <message>         - Ask question / discuss
  exit / quit       - Exit chat
        """)
    
    # Default callbacks
    async def _default_input(self, prompt: str) -> str:
        return await asyncio.get_event_loop().run_in_executor(None, input, prompt)
    
    async def _default_output(self, message: str):
        print(message)
    
    def _output(self, message: str):
        """Sync output wrapper."""
        asyncio.create_task(self._output_callback(message))
    
    async def _output_callback(self, message: str):
        print(message)


# Missing imports
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Awaitable
import asyncio
import uuid