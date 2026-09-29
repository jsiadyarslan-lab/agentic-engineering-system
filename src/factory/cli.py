#!/usr/bin/env python3
"""Factory CLI Entry Point - Production Mode with Interactive Human Gate."""

import asyncio
import argparse
import os
import sys
import uuid
from typing import Optional

from src.factory.orchestrator import AgentFactoryOrchestrator, MissionState
from src.factory.events import EventType, FactoryEvent


class CLIMonitor:
    """Monitor and display mission progress in CLI."""
    
    def __init__(self):
        self._current_state: Optional[MissionState] = None
        self._mission_id: Optional[str] = None
        self._approval_future: Optional[asyncio.Future] = None
    
    def set_dependencies(self, chat_interface, human_gate):
        # Not needed - ChatInterface handles approval directly
        pass
    
    async def on_event(self, event: FactoryEvent):
        """Handle factory events."""
        if event.event_type == EventType.STATE_TRANSITION:
            await self._on_state_transition(event)
        elif event.event_type == EventType.AGENT_COMPLETION:
            await self._on_agent_completion(event)
        # Note: HUMAN_APPROVAL_REQUEST is handled by ChatInterface directly
    
    async def _on_state_transition(self, event: FactoryEvent):
        """Print state transition."""
        mission_id = event.mission_id[:8] if event.mission_id else "unknown"
        from_state = event.state_from or "UNKNOWN"
        to_state = event.state_to or "UNKNOWN"
        actor = event.payload.get("actor", "orchestrator")
        
        # Print transition with timestamp
        timestamp = event.timestamp.strftime("%H:%M:%S")
        print(f"[{timestamp}] {mission_id}: {from_state} -> {to_state} ({actor})")
        
        try:
            self._current_state = MissionState(to_state)
        except ValueError:
            self._current_state = None
        self._mission_id = event.mission_id
        
        # If we're waiting for approval and got approval, resolve the future
        if to_state == "EXECUTING" and self._approval_future and not self._approval_future.done():
            self._approval_future.set_result(True)
    
    async def _on_agent_completion(self, event: FactoryEvent):
        """Print agent completion."""
        agent = event.agent_type or "unknown"
        success = event.payload.get("success", False)
        timestamp = event.timestamp.strftime("%H:%M:%S")
        status = "✓" if success else "✗"
        print(f"[{timestamp}] Agent {agent}: {status}")


async def main():
    parser = argparse.ArgumentParser(description="Agent Factory CLI")
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # factory run "task"
    run_parser = subparsers.add_parser("run", help="Run a mission")
    run_parser.add_argument("task", help="Task description")
    run_parser.add_argument("--codebase", default=".", help="Codebase path")
    run_parser.add_argument("--test-mode", action="store_true", help="Run in test mode (auto-approve)")
    run_parser.add_argument("--api-key", help="API key (overrides env var)")
    run_parser.add_argument("--provider", default="nvidia", choices=["nvidia", "openai", "anthropic", "google", "ollama", "custom"], help="LLM provider")
    run_parser.add_argument("--model", default="nvidia/nemotron-3-ultra", help="Model name")
    run_parser.add_argument("--ws-port", type=int, default=8765, help="WebSocket server port")
    run_parser.add_argument("--no-ws", action="store_true", help="Disable WebSocket server")
    
    # factory status <mission_id>
    status_parser = subparsers.add_parser("status", help="Get mission status")
    status_parser.add_argument("mission_id", help="Mission ID")
    
    # factory chat
    subparsers.add_parser("chat", help="Interactive chat mode")
    
    args = parser.parse_args()
    
    if args.command == "run":
        # Check for API key (cli arg takes precedence over env)
        api_key = args.api_key
        auto_approve = args.test_mode
        
        if auto_approve:
            print("[INFO] Test mode: auto-approving all human gates.")
        else:
            print("[INFO] Interactive human approval enabled.")
        
        # Create orchestrator with real provider
        try:
            orchestrator = await AgentFactoryOrchestrator.create_for_production(
                api_key=api_key,
                provider_type=args.provider,
                model=args.model,
            )
        except ValueError as e:
            print(f"[ERROR] {e}")
            return 1
        
        if auto_approve:
            orchestrator.human_gate.test_mode = True
        
        # Start WebSocket server for real-time event streaming (unless disabled)
        if not args.no_ws:
            try:
                await orchestrator.start_ws_server(port=args.ws_port)
                print(f"[INFO] WebSocket server started on ws://127.0.0.1:{args.ws_port}")
            except Exception as e:
                print(f"[WARNING] Could not start WebSocket server: {e}")
        
        # Set up CLI monitor
        monitor = CLIMonitor()
        monitor.set_dependencies(
            chat_interface=orchestrator.chat_interface,
            human_gate=orchestrator.human_gate,
        )
        
        # Subscribe to events
        orchestrator.event_bus.subscribe(monitor.on_event)
        
        # Start mission
        print(f"Starting mission: {args.task}")
        mission = await orchestrator.start_mission(args.task)
        
        # Wait for completion - state polling
        for _ in range(3000):  # 300 seconds max (3000 * 0.1)
            await asyncio.sleep(0.1)
            if mission.state in (MissionState.COMPLETED, MissionState.ABORTED, MissionState.ESCALATED):
                break
        
        # Stop WebSocket server
        if not args.no_ws:
            await orchestrator.stop_ws_server()
        
        # Print final status
        print(f"\n{'='*60}")
        print(f"Mission {mission.mission_id[:8]}: {mission.state.value}")
        print(f"Evidence hashes: {len(mission.evidence_hashes)}")
        
        if mission.verification:
            print(f"Verification: {'PASSED' if mission.verification.passed else 'FAILED'}")
        
        if mission.last_error:
            print(f"Last error: {mission.last_error}")
        
        if mission.human_decision:
            print(f"Human decision: {mission.human_decision.decision_type.value} - {mission.human_decision.feedback}")
        
    elif args.command == "status":
        # For status, create a minimal orchestrator (no LLM needed for status check)
        # Use create_for_production with Ollama (no API key needed) or require API key
        try:
            orchestrator = await AgentFactoryOrchestrator.create_for_production(
                provider_type="ollama",
                model="llama3",
            )
        except ValueError:
            # Fallback: create with NVIDIA if key available
            orchestrator = await AgentFactoryOrchestrator.create_for_production(
                provider_type="nvidia",
                model="nvidia/nemotron-3-ultra",
            )
        status = orchestrator.get_mission_status(args.mission_id)
        print(status)
        
    elif args.command == "chat":
        print("Chat mode not yet implemented")
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))