"""Python gRPC client for substrate-linux bridge."""

import asyncio
import grpc
import hashlib
import os
from dataclasses import dataclass
from typing import List, Optional, AsyncIterator
from pathlib import Path

# Import generated protobuf classes
try:
    from substrate.proto import substrate_pb2
    from substrate.proto import substrate_pb2_grpc
except ImportError:
    # Generate with: python -m grpc_tools.protoc --proto_path=src/substrate/proto --python_out=. --grpc_python_out=. src/substrate/proto/substrate.proto
    substrate_pb2 = None
    substrate_pb2_grpc = None


@dataclass
class ExecutionLimits:
    """Resource limits for sandbox execution."""
    memory_bytes: Optional[int] = None
    cpu_percent: Optional[float] = None
    cpu_time_seconds: Optional[int] = None
    max_processes: Optional[int] = None
    max_file_size: Optional[int] = None
    max_open_files: Optional[int] = None
    wall_time_seconds: Optional[int] = None
    max_output_bytes: Optional[int] = None
    max_artifact_bytes: Optional[int] = None
    max_workspace_bytes: Optional[int] = None

    def to_proto(self):
        """Convert to protobuf ExecutionLimits."""
        from substrate.proto import substrate_pb2
        return substrate_pb2.ExecutionLimits(
            memory_bytes=self.memory_bytes or 0,
            cpu_percent=self.cpu_percent or 0.0,
            cpu_time_seconds=self.cpu_time_seconds or 0,
            max_processes=self.max_processes or 0,
            max_file_size=self.max_file_size or 0,
            max_open_files=self.max_open_files or 0,
            wall_time_seconds=self.wall_time_seconds or 0,
            max_output_bytes=self.max_output_bytes or 0,
            max_artifact_bytes=self.max_artifact_bytes or 0,
            max_workspace_bytes=self.max_workspace_bytes or 0,
        )


@dataclass
class ExecutionResult:
    """Result of a substrate execution."""
    sandbox_id: str
    executed: bool
    exit_code: Optional[int]
    termination: int
    duration_ms: int
    stdout: str
    stderr: str
    limits_applied: 'ExecutionLimits'
    artifacts: List['ArtifactCustodyEntry']
    started_at: float
    finished_at: float


@dataclass
class ArtifactCustodyEntry:
    """Artifact produced during execution."""
    path: str
    sha256: str
    size: int
    kind: str


@dataclass
class ExecutionLimits:
    """Resource limits for execution."""
    memory_bytes: Optional[int] = None
    cpu_percent: Optional[float] = None
    cpu_time_seconds: Optional[int] = None
    max_processes: Optional[int] = None
    max_file_size: Optional[int] = None
    max_open_files: Optional[int] = None
    wall_time_seconds: Optional[int] = None
    max_output_bytes: Optional[int] = None
    max_artifact_bytes: Optional[int] = None
    max_workspace_bytes: Optional[int] = None


@dataclass
class ExecutionResult:
    """Result of a substrate execution."""
    sandbox_id: str
    executed: bool
    exit_code: Optional[int]
    termination: int
    duration_ms: int
    stdout: str
    stderr: str
    limits_applied: 'ExecutionLimits'
    artifacts: List['ArtifactCustodyEntry']
    started_at: float
    finished_at: float


@dataclass
class ArtifactCustodyEntry:
    """Artifact produced during execution."""
    path: str
    sha256: str
    size: int
    kind: str


