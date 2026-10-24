"""Test for Factory Event Bus - Phase 3 Batch 1

This test uses the orchestrator's event bus to capture events from a full mission.
Requires a real LLM provider (Ollama, NVIDIA, OpenAI, Anthropic, Google) to be configured.
"""

import asyncio
import pytest
from datetime import datetime
from src.factory.orchestrator import AgentFactoryOrchestrator, MissionState
from src.factory.events import EventBus, FactoryEvent, EventType


def _has_provider():
    """Check if any LLM provider is available for testing."""
    import os
    try:
        import requests
    except ImportError:
        # (AES-EXP-04) لا مكتبة requests على مضيف الاختبار المعزول —
        # لا مزود قابل للاستقصاء؛ تخطٍ صادق بدل انهيار تجميع الملف.
        return False
    # Check for API keys
    if os.getenv("NVIDIA_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return True
    # Check for Ollama
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
async def test_event_bus_captures_events():
    """Test that EventBus captures and stores events correctly from a full mission."""
    # Determine provider
    import os
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
    
    # Start a mission
    mission = await orchestrator.start_mission(user_request="Fix typo in README.md")
    
    # Wait for completion with timeout - state polling
    for _ in range(3000):  # 300 seconds max (3000 * 0.1)
        await asyncio.sleep(0.1)
        if mission.state in (MissionState.COMPLETED, MissionState.ABORTED, MissionState.ESCALATED):
            break
    
    # Verify mission completed (or at least progressed through states)
    # Note: With real LLM, mission may ESCALATE if approval is not handled
    assert mission.state in (MissionState.COMPLETED, MissionState.ESCALATED), f"Mission state: {mission.state}"
    
    # Verify history has events
    history = bus.history()
    print(f"\n=== CAPTURED EVENTS ({len(history)}) ===")
    for e in history:
        print(f"  [{e.timestamp.isoformat()}] {e.event_type.value} | {e.state_from}->{e.state_to} | agent={e.agent_type} | hash={e.evidence_hash[:16] if e.evidence_hash else 'N/A'}...")
    
    # Verify we have events
    assert len(history) >= 5, f"Expected 5+ events, got {len(history)}"
    
    # Verify state transitions
    state_events = [e for e in history if e.event_type == EventType.STATE_TRANSITION]
    assert len(state_events) >= 3, f"Expected 3+ state transitions, got {len(state_events)}"
    
    # Verify agent completions (if any)
    agent_events = [e for e in history if e.event_type == EventType.AGENT_COMPLETION]
    
    # Verify all agent completions have evidence hashes
    for ae in agent_events:
        assert ae.evidence_hash, f"Agent {ae.agent_type} missing evidence_hash"
        assert ae.source == "real", f"Agent {ae.agent_type} source should be 'real'"
    
    print(f"\nTotal events: {len(history)}")
    print("TEST PASSED")


if __name__ == "__main__":
    # Run test manually
    asyncio.run(test_event_bus_captures_events())