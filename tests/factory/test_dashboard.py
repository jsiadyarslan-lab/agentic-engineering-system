"""Test for HTML Dashboard - Phase 3 Batch 3"""

import asyncio
import subprocess
import sys
import time
import os
from pathlib import Path

# This test requires websockets package and manual browser verification
# Run with: python -m pytest tests/factory/test_dashboard.py -v -s


def test_dashboard_file_exists():
    """Verify dashboard.html exists and is valid HTML."""
    # Get project root
    project_root = Path(__file__).parent.parent.parent
    dashboard_path = project_root / "src" / "factory" / "events" / "dashboard.html"
    assert dashboard_path.exists(), f"dashboard.html not found at {dashboard_path}"
    
    content = dashboard_path.read_text(encoding='utf-8')
    assert '<title>AgentFactory Visual Cockpit</title>' in content
    assert 'WebSocket' in content
    assert 'event_type' in content
    assert 'state_transition' in content
    assert 'agent_completion' in content
    assert 'human_approval_request' in content
    print("[OK] dashboard.html exists and contains required elements")


def test_dashboard_no_external_deps():
    """Verify dashboard uses only vanilla JS/CSS (no build step)."""
    project_root = Path(__file__).parent.parent.parent
    dashboard_path = project_root / "src" / "factory" / "events" / "dashboard.html"
    content = dashboard_path.read_text(encoding='utf-8')
    
    # No npm, no webpack, no react, no vue, no typescript
    assert 'npm' not in content.lower()
    assert 'webpack' not in content.lower()
    assert 'react' not in content.lower()
    assert 'vue' not in content.lower()
    assert 'typescript' not in content.lower()
    assert 'import ' not in content or 'type="module"' not in content
    print("[OK] Dashboard uses only vanilla HTML/CSS/JS")


if __name__ == "__main__":
    test_dashboard_file_exists()
    test_dashboard_no_external_deps()
    print("\n[OK] Dashboard structure tests passed")
    print("\nTo manually verify:")
    print("  1. pip install websockets")
    print("  2. python -m src.factory.events.ws_server  # or run orchestrator with test")
    print("  3. Open src/factory/events/dashboard.html in browser")
    print("  4. Start a mission: python -c \"import asyncio; from src.factory.orchestrator import AgentFactoryOrchestrator; asyncio.run(AgentFactoryOrchestrator.create_for_test().start_mission('test'))\"")