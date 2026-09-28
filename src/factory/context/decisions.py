#!/usr/bin/env python3
"""
Decision Log
Manages decision log for audit trail and accountability.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path
import sqlite3


@dataclass
class Decision:
    """A recorded decision."""
    decision_id: str
    mission_id: str
    decision_type: str  # "approval", "modification", "rejection", "escalation"
    actor: str  # "human", "orchestrator", "agent_type"
    decision: str  # "APPROVE", "MODIFY", "REJECT", "ESCALATE"
    rationale: str
    details: Dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    related_evidence: List[str] = field(default_factory=list)  # evidence hashes


class DecisionLog:
    """Append-only decision log for audit trail."""
    
    def __init__(self, mission_id: str):
        self.mission_id = mission_id
        self._db_path = Path(f".decisions_{mission_id}.db")
        self._decisions: List[Decision] = []
        self._initialize_db()
    
    def _initialize_db(self):
        """Initialize SQLite database."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                decision_id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                decision_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                decision TEXT NOT NULL,
                rationale TEXT NOT NULL,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                related_evidence TEXT
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_decisions_mission ON decisions(mission_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions(timestamp)
        """)
        conn.commit()
        conn.close()
    
    def log_decision(
        self,
        *args,
        decision_type: str = None,
        actor: str = None,
        decision: str = None,
        rationale: str = None,
        details: Dict = None,
        related_evidence: List[str] = None,
        **kwargs
    ) -> Decision:
        """Log a decision. Supports multiple calling conventions:
        - log_decision(mission_id, decision_dict)  # HumanApprovalGate test mode
        - log_decision(decision_type, actor, decision, rationale, details, related_evidence)  # Original
        """
        # Handle backward compatibility - if called with mission_id and dict (2 positional args)
        if len(args) == 2 and isinstance(args[0], str) and isinstance(args[1], dict):
            mission_id = args[0]
            decision_dict = args[1]
            # Extract fields from dict
            decision_type = decision_dict.get("decision_type", "approval")
            actor = decision_dict.get("reviewer", "human")
            decision = decision_dict.get("decision_type", "APPROVE")
            rationale = decision_dict.get("feedback", "")
            details = decision_dict.get("details", {})
            related_evidence = []
        elif len(args) >= 4:
            # Original calling convention: decision_type, actor, decision, rationale, ...
            decision_type = args[0]
            actor = args[1]
            decision = args[2]
            rationale = args[3]
            details = args[4] if len(args) > 4 else details or {}
            related_evidence = args[5] if len(args) > 5 else related_evidence or []
        else:
            # Keyword arguments or mixed
            decision_type = decision_type or kwargs.get('decision_type', 'approval')
            actor = actor or kwargs.get('actor', 'human')
            decision = decision or kwargs.get('decision', 'APPROVE')
            rationale = rationale or kwargs.get('rationale', '')
            details = details or kwargs.get('details', {})
            related_evidence = related_evidence or kwargs.get('related_evidence', [])
        
        decision_id = str(uuid.uuid4())[:8]
        decision_obj = Decision(
            decision_id=decision_id,
            mission_id=self.mission_id,
            decision_type=decision_type,
            actor=actor,
            decision=decision,
            rationale=rationale,
            details=details or {},
            related_evidence=related_evidence or []
        )
        
        self._decisions.append(decision_obj)
        
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO decisions (decision_id, mission_id, decision_type, actor, decision, rationale, details, related_evidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            decision_obj.decision_id, decision_obj.mission_id, decision_obj.decision_type,
            decision_obj.actor, decision_obj.decision, decision_obj.rationale,
            json.dumps(decision_obj.details), json.dumps(decision_obj.related_evidence)
        ))
        conn.commit()
        conn.close()
        
        return decision_obj
    
    def get_decisions(self, decision_type: Optional[str] = None) -> List[Decision]:
        """Get all decisions, optionally filtered by type."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        if decision_type:
            cursor.execute(
                "SELECT * FROM decisions WHERE mission_id = ? AND decision_type = ? ORDER BY timestamp",
                (self.mission_id, decision_type)
            )
        else:
            cursor.execute(
                "SELECT * FROM decisions WHERE mission_id = ? ORDER BY timestamp",
                (self.mission_id,)
            )
        
        rows = cursor.fetchall()
        conn.close()
        
        decisions = []
        for row in rows:
            decisions.append(Decision(
                decision_id=row[0],
                mission_id=row[1],
                decision_type=row[2],
                actor=row[3],
                decision=row[4],
                rationale=row[5],
                details=json.loads(row[6]) if row[6] else {},
                timestamp=datetime.fromisoformat(row[7]),
                related_evidence=json.loads(row[8]) if row[7] else []
            ))
        
        conn.close()
        return decision_objs
    
    def get_latest_decision(self) -> Optional[Decision]:
        """Get the most recent decision."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM decisions WHERE mission_id = ? ORDER BY timestamp DESC LIMIT 1",
            (self.mission_id,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Decision(
                decision_id=row[0],
                mission_id=row[1],
                decision_type=row[2],
                actor=row[3],
                decision=row[4],
                rationale=row[5],
                details=json.loads(row[6]) if row[6] else {},
                timestamp=datetime.fromisoformat(row[7]),
                related_evidence=json.loads(row[8]) if row[7] else []
            )
        return None


# Import required modules
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import json
import uuid
from pathlib import Path
import sqlite3