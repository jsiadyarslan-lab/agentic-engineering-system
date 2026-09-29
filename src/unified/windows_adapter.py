"""
Windows Executor Adapter — Unified Engineering Agents System

Implements ExecutionSandbox protocol using Windows Job Objects for partial isolation.
Wraps the existing WindowsExecutor from substrate.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from unified.domain_model import (
    SandboxTermination,
    SandboxRequest,
    SandboxExecutionRecord,
    Artifact,
)
from unified.sandbox import ExecutionSandbox, SandboxError, SandboxUnavailableError


class WindowsExecutorAdapter:
    """
    Windows sandbox adapter using Job Objects for partial isolation.
    Implements the ExecutionSandbox protocol.
    
    Provides:
    - Memory limits (process and job)
    - CPU time limits
    - Process count limits
    - Working directory enforcement
    - Artifact capture with SHA256
    
    IMPORTANT: Provides PARTIAL isolation only - no filesystem/network isolation.
    isolation_level = "PARTIAL_JOB_OBJECT"
    """
    
    def __init__(
        self,
        default_memory_bytes: int = 2 * 1024 * 1024 * 1024,  # 2GB
        default_cpu_percent: float = 100.0,
        default_cpu_time_seconds: int = 300,
        default_max_processes: int = 100,
        default_wall_time_seconds: int = 300,
        artifacts_base_dir: Optional[str] = None,
    ):
        self.default_memory_bytes = default_memory_bytes
        self.default_cpu_percent = default_cpu_percent
        self.default_cpu_time_seconds = default_cpu_time_seconds
        self.default_max_processes = default_max_processes
        self.default_wall_time_seconds = default_wall_time_seconds
        self.artifacts_base_dir = artifacts_base_dir or os.path.join(tempfile.gettempdir(), "unified_artifacts")
        
        # Ensure artifacts directory exists
        os.makedirs(self.artifacts_base_dir, exist_ok=True)
        
        # Try to import Windows-specific modules
        try:
            import win32api
            import win32con
            import win32job
            import win32process
            import win32security
            import win32event
            import win32file
            import win32pipe
            import pywintypes
            self._has_pywin32 = True
        except ImportError:
            self._has_pywin32 = False
    
    @property
    def backend_name(self) -> str:
        return "WindowsExecutorAdapter"
    
    def is_available(self) -> bool:
        return True  # Always available (falls back to subprocess)
    
    async def execute(self, request: SandboxRequest) -> SandboxExecutionRecord:
        """Execute command in sandbox with resource limits."""
        sandbox_id = request.sandbox_id
        artifacts_dir = os.path.join(self.artifacts_base_dir, sandbox_id)
        os.makedirs(artifacts_dir, exist_ok=True)
        
        # Build command line
        if isinstance(request.command, list):
            cmd_line = subprocess.list2cmdline(request.command)
        else:
            cmd_line = request.command
        
        # Prepare environment
        env = {**os.environ}
        
        # Determine if we can use Job Objects
        use_job_objects = self._has_pywin32
        
        start_time = time.time()
        started_at = datetime.now(timezone.utc)
        
        if use_job_objects:
            record = await self._execute_with_job_objects(
                sandbox_id=sandbox_id,
                command=request.command,
                cmd_line=cmd_line,
                env=env,
                working_dir=request.working_dir,
                artifacts_dir=artifacts_dir,
                memory_bytes=request.memory_bytes or self.default_memory_bytes,
                cpu_percent=request.cpu_percent or self.default_cpu_percent,
                cpu_time_seconds=request.cpu_time_seconds or self.default_cpu_time_seconds,
                max_processes=request.max_processes or self.default_max_processes,
                wall_time_seconds=request.wall_time_seconds,
            )
        else:
            record = await self._execute_subprocess_fallback(
                sandbox_id=sandbox_id,
                command=request.command,
                env=env,
                working_dir=request.working_dir,
                artifacts_dir=artifacts_dir,
                wall_time_seconds=request.wall_time_seconds,
            )
        
        return record
    
    async def _execute_with_job_objects(
        self,
        sandbox_id: str,
        command: List[str],
        cmd_line: str,
        env: Dict[str, str],
        working_dir: str,
        artifacts_dir: str,
        memory_bytes: int,
        cpu_percent: float,
        cpu_time_seconds: int,
        max_processes: int,
        wall_time_seconds: int,
    ) -> SandboxExecutionRecord:
        """Execute using Windows Job Objects for resource limits."""
        import win32api
        import win32con
        import win32job
        import win32process
        import win32security
        import win32event
        import win32file
        import win32pipe
        import pywintypes
        
        # Create job object
        job_handle = win32job.CreateJobObject(None, "")
        
        try:
            # Configure job limits
            self._configure_job_limits(
                job_handle, memory_bytes, cpu_percent, cpu_time_seconds, max_processes
            )
            
            # Prepare startup info
            startup_info = win32process.STARTUPINFO()
            startup_info.dwFlags = win32con.STARTF_USESTDHANDLES
            
            # Create pipes for stdout/stderr
            stdout_read, stdout_write = win32pipe.CreatePipe()
            stderr_read, stderr_write = win32pipe.CreatePipe()
            
            startup_info.hStdOutput = stdout_write
            startup_info.hStdError = stderr_write
            startup_info.hStdInput = win32api.GetStdHandle(win32con.STD_INPUT_HANDLE)
            startup_info.dwFlags |= win32con.STARTF_USESTDHANDLES
            
            # Create process
            process_info = win32process.CreateProcess(
                None,  # Application name
                cmd_line,  # Command line
                None,  # Process security
                None,  # Thread security
                True,  # Inherit handles
                win32con.CREATE_SUSPENDED | win32con.CREATE_UNICODE_ENVIRONMENT,
                self._prepare_environment(env),
                working_dir,
                startup_info,
            )
            
            process_handle, thread_handle, process_id, thread_id = process_info
            
            try:
                # Assign process to job
                win32job.AssignProcessToJobObject(job_handle, process_handle)
                
                # Resume thread
                win32process.ResumeThread(thread_handle)
                
                # Read output with timeout
                stdout_data, stderr_data = await self._read_output_with_timeout(
                    stdout_read, stderr_read, wall_time_seconds
                )
                
                # Wait for process
                exit_code = await self._wait_for_process(process_handle, wall_time_seconds)
                
                # Collect artifacts
                artifacts = self._collect_artifacts(artifacts_dir, sandbox_id)
                
                # Build result
                finished_at = datetime.now(timezone.utc)
                duration_ms = int((time.time() - start_time) * 1000)
                
                # Calculate evidence hash
                stdout_str = stdout_data.decode('utf-8', errors='replace')
                stderr_str = stderr_data.decode('utf-8', errors='replace')
                evidence_hash = self._compute_evidence_hash(
                    command, stdout_str, stderr_str, {
                        "memory_bytes": memory_bytes,
                        "cpu_percent": cpu_percent,
                        "cpu_time_seconds": cpu_time_seconds,
                        "max_processes": max_processes,
                        "wall_time_seconds": wall_time_seconds,
                    }
                )
                
                # Write stdout/stderr as artifacts
                stdout_artifact_id = await self._write_output_artifact(
                    artifacts_dir, sandbox_id, "stdout", stdout_data
                )
                stderr_artifact_id = await self._write_output_artifact(
                    artifacts_dir, sandbox_id, "stderr", stderr_data
                )
                
                artifact_ids = [stdout_artifact_id, stderr_artifact_id]
                for art in artifacts:
                    artifact_ids.append(art["artifact_id"])
                
                return SandboxExecutionRecord(
                    sandbox_id=sandbox_id,
                    executed=True,
                    exit_code=exit_code,
                    termination=self._map_termination_status(exit_code),
                    duration_ms=duration_ms,
                    stdout_reference=stdout_artifact_id,
                    stderr_reference=stderr_artifact_id,
                    started_at=started_at,
                    finished_at=finished_at,
                    artifacts=artifact_ids,
                )
                
            finally:
                # Cleanup
                try:
                    win32job.TerminateJobObject(job_handle, 0)
                except:
                    pass
                try:
                    win32api.CloseHandle(job_handle)
                except:
                    pass
        
        except Exception as e:
            # Fallback to subprocess
            return await self._execute_subprocess_fallback(
                sandbox_id=sandbox_id,
                command=command,
                env=env,
                working_dir=working_dir,
                artifacts_dir=artifacts_dir,
                wall_time_seconds=wall_time_seconds,
            )
    
    def _configure_job_limits(
        self,
        job_handle,
        memory_bytes: int,
        cpu_percent: float,
        cpu_time_seconds: int,
        max_processes: int,
    ):
        """Configure Job Object limits."""
        import win32job
        import win32con
        
        # Memory limits
        if memory_bytes:
            try:
                info = win32job.JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
                info.BasicLimitInformation.LimitFlags |= (
                    win32job.JOB_OBJECT_LIMIT_JOB_MEMORY |
                    win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
                )
                info.BasicLimitInformation.JobMemoryLimit = memory_bytes
                info.BasicLimitInformation.ProcessMemoryLimit = memory_bytes
                
                win32job.SetInformationJobObject(
                    job_handle,
                    win32job.JobObjectExtendedLimitInformation,
                    info
                )
            except AttributeError:
                # Fallback: use dict approach
                info_dict = {
                    "BasicLimitInformation": {
                        "LimitFlags": (
                            win32job.JOB_OBJECT_LIMIT_JOB_MEMORY |
                            win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
                        ),
                        "JobMemoryLimit": memory_bytes,
                        "ProcessMemoryLimit": memory_bytes,
                    }
                }
                win32job.SetInformationJobObject(
                    job_handle,
                    win32job.JobObjectExtendedLimitInformation,
                    info_dict
                )
        
        # CPU rate control
        if cpu_percent and cpu_percent < 100:
            try:
                cpu_rate = int(cpu_percent * 100)  # Percentage * 100
                cpu_rate_info = win32job.JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
                cpu_rate_info.ControlFlags = (
                    win32job.JOB_OBJECT_CPU_RATE_CONTROL_ENABLE |
                    win32job.JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
                )
                cpu_rate_info.CpuRate = cpu_rate
                
                win32job.SetInformationJobObject(
                    job_handle,
                    win32job.JobObjectCpuRateControlInformation,
                    cpu_rate_info
                )
            except Exception:
                pass  # CPU rate control not available
        
        # Process count limit
        if max_processes:
            info = win32job.JOBOBJECT_BASIC_LIMIT_INFORMATION()
            info.LimitFlags = win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            info.ActiveProcessLimit = max_processes
            win32job.SetInformationJobObject(
                job_handle,
                win32job.JobObjectBasicLimitInformation,
                info
            )
        
        # CPU time limit
        if cpu_time_seconds:
            info = win32job.JOBOBJECT_BASIC_LIMIT_INFORMATION()
            info.LimitFlags |= win32job.JOB_OBJECT_LIMIT_PROCESS_TIME
            info.PerProcessUserTimeLimit = cpu_time_seconds * 10000000  # 100ns units
            win32job.SetInformationJobObject(
                job_handle,
                win32job.JobObjectBasicLimitInformation,
                info
            )
    
    async def _read_output_with_timeout(
        self,
        stdout_read,
        stderr_read,
        timeout: int,
    ) -> tuple:
        """Read stdout/stderr with timeout."""
        import win32file
        
        stdout_data = b""
        stderr_data = b""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Read stdout
            try:
                result = win32file.ReadFile(stdout_read, 4096, None)
                if result[0] == 0 and result[1]:
                    stdout_data += result[1]
                elif result[0] != 0:
                    pass  # EOF or error
            except:
                pass
            
            # Read stderr
            try:
                result = win32file.ReadFile(stderr_read, 4096, None)
                if result[0] == 0 and result[1]:
                    stderr_data += result[1]
                elif result[0] != 0:
                    pass  # EOF or error
            except:
                pass
            
            # Small delay to prevent busy loop
            await asyncio.sleep(0.01)
            
            if time.time() - start_time > timeout:
                break
        
        return stdout_data, stderr_data
    
    async def _wait_for_process(self, process_handle, timeout: int) -> int:
        """Wait for process to complete with timeout."""
        import win32event
        import win32con
        import win32process
        
        result = win32event.WaitForSingleObject(process_handle, timeout * 1000)
        if result == win32con.WAIT_TIMEOUT:
            raise TimeoutError("Process timed out")
        elif result == win32con.WAIT_OBJECT_0:
            exit_code = win32process.GetExitCodeProcess(process_handle)
            return exit_code
        else:
            raise RuntimeError(f"Wait failed: {result}")
    
    def _prepare_environment(self, env: Dict[str, str]) -> Dict[str, str]:
        """Prepare environment block for CreateProcess."""
        # Windows requires environment as a single string with null separators
        env_strings = []
        for k, v in env.items():
            env_strings.append(f"{k}={v}")
        return "\0".join(env_strings) + "\0\0"
    
    def _collect_artifacts(self, artifacts_dir: str, sandbox_id: str) -> List[Dict]:
        """Collect artifacts from execution directory."""
        artifacts = []
        artifacts_path = Path(artifacts_dir)
        
        if artifacts_path.exists():
            for file_path in artifacts_path.rglob("*"):
                if file_path.is_file() and file_path.name not in ("stdout", "stderr"):
                    try:
                        with open(file_path, 'rb') as f:
                            content = f.read()
                        sha256 = hashlib.sha256(content).hexdigest()
                        
                        artifacts.append({
                            "artifact_id": f"artifact-{uuid.uuid4().hex[:12]}",
                            "name": file_path.name,
                            "path": str(file_path.relative_to(artifacts_path)),
                            "sha256": sha256,
                            "size_bytes": file_path.stat().st_size,
                            "content_type": "application/octet-stream",
                        })
                    except Exception:
                        pass
        
        return artifacts
    
    async def _write_output_artifact(
        self,
        artifacts_dir: str,
        sandbox_id: str,
        name: str,
        content: bytes,
    ) -> str:
        """Write stdout/stderr as artifact and return artifact_id."""
        artifact_id = f"artifact-{uuid.uuid4().hex[:12]}"
        file_path = Path(artifacts_dir) / name
        with open(file_path, 'wb') as f:
            f.write(content)
        return artifact_id
    
    def _compute_evidence_hash(
        self,
        command: List[str],
        stdout: str,
        stderr: str,
        limits: Dict[str, Any],
    ) -> str:
        """Compute evidence hash for audit trail."""
        evidence_data = {
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "limits": limits,
            "timestamp": time.time(),
        }
        evidence_json = json.dumps(evidence_data, sort_keys=True)
        return hashlib.sha256(evidence_json.encode()).hexdigest()
    
    def _map_termination_status(self, exit_code: int) -> SandboxTermination:
        """Map exit code to termination status."""
        if exit_code == 0:
            return SandboxTermination.COMPLETED
        elif exit_code < 0:
            return SandboxTermination.FAILED_TO_START
        else:
            return SandboxTermination.COMPLETED  # Non-zero exit is still COMPLETED, just failed
    
    async def _execute_subprocess_fallback(
        self,
        sandbox_id: str,
        command: List[str],
        env: Dict[str, str],
        working_dir: str,
        artifacts_dir: str,
        wall_time_seconds: int,
    ) -> SandboxExecutionRecord:
        """Fallback to subprocess when Job Objects unavailable."""
        started_at = datetime.now(timezone.utc)
        start_time = time.time()
        
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=env,
            )
            
            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    process.communicate(),
                    timeout=wall_time_seconds,
                )
                exit_code = process.returncode
            except asyncio.TimeoutError:
                process.kill()
                stdout_data, stderr_data = await process.communicate()
                exit_code = -1
                termination = SandboxTermination.TIMEOUT
            
            finished_at = datetime.now(timezone.utc)
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Collect artifacts
            artifacts = self._collect_artifacts(artifacts_dir, sandbox_id)
            
            stdout_str = stdout_data.decode('utf-8', errors='replace')
            stderr_str = stderr_data.decode('utf-8', errors='replace')
            evidence_hash = self._compute_evidence_hash(
                command, stdout_str, stderr_str, {"wall_time_seconds": wall_time_seconds}
            )
            
            # Write stdout/stderr as artifacts
            stdout_artifact_id = await self._write_output_artifact(
                artifacts_dir, sandbox_id, "stdout", stdout_data
            )
            stderr_artifact_id = await self._write_output_artifact(
                artifacts_dir, sandbox_id, "stderr", stderr_data
            )
            
            artifact_ids = [stdout_artifact_id, stderr_artifact_id]
            for art in artifacts:
                artifact_ids.append(art["artifact_id"])
            
            return SandboxExecutionRecord(
                sandbox_id=sandbox_id,
                executed=True,
                exit_code=exit_code,
                termination=termination if 'termination' in locals() else self._map_termination_status(exit_code),
                duration_ms=duration_ms,
                stdout_reference=stdout_artifact_id,
                stderr_reference=stderr_artifact_id,
                started_at=started_at,
                finished_at=finished_at,
                artifacts=artifact_ids,
            )
            
        except Exception as e:
            finished_at = datetime.now(timezone.utc)
            duration_ms = int((time.time() - start_time) * 1000)
            
            return SandboxExecutionRecord(
                sandbox_id=sandbox_id,
                executed=False,
                exit_code=None,
                termination=SandboxTermination.FAILED_TO_START,
                duration_ms=duration_ms,
                stdout_reference="",
                stderr_reference="",
                started_at=started_at,
                finished_at=finished_at,
                artifacts=[],
            )
    
    async def write_artifact(
        self,
        sandbox_id: str,
        path: str,
        content: bytes,
    ) -> Artifact:
        """Write artifact to sandbox /artifacts directory."""
        artifacts_dir = os.path.join(self.artifacts_base_dir, sandbox_id)
        os.makedirs(artifacts_dir, exist_ok=True)
        
        file_path = Path(artifacts_dir) / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'wb') as f:
            f.write(content)
        
        sha256 = hashlib.sha256(content).hexdigest()
        artifact_id = f"artifact-{uuid.uuid4().hex[:12]}"
        
        return Artifact(
            artifact_id=artifact_id,
            name=Path(path).name,
            path=path,
            sha256=sha256,
            size_bytes=len(content),
            created_by=sandbox_id,
            content_type="application/octet-stream",
        )
    
    async def read_artifact(self, sandbox_id: str, path: str) -> bytes:
        """Read artifact from sandbox /artifacts directory."""
        artifacts_dir = os.path.join(self.artifacts_base_dir, sandbox_id)
        file_path = Path(artifacts_dir) / path
        
        if not file_path.exists():
            raise FileNotFoundError(f"Artifact not found: {path}")
        
        with open(file_path, 'rb') as f:
            return f.read()
    
    async def list_artifacts(self, sandbox_id: str) -> List[Artifact]:
        """List artifacts in sandbox /artifacts."""
        artifacts_dir = os.path.join(self.artifacts_base_dir, sandbox_id)
        artifacts = []
        
        if not os.path.exists(artifacts_dir):
            return artifacts
        
        for file_path in Path(artifacts_dir).rglob("*"):
            if file_path.is_file():
                with open(file_path, 'rb') as f:
                    content = f.read()
                sha256 = hashlib.sha256(content).hexdigest()
                artifact_id = f"artifact-{uuid.uuid4().hex[:12]}"
                
                artifacts.append(Artifact(
                    artifact_id=artifact_id,
                    name=file_path.name,
                    path=str(file_path.relative_to(artifacts_dir)),
                    sha256=sha256,
                    size_bytes=len(content),
                    created_by=sandbox_id,
                    content_type="application/octet-stream",
                ))
        
        return artifacts
    
    async def teardown(self, sandbox_id: str) -> None:
        """Teardown sandbox - best effort cleanup."""
        artifacts_dir = os.path.join(self.artifacts_base_dir, sandbox_id)
        if os.path.exists(artifacts_dir):
            try:
                import shutil
                shutil.rmtree(artifacts_dir)
            except Exception:
                pass  # Best effort


def create_windows_executor_adapter(**kwargs) -> ExecutionSandbox:
    """Factory function to create WindowsExecutorAdapter."""
    return WindowsExecutorAdapter(**kwargs)