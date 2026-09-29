"""
Event contracts for the AgentFactory system.
Defines the standard event structure for mission lifecycle tracking.
"""

from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Any, Dict
from enum import Enum


class EventType(str, Enum):
    """Types of events emitted during mission execution."""
    STATE_TRANSITION = "state_transition"
    AGENT_COMPLETION = "agent_completion"
    HUMAN_APPROVAL_REQUEST = "human_approval_request"
    EVIDENCE_RECORDED = "evidence_recorded"


class FactoryEvent(BaseModel):
    """Standard event emitted by the orchestrator during mission execution."""
    mission_id: str
    timestamp: datetime
    event_type: EventType
    state_from: Optional[str] = None
    state_to: Optional[str] = None
    agent_type: Optional[str] = None
    payload: Dict[str, Any] = {}
    evidence_hash: Optional[str] = None
    source: str = "real"  # "real"