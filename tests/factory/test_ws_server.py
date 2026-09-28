"""Test for WebSocket Event Server - Phase 3 Batch 2

This test uses the orchestrator's event bus to capture events from a full mission
and verifies they are broadcast via WebSocket.
"""

import asyncio
import json
import pytest
import websockets
from src.factory.orchestrator import AgentFactoryOrchestrator, MissionState
from src.factory.events import WebSocketEventServer, run_server


@pytest.mark.asyncio
async def test_websocket_server_broadcasts_events():
    """Test that WebSocket server receives and broadcasts events from EventBus."""
    # Create orchestrator with test_mode for auto-approve
    orchestrator = await AgentFactoryOrchestrator.create_for_test(test_mode=True)
    bus = orchestrator.event_bus
    
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
            
            # Start a mission (will generate events)
            mission = await orchestrator.start_mission(user_request="Fix typo in README.md")
            
            # Collect events from WebSocket
            received_events = []
            
            # Wait for mission completion while collecting WebSocket messages
            for _ in range(3000):  # 300 seconds max
                await asyncio.sleep(0.1)
                
                # Try to receive messages non-blocking
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.05)
                    data = json.loads(msg)
                    if data.get("type") == "event":
                        received_events.append(data["data"])
                except asyncio.TimeoutError:
                    pass
                except websockets.exceptions.ConnectionClosed:
                    break
                
                if mission.state in (MissionState.COMPLETED, MissionState.ABORTED, MissionState.ESCALATED):
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
            assert len(received_events) >= 20, f"Expected 20+ events via WebSocket, got {len(received_events)}"
            
            # Verify event types
            event_types = {e["event_type"] for e in received_events}
            assert "state_transition" in event_types
            assert "agent_completion" in event_types
            assert "human_approval_request" in event_types
            
            # Verify all agent completions have evidence_hash
            agent_events = [e for e in received_events if e["event_type"] == "agent_completion"]
            assert len(agent_events) >= 8
            for ae in agent_events:
                assert ae["evidence_hash"], f"Missing evidence_hash in {ae}"
                assert ae["source"] == "mock"
            
            # Verify state transitions include COMPLETED
            state_events = [e for e in received_events if e["event_type"] == "state_transition"]
            states_to = [e["state_to"] for e in state_events if e["state_to"]]
            assert "COMPLETED" in states_to
            
            # Print received events for verification
            print(f"\n=== WEBSOCKET RECEIVED {len(received_events)} EVENTS ===")
            for e in received_events:
                print(f"  [{e['event_type']}] {e.get('state_from','-')}->{e.get('state_to','-')} agent={e.get('agent_type','-')} hash={e.get('evidence_hash','N/A')[:16] if e.get('evidence_hash') else 'N/A'}...")
            
            print("TEST PASSED")
    
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(test_websocket_server_broadcasts_events())