"""WebSocket Server - Phase 3 Batch 2: Broadcasts FactoryEvents to connected clients"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Set, TYPE_CHECKING

if TYPE_CHECKING:
    import websockets
    from websockets.server import WebSocketServerProtocol

from .bus import EventBus
from .contracts import FactoryEvent

logger = logging.getLogger(__name__)


class WebSocketEventServer:
    """
    WebSocket server that subscribes to EventBus and broadcasts events
    to all connected clients. Designed for Phase 3 Visual Cockpit.
    """
    
    def __init__(self, event_bus: EventBus, host: str = "127.0.0.1", port: int = 8765):
        self.event_bus = event_bus
        self.host = host
        self.port = port
        self._clients: Set["WebSocketServerProtocol"] = set()
        self._server = None
        self._running = False
        self._broadcast_task = None
    
    async def start(self) -> None:
        """Start the WebSocket server and subscribe to EventBus."""
        # Lazy import websockets
        global websockets
        import websockets
        from websockets.server import WebSocketServerProtocol
        
        self._running = True
        
        # Subscribe to EventBus
        self.event_bus.subscribe(self._on_event)
        
        # Start WebSocket server
        self._server = await websockets.serve(
            self._handle_client,
            self.host,
            self.port,
            ping_interval=20,
            ping_timeout=10,
        )
        
        logger.info(f"WebSocket server started on ws://{self.host}:{self.port}")
    
    async def stop(self) -> None:
        """Stop the WebSocket server."""
        self._running = False
        
        # Close all client connections
        for client in self._clients.copy():
            await client.close()
        self._clients.clear()
        
        # Stop server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        
        logger.info("WebSocket server stopped")
    
    async def _handle_client(self, websocket) -> None:
        """Handle new client connection."""
        self._clients.add(websocket)
        logger.info(f"Client connected: {websocket.remote_address} (total: {len(self._clients)})")
        
        try:
            # Send welcome message with server info
            await websocket.send(json.dumps({
                "type": "welcome",
                "message": "Connected to AgentFactory Event Stream",
                "protocol_version": "1.0"
            }))
            
            # Keep connection alive, handle incoming messages (ping/pong, future commands)
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get("type") == "ping":
                        await websocket.send(json.dumps({"type": "pong"}))
                except json.JSONDecodeError:
                    pass
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            logger.info(f"Client disconnected: {websocket.remote_address} (total: {len(self._clients)})")
    
    async def _on_event(self, event: FactoryEvent) -> None:
        """Callback for EventBus - broadcast event to all connected clients."""
        if not self._clients:
            return
        
        # Serialize event to JSON
        message = json.dumps({
            "type": "event",
            "data": event.model_dump(mode="json")
        })
        
        # Broadcast to all clients (fire and forget, don't block on slow clients)
        disconnected = set()
        for client in self._clients:
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client)
            except Exception:
                disconnected.add(client)
        
        # Clean up disconnected clients
        for client in disconnected:
            self._clients.discard(client)
    
    @property
    def client_count(self) -> int:
        return len(self._clients)
    
    @property
    def is_running(self) -> bool:
        return self._running and self._server is not None


async def run_server(event_bus: EventBus, host: str = "127.0.0.1", port: int = 8765) -> WebSocketEventServer:
    """Convenience function to create and start server."""
    server = WebSocketEventServer(event_bus, host, port)
    await server.start()
    return server


async def _run_standalone_server(host: str = "127.0.0.1", port: int = 8765):
    """Run WebSocket server standalone for testing."""
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    bus = EventBus()
    server = WebSocketEventServer(bus, host, port)
    await server.start()
    
    print(f"WebSocket server running on ws://{host}:{port}")
    print("Press Ctrl+C to stop...")
    
    try:
        await asyncio.Event().wait()  # Run forever
    except KeyboardInterrupt:
        pass
    finally:
        await server.stop()
        print("Server stopped")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AgentFactory WebSocket Event Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind")
    args = parser.parse_args()
    
    asyncio.run(_run_standalone_server(args.host, args.port))