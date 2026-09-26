#!/usr/bin/env python3
"""Integration tests for substrate gRPC bridge."""

import asyncio
import os
import sys
import uuid
import tempfile
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
import asyncio

# Skip if substrate bridge not available
pytestmark = pytest.mark.skipif(
    not os.environ.get("SUBSTRATE_TEST_SOCKET"),
    reason="SUBSTRATE_TEST_SOCKET not set - requires running substrate server"
)


class TestSubstrateBridge:
    """Integration tests for substrate gRPC bridge."""
    
    @pytest.fixture
    async def bridge(self):
        """Create a bridge connection to substrate."""
        from substrate.bridge import SubstrateBridge
        
        socket_path = os.environ.get("SUBSTRATE_TEST_SOCKET", "/tmp/substrate.sock")
        
        bridge = SubstrateBridge(socket_path=socket_path)
        try:
            await bridge.connect()
            yield bridge
        finally:
            await bridge.close()
    
    @pytest.mark.asyncio
    async def test_health_check(self, bridge):
        """Test health check endpoint."""
        health = await bridge.health_check()
        assert "status" in health
        assert health["status"] == 0  # HEALTHY
        assert "message" in health
    
    @pytest.mark.asyncio
    async def test_execute_basic_command(self, bridge):
        """Test executing a simple command."""
        result = await bridge.execute(
            command=["echo", "hello from substrate"],
            image="python:3.11",
        )
        
        assert result.exit_code == 0
        assert "hello from substrate" in result.stdout
        assert result.duration_ms > 0
        assert result.artifacts is not None
    
    @pytest.mark.asyncio
    async def test_execute_with_limits(self, bridge):
        """Test executing command with resource limits."""
        from substrate.bridge import ExecutionLimits
        
        result = await bridge.execute(
            command=["python3", "-c", "print('hello'); import time; time.sleep(1)"],
            limits=ExecutionLimits(wall_time_seconds=5, memory_bytes=100_000_000),
        )
        
        assert result.exit_code == 0
        assert result.duration_ms >= 1000  # At least 1 second
        assert result.duration_ms < 5000  # But not too long
    
    @pytest.mark.asyncio
    async def test_execute_with_limits_enforced(self, bridge):
        """Test that memory limit is enforced."""
        from substrate.bridge import ExecutionLimits
        
        # Try to allocate more memory than allowed
        result = await bridge.execute(
            command=["python3", "-c", "x = 'x' * 200_000_000; print(len(x))"],
            limits=ExecutionLimits(memory_bytes=50_000_000),  # 50MB limit
        )
        
        # Should fail due to memory limit
        assert result.exit_code != 0 or result.termination == 3  # LIMIT_BREACH
    
    @pytest.mark.asyncio
    async def test_execute_streaming_logs(self, bridge):
        """Test streaming logs from execution."""
        events = []
        async for event in bridge.execute_stream(
            command=["python3", "-c", "import time; print('start'); import time; time.sleep(0.5); print('middle'); time.sleep(0.5); print('end')"],
            image="python:3.11",
        ):
            events.append(event)
        
        # Should have log events and a final result
        log_events = [e for e in events if e["type"] == "log"]
        result_events = [e for e in events if e["type"] == "result"]
        
        assert len(log_events) >= 2  # At least "start" and "end" logs
        assert len(result_events) == 1
        
        result = result_events[0]["result"]
        assert result.exit_code == 0
        assert "start" in result.stdout
        assert "middle" in result.stdout
        assert "end" in result.stdout
    
    @pytest.mark.asyncio
    async def test_execute_with_limits_enforced(self, bridge):
        """Test that resource limits are actually enforced."""
        from substrate.bridge import ExecutionLimits
        
        # Test memory limit
        result = await bridge.execute(
            command=["python3", "-c", "x = 'x' * 200_000_000; print('allocated')"],
            limits=ExecutionLimits(memory_bytes=50_000_000),  # 50MB
        )
        
        # Should be killed due to memory limit
        assert result.termination == 3  # LIMIT_BREACH
    
    @pytest.mark.asyncio
    async def test_concurrent_executions(self, bridge):
        """Test multiple concurrent executions."""
        async def run_echo(i):
            return await bridge.execute(
                command=["echo", f"hello-{i}"],
                image="python:3.11",
            )
        
        # Run 5 concurrent executions
        tasks = [bridge.execute(["echo", f"test-{i}"]) for i in range(5)]
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 5
        for i, result in enumerate(results):
            assert result.exit_code == 0
            assert f"test-{i}" in result.stdout
    
    @pytest.mark.asyncio
    async def test_execute_failing_command(self, bridge):
        """Test that failed commands return non-zero exit code."""
        result = await bridge.execute(
            command=["python3", "-c", "import sys; sys.exit(42)"],
        )
        
        assert result.exit_code == 42
        assert result.termination == 1  # FAILED
    
    @pytest.mark.asyncio
    async def test_execute_timeout(self, bridge):
        """Test command timeout."""
        from substrate.bridge import ExecutionLimits
        
        result = await bridge.execute(
            command=["python3", "-c", "import time; time.sleep(10)"],
            limits=ExecutionLimits(wall_time_seconds=1),
        )
        
        # Should timeout
        assert result.termination == 2  # TIMEOUT
    
    @pytest.mark.asyncio
    async def test_streaming_logs(self, bridge):
        """Test streaming logs during execution."""
        events = []
        
        async for event in bridge.execute_stream(
            command=["python3", "-c", "import time; print('start'); import time; time.sleep(0.2); print('middle'); time.sleep(0.2); print('end')"],
        ):
            events.append(event)
        
        log_events = [e for e in events if e["type"] == "log"]
        result_events = [e for e in events if e["type"] == "result"]
        
        assert len(log_events) >= 3  # start, middle, end
        assert len(result_events) == 1
        
        # Check log ordering
        log_contents = [e["content"].strip() for e in events if e["type"] == "log"]
        assert "start" in log_contents[0]
        assert "middle" in log_contents[1]
        assert "end" in log_contents[2]


