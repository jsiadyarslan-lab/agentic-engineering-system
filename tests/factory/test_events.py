"""Test for Factory Event Bus - Phase 3 Batch 1"""

import asyncio
import pytest
from datetime import datetime
from src.factory.events import EventBus, FactoryEvent, EventType


@pytest.mark.asyncio
async def test_event_bus_captures_events():
    """Test that EventBus captures and stores events correctly."""
    bus = EventBus()
    
    # Create some test events
    now = datetime.utcnow()
    events = [
        FactoryEvent(
            event_type=EventType.STATE_TRANSITION,
            mission_id="test-mission",
            timestamp=now,
            state_from="IDLE",
            state_to="EXPLORING",
            agent_type="explorer",
            payload={"actor": "orchestrator"},
            evidence_hash="abc123",
            source="mock",
        ),
        FactoryEvent(
            event_type=EventType.AGENT_COMPLETION,
            mission_id="test-mission",
            timestamp=now,
            state_from="EXPLORING",
            state_to="ANALYZING",
            agent_type="explorer",
            payload={"success": True},
            evidence_hash="def456",
            source="mock",
        ),
        FactoryEvent(
            event_type=EventType.HUMAN_APPROVAL_REQUEST,
            mission_id="test-mission",
            timestamp=now,
            state_from="REVIEWING",
            state_to="AWAITING_APPROVAL",
            agent_type="reviewer",
            payload={"plan": {}, "design_spec": {}},
            evidence_hash="",
            source="mock",
        ),
    ]
    
    # Publish events
    for event in events:
        await bus.publish(event)
    
    # Wait a bit for async processing
    await asyncio.sleep(0.1)
    
    # Verify history
    history = bus.history()
    assert len(history) >= 3, f"Expected 3+ events, got {len(history)}"
    
    # Verify state transitions
    state_events = [e for e in history if e.event_type == EventType.STATE_TRANSITION]
    assert len(state_events) >= 1, f"Expected 1+ state transitions, got {len(state_events)}"
    
    # Verify agent completions have evidence hashes
    agent_events = [e for e in history if e.event_type == EventType.AGENT_COMPLETION]
    assert len(agent_events) >= 1, f"Expected 1+ agent completions, got {len(agent_events)}"
    for ae in agent_events:
        assert ae.evidence_hash, f"Agent {ae.agent_type} missing evidence_hash"
        assert ae.source == "mock", f"Agent {ae.agent_type} source should be 'mock'"
    
    # Verify human approval request event
    approval_events = [e for e in history if e.event_type == EventType.HUMAN_APPROVAL_REQUEST]
    assert len(approval_events) >= 1, f"Expected human_approval_request event, got {len(approval_events)}"
    assert "plan" in approval_events[0].payload
    assert "design_spec" in approval_events[0].payload
    
    # Print events for visual verification
    print("\n=== CAPTURED EVENTS ===")
    for e in history:
        print(f"  [{e.timestamp.isoformat()}] {e.event_type.value} | {e.state_from}->{e.state_to} | agent={e.agent_type} | hash={e.evidence_hash[:16] if e.evidence_hash else 'N/A'}...")
    
    print(f"\nTotal events: {len(history)}")
    print("TEST PASSED")


if __name__ == "__main__":
    # Run test manually
    asyncio.run(test_event_bus_captures_events())