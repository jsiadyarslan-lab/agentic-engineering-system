"""Event Bus - In-process Pub/Sub for Factory Events"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import List, Optional

from .contracts import FactoryEvent


class EventBus:
    """
    In-process event bus for publishing and subscribing to FactoryEvents.
    Thread-safe for asyncio use.
    """
    
    def __init__(self, max_history: int = 1000):
        self._subscribers: List[Callable[[FactoryEvent], Awaitable[None]]] = []
        self._history: List[FactoryEvent] = []
        self._max_history = max_history
        self._lock = asyncio.Lock()
    
    def subscribe(self, callback: Callable[[FactoryEvent], Awaitable[None]]) -> None:
        """Subscribe to events. Callback receives each published event."""
        self._subscribers.append(callback)
    
    async def publish(self, event: FactoryEvent) -> None:
        """Publish an event to all subscribers and store in history."""
        async with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history.pop(0)
        
        # Notify subscribers (outside lock to avoid deadlock)
        for sub in self._subscribers:
            try:
                await sub(event)
            except Exception:
                # Subscriber errors shouldn't break the bus
                pass
    
    def history(self) -> List[FactoryEvent]:
        """Get copy of event history."""
        return list(self._history)
    
    def clear_history(self) -> None:
        """Clear event history."""
        self._history.clear()