#!/usr/bin/env python3
"""
Artifact Registry
Manages artifacts produced during execution with hash-chaining for integrity.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path
import sqlite3


@dataclass
class Artifact:
    """Artifact produced during execution."""
    artifact_id: str
    mission_id: str
    path: str
    sha256: str
    size: int
    kind: str  # "file", "log", "report", "evidence"
    created_by: str  # agent_type
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict = field(default_factory=dict)


class ArtifactRegistry:
    """Registry for artifacts with hash-chaining for integrity."""
    
    def __init__(self, mission_id: str):
        self.mission_id = mission_id
        self._db_path = Path(f".artifacts_{mission_id}.db")
        self._artifacts: Dict[str, Artifact] = {}
        self._initialize_db()
    
    def _initialize_db(self):
        """Initialize SQLite database."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size INTEGER NOT NULL,
                kind TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_artifacts_mission ON artifacts(mission_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_artifacts_sha256 ON artifacts(sha256)
        """)
        conn.commit()
        conn.close()
    
    def register_artifact(
        self,
        path: str,
        sha256: str,
        size: int,
        kind: str,
        created_by: str,
        metadata: Dict = None
    ) -> Artifact:
        """Register a new artifact."""
        artifact_id = str(uuid.uuid4())[:8]
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=self.mission_id,
            path=path,
            sha256=sha256,
            size=size,
            kind=kind,
            created_by=created_by,
            metadata=metadata or {}
        )
        
        self._artifacts[artifact_id] = artifact
        
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO artifacts (artifact_id, mission_id, path, sha256, size, kind, created_by, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (artifact.artifact_id, artifact.mission_id, artifact.path, artifact.sha256,
              artifact.size, artifact.kind, artifact.created_by, json.dumps(artifact.metadata)))
        conn.commit()
        conn.close()
        
        return artifact
    
    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        """Get artifact by ID."""
        if artifact_id in self._artifacts:
            return self._artifacts[artifact_id]
        
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Artifact(
                artifact_id=row[0],
                mission_id=row[1],
                path=row[2],
                sha256=row[3],
                size=row[4],
                kind=row[5],
                created_by=row[6],
                created_at=datetime.fromisoformat(row[7]),
                metadata=json.loads(row[8]) if row[7] else {}
            )
        return None
    
    def get_artifacts_by_hash(self, sha256: str) -> List[Artifact]:
        """Get artifacts by SHA256 hash."""
        artifacts = []
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM artifacts WHERE sha256 = ?", (sha256,))
        rows = cursor.fetchall()
        conn.close()
        
        for row in rows:
            artifacts.append(Artifact(
                artifact_id=row[0],
                mission_id=row[1],
                path=row[2],
                sha256=row[3],
                size=row[4],
                kind=row[5],
                created_by=row[6],
                created_at=datetime.fromisoformat(row[7]),
                metadata=json.loads(row[8]) if row[7] else {}
            ))
        return artifacts
    
    def verify_integrity(self) -> Dict[str, Any]:
        """Verify integrity of all artifacts by re-computing hashes."""
        results = {"verified": [], "corrupted": [], "missing": []}
        
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM artifacts WHERE mission_id = ?", (self.mission_id,))
        rows = cursor.fetchall()
        conn.close()
        
        for row in rows:
            artifact = Artifact(
                artifact_id=row[0],
                mission_id=row[1],
                path=row[2],
                sha256=row[3],
                size=row[4],
                kind=row[5],
                created_by=row[6],
                created_at=datetime.fromisoformat(row[7]),
                metadata=json.loads(row[8]) if row[7] else {}
            )
            
            file_path = Path(artifact.path)
            if not file_path.exists():
                results["missing"].append(artifact.artifact_id)
                continue
            
            try:
                with open(file_path, 'rb') as f:
                    content = f.read()
                    computed_hash = hashlib.sha256(content).hexdigest()
                    if computed_hash == artifact.sha256:
                        results["verified"].append(artifact.artifact_id)
                    else:
                        results["corrupted"].append({
                            "artifact_id": artifact.artifact_id,
                            "expected": artifact.sha256,
                            "actual": computed_hash
                        })
            except Exception as e:
                results["corrupted"].append({
                    "artifact_id": artifact.artifact_id,
                    "error": str(e)
                })
        
        return results


# Import required modules
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import json
import uuid
from pathlib import Path
import sqlite3
import hashlib