#!/usr/bin/env python3
"""
Shared Context Manager
Manages shared context across agents in a mission.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path
import sqlite3


@dataclass
class SharedContextManager:
    """Manages shared context across agents in a mission."""
    
    mission_id: str
    _data: Dict[str, Any] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    
    @classmethod
    async def initialize_mission(cls, mission_id: str, user_request: str) -> 'SharedContextManager':
        """Initialize a new mission context."""
        manager = cls(mission_id=mission_id)
        await manager._initialize_db()
        await manager.set("user_request", user_request)
        return manager
    
    async def _initialize_db(self):
        """Initialize SQLite database for persistence."""
        self._db_path = Path(f".context_{self.mission_id}.db")
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS context (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    
    async def get(self, key: str) -> Optional[Any]:
        """Get a value from context."""
        async with self._lock:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM context WHERE key = ?", (key,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return json.loads(row[0])
        return None
    
    async def set(self, key: str, value: Any) -> None:
        """Set a value in context."""
        async with self._lock:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO context (key, value, updated_at) VALUES (?, ?, ?)",
                (key, json.dumps(value, default=str), datetime.utcnow().isoformat())
            )
            conn.commit()
            conn.close()
            self._data[key] = value
    
    def summarize(self, budget: int) -> str:
        """Summarize context to fit within token budget."""
        return json.dumps(self._data, default=str)[:budget]
    
    def prioritize(self, task: Any) -> str:
        """Prioritize context elements for a task."""
        return json.dumps(self._data, default=str)[:1000]
    
    def get_workspace_path(self) -> str:
        """Get the workspace path for the mission."""
        return str(Path.cwd())


# Import required modules
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import asyncio
import json
import sqlite3
from pathlib import Path
import uuid