#!/usr/bin/env python3
"""
Windows Execution Backend with Job Objects
Provides partial isolation using Windows Job Objects for resource limits.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, List, Union
import logging

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
    import win32api
    import win32con
    import win32job
    import win32process
    import win32security
    import win32event
    import win32file
    import win32pipe
    import pywintypes
    HAS_PYWIN32 = True
except ImportError:
    HAS_PYWIN32 = False

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, List, Union
from pathlib import Path
import hashlib
import json
import time

logger = logging.getLogger(__name__)


@dataclass
class ExecutionLimits:
    """Resource limits for execution."""
    memory_bytes: Optional[int] = None          # Memory limit in bytes
    cpu_percent: Optional[float] = None         # CPU percentage limit (0-100)
    cpu_time_seconds: Optional[int] = None      # CPU time limit in seconds
    max_processes: Optional[int] = None         # Max process count
    max_file_size: Optional[int] = None         # Max file size in bytes
    max_output_bytes: Optional[int] = None      # Max output bytes
    wall_time_seconds: Optional[int] = None     # Wall clock timeout in seconds


@dataclass
class ExecutionResult:
    """Result of a command execution."""
    sandbox_id: str
    executed: bool
    exit_code: Optional[int]
    termination: str  # COMPLETED, FAILED, TIMEOUT, LIMIT_BREACH, FAILED_TO_START
    duration_ms: int
    stdout: str
    stderr: str
    limits_applied: 'ExecutionLimits'
    artifacts: List[Dict] = field(default_factory=list)
    started_at: float
    finished_at: float
    isolation_level: str = "PARTIAL_JOB_OBJECT"
    evidence_hash: str = ""


@dataclass
class ArtifactInfo:
    """Information about an artifact produced during execution."""
    path: str
    sha256: str
    size: int
    kind: str = "file"


class WindowsExecutor:
    """
    Windows Execution Backend using Job Objects for partial isolation.
    
    Provides resource limits via Windows Job Objects:
    - Memory limits (process and job)
    - CPU time limits
    - Process count limits
    - Working directory enforcement
    
    Falls back to subprocess if Job Objects unavailable.
    
    IMPORTANT: Provides PARTIAL isolation only - no filesystem/network isolation.
    isolation_level = "PARTIAL_JOB_OBJECT"
    """
    
    def __init__(
        self,
        default_limits: Optional[ExecutionLimits] = None,
        job_objects_enabled: bool = True,
    ):
        self.default_limits = default_limits or ExecutionLimits()
        self.job_objects_enabled = job_objects_enabled and HAS_PYWIN32
        
        if not HAS_PYWIN32:
            logger.warning("pywin32 not available - falling back to subprocess")
            self.job_objects_enabled = False
        elif not job_objects_enabled:
            logger.info("Job Objects disabled by configuration")
            self.job_objects_enabled = False
        else:
            logger.info("WindowsExecutor initialized with Job Objects support")
    
    def execute(
        self,
        command: List[str],
        image: str = "cmd.exe",
        limits: Optional[ExecutionLimits] = None,
        env: Optional[Dict[str, str]] = None,
        working_dir: Optional[str] = None,
        artifacts_dir: Optional[str] = None,
        sandbox_id: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> 'ExecutionResult':
        """
        Execute a command with resource limits.
        
        Args:
            command: Command to execute as list of strings
            image: Executable image (default: cmd.exe)
            limits: Resource limits
            env: Environment variables
            working_dir: Working directory
            artifacts_dir: Directory for artifacts
            sandbox_id: Unique sandbox identifier
            
        Returns:
            ExecutionResult with evidence
        """
        sandbox_id = sandbox_id or str(uuid.uuid4())[:8]
        limits = limits or ExecutionLimits()
        working_dir = working_dir or os.getcwd()
        artifacts_dir = artifacts_dir or tempfile.gettempdir()
        
        # Ensure directories exist
        os.makedirs(artifacts_dir, exist_ok=True)
        
        # Combine limits
        limits = self._merge_limits(limits)
        
        # Generate sandbox ID
        sandbox_id = sandbox_id or str(uuid.uuid4())[:8]
        
        # Prepare environment
        env = env or {}
        env = {**os.environ, **env}
        
        # Start timing
        start_time = time.time()
        started_at = datetime.utcnow()
        
        # Choose execution method
        if self.job_objects_enabled:
            result = self._execute_with_job_objects(
                command=command,
                image=image,
                limits=limits,
                env=env,
                working_dir=working_dir,
                artifacts_dir=artifacts_dir,
                sandbox_id=sandbox_id,
                timeout=limits.wall_time_seconds,
            )
        else:
            result = self._execute_subprocess_fallback(
                command=command,
                image=image,
                limits=limits,
                env=env,
                working_dir=working_dir,
                artifacts_dir=artifacts_dir,
                sandbox_id=sandbox_id,
            )
        
        # Calculate duration
        finished_at = time.time()
        duration_ms = int((time.time() - start_time) * 1000)
        
        return result
    
    def _merge_limits(self, limits: Optional[ExecutionLimits]) -> 'ExecutionLimits':
        """Merge provided limits with defaults."""
        if limits is None:
            return self.default_limits
        
        # Merge with defaults
        merged = ExecutionLimits()
        for field_name in ['memory_bytes', 'cpu_percent', 'cpu_time_seconds',
                          'max_processes', 'max_file_size', 'max_output_bytes',
                          'wall_time_seconds']:
            value = getattr(limits, field_name)
            default_value = getattr(self.default_limits, field_name)
            setattr(merged, field_name, value if value is not None else getattr(self.default_limits, field_name))
        return limits
    
    def _execute_with_job_objects(
        self,
        command: List[str],
        image: str,
        limits: ExecutionLimits,
        env: Dict[str, str],
        working_dir: str,
        artifacts_dir: str,
        sandbox_id: str,
        timeout: Optional[int] = None,
    ) -> 'ExecutionResult':
        """Execute using Windows Job Objects for resource limits."""
        
        # Create job object
        job_handle = win32job.CreateJobObject(None, "")
        
        try:
            # Configure job limits
            self._configure_job_limits(job_handle, limits)
            
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
            if isinstance(command, list):
                cmd_line = subprocess.list2cmdline(command)
            else:
                cmd_line = command
            
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
                stdout_data, stderr_data = self._read_output_with_timeout(
                    stdout_read, stderr_read,
                    timeout or 60
                )
                
                # Wait for process
                exit_code = self._wait_for_process(process_handle, limits.wall_time_seconds or 60)
                
                # Get job memory usage
                job_memory = win32job.QueryInformationJobObject(
                    job_handle, win32job.JobObjectBasicAccountingInformation
                )
                
                # Collect artifacts
                artifacts = self._collect_artifacts(artifacts_dir, sandbox_id)
                
                # Build result
                finished_at = time.time()
                
                # Calculate evidence hash
                stdout_str = stdout_data.decode('utf-8', errors='replace')
                stderr_str = stderr_data.decode('utf-8', errors='replace')
                evidence_hash = self._compute_evidence_hash(
                    command, stdout_str, stderr_str, limits
                )
                
                return ExecutionResult(
                    sandbox_id=sandbox_id,
                    executed=True,
                    exit_code=exit_code,
                    termination=self._get_termination_status(exit_code),
                    duration_ms=int((time.time() - start_time) * 1000),
                    stdout=stdout_str,
                    stderr=stderr_str,
                    limits_applied=limits,
                    artifacts=[],
                    started_at=time.time(),
                    finished_at=time.time(),
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
            logger.error(f"Job Object execution failed: {e}")
            # Fallback to subprocess
            return self._execute_subprocess_fallback(
                command=command,
                image=image,
                limits=limits,
                env=env,
                working_dir=working_dir,
                artifacts_dir=artifacts_dir,
            )
    
    def _configure_job_limits(self, job_handle, limits: ExecutionLimits):
        """Configure Job Object limits."""
        
        # Memory limits
        if limits.memory_bytes:
            info = win32job.JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags |= win32job.JOB_OBJECT_LIMIT_JOB_MEMORY
            info.BasicLimitInformation.JobMemoryLimit = limits.memory_bytes
            info.BasicLimitInformation.LimitFlags |= win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
            info.BasicLimitInformation.ProcessMemoryLimit = limits.memory_bytes
            
            win32job.SetInformationJobObject(
                job_handle,
                win32job.JobObjectExtendedLimitInformation,
                info
            )
        
        # CPU limits
        if limits.cpu_percent and limits.cpu_percent < 100:
            # CPU rate control (requires Windows 8+)
            try:
                cpu_rate = int(limits.cpu_percent * 100)  # Percentage * 100
                cpu_rate_info = win32job.JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
                cpu_rate_info.ControlFlags = win32job.JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | \
                                            win32job.JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
                cpu_rate_info.CpuRate = cpu_rate
                
                win32job.SetInformationJobObject(
                    job_handle,
                    win32job.JobObjectCpuRateControlInformation,
                    cpu_rate_info
                )
            except Exception as e:
                logger.warning(f"CPU rate control not available: {e}")
        
        # Process count limit
        if limits.max_processes:
            info = win32job.JOBOBJECT_BASIC_LIMIT_INFORMATION()
            info.LimitFlags = win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            info.ActiveProcessLimit = limits.max_processes
            win32job.SetInformationJobObject(
                job_handle,
                win32job.JobObjectBasicLimitInformation,
                info
            )
        
        # CPU time limit
        if limits.cpu_time_seconds:
            info = win32job.JOBOBJECT_BASIC_LIMIT_INFORMATION()
            info.LimitFlags |= win32job.JOB_OBJECT_LIMIT_PROCESS_TIME
            info.PerProcessUserTimeLimit = limits.cpu_time_seconds * 10000000  # 100ns units
            win32job.SetInformationJobObject(
                job_handle,
                win32job.JobObjectBasicLimitInformation,
                info
            )
    
    def _read_output_with_timeout(
        self,
        stdout_read,
        stderr_read,
        timeout: int,
    ) -> tuple:
        """Read stdout/stderr with timeout."""
        stdout_data = b""
        stderr_data = b""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Read stdout
            try:
                data = win32file.ReadFile(stdout_read, 4096, None)
                if data[0] == 0 and data[1]:
                    stdout_data += data[1]
                    stdout_data += b"\n"
                elif data[0] != 0:
                    break
            except:
                pass
            
            # Read stderr
            try:
                data = win32file.ReadFile(stderr_read, 4096, None)
                if data[0] == 0 and data[1]:
                    stderr_data += data[1]
                    stderr_data += b"\n"
                elif data[0] != 0:
                    break
            except:
                pass
            
            if time.time() - start_time > timeout:
                break
        
        return stdout_data, stderr_data
    
    def _wait_for_process(self, process_handle, timeout: int) -> int:
        """Wait for process to complete with timeout."""
        result = win32event.WaitForSingleObject(process_handle, timeout * 1000)
        if result == win32con.WAIT_TIMEOUT:
            raise TimeoutError("Process timed out")
        elif result == win32con.WAIT_OBJECT_0:
            exit_code = win32process.GetExitCodeProcess(process_handle)
            return exit_code
        else:
            raise RuntimeError(f"Wait failed: {result}")
    
    def _collect_artifacts(self, artifacts_dir: str, sandbox_id: str) -> List[Dict]:
        """Collect artifacts from execution directory."""
        artifacts = []
        artifacts_path = Path(artifacts_dir) / sandbox_id
        
        if artifacts_path.exists():
            for file_path in artifacts_path.rglob("*"):
                if file_path.is_file():
                    with open(file_path, 'rb') as f:
                        content = f.read()
                        sha256 = hashlib.sha256(content).hexdigest()
                    
                    artifacts.append({
                        "path": str(file_path.relative_to(Path(artifacts_dir))),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size": file_path.stat().st_size,
                        "kind": "file",
                    })
        
        return artifacts
    
    def _compute_evidence_hash(
        self,
        command: List[str],
        stdout: str,
        stderr: str,
        limits: ExecutionLimits,
    ) -> str:
        """Compute evidence hash for audit trail."""
        evidence_data = {
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "limits": {
                "memory_bytes": limits.memory_bytes,
                "cpu_percent": limits.cpu_percent,
                "wall_time_seconds": limits.wall_time_seconds,
            },
            "timestamp": time.time(),
        }
        evidence_json = json.dumps(evidence_data, sort_keys=True)
        return hashlib.sha256(evidence_json.encode()).hexdigest()
    
    def _get_termination_status(self, exit_code: int) -> str:
        """Map exit code to termination status."""
        if exit_code == 0:
            return "COMPLETED"
        elif exit_code < 0:
            return "FAILED"
        else:
            return "FAILED"
    
    def _execute_subprocess_fallback(
        self,
        command: List[str],
        image: str,
        limits: ExecutionLimits,
        env: Dict[str, str],
        working_dir: str,
        artifacts_dir: str,
        sandbox_id: str,
    ) -> ExecutionResult:
        """Fallback to subprocess when Job Objects unavailable."""
        
        sandbox_id = sandbox_id or str(uuid.uuid4())[:8]
        start_time = time.time()
        started_at = datetime.utcnow()
        
        # Prepare environment
        env = {**os.environ, **(env or {})}
        
        try:
            # Run with timeout
            timeout = limits.wall_time_seconds or 60
            
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=working_dir,
                env=env,
                text=True,
            )
            
            try:
                stdout, stderr = process.communicate(timeout=limits.wall_time_seconds or 60)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                return ExecutionResult(
                    sandbox_id=sandbox_id,
                    executed=True,
                    exit_code=None,
                    termination="TIMEOUT",
                    duration_ms=int((time.time() - time.time()) * 1000),
                    stdout="",
                    stderr="Timeout",
                    limits_applied=limits,
                    artifacts=[],
                    started_at=started_at.timestamp(),
                    finished_at=time.time(),
                )
            
            # Collect artifacts
            artifacts = self._collect_artifacts(artifacts_dir, sandbox_id)
            
            # Evidence hash
            evidence_hash = self._compute_evidence_hash(
                command=command,
                stdout=stdout,
                stderr=stderr,
                limits=limits,
            )
            
            return ExecutionResult(
                sandbox_id=sandbox_id,
                executed=True,
                exit_code=process.returncode,
                termination=self._get_termination_status(process.returncode),
                duration_ms=int((time.time() - start_time) * 1000),
                stdout=stdout,
                stderr=stderr,
                limits_applied=limits,
                artifacts=[],
                started_at=started_at.timestamp(),
                finished_at=datetime.utcnow().timestamp(),
            )
        
        except Exception as e:
            logger.error(f"Subprocess execution failed: {e}")
            return ExecutionResult(
                sandbox_id=sandbox_id,
                executed=False,
                exit_code=None,
                termination="FAILED_TO_START",
                duration_ms=0,
                stdout="",
                stderr=str(e),
                limits_applied=limits,
                artifacts=[],
                started_at=time.time(),
                finished_at=time.time(),
            )
    
    def _collect_artifacts(self, artifacts_dir: str, sandbox_id: str) -> List[Dict]:
        """Collect artifacts from execution directory."""
        artifacts = []
        artifacts_path = Path(artifacts_dir) / sandbox_id
        
        if artifacts_path.exists():
            for file_path in artifacts_path.rglob("*"):
                if file_path.is_file():
                    try:
                        with open(file_path, 'rb') as f:
                            content = f.read()
                            sha256 = hashlib.sha256(content).hexdigest()
                        
                        artifacts.append({
                            "path": str(file_path.relative_to(Path(artifacts_dir))),
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "size": file_path.stat().st_size,
                            "kind": "file",
                        })
                    except Exception as e:
                        logger.warning(f"Failed to read artifact {file_path}: {e}")
        
        return artifacts
    
    def _compute_evidence_hash(
        self,
        command: List[str],
        stdout: str,
        stderr: str,
        limits: ExecutionLimits,
    ) -> str:
        """Compute evidence hash for audit trail."""
        evidence_data = {
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "limits": {
                "memory_bytes": limits.memory_bytes,
                "cpu_percent": limits.cpu_percent,
                "wall_time_seconds": limits.wall_time_seconds,
            },
            "timestamp": time.time(),
        }
        evidence_json = json.dumps(evidence_data, sort_keys=True)
        return hashlib.sha256(evidence_json.encode()).hexdigest()
    
    def _get_termination_status(self, exit_code: int) -> str:
        """Map exit code to termination status."""
        if exit_code == 0:
            return "COMPLETED"
        elif exit_code < 0:
            return "FAILED"
        else:
            return "FAILED"


# Import required modules
import os
import tempfile
import uuid
import subprocess
import win32pipe
import win32file
import win32event
import win32con
import win32api
import hashlib
import json
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Check for pywin32
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
    import win32api
    HAS_PYWIN32 = True
except ImportError:
    HAS_PYWIN32 = False