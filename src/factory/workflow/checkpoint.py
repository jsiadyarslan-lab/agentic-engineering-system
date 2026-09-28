#!/usr/bin/env python3
"""
Checkpoint Manager
Manages checkpoints for workflow resumption.
"""

from __future__ import annotations

import json
import uuid
import hashlib
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path


@dataclass
class Checkpoint:
    """A workflow checkpoint."""
    checkpoint_id: str
    mission_id: str
    step: int
    state: Dict
    dag_state: Dict
    created_at: datetime = field(default_factory=datetime.utcnow)
    hash: str = ""
    
    def __post_init__(self):
        if not self.hash:
            self.hash = self._compute_hash()
    
    def _compute_hash(self) -> str:
        """Compute hash of checkpoint for integrity verification."""
        data = {
            "checkpoint_id": self.checkpoint_id,
            "mission_id": self.mission_id,
            "step": self.step,
            "state": self.state,
            "dag_state": self.dag_state,
            "created_at": self.created_at.isoformat(),
        }
        data_json = json.dumps({"state": self.state, "dag_state": self.dag_state}, sort_keys=True)
        return hashlib.sha256(data_json.encode()).hexdigest()
    
    def verify(self) -> bool:
        """Verify checkpoint integrity."""
        return self.hash == self._compute_hash()


class CheckpointManager:
    """Manages workflow checkpoints for resumption."""
    
    def __init__(self, base_path: str = ".checkpoints"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def save_checkpoint(self, checkpoint: Checkpoint) -> str:
        """Save a checkpoint to disk."""
        checkpoint_file = self.base_path / f"checkpoint_{checkpoint.checkpoint_id}.json"
        with open(checkpoint_file, 'w') as f:
            json.dump({
                "checkpoint_id": checkpoint.checkpoint_id,
                "mission_id": checkpoint.mission_id,
                "step": checkpoint.step,
                "state": checkpoint.state,
                "dag_state": checkpoint.dag_state,
                "created_at": checkpoint.created_at.isoformat(),
                "hash": checkpoint.hash,
            }, f, indent=2)
        return checkpoint.checkpoint_id
    
    def load_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Load a checkpoint from disk."""
        checkpoint_file = self.base_path / f"checkpoint_{checkpoint_id}.json"
        if not checkpoint_file.exists():
            return None
        
        with open(checkpoint_file, 'r') as f:
            data = json.load(f)
        
        checkpoint = Checkpoint(
            checkpoint_id=data["checkpoint_id"],
            mission_id=data["mission_id"],
            step=data["step"],
            state=data["state"],
            dag_state=data["dag_state"],
            created_at=datetime.fromisoformat(data["created_at"]),
            hash=data["hash"],
        )
        
        # Verify integrity
        if not checkpoint.verify():
            raise ValueError(f"Checkpoint {checkpoint_id} failed integrity check")
        
        return checkpoint
    
    def list_checkpoints(self, mission_id: str) -> List[str]:
        """List all checkpoints for a mission."""
        checkpoints = []
        for file in self.base_path.glob(f"checkpoint_*_{mission_id}.json"):
            checkpoint_id = file.stem.replace("checkpoint_", "")
            checkpoints.append(checkpoint_id)
        return sorted(checkpoints)
    
    def get_latest_checkpoint(self, mission_id: str) -> Optional[str]:
        """Get the latest checkpoint for a mission."""
        checkpoints = self.list_checkpoints(mission_id)
        return checkpoints[-1] if checkpoints else None


# Import required modules
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import json
import uuid
import hashlib
from pathlib import Path