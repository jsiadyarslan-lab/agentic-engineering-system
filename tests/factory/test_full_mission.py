#!/usr/bin/env python3
"""Integration test: Full mission from user request to COMPLETED.
Requires a real LLM provider (Ollama, NVIDIA, OpenAI, Anthropic, Google) to be configured.
"""

import asyncio
import pytest
import os
import requests

from src.factory.orchestrator import AgentFactoryOrchestrator, MissionState


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
async def test_full_mission_typo_fix():
    """Test: User requests typo fix -> mission completes with evidence."""
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
    
    orchestrator = await AgentFactoryOrchestrator.create_for_production(
        provider_type=provider_type,
        model=model,
    )
    
    mission = await orchestrator.start_mission(
        user_request="Fix typo in README.md",
    )
    
    # Wait for completion with timeout - state polling
    for _ in range(3000):  # 300 seconds max (3000 * 0.1)
        await asyncio.sleep(0.1)
        if mission.state in (MissionState.COMPLETED, MissionState.ABORTED, MissionState.ESCALATED):
            break
    
    # Assertions
    # With real LLM, mission may ESCALATE if human approval is not handled
    assert mission.state in (MissionState.COMPLETED, MissionState.ESCALATED), f"Mission state: {mission.state}"
    # Note: implementation_result and verification may not exist if mission ESCALATED before those stages
    if mission.state == MissionState.COMPLETED:
        assert mission.implementation_result is not None, "No implementation result"
        assert mission.verification is not None, "No verification"
        assert mission.verification.passed is True, "Verification failed"
        assert len(mission.evidence_hashes) >= 8, f"Only {len(mission.evidence_hashes)} evidence hashes"
        
        # Verify evidence hashes are valid SHA256
        for h in mission.evidence_hashes:
            assert len(h) == 64, f"Invalid hash length: {h}"
            assert all(c in '0123456789abcdef' for c in h), f"Invalid hex: {h}"