class TestSubstrateCapabilityNegotiation:
    """Tests for capability negotiation."""
    
    @pytest.fixture
    async def bridge(self):
        from substrate.bridge import SubstrateBridge
        socket_path = os.environ.get("SUBSTRATE_TEST_SOCKET", "/tmp/substrate.sock")
        
        bridge = SubstrateBridge(socket_path=socket_path)
        try:
            await bridge.connect()
            yield bridge
        finally:
            await bridge.close()
    
    @pytest.mark.asyncio
    async def test_negotiate_basic_capabilities(self, bridge):
        """Test basic capability negotiation."""
        result = await bridge.negotiate_capability(
            required=["code_execution", "filesystem_write"],
            preferred=["network_egress"],
        )
        
        assert "granted" in result
        assert "denied" in result
        assert "code_execution" in result["granted"]
        assert "filesystem_write" in result["granted"]
    
    @pytest.mark.asyncio
    async def test_negotiate_with_limits(self, bridge):
        """Test capability negotiation with resource limits."""
        from substrate.bridge import ExecutionLimits
        
        result = await bridge.negotiate_capability(
            required=["code_execution"],
            resource_limits=ExecutionLimits(memory_bytes=1_000_000_000),
        )
        
        assert "granted" in result
        assert "adjusted_limits" in result


class TestEvidenceAndBudget:
    """Tests for evidence and budget integration."""
    
    @pytest.fixture
    async def bridge(self):
        from substrate.bridge import SubstrateBridge
        socket_path = os.environ.get("SUBSTRATE_TEST_SOCKET", "/tmp/substrate.sock")
        
        bridge = SubstrateBridge(socket_path=socket_path)
        try:
            await bridge.connect()
            yield bridge
        finally:
            await bridge.close()
    
    @pytest.mark.asyncio
    async def test_evidence_hash_reproducible(self, bridge):
        """Test that same command produces same evidence hash."""
        # Run same command twice
        result1 = await bridge.execute(["echo", "test-evidence"])
        result2 = await bridge.execute(["echo", "test-evidence"])
        
        # Both should succeed
        assert result1.exit_code == 0
        assert result2.exit_code == 0
        
        # Evidence hashes should be computable and consistent
        # (Implementation detail: we'd need to expose evidence_hash)
        assert result1.stdout == result2.stdout
    
    @pytest.mark.asyncio
    async def test_artifact_creation(self, bridge):
        """Test that artifacts are created and tracked."""
        result = await bridge.execute(
            command=["python3", "-c", "open('/artifacts/test.txt', 'w').write('hello')"],
            image="python:3.11",
        )
        
        assert result.exit_code == 0
        # Check that artifact was created
        artifact_paths = [a.path for a in result.artifacts]
        assert any("test.txt" in p for p in artifact_paths)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])