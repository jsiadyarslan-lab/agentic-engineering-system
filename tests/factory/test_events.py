"""Test for Factory Event Bus - Phase 3 Batch 1

This test uses the orchestrator's event bus to capture events from a full mission.
"""

import asyncio
import pytest
from datetime import datetime
from src.factory.orchestrator import AgentFactoryOrchestrator, MissionState
from src.factory.events import EventBus, FactoryEvent, EventType


@pytest.mark.asyncio
async def test_event_bus_captures_events():
    """Test that EventBus captures and stores events correctly from a full mission."""
    # Create orchestrator with test_mode for auto-approve
    orchestrator = await AgentFactoryOrchestrator.create_for_test(test_mode=True)
    bus = orchestrator.event_bus
    
    # Start a mission
    mission = await orchestrator.start_mission(user_request="Fix typo in README.md")
    
    # Wait for completion with timeout - state polling
    for _ in range(3000):  # 300 seconds max (3000 * 0.1)
        await asyncio.sleep(0.1)
        if mission.state in (MissionState.COMPLETED, MissionState.ABORTED, MissionState.ESCALATED):
            break
    
    # Verify mission completed
    assert mission.state == MissionState.COMPLETED, f"Mission state: {mission.state}"
    
    # Verify history has events
    history = bus.history()
    print(f"\n=== CAPTURED EVENTS ({len(history)}) ===")
    for e in history:
        print(f"  [{e.timestamp.isoformat()}] {e.event_type.value} | {e.state_from}->{e.state_to} | agent={e.agent_type} | hash={e.evidence_hash[:16] if e.evidence_hash else 'N/A'}...")
    
    # Verify we have at least 20 events (11 state transitions + 8 agent completions + 1 human approval)
    assert len(history) >= 20, f"Expected 20+ events, got {len(history)}"
    
    # Verify state transitions
    state_events = [e for e in history if e.event_type == EventType.STATE_TRANSITION]
    assert len(state_events) >= 11, f"Expected 11+ state transitions, got {len(state_events)}"
    
    # Verify agent completions
    agent_events = [e for e in history if e.event_type == EventType.AGENT_COMPLETION]
    assert len(agent_events) >= 8, f"Expected 8+ agent completions, got {len(agent_events)}"
    
    # Verify all agent completions have evidence hashes
    for ae in agent_events:
        assert ae.evidence_hash, f"Agent {ae.agent_type} missing evidence_hash"
        assert ae.source == "mock", f"Agent {ae.agent_type} source should be 'mock'"
    
    # Verify human approval request event
    approval_events = [e for e in history if e.event_type == EventType.HUMAN_APPROVAL_REQUEST]
    assert len(approval_events) >= 1, f"Expected human_approval_request event, got {len(approval_events)}"
    assert "plan" in approval_events[0].payload
    assert "design_spec" in approval_events[0].payload
    
    print(f"\nTotal events: {len(history)}")
    print("TEST PASSED")


if __name__ == "__main__":
    # Run test manually
    asyncio.run(test_event_bus_captures_events())