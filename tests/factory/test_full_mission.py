#!/usr/bin/env python3
"""Integration test: Full mission from user request to COMPLETED."""

import asyncio
import pytest

from src.factory.orchestrator import AgentFactoryOrchestrator, MissionState


@pytest.mark.asyncio
async def test_full_mission_typo_fix():
    """Test: User requests typo fix -> mission completes with evidence."""
    orchestrator = await AgentFactoryOrchestrator.create_for_test(test_mode=True)
    
    mission = await orchestrator.start_mission(
        user_request="Fix typo in README.md",
    )
    
    # Wait for completion with timeout - state polling
    for _ in range(3000):  # 300 seconds max (3000 * 0.1)
        await asyncio.sleep(0.1)
        if mission.state in (MissionState.COMPLETED, MissionState.ABORTED, MissionState.ESCALATED):
            break
    
    # Assertions
    assert mission.state == MissionState.COMPLETED, f"Mission state: {mission.state}"
    assert mission.implementation_result is not None, "No implementation result"
    assert mission.verification is not None, "No verification"
    assert mission.verification.passed is True, "Verification failed"
    assert len(mission.evidence_hashes) >= 8, f"Only {len(mission.evidence_hashes)} evidence hashes"
    
    # Verify evidence hashes are valid SHA256
    for h in mission.evidence_hashes:
        assert len(h) == 64, f"Invalid hash length: {h}"
        assert all(c in '0123456789abcdef' for c in h), f"Invalid hex: {h}"