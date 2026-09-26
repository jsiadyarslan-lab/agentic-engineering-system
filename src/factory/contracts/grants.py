#!/usr/bin/env python3
"""
Grant Manager - Capability-based access control for agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid


class GrantType(str, Enum):
    """Types of grants."""
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    ADMIN = "admin"


@dataclass
class Grant:
    """A capability grant."""
    grant_id: str
    subject: str  # agent_id or user_id
    grant_type: GrantType
    resource: str  # resource path or pattern
    constraints: Dict = field(default_factory=dict)
    issued_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    revoked: bool = False
    issued_by: str = "system"
    
    def is_valid(self) -> bool:
        if self.revoked:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True
    
    def matches(self, grant_type: GrantType, resource: str) -> bool:
        """Check if this grant covers the requested access."""
        if not self.is_valid():
            return False
        if self.grant_type != grant_type:
            return False
        # Simple path matching - could be enhanced with glob patterns
        return self._match_resource(resource)
    
    def _match_resource(self, resource: str) -> bool:
        """Check if resource matches grant pattern."""
        # Simple prefix matching for now
        return resource.startswith(self.resource.rstrip('*'))


@dataclass
class GrantRequest:
    """Request for a new grant."""
    subject: str
    grant_type: GrantType
    resource: str
    constraints: Dict = field(default_factory=dict)
    ttl_seconds: int = 3600  # 1 hour default
    requested_by: str = "system"


class GrantManager:
    """
    Manages capability grants for agents.
    Implements capability-based access control.
    """
    
    def __init__(self):
        self._grants: Dict[str, Grant] = {}  # grant_id -> Grant
        self._subject_grants: Dict[str, Set[str]] = {}  # subject -> set of grant_ids
    
    def issue_grant(self, request: GrantRequest) -> Grant:
        """Issue a new grant."""
        grant_id = f"grant_{uuid.uuid4().hex[:12]}"
        expires_at = datetime.utcnow() + timedelta(seconds=request.ttl_seconds)
        
        grant = Grant(
            grant_id=grant_id,
            subject=request.subject,
            grant_type=request.grant_type,
            resource=request.resource,
            constraints=request.constraints,
            expires_at=datetime.utcnow() + timedelta(seconds=request.ttl_seconds),
            issued_by=request.requested_by,
        )
        
        self._grants[grant.grant_id] = grant
        
        if request.subject not in self._subject_grants:
            self._subject_grants[request.subject] = set()
        self._subject_grants[request.subject].add(grant.grant_id)
        
        return grant
    
    def revoke_grant(self, grant_id: str, revoked_by: str = "system") -> bool:
        """Revoke a grant."""
        if grant_id in self._grants:
            self._grants[grant_id].revoked = True
            return True
        return False
    
    def revoke_subject_grants(self, subject: str, revoked_by: str = "system") -> int:
        """Revoke all grants for a subject."""
        count = 0
        if subject in self._subject_grants:
            for grant_id in self._subject_grants[subject]:
                if grant_id in self._grants:
                    self._grants[grant_id].revoked = True
                    count += 1
        return count
    
    def check_access(self, subject: str, grant_type: GrantType, resource: str) -> bool:
        """Check if subject has access to resource."""
        if subject not in self._subject_grants:
            return False
        
        for grant_id in self._subject_grants[subject]:
            grant = self._grants.get(grant_id)
            if grant and grant.matches(grant_type, resource):
                return True
        return False
    
    def get_subject_grants(self, subject: str) -> List[Grant]:
        """Get all valid grants for a subject."""
        grants = []
        if subject in self._subject_grants:
            for grant_id in self._subject_grants[subject]:
                grant = self._grants.get(grant_id)
                if grant and grant.is_valid():
                    grants.append(grant)
        return grants
    
    def cleanup_expired(self) -> int:
        """Remove expired grants. Returns count of removed."""
        now = datetime.utcnow()
        removed = 0
        to_remove = []
        
        for grant_id, grant in self._grants.items():
            if grant.expires_at and datetime.utcnow() > grant.expires_at:
                to_remove.append(grant_id)
        
        for grant_id in to_remove:
            grant = self._grants.pop(grant_id, None)
            if grant and grant.subject in self._subject_grants:
                self._subject_grants[grant.subject].discard(grant_id)
            removed += 1
        
        return removed


# Global grant manager instance
_global_grant_manager = None


def get_grant_manager() -> 'GrantManager':
    """Get global grant manager."""
    global _global_grant_manager
    if _global_grant_manager is None:
        _global_grant_manager = GrantManager()
    return _global_grant_manager


def set_grant_manager(manager) -> None:
    """Set global grant manager (for testing)."""
    global _global_grant_manager
    _global_grant_manager = manager


# Import required modules
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid