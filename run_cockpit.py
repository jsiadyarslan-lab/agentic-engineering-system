#!/usr/bin/env python3
"""
Unified Cockpit Runner - Phase 3 Visual Cockpit
Runs WebSocket server + starts a mission for live dashboard viewing.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.factory.orchestrator import AgentFactoryOrchestrator
from src.factory.events import WebSocketEventServer


async def run_cockpit(user_request: str = "Live dashboard demo mission"):
    """Run the complete cockpit: WebSocket server + mission."""
    
    print("=" * 60)
    print("AgentFactory Visual Cockpit - Phase 3")
    print("=" * 60)
    
    # Create orchestrator
    print("\n[1/4] Creating orchestrator...")
    orch = await AgentFactoryOrchestrator.create_for_test(test_mode=True)
    print("    [OK] Orchestrator ready")
    
    # Start WebSocket server (try fixed port 8765, fall back to auto)
    print("\n[2/4] Starting WebSocket server...")
    for port in [8765, 8766, 8767, 8768, 0]:
        try:
            server = WebSocketEventServer(orch.event_bus, host='127.0.0.1', port=port)
            await server.start()
            actual_port = server._server.sockets[0].getsockname()[1]
            print(f"    [OK] Server running on ws://127.0.0.1:{actual_port} (clients: {server.client_count})")
            break
        except OSError as e:
            if e.errno == 10048 and port != 0:  # Address in use, try next
                continue
            raise
    
    # Open dashboard in browser with port parameter
    print("\n[3/4] Opening dashboard in browser...")
    dashboard_path = Path(__file__).parent / "src" / "factory" / "events" / "dashboard.html"
    dashboard_url = f"{dashboard_path.as_uri()}?port={actual_port}"
    if sys.platform == "win32":
        import subprocess
        subprocess.Popen(["start", "", dashboard_url], shell=True)
    elif sys.platform == "darwin":
        import subprocess
        subprocess.Popen(["open", dashboard_url])
    else:
        import subprocess
        subprocess.Popen(["xdg-open", dashboard_url])
    print(f"    [OK] Opened: {dashboard_url}")
    
    # Give browser time to connect
    await asyncio.sleep(1.5)
    print(f"    [OK] WebSocket clients connected: {server.client_count}")
    
    # Start mission
    print(f"\n[4/4] Starting mission: '{user_request}'")
    mission = await orch.start_mission(user_request=user_request)
    print(f"    [OK] Mission ID: {mission.mission_id}")
    
    # Wait for completion with live updates
    print("\n" + "-" * 60)
    print("Mission running -- watch the dashboard for live events!")
    print("-" * 60)
    
    last_state = None
    for i in range(300):  # 30 seconds max
        await asyncio.sleep(0.1)
        if mission.state != last_state:
            print(f"  State: {mission.state.value}")
            last_state = mission.state
        if mission.state.value in ('COMPLETED', 'ABORTED', 'ESCALATED'):
            print(f"\n  [OK] Final state: {mission.state.value}")
            break
    else:
        print(f"\n  [WARN] Timeout at state: {mission.state.value}")
    
    # Keep server alive for a bit to show final events
    print("\n[Done] Keeping server alive for 5s to show final events...")
    await asyncio.sleep(5)
    
    await server.stop()
    print("Server stopped.")


if __name__ == "__main__":
    # Allow custom request from command line
    request = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Live dashboard demo mission"
    try:
        asyncio.run(run_cockpit(request))
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()