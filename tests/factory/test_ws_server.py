"""Test for WebSocket Event Server - Phase 3 Batch 2

This test uses the orchestrator's event bus to capture events from a full mission
and verifies they are broadcast via WebSocket.
Requires a real LLM provider (Ollama, NVIDIA, OpenAI, Anthropic, Google) to be configured.
"""

import asyncio
import json
import pytest
import websockets
import os
requests = pytest.importorskip("requests")  # (AES-EXP-04) تخطٍ صادق عند غياب المكتبة
from src.factory.orchestrator import AgentFactoryOrchestrator, MissionState
from src.factory.events import WebSocketEventServer, run_server


def _has_provider():
    """Check if any LLM provider is available for testing."""
    if os.getenv("NVIDIA_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return True
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=2)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            if models:
                return True
    except:
        pass
    return False


@pytest.mark.asyncio
@pytest.mark.skipif(not _has_provider(), reason="No LLM provider configured for testing")
async def test_websocket_server_broadcasts_events():
    """Test that WebSocket server receives and broadcasts events from EventBus."""
    # Determine provider
    if os.getenv("NVIDIA_API_KEY"):
        provider_type, model = "nvidia", "nvidia/nemotron-3-ultra"
    elif os.getenv("OPENAI_API_KEY"):
        provider_type, model = "openai", "gpt-4o"
    elif os.getenv("ANTHROPIC_API_KEY"):
        provider_type, model = "anthropic", "claude-3-5-sonnet-20241022"
    elif os.getenv("GOOGLE_API_KEY"):
        provider_type, model = "google", "gemini-1.5-pro"
    else:
        provider_type, model = "ollama", "llama3"
    
    # Create orchestrator with real provider
    orchestrator = await AgentFactoryOrchestrator.create_for_production(
        provider_type=provider_type,
        model=model,
    )
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
            # mock_mode removed - no longer in welcome message
            
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
            
            # Verify we received events (with real provider, may not complete full mission)
            assert len(received_events) >= 5, f"Expected 5+ events via WebSocket, got {len(received_events)}"
            
            # Verify event types
            event_types = {e["event_type"] for e in received_events}
            assert "state_transition" in event_types
            # agent_completion and human_approval_request may not appear if mission doesn't progress that far
            
            # Verify all agent completions have evidence_hash
            agent_events = [e for e in received_events if e["event_type"] == "agent_completion"]
            for ae in agent_events:
                assert ae["evidence_hash"], f"Missing evidence_hash in {ae}"
                assert ae["source"] == "real"
            
            # Verify state transitions include some progress
            state_events = [e for e in received_events if e["event_type"] == "state_transition"]
            assert len(state_events) >= 3
            
            # Print received events for verification
            print(f"\n=== WEBSOCKET RECEIVED {len(received_events)} EVENTS ===")
            for e in received_events:
                print(f"  [{e['event_type']}] {e.get('state_from','-')}->{e.get('state_to','-')} agent={e.get('agent_type','-')} hash={e.get('evidence_hash','N/A')[:16] if e.get('evidence_hash') else 'N/A'}...")
            
            print("TEST PASSED")
    
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(test_websocket_server_broadcasts_events())