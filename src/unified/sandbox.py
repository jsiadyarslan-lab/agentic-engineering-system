"""
Unified Sandbox Interface — Unified Engineering Agents System

Cross-platform sandbox abstraction with two implementations:
- Linux: LocalSubstrateAdapter (namespaces, seccomp, pivot_root, rlimits)
- Windows: WindowsExecutorAdapter (Job Objects for memory/CPU/process limits)

Both implement ExecutionSandbox protocol. No host execution fallback (fail-closed).
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
from pydantic import BaseModel, Field

from unified.domain_model import (
    SandboxTermination,
    SandboxRequest,
    SandboxExecutionRecord,
    Artifact,
    EngineeringDomain,
)
from unified.contracts import Grant


# ============================================================
# SANDBOX PROTOCOL
# ============================================================

@runtime_checkable
class ExecutionSandbox(Protocol):
    """
    Protocol for sandbox execution.
    All sandbox implementations must satisfy this interface.
    """

    async def execute(self, request: SandboxRequest) -> SandboxExecutionRecord:
        """Execute command in sandbox. Single execute per sandbox_id."""
        ...

    async def write_artifact(
        self,
        sandbox_id: str,
        path: str,
        content: bytes,
        artifact_id: Optional[str] = None,
    ) -> Artifact:
        """Write artifact to sandbox /artifacts directory.

        E10-CW1-R1: optional planned artifact identity (fixed pre-effect by
        the durable intent record)."""
        ...

    async def read_artifact(
        self,
        sandbox_id: str,
        path: str,
    ) -> bytes:
        """Read artifact from sandbox /artifacts directory."""
        ...

    async def list_artifacts(self, sandbox_id: str) -> List[Artifact]:
        """List artifacts in sandbox /artifacts."""
        ...

    async def teardown(self, sandbox_id: str) -> None:
        """Teardown sandbox (always attempted)."""
        ...

    def is_available(self) -> bool:
        """Check if sandbox backend is available."""
        ...

    @property
    def backend_name(self) -> str:
        """Human-readable backend name."""
        ...


# ============================================================
# SANDBOX CONFIGURATION
# ============================================================

class SandboxBackend(str, Enum):
    """Available sandbox backends."""
    LOCAL_SUBSTRATE = "local_substrate"  # Linux namespaces/seccomp
    WINDOWS_EXECUTOR = "windows_executor"  # Windows Job Objects
    DOCKER = "docker"  # Future: Docker-based


class ImageAllowlistEntry(BaseModel):
    """Allowed container image with pinned digest."""
    name: str  # e.g., "python:3.11-slim"
    digest: str  # sha256:...
    description: str = ""
    allowed_domains: List[EngineeringDomain] = Field(default_factory=list)


# Default allowlist - MUST be configured per deployment
DEFAULT_IMAGE_ALLOWLIST: List[ImageAllowlistEntry] = [
    ImageAllowlistEntry(
        name="python:3.11-slim",
        digest="sha256:a1b2c3d4...",  # PLACEHOLDER - must be replaced
        description="Python 3.11 slim for general execution",
        allowed_domains=[EngineeringDomain.CODEBASE, EngineeringDomain.TESTING],
    ),
    ImageAllowlistEntry(
        name="node:20-alpine",
        digest="sha256:e5f6g7h8...",  # PLACEHOLDER
        description="Node.js 20 for JavaScript/TypeScript",
        allowed_domains=[EngineeringDomain.CODEBASE, EngineeringDomain.TESTING],
    ),
    ImageAllowlistEntry(
        name="golang:1.22-alpine",
        digest="sha256:i9j0k1l2...",  # PLACEHOLDER
        description="Go 1.22 for Go projects",
        allowed_domains=[EngineeringDomain.CODEBASE],
    ),
    ImageAllowlistEntry(
        name="rust:1.77-slim",
        digest="sha256:m3n4o5p6...",  # PLACEHOLDER
        description="Rust 1.77 for Rust projects",
        allowed_domains=[EngineeringDomain.CODEBASE],
    ),
]


# ============================================================
# RESOURCE LIMITS
# ============================================================

@dataclass
class ResourceLimits:
    """Resource limits for sandbox execution."""
    memory_bytes: Optional[int] = None  # Max memory
    cpu_percent: Optional[float] = None  # CPU percentage (0-100 per core)
    cpu_time_seconds: Optional[int] = None  # CPU time limit
    max_processes: Optional[int] = None  # Max processes
    wall_time_seconds: int = 300  # Wall clock timeout

    # Network
    network_mode: str = "NONE"  # Always NONE per ADR-008

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_bytes": self.memory_bytes,
            "cpu_percent": self.cpu_percent,
            "cpu_time_seconds": self.cpu_time_seconds,
            "max_processes": self.max_processes,
            "wall_time_seconds": self.wall_time_seconds,
            "network_mode": self.network_mode,
        }

    @classmethod
    def from_request(cls, request: SandboxRequest) -> "ResourceLimits":
        """Create limits from sandbox request."""
        return cls(
            memory_bytes=request.memory_bytes,
            cpu_percent=request.cpu_percent,
            cpu_time_seconds=request.cpu_time_seconds,
            max_processes=request.max_processes,
            wall_time_seconds=request.wall_time_seconds,
            network_mode=request.network_mode,
        )

    def validate_against_defaults(self, defaults: "ResourceLimits") -> List[str]:
        """Validate limits are not higher than defaults. Returns violations."""
        violations = []
        if self.memory_bytes and defaults.memory_bytes:
            if self.memory_bytes > defaults.memory_bytes:
                violations.append(f"memory_bytes {self.memory_bytes} > default {defaults.memory_bytes}")
        if self.cpu_percent and defaults.cpu_percent:
            if self.cpu_percent > defaults.cpu_percent:
                violations.append(f"cpu_percent {self.cpu_percent} > default {defaults.cpu_percent}")
        if self.cpu_time_seconds and defaults.cpu_time_seconds:
            if self.cpu_time_seconds > defaults.cpu_time_seconds:
                violations.append(f"cpu_time_seconds {self.cpu_time_seconds} > default {defaults.cpu_time_seconds}")
        if self.max_processes and defaults.max_processes:
            if self.max_processes > defaults.max_processes:
                violations.append(f"max_processes {self.max_processes} > default {defaults.max_processes}")
        if self.wall_time_seconds > defaults.wall_time_seconds:
            violations.append(f"wall_time_seconds {self.wall_time_seconds} > default {defaults.wall_time_seconds}")
        return violations


# Default resource limits (can be lowered, not raised)
DEFAULT_RESOURCE_LIMITS = ResourceLimits(
    memory_bytes=2 * 1024 * 1024 * 1024,  # 2GB
    cpu_percent=100.0,  # 1 core
    cpu_time_seconds=300,
    max_processes=100,
    wall_time_seconds=300,
)


# ============================================================
# SANDBOX MANAGER
# ============================================================

class SandboxManager:
    """
    Manages sandbox lifecycle: single execute per sandbox_id,
    tracks active sandboxes, enforces teardown.
    """

    def __init__(
        self,
        sandbox: ExecutionSandbox,
        image_allowlist: Optional[List[ImageAllowlistEntry]] = None,
        default_limits: Optional[ResourceLimits] = None,
        grant_validator: Optional[callable] = None,
        event_emitter: Optional[callable] = None,
        evidence_store: Optional[Any] = None,  # FileEvidenceStore
    ):
        self.sandbox = sandbox
        self.image_allowlist = image_allowlist or DEFAULT_IMAGE_ALLOWLIST
        self.default_limits = default_limits or DEFAULT_RESOURCE_LIMITS
        self.grant_validator = grant_validator
        self.event_emitter = event_emitter
        self.evidence_store = evidence_store

        # Track active sandboxes
        self._active: Dict[str, SandboxRequest] = {}
        self._completed: Dict[str, SandboxExecutionRecord] = {}

    def validate_image(self, image: str) -> bool:
        """Check if image is in allowlist."""
        for entry in self.image_allowlist:
            if entry.name == image:
                return True
        return False

    def validate_limits(self, limits: ResourceLimits) -> List[str]:
        """Validate limits against defaults."""
        return limits.validate_against_defaults(self.default_limits)

    def validate_grants(self, grant_ids: List[str], subject: str) -> List[str]:
        """Validate all required grants. Returns list of invalid grant_ids."""
        if not self.grant_validator:
            return grant_ids  # No validator = fail closed

        invalid = []
        for grant_id in grant_ids:
            if not self.grant_validator(grant_id, subject):
                invalid.append(grant_id)
        return invalid

    async def execute(self, request: SandboxRequest) -> SandboxExecutionRecord:
        """
        Execute request in sandbox.
        Enforces: single execute per sandbox_id, image allowlist, limits, grants.
        """
        # Check single execute per sandbox_id
        if request.sandbox_id in self._active or request.sandbox_id in self._completed:
            raise SandboxError(f"Sandbox {request.sandbox_id} already used")

        # Validate image
        if not self.validate_image(request.image):
            raise SandboxError(f"Image not in allowlist: {request.image}")

        # Validate limits
        limits = ResourceLimits.from_request(request)
        violations = self.validate_limits(limits)
        if violations:
            raise SandboxError(f"Resource limit violations: {', '.join(violations)}")

        # Validate grants
        invalid_grants = self.validate_grants(request.required_grant_ids, "agent")
        if invalid_grants:
            raise SandboxError(f"Invalid grants: {', '.join(invalid_grants)}")

        # Track as active
        self._active[request.sandbox_id] = request

        # Emit start event
        if self.event_emitter:
            from unified.event_catalog import SandboxStartedEvent, EventType, FactoryEvent
            event = FactoryEvent.create(
                event_type=EventType.SANDBOX_STARTED,
                mission_id="unknown",  # Would come from context
                payload=SandboxStartedEvent(
                    sandbox_id=request.sandbox_id,
                    mission_id="unknown",
                    command=request.command,
                    image=request.image,
                ),
                source="sandbox_manager",
            )
            self.event_emitter(event)

        try:
            # Execute
            record = await self.sandbox.execute(request)

            # Store completed
            self._completed[request.sandbox_id] = record
            del self._active[request.sandbox_id]

            # Emit completion event
            if self.event_emitter:
                from unified.event_catalog import SandboxCompletedEvent, EventType, FactoryEvent
                event = FactoryEvent.create(
                    event_type=EventType.SANDBOX_COMPLETED,
                    mission_id="unknown",
                    payload=SandboxCompletedEvent(
                        sandbox_id=request.sandbox_id,
                        mission_id="unknown",
                        exit_code=record.exit_code,
                        termination=record.termination.value,
                        duration_ms=record.duration_ms,
                        artifacts=record.artifacts,
                    ),
                    source="sandbox_manager",
                )
                self.event_emitter(event)

            return record

        except Exception as e:
            # Ensure cleanup on error
            await self._cleanup_sandbox(request.sandbox_id)
            del self._active[request.sandbox_id]
            raise

    async def write_artifact(
        self,
        sandbox_id: str,
        path: str,
        content: bytes,
        artifact_id: Optional[str] = None,
    ) -> Artifact:
        """Write artifact to sandbox.

        E10-CW1-R1: `artifact_id` carries the PLANNED identity fixed by the
        durable intent record BEFORE the side effect — the same identity must
        survive a crash between the intent and the outcome record."""
        # Allow writing to any sandbox_id - create directory if needed
        if sandbox_id not in self._active:
            # Create sandbox directory structure
            import os
            artifacts_dir = os.path.join(self.sandbox.artifacts_base_dir, sandbox_id)
            os.makedirs(artifacts_dir, exist_ok=True)
        if artifact_id is not None:
            try:
                artifact = await self.sandbox.write_artifact(
                    sandbox_id, path, content, artifact_id=artifact_id
                )
            except TypeError:
                # adapter predates the planned-identity parameter
                artifact = await self.sandbox.write_artifact(sandbox_id, path, content)
                artifact.artifact_id = artifact_id
        else:
            artifact = await self.sandbox.write_artifact(sandbox_id, path, content)
        
        # Store in evidence store if available
        if self.evidence_store:
            self.evidence_store.store_artifact(artifact)
        
        return artifact

    async def read_artifact(self, sandbox_id: str, path: str) -> bytes:
        """Read artifact from sandbox."""
        # Allow reading from any sandbox directory that exists
        if sandbox_id not in self._active and sandbox_id not in self._completed:
            # Check if directory exists
            import os
            artifacts_dir = os.path.join(self.sandbox.artifacts_base_dir, sandbox_id)
            if not os.path.exists(artifacts_dir):
                raise SandboxError(f"Sandbox {sandbox_id} not found")
        return await self.sandbox.read_artifact(sandbox_id, path)

    async def list_artifacts(self, sandbox_id: str) -> List[Artifact]:
        """List artifacts in sandbox."""
        if sandbox_id not in self._active and sandbox_id not in self._completed:
            raise SandboxError(f"Sandbox {sandbox_id} not found")
        return await self.sandbox.list_artifacts(sandbox_id)

    async def teardown(self, sandbox_id: str) -> None:
        """Teardown sandbox."""
        await self._cleanup_sandbox(sandbox_id)
        self._active.pop(sandbox_id, None)
        self._completed.pop(sandbox_id, None)

    async def _cleanup_sandbox(self, sandbox_id: str) -> None:
        """Internal cleanup - always attempted."""
        try:
            await self.sandbox.teardown(sandbox_id)
        except Exception:
            pass  # Best effort

    def get_active_count(self) -> int:
        return len(self._active)

    def get_completed_count(self) -> int:
        return len(self._completed)


# ============================================================
# EXCEPTIONS
# ============================================================

class SandboxError(Exception):
    """Sandbox operation error."""
    pass


class SandboxUnavailableError(SandboxError):
    """Sandbox backend not available."""
    pass


class ImageNotAllowedError(SandboxError):
    """Image not in allowlist."""
    pass


class ResourceLimitViolationError(SandboxError):
    """Resource limit exceeds defaults."""
    pass


class GrantValidationError(SandboxError):
    """Grant validation failed."""
    pass


# ============================================================
# FACTORY FUNCTIONS
# ============================================================

def create_sandbox_manager(
    backend: Optional[SandboxBackend] = None,
    image_allowlist: Optional[List[ImageAllowlistEntry]] = None,
    default_limits: Optional[ResourceLimits] = None,
    grant_validator: Optional[callable] = None,
    event_emitter: Optional[callable] = None,
    evidence_store: Optional[Any] = None,
    artifacts_base_dir: Optional[str] = None,
) -> SandboxManager:
    """
    Create SandboxManager with appropriate backend.
    Auto-detects platform if backend not specified.
    """
    if backend is None:
        import platform
        if platform.system() == "Windows":
            backend = SandboxBackend.WINDOWS_EXECUTOR
        else:
            backend = SandboxBackend.LOCAL_SUBSTRATE

    sandbox = create_sandbox_backend(backend, artifacts_base_dir=artifacts_base_dir)
    return SandboxManager(
        sandbox=sandbox,
        image_allowlist=image_allowlist,
        default_limits=default_limits,
        grant_validator=grant_validator,
        event_emitter=event_emitter,
        evidence_store=evidence_store,
    )


def create_sandbox_backend(backend: SandboxBackend, artifacts_base_dir: Optional[str] = None) -> ExecutionSandbox:
    """Create sandbox backend implementation."""
    if backend == SandboxBackend.LOCAL_SUBSTRATE:
        return create_local_substrate_adapter()
    elif backend == SandboxBackend.WINDOWS_EXECUTOR:
        return create_windows_executor_adapter(artifacts_base_dir=artifacts_base_dir)
    elif backend == SandboxBackend.DOCKER:
        return create_docker_adapter()
    else:
        raise ValueError(f"Unknown sandbox backend: {backend}")


def create_local_substrate_adapter() -> ExecutionSandbox:
    """Create LocalSubstrateAdapter (Linux only)."""
    try:
        from core.substrate import LocalSubstrateAdapter
        return LocalSubstrateAdapter()
    except ImportError as e:
        raise SandboxUnavailableError(f"LocalSubstrateAdapter not available: {e}")


def create_windows_executor_adapter(artifacts_base_dir: Optional[str] = None) -> ExecutionSandbox:
    """Create WindowsExecutorAdapter (Windows only)."""
    try:
        from unified.windows_adapter import create_windows_executor_adapter as _create
        return _create(artifacts_base_dir=artifacts_base_dir)
    except ImportError as e:
        raise SandboxUnavailableError(f"WindowsExecutorAdapter not available: {e}")


def create_docker_adapter() -> ExecutionSandbox:
    """Create Docker-based sandbox adapter (future)."""
    raise NotImplementedError("Docker adapter not yet implemented")


# ============================================================
# ADAPTER BASE CLASS (for implementations)
# ============================================================

class BaseSandboxAdapter:
    """Base class for sandbox adapters."""

    def __init__(self):
        self._sandboxes: Dict[str, Any] = {}  # sandbox_id -> backend-specific handle

    @abc.abstractmethod
    async def execute(self, request: SandboxRequest) -> SandboxExecutionRecord:
        pass

    @abc.abstractmethod
    async def write_artifact(
        self, sandbox_id: str, path: str, content: bytes,
        artifact_id: Optional[str] = None,
    ) -> Artifact:
        """E10-CW1-R1: optional planned artifact identity (fixed pre-effect
        by the durable intent record). Legacy adapters may omit the
        parameter — the manager falls back and rebinds the identity."""
        pass

    @abc.abstractmethod
    async def read_artifact(self, sandbox_id: str, path: str) -> bytes:
        pass

    @abc.abstractmethod
    async def list_artifacts(self, sandbox_id: str) -> List[Artifact]:
        pass

    @abc.abstractmethod
    async def teardown(self, sandbox_id: str) -> None:
        pass

    @abc.abstractmethod
    def is_available(self) -> bool:
        pass

    @property
    @abc.abstractmethod
    def backend_name(self) -> str:
        pass

    def _generate_sandbox_id(self) -> str:
        return f"sandbox-{uuid.uuid4().hex[:12]}"

    def _compute_sha256(self, content: bytes) -> str:
        import hashlib
        return hashlib.sha256(content).hexdigest()


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Protocol
    "ExecutionSandbox",
    # Enums
    "SandboxBackend",
    # Models
    "ImageAllowlistEntry",
    "DEFAULT_IMAGE_ALLOWLIST",
    "ResourceLimits",
    "DEFAULT_RESOURCE_LIMITS",
    # Manager
    "SandboxManager",
    # Exceptions
    "SandboxError",
    "SandboxUnavailableError",
    "ImageNotAllowedError",
    "ResourceLimitViolationError",
    "GrantValidationError",
    # Factory
    "create_sandbox_manager",
    "create_sandbox_backend",
    "create_local_substrate_adapter",
    "create_windows_executor_adapter",
    "create_docker_adapter",
    # Base
    "BaseSandboxAdapter",
]