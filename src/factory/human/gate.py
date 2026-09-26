#!/usr/bin/env python3
"""
Human Approval Gate
Interface for human approval of mission plans and designs.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import asyncio

from factory.context.decisions import DecisionLog


class DecisionType(str, Enum):
    """Type of human decision."""
    APPROVE = "APPROVE"
    MODIFY = "MODIFY"
    REJECT = "REJECT"
    DISCUSS = "DISCUSS"


@dataclass
class HumanDecision:
    """Human decision record."""
    decision_id: str
    mission_id: str
    decision_type: DecisionType
    approved: bool
    feedback: str
    reviewer: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "decision_id": self.decision_id,
            "mission_id": self.mission_id,
            "decision_type": self.decision_type.value,
            "approved": self.approved,
            "feedback": self.feedback,
            "reviewer": self.reviewer,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


class HumanApprovalGate:
    """
    Human approval gate for mission approvals.
    Integrates with chat interface for human-in-the-loop decisions.
    """
    
    def __init__(
        self,
        chat_interface: "ChatInterface",
        decision_log: "DecisionLog",
        default_timeout: float = 24 * 3600,  # 24 hours
    ):
        self.chat = chat_interface
        self.decision_log = decision_log
        self.default_timeout = default_timeout
        self._pending_approvals: Dict[str, asyncio.Future] = {}
    
    async def request_approval(
        self,
        mission_id: str,
        request_data: Dict,
        timeout: Optional[float] = None,
    ) -> HumanDecision:
        """
        Request human approval for a mission plan/design.
        
        Args:
            mission_id: Mission ID requesting approval
            request_data: Dictionary with plan, design_spec, review_summary
            timeout: Approval timeout in seconds (default: 24 hours)
            
        Returns:
            HumanDecision with approval status and feedback
        """
        approval_id = str(uuid.uuid4())[:8]
        timeout = timeout or self.default_timeout
        
        # Create future for the decision
        future = asyncio.get_event_loop().create_future()
        self._pending_approvals[mission_id] = future
        
        # Send approval request to chat interface
        await self._send_approval_request(mission_id, {
            "approval_id": str(uuid.uuid4())[:8],
            "mission_id": mission_id,
            "request_data": request_data,
            "timeout": timeout,
        })
        
        try:
            # Wait for human decision with timeout
            decision = await asyncio.wait_for(future, timeout=timeout)
            
            # Log decision
            self.decision_log.log_decision(mission_id, decision.to_dict())
            
            return decision
            
        except asyncio.TimeoutError:
            # Timeout - treat as rejection
            decision = HumanDecision(
                decision_id=str(uuid.uuid4())[:8],
                mission_id=mission_id,
                decision_type=DecisionType.REJECT,
                approved=False,
                feedback=f"Approval timed out after {timeout/3600:.1f} hours",
                reviewer="system (timeout)",
            )
            self.decision_log.log_decision(mission_id, decision.to_dict())
            return decision
        finally:
            self._pending_approvals.pop(mission_id, None)
    
    async def _send_approval_request(self, mission_id: str, request_data: Dict):
        """Send approval request to chat interface."""
        await self.chat.send_approval_request(request_data)
    
    def submit_decision(
        self,
        mission_id: str,
        decision_type: DecisionType,
        feedback: str,
        reviewer: str,
        details: Optional[Dict] = None,
    ) -> bool:
        """
        Submit a human decision for a pending approval.
        
        Returns:
            True if decision was accepted, False if no pending approval
        """
        if mission_id not in self._pending_approvals:
            return False
        
        future = self._pending_approvals[mission_id]
        
        decision = HumanDecision(
            decision_id=str(uuid.uuid4())[:8],
            mission_id=mission_id,
            decision_type=decision_type,
            approved=(decision_type == DecisionType.APPROVE),
            feedback=feedback,
            reviewer=reviewer,
            details={},
        )
        
        # Complete the future
        if not self._pending_approvals[mission_id].done():
            self._pending_approvals[mission_id].set_result(decision)
        
        return True
    
    def get_pending_approvals(self) -> List[str]:
        """Get list of missions awaiting approval."""
        return list(self._pending_approvals.keys())


# Missing imports
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
import asyncio
import hashlib