"""Test for WebSocket Event Server - Phase 3 Batch 2"""

import asyncio
import json
import pytest
import websockets
from datetime import datetime

from src.factory.events import EventBus, WebSocketEventServer, run_server, FactoryEvent, EventType


@pytest.mark.asyncio
async def test_websocket_server_broadcasts_events():
    """Test that WebSocket server receives and broadcasts events from EventBus."""
    # Create our own event bus (orchestrator doesn't have one)
    bus = EventBus()
    
    # Start WebSocket server on ephemeral port
    server = await run_server(bus, host="127.0.0.1", port=0)
    actual_port = server._server.sockets[0].getsockname()[1]
    
    try:
        # Connect WebSocket client
        uri = f"ws://127.0.0.1:{actual_port}"
        async with websockets.connect(uri) as ws:
            # Receive welcome message
            welcome = json.loads(await ws.recv())
            assert welcome["type"] == "welcome"
            assert welcome["mock_mode"] is True
            
            # Manually publish test events to the bus
            now = datetime.utcnow()
            test_events = [
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
            
            # Collect events from WebSocket
            received_events = []
            
            # Publish events and collect WebSocket messages
            for event in test_events:
                await bus.publish(event)
                # Small delay to allow WebSocket to process
                await asyncio.sleep(0.05)
                
                # Try to receive messages non-blocking
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.2)
                    data = json.loads(msg)
                    if data.get("type") == "event":
                        received_events.append(data["data"])
                except asyncio.TimeoutError:
                    pass
                except websockets.exceptions.ConnectionClosed:
                    break
            
            # Drain remaining events from socket buffer
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    data = json.loads(msg)
                    if data.get("type") == "event":
                        received_events.append(data["data"])
                except asyncio.TimeoutError:
                    break
            
            # Verify we received events
            assert len(received_events) >= 3, f"Expected 3+ events via WebSocket, got {len(received_events)}"
            
            # Verify event types
            event_types = {e["event_type"] for e in received_events}
            assert "state_transition" in event_types
            assert "agent_completion" in event_types
            assert "human_approval_request" in event_types
            
            # Verify all agent completions have evidence_hash
            agent_events = [e for e in received_events if e["event_type"] == "agent_completion"]
            assert len(agent_events) >= 1
            for ae in agent_events:
                assert ae["evidence_hash"], f"Missing evidence_hash in {ae}"
                assert ae["source"] == "mock"
            
            # Verify state transitions
            state_events = [e for e in received_events if e["event_type"] == "state_transition"]
            states_to = [e["state_to"] for e in state_events if e["state_to"]]
            assert len(states_to) >= 1
            
            # Print received events for verification
            print(f"\n=== WEBSOCKET RECEIVED {len(received_events)} EVENTS ===")
            for e in received_events:
                print(f"  [{e['event_type']}] {e.get('state_from','-')}->{e.get('state_to','-')} agent={e.get('agent_type','-')} hash={e.get('evidence_hash','N/A')[:16] if e.get('evidence_hash') else 'N/A'}...")
            
            print("TEST PASSED")
    
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(test_websocket_server_broadcasts_events())