class SubstrateBridge:
    """Async gRPC client for substrate-linux."""
    
    def __init__(
        self,
        socket_path: str = "/tmp/substrate.sock",
        timeout: float = 60.0,
        max_concurrent: int = 100,
    ):
        self.socket_path = socket_path
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self._channel: Optional[grpc.aio.Channel] = None
        self._stub = None
        self._semaphore = asyncio.Semaphore(100)
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def connect(self) -> None:
        """Establish gRPC connection to substrate."""
        if self._channel is not None:
            return
        
        # Unix socket connection
        target = f"unix:{self.socket_path}"
        self._channel = grpc.aio.insecure_channel(target)
        self._stub = substrate_pb2_grpc.SubstrateServiceStub(self._channel)
        
        # Wait for channel to be ready
        try:
            await asyncio.wait_for(self._channel.channel_ready(), timeout=10.0)
        except asyncio.TimeoutError:
            raise ConnectionError(f"Failed to connect to substrate at {self.socket_path}")
    
    async def close(self) -> None:
        """Close the gRPC connection."""
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None
    
    async def execute(
        self,
        command: List[str],
        image: str = "python:3.11",
        limits: Optional[ExecutionLimits] = None,
        env: Optional[dict] = None,
        network: str = "NONE",
        workspace_root: str = "/work",
        artifacts_dir: str = "/artifacts",
        sandbox_id: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute a command in the substrate."""
        if not self._stub:
            await self.connect()
        
        import uuid
        sandbox_id = sandbox_id or str(uuid.uuid4())
        limits = limits or ExecutionLimits()
        
        from substrate.proto import substrate_pb2
        
        request = substrate_pb2.ExecuteRequest(
            sandbox_id=sandbox_id,
            image=image,
            command=command,
            limits=limits.to_proto(),
            env={k: str(v) for k, v in (env or {}).items()},
            network=substrate_pb2.NetworkMode.Value(network),
            workspace_root=workspace_root,
            artifacts_dir=artifacts_dir,
        )
        
        try:
            response = await asyncio.wait_for(
                self._stub.Execute(request),
                timeout=self.timeout
            )
        except grpc.RpcError as e:
            raise RuntimeError(f"Execution failed: {e.details()}")
        
        return ExecutionResult(
            sandbox_id=response.sandbox_id,
            executed=response.executed,
            exit_code=response.exit_code if response.exit_code != 0 else None,
            termination=response.termination,
            duration_ms=response.duration_ms,
            stdout=response.stdout,
            stderr=response.stderr,
            limits_applied=ExecutionLimits(
                memory_bytes=response.limits_applied.memory_bytes or None,
                cpu_percent=response.limits_applied.cpu_percent or None,
                cpu_time_seconds=response.limits_applied.cpu_time_seconds or None,
                max_processes=response.limits_applied.max_processes or None,
                max_file_size=response.limits_applied.max_file_size or None,
                max_open_files=response.limits_applied.max_open_files or None,
                wall_time_seconds=response.limits_applied.wall_time_seconds or None,
                max_output_bytes=response.limits_applied.max_output_bytes or None,
                max_artifact_bytes=response.limits_applied.max_artifact_bytes or None,
                max_workspace_bytes=response.limits_applied.max_workspace_bytes or None,
            ),
            artifacts=[
                ArtifactCustodyEntry(
                    path=a.path,
                    sha256=a.sha256,
                    size=a.size,
                    kind=a.kind,
                )
                for a in response.artifacts
            ],
            started_at=response.started_at,
            finished_at=response.finished_at,
        )
    
    async def execute_stream(
        self,
        command: List[str],
        image: str = "python:3.11",
        limits: Optional[ExecutionLimits] = None,
        env: Optional[dict] = None,
        network: str = "NONE",
        workspace_root: str = "/work",
        artifacts_dir: str = "/artifacts",
        sandbox_id: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """Execute command with streaming logs."""
        if not self._stub:
            await self.connect()
        
        import uuid
        sandbox_id = sandbox_id or str(uuid.uuid4())
        limits = limits or ExecutionLimits()
        
        from substrate.proto import substrate_pb2
        
        request = substrate_pb2.ExecuteStreamRequest(
            request=substrate_pb2.ExecuteRequest(
                sandbox_id=str(uuid.uuid4()),
                image=image,
                command=command,
                limits=limits.to_proto(),
                env={k: str(v) for k, v in (env or {}).items()},
                network=substrate_pb2.NetworkMode.Value(network),
                workspace_root=workspace_root,
                artifacts_dir=artifacts_dir,
            )
        )
        
        try:
            stream = await self._stub.ExecuteStream(request)
            async for response in stream:
                if response.log:
                    yield {
                        "type": "log",
                        "sandbox_id": response.log.sandbox_id,
                        "stream": response.log.stream,
                        "content": response.log.content,
                        "timestamp": response.log.timestamp,
                    }
                elif response.final_response:
                    resp = response.final_response
                    yield {
                        "type": "result",
                        "result": ExecutionResult(
                            sandbox_id=resp.sandbox_id,
                            executed=resp.executed,
                            exit_code=resp.exit_code if resp.exit_code != 0 else None,
                            termination=resp.termination,
                            duration_ms=resp.duration_ms,
                            stdout=resp.stdout,
                            stderr=resp.stderr,
                            limits_applied=ExecutionLimits(
                                memory_bytes=resp.limits_applied.memory_bytes or None,
                                cpu_percent=resp.limits_applied.cpu_percent or None,
                                cpu_time_seconds=resp.limits_applied.cpu_time_seconds or None,
                                max_processes=resp.limits_applied.max_processes or None,
                                max_file_size=resp.limits_applied.max_file_size or None,
                                max_open_files=resp.limits_applied.max_open_files or None,
                                wall_time_seconds=resp.limits_applied.wall_time_seconds or None,
                                max_output_bytes=resp.limits_applied.max_output_bytes or None,
                                max_artifact_bytes=resp.limits_applied.max_artifact_bytes or None,
                                max_workspace_bytes=resp.limits_applied.max_workspace_bytes or None,
                            ),
                            artifacts=[
                                ArtifactCustodyEntry(
                                    path=a.path,
                                    sha256=a.sha256,
                                    size=a.size,
                                    kind=a.kind,
                                )
                                for a in resp.artifacts
                            ],
                            started_at=resp.started_at,
                            finished_at=resp.finished_at,
                        ),
                    }
                else:
                    yield {"type": "error", "message": "No response data"}
        except grpc.RpcError as e:
            raise RuntimeError(f"Stream execution failed: {e.details()}")
    
    async def health_check(self) -> dict:
        """Check substrate health."""
        if not self._stub:
            await self.connect()
        
        from substrate.proto import substrate_pb2
        
        request = substrate_pb2.HealthCheckRequest()
        response = await self._stub.HealthCheck(request)
        
        return {
            "status": response.status.status,
            "message": response.status.message,
            "timestamp": response.status.timestamp,
        }
    
    async def negotiate_capability(
        self,
        required: List[str],
        preferred: List[str] = None,
        resource_limits: Optional[ExecutionLimits] = None,
    ) -> dict:
        """Negotiate capabilities with substrate."""
        if not self._stub:
            await self.connect()
        
        from substrate.proto import substrate_pb2
        
        request = substrate_pb2.CapabilityRequest(
            required=required,
            preferred=preferred or [],
            resource_limits=(resource_limits or ExecutionLimits()).to_proto(),
        )
        
        response = await self._stub.NegotiateCapability(request)
        
        return {
            "granted": list(response.granted),
            "denied": list(response.denied),
            "adjusted_limits": ExecutionLimits(
                memory_bytes=response.adjusted_limits.memory_bytes or None,
                cpu_percent=response.adjusted_limits.cpu_percent or None,
                cpu_time_seconds=response.adjusted_limits.cpu_time_seconds or None,
                max_processes=response.adjusted_limits.max_processes or None,
                max_file_size=response.adjusted_limits.max_file_size or None,
                max_open_files=response.adjusted_limits.max_open_files or None,
                wall_time_seconds=response.adjusted_limits.wall_time_seconds or None,
                max_output_bytes=response.adjusted_limits.max_output_bytes or None,
                max_artifact_bytes=response.adjusted_limits.max_artifact_bytes or None,
                max_workspace_bytes=response.adjusted_limits.max_workspace_bytes or None,
            ),
            "substrate_type": response.substrate_type,
        }
    
    async def close(self) -> None:
        """Close the gRPC connection."""
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


async def test_bridge():
    """Test the substrate bridge."""
    async with SubstrateBridge() as bridge:
        # Health check
        health = await bridge.health_check()
        print(f"Health: {health}")
        
        # Execute simple command
        result = await bridge.execute(
            command=["echo", "hello from substrate"],
            image="python:3.11",
        )
        print(f"Exit code: {result.exit_code}")
        print(f"Stdout: {result.stdout}")
        print(f"Stderr: {result.stderr}")
        print(f"Duration: {result.duration_ms}ms")
        
        # Test with limits
        result = await bridge.execute(
            command=["python3", "-c", "print('hello'); import time; time.sleep(2)"],
            limits=ExecutionLimits(wall_time_seconds=5, memory_bytes=100_000_000),
        )
        print(f"Exit code: {result.exit_code}")
        print(f"Duration: {result.duration_ms}ms")
        
        # Test streaming
        print("\nStreaming test:")
        async for event in bridge.execute_stream(
            command=["python3", "-c", "import time; print('start'); time.sleep(1); print('end')"],
        ):
            print(f"Event: {event}")


if __name__ == "__main__":
    asyncio.run(test_bridge())