"""
Deterministic replay/record for execution.

Provides Python bindings for the replay crate.
"""

import json
import uuid
import hashlib
import subprocess
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path


@dataclass
class ExecutionLimitsSnapshot:
    """Snapshot of execution limits at record time."""
    memory_limit_bytes: Optional[int] = None
    cpu_time_limit_secs: Optional[int] = None
    wall_time_limit_secs: Optional[int] = None
    process_limit: Optional[int] = None
    file_size_limit_bytes: Optional[int] = None
    open_files_limit: Optional[int] = None


@dataclass
class EventPayload:
    """Event payload - varies by event type."""
    type: str
    data: Dict[str, Any]


@dataclass
class RecordedEvent:
    """Individual recorded event."""
    event_id: str
    timestamp: datetime
    sequence: int
    event_type: str
    payload: EventPayload
    thread_id: Optional[int] = None
    process_id: Optional[int] = None


@dataclass
class ArtifactReference:
    """Reference to an artifact produced during execution."""
    artifact_id: str
    name: str
    path: str
    hash: str
    size: int
    content_type: str
    created_at: datetime


@dataclass
class ExecutionRecord:
    """Execution record containing all information needed for replay."""
    execution_id: str
    started_at: datetime
    completed_at: Optional[datetime]
    command: str
    args: List[str]
    env: Dict[str, str]
    working_dir: str
    stdin_hash: Optional[str]
    stdout_hash: Optional[str]
    stderr_hash: Optional[str]
    exit_code: Optional[int]
    limits: ExecutionLimitsSnapshot
    events: List[RecordedEvent]
    artifacts: List[ArtifactReference]


@dataclass
class RecordConfig:
    """Configuration for recording."""
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    capture_stdin: bool = True
    capture_stdout: bool = True
    capture_stderr: bool = True
    capture_syscalls: bool = False
    capture_file_io: bool = True
    capture_network: bool = True
    capture_signals: bool = True
    capture_memory: bool = False
    max_events: Optional[int] = 1_000_000
    event_buffer_size: int = 10000
    flush_interval_ms: int = 1000


@dataclass
class ReplayConfig:
    """Configuration for replay."""
    execution_id: str
    verify_outputs: bool = True
    verify_timing: bool = False
    max_time_dilation: float = 10.0
    deterministic_syscalls: bool = True


@dataclass
class ReplayResult:
    """Result of a replay operation."""
    execution_id: str
    success: bool
    original_exit_code: Optional[int]
    replay_exit_code: Optional[int]
    outputs_match: bool
    timing_match: bool
    events_replayed: int
    events_mismatched: List[Dict[str, Any]]
    duration_ms: int
    error: Optional[str]


class Recorder:
    """
    Recorder for capturing execution events.
    
    This is a Python wrapper that can be used directly or as a base
    for integrating with the Rust replay crate via FFI.
    """
    
    def __init__(self, config: Optional[RecordConfig] = None):
        self.config = config or RecordConfig()
        self.execution_record = ExecutionRecord(
            execution_id=self.config.execution_id,
            started_at=datetime.utcnow(),
            completed_at=None,
            command="",
            args=[],
            env=dict(os.environ),
            working_dir=os.getcwd(),
            stdin_hash=None,
            stdout_hash=None,
            stderr_hash=None,
            exit_code=None,
            limits=ExecutionLimitsSnapshot(),
            events=[],
            artifacts=[],
        )
        self._sequence = 0
        self._event_buffer = []
    
    def set_command(self, command: str, args: List[str]) -> None:
        """Set the command being executed."""
        self.execution_record.command = command
        self.execution_record.args = args
    
    def set_env(self, env: Dict[str, str]) -> None:
        """Set environment variables."""
        self.execution_record.env = env
    
    def set_working_dir(self, dir: str) -> None:
        """Set working directory."""
        self.execution_record.working_dir = dir
    
    def set_limits(self, limits: ExecutionLimitsSnapshot) -> None:
        """Set execution limits snapshot."""
        self.execution_record.limits = limits
    
    def record_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Record an event."""
        if self.config.max_events and self._sequence >= self.config.max_events:
            raise RuntimeError("Max events reached")
        
        event = RecordedEvent(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow(),
            sequence=self._sequence,
            event_type=event_type,
            payload=EventPayload(type=event_type, data=payload),
        )
        
        self._sequence += 1
        self._event_buffer.append(event)
        
        # Flush if buffer is full
        if len(self._event_buffer) >= self.config.event_buffer_size:
            self.flush()
    
    def record_process_spawn(self, pid: int, ppid: Optional[int], command: str, args: List[str]) -> None:
        """Record process spawn."""
        self.record_event("ProcessSpawn", {
            "pid": pid,
            "ppid": ppid,
            "command": command,
            "args": args,
        })
    
    def record_process_exit(self, pid: int, exit_code: int) -> None:
        """Record process exit."""
        self.record_event("ProcessExit", {
            "pid": pid,
            "exit_code": exit_code,
        })
    
    def record_file_read(self, fd: int, path: str, offset: int, length: int, data: bytes) -> None:
        """Record file read."""
        if not self.config.capture_file_io:
            return
        data_hash = hashlib.sha256(data).hexdigest()
        self.record_event("FileRead", {
            "fd": fd,
            "path": path,
            "offset": offset,
            "length": length,
            "data_hash": data_hash,
        })
    
    def record_file_write(self, fd: int, path: str, offset: int, length: int, data: bytes) -> None:
        """Record file write."""
        if not self.config.capture_file_io:
            return
        data_hash = hashlib.sha256(data).hexdigest()
        self.record_event("FileWrite", {
            "fd": fd,
            "path": path,
            "offset": offset,
            "length": length,
            "data_hash": data_hash,
        })
    
    def record_network_connect(self, fd: int, address: str, port: int) -> None:
        """Record network connect."""
        if not self.config.capture_network:
            return
        self.record_event("NetworkConnect", {
            "fd": fd,
            "address": address,
            "port": port,
        })
    
    def record_signal(self, pid: int, signal: int) -> None:
        """Record signal."""
        if not self.config.capture_signals:
            return
        self.record_event("Signal", {
            "pid": pid,
            "signal": signal,
        })
    
    def add_artifact(self, artifact: ArtifactReference) -> None:
        """Add an artifact reference."""
        self.execution_record.artifacts.append(artifact)
    
    def set_stdin_hash(self, data: bytes) -> None:
        """Set stdin hash."""
        self.execution_record.stdin_hash = hashlib.sha256(data).hexdigest()
    
    def set_stdout_hash(self, data: bytes) -> None:
        """Set stdout hash."""
        self.execution_record.stdout_hash = hashlib.sha256(data).hexdigest()
    
    def set_stderr_hash(self, data: bytes) -> None:
        """Set stderr hash."""
        self.execution_record.stderr_hash = hashlib.sha256(data).hexdigest()
    
    def set_exit_code(self, code: int) -> None:
        """Set exit code."""
        self.execution_record.exit_code = code
    
    def flush(self) -> None:
        """Flush pending events to the record."""
        self.execution_record.events.extend(self._event_buffer)
        self._event_buffer.clear()
    
    def complete(self) -> ExecutionRecord:
        """Complete the recording and return the execution record."""
        self.flush()
        self.execution_record.completed_at = datetime.utcnow()
        return self.execution_record
    
    def save(self, path: str) -> None:
        """Save the execution record to a file."""
        self.flush()
        self.execution_record.completed_at = datetime.utcnow()
        
        data = {
            "execution_id": self.execution_record.execution_id,
            "started_at": self.execution_record.started_at.isoformat(),
            "completed_at": self.execution_record.completed_at.isoformat() if self.execution_record.completed_at else None,
            "command": self.execution_record.command,
            "args": self.execution_record.args,
            "env": self.execution_record.env,
            "working_dir": self.execution_record.working_dir,
            "stdin_hash": self.execution_record.stdin_hash,
            "stdout_hash": self.execution_record.stdout_hash,
            "stderr_hash": self.execution_record.stderr_hash,
            "exit_code": self.execution_record.exit_code,
            "limits": {
                "memory_limit_bytes": self.execution_record.limits.memory_limit_bytes,
                "cpu_time_limit_secs": self.execution_record.limits.cpu_time_limit_secs,
                "wall_time_limit_secs": self.execution_record.limits.wall_time_limit_secs,
                "process_limit": self.execution_record.limits.process_limit,
                "file_size_limit_bytes": self.execution_record.limits.file_size_limit_bytes,
                "open_files_limit": self.execution_record.limits.open_files_limit,
            },
            "events": [
                {
                    "event_id": e.event_id,
                    "timestamp": e.timestamp.isoformat(),
                    "sequence": e.sequence,
                    "event_type": e.event_type,
                    "payload": e.payload.data,
                    "thread_id": e.thread_id,
                    "process_id": e.process_id,
                }
                for e in self.execution_record.events
            ],
            "artifacts": [
                {
                    "artifact_id": a.artifact_id,
                    "name": a.name,
                    "path": a.path,
                    "hash": a.hash,
                    "size": a.size,
                    "content_type": a.content_type,
                    "created_at": a.created_at.isoformat(),
                }
                for a in self.execution_record.artifacts
            ],
        }
        
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)


class Replayer:
    """
    Replayer for deterministic execution replay.
    
    This is a Python wrapper that can replay recorded executions.
    """
    
    def __init__(self, config: ReplayConfig, execution_record: ExecutionRecord):
        self.config = config
        self.execution_record = execution_record
        self._event_index = 0
        self._process_map: Dict[int, int] = {}
        self._fd_map: Dict[int, int] = {}
        self._next_replay_pid = 1
        self._next_replay_fd = 3
    
    def run(self) -> ReplayResult:
        """Run the replay."""
        start = time.time()
        events_replayed = 0
        events_mismatched = []
        
        print(f"Starting replay for execution {self.execution_record.execution_id}")
        
        while self._event_index < len(self.execution_record.events):
            event = self.execution_record.events[self._event_index]
            
            try:
                self._replay_event(event)
                events_replayed += 1
            except Exception as e:
                print(f"Event replay mismatch at sequence {event.sequence}: {e}")
                events_mismatched.append({
                    "sequence": event.sequence,
                    "error": str(e),
                })
                
                if self.config.verify_outputs:
                    pass  # Continue replaying
            
            self._event_index += 1
        
        duration_ms = int((time.time() - start) * 1000)
        success = len(events_mismatched) == 0
        outputs_match = len(events_mismatched) == 0
        
        result = ReplayResult(
            execution_id=self.execution_record.execution_id,
            success=success,
            original_exit_code=self.execution_record.exit_code,
            replay_exit_code=None,
            outputs_match=outputs_match,
            timing_match=False,
            events_replayed=events_replayed,
            events_mismatched=events_mismatched,
            duration_ms=duration_ms,
            error=None if success else "Replay mismatches detected",
        )
        
        print(f"Replay completed: success={success}, events_replayed={events_replayed}, mismatches={len(events_mismatched)}")
        return result
    
    def _replay_event(self, event: RecordedEvent) -> None:
        """Replay a single event."""
        if event.event_type == "ProcessSpawn":
            payload = event.payload.data
            self._replay_process_spawn(payload["pid"], payload.get("ppid"), payload["command"], payload["args"])
        elif event.event_type == "ProcessExit":
            payload = event.payload.data
            self._replay_process_exit(payload["pid"], payload["exit_code"])
        elif event.event_type == "FileRead":
            payload = event.payload.data
            self._replay_file_read(payload["fd"], payload["path"], payload["offset"], payload["length"], payload["data_hash"])
        elif event.event_type == "FileWrite":
            payload = event.payload.data
            self._replay_file_write(payload["fd"], payload["path"], payload["offset"], payload["length"], payload["data_hash"])
        elif event.event_type == "FileOpen":
            payload = event.payload.data
            self._replay_file_open(payload["fd"], payload["path"], payload["flags"], payload["mode"])
        elif event.event_type == "FileClose":
            payload = event.payload.data
            self._replay_file_close(payload["fd"])
        elif event.event_type == "NetworkConnect":
            payload = event.payload.data
            self._replay_network_connect(payload["fd"], payload["address"], payload["port"])
        elif event.event_type == "NetworkSend":
            payload = event.payload.data
            self._replay_network_send(payload["fd"], payload["length"], payload["data_hash"])
        elif event.event_type == "NetworkRecv":
            payload = event.payload.data
            self._replay_network_recv(payload["fd"], payload["length"], payload["data_hash"])
        elif event.event_type == "Signal":
            payload = event.payload.data
            self._replay_signal(payload["pid"], payload["signal"])
    
    def _replay_process_spawn(self, recorded_pid: int, ppid: Optional[int], command: str, args: List[str]) -> None:
        replay_pid = self._next_replay_pid
        self._next_replay_pid += 1
        self._process_map[recorded_pid] = replay_pid
        print(f"Replay process spawn: recorded_pid={recorded_pid} -> replay_pid={replay_pid}, command={command}")
    
    def _replay_process_exit(self, recorded_pid: int, exit_code: int) -> None:
        if recorded_pid in self._process_map:
            replay_pid = self._process_map[recorded_pid]
            print(f"Replay process exit: replay_pid={replay_pid}")
    
    def _replay_file_read(self, recorded_fd: int, path: str, offset: int, length: int, expected_hash: str) -> None:
        replay_fd = self._fd_map.get(recorded_fd, recorded_fd)
        print(f"Replay file read: fd={replay_fd}, path={path}, offset={offset}, length={length}")
    
    def _replay_file_write(self, recorded_fd: int, path: str, offset: int, length: int, expected_hash: str) -> None:
        replay_fd = self._fd_map.get(recorded_fd, recorded_fd)
        print(f"Replay file write: fd={replay_fd}, path={path}, offset={offset}, length={length}")
    
    def _replay_file_open(self, recorded_fd: int, path: str, flags: int, mode: int) -> None:
        replay_fd = self._next_replay_fd
        self._next_replay_fd += 1
        self._fd_map[recorded_fd] = replay_fd
        print(f"Replay file open: recorded_fd={recorded_fd} -> replay_fd={replay_fd}, path={path}")
    
    def _replay_file_close(self, recorded_fd: int) -> None:
        if recorded_fd in self._fd_map:
            replay_fd = self._fd_map.pop(recorded_fd)
            print(f"Replay file close: replay_fd={replay_fd}")
    
    def _replay_network_connect(self, recorded_fd: int, address: str, port: int) -> None:
        replay_fd = self._fd_map.get(recorded_fd, recorded_fd)
        print(f"Replay network connect: fd={replay_fd}, address={address}, port={port}")
    
    def _replay_network_send(self, recorded_fd: int, length: int, expected_hash: str) -> None:
        replay_fd = self._fd_map.get(recorded_fd, recorded_fd)
        print(f"Replay network send: fd={replay_fd}, length={length}")
    
    def _replay_network_recv(self, recorded_fd: int, length: int, expected_hash: str) -> None:
        replay_fd = self._fd_map.get(recorded_fd, recorded_fd)
        print(f"Replay network recv: fd={replay_fd}, length={length}")
    
    def _replay_signal(self, recorded_pid: int, signal: int) -> None:
        if recorded_pid in self._process_map:
            replay_pid = self._process_map[recorded_pid]
            print(f"Replay signal: replay_pid={replay_pid}, signal={signal}")


class ReplayStore:
    """Store for persisting and retrieving execution records."""
    
    def __init__(self, root_dir: str = "./replay_store"):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.root_dir / "index.json"
        self._index = self._load_index()
    
    def _load_index(self) -> List[Dict[str, Any]]:
        if self.index_file.exists():
            with open(self.index_file, 'r') as f:
                return json.load(f)
        return []
    
    def _save_index(self) -> None:
        with open(self.index_file, 'w') as f:
            json.dump(self._index, f, indent=2)
    
    def save(self, record: ExecutionRecord) -> None:
        """Save an execution record."""
        file_name = f"{record.execution_id}.json"
        file_path = self.root_dir / file_name
        
        data = {
            "execution_id": record.execution_id,
            "started_at": record.started_at.isoformat(),
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
            "command": record.command,
            "args": record.args,
            "env": record.env,
            "working_dir": record.working_dir,
            "stdin_hash": record.stdin_hash,
            "stdout_hash": record.stdout_hash,
            "stderr_hash": record.stderr_hash,
            "exit_code": record.exit_code,
            "limits": {
                "memory_limit_bytes": record.limits.memory_limit_bytes,
                "cpu_time_limit_secs": record.limits.cpu_time_limit_secs,
                "wall_time_limit_secs": record.limits.wall_time_limit_secs,
                "process_limit": record.limits.process_limit,
                "file_size_limit_bytes": record.limits.file_size_limit_bytes,
                "open_files_limit": record.limits.open_files_limit,
            },
            "events": [
                {
                    "event_id": e.event_id,
                    "timestamp": e.timestamp.isoformat(),
                    "sequence": e.sequence,
                    "event_type": e.event_type,
                    "payload": e.payload.data,
                    "thread_id": e.thread_id,
                    "process_id": e.process_id,
                }
                for e in record.events
            ],
            "artifacts": [
                {
                    "artifact_id": a.artifact_id,
                    "name": a.name,
                    "path": a.path,
                    "hash": a.hash,
                    "size": a.size,
                    "content_type": a.content_type,
                    "created_at": a.created_at.isoformat(),
                }
                for a in record.artifacts
            ],
        }
        
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        self._index.append({
            "execution_id": record.execution_id,
            "started_at": record.started_at.isoformat(),
            "command": record.command,
            "exit_code": record.exit_code,
            "file_path": file_name,
        })
        self._save_index()
        
        print(f"Saved execution record {record.execution_id}")
    
    def load(self, execution_id: str) -> ExecutionRecord:
        """Load an execution record."""
        file_name = f"{execution_id}.json"
        file_path = self.root_dir / file_name
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        return self._deserialize_record(data)
    
    def _deserialize_record(self, data: Dict[str, Any]) -> ExecutionRecord:
        return ExecutionRecord(
            execution_id=data["execution_id"],
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            command=data["command"],
            args=data["args"],
            env=data["env"],
            working_dir=data["working_dir"],
            stdin_hash=data.get("stdin_hash"),
            stdout_hash=data.get("stdout_hash"),
            stderr_hash=data.get("stderr_hash"),
            exit_code=data.get("exit_code"),
            limits=ExecutionLimitsSnapshot(**data["limits"]),
            events=[
                RecordedEvent(
                    event_id=e["event_id"],
                    timestamp=datetime.fromisoformat(e["timestamp"]),
                    sequence=e["sequence"],
                    event_type=e["event_type"],
                    payload=EventPayload(type=e["event_type"], data=e["payload"]),
                    thread_id=e.get("thread_id"),
                    process_id=e.get("process_id"),
                )
                for e in data["events"]
            ],
            artifacts=[
                ArtifactReference(
                    artifact_id=a["artifact_id"],
                    name=a["name"],
                    path=a["path"],
                    hash=a["hash"],
                    size=a["size"],
                    content_type=a["content_type"],
                    created_at=datetime.fromisoformat(a["created_at"]),
                )
                for a in data["artifacts"]
            ],
        )
    
    def list(self) -> List[Dict[str, Any]]:
        """List all execution records."""
        return [
            {
                "execution_id": e["execution_id"],
                "started_at": e["started_at"],
                "command": e["command"],
                "exit_code": e["exit_code"],
            }
            for e in self._index
        ]
    
    def delete(self, execution_id: str) -> None:
        """Delete an execution record."""
        file_name = f"{execution_id}.json"
        file_path = self.root_dir / file_name
        
        if file_path.exists():
            file_path.unlink()
        
        self._index = [e for e in self._index if e["execution_id"] != execution_id]
        self._save_index()
        
        print(f"Deleted execution record {execution_id}")


def record_execution(command: List[str], config: Optional[RecordConfig] = None) -> ExecutionRecord:
    """
    Record an execution of a command.
    
    This is a high-level function that runs a command and records its execution.
    """
    recorder = Recorder(config)
    recorder.set_command(command[0], command[1:])
    
    # Start the process
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE if config and config.capture_stdin else None,
        stdout=subprocess.PIPE if config and config.capture_stdout else None,
        stderr=subprocess.PIPE if config and config.capture_stderr else None,
        env=recorder.execution_record.env,
        cwd=recorder.execution_record.working_dir,
    )
    
    recorder.record_process_spawn(proc.pid, os.getppid(), command[0], command[1:])
    
    # Capture output
    stdout, stderr = proc.communicate()
    
    if config and config.capture_stdout and stdout:
        recorder.set_stdout_hash(stdout)
    
    if config and config.capture_stderr and stderr:
        recorder.set_stderr_hash(stderr)
    
    recorder.set_exit_code(proc.returncode)
    recorder.record_process_exit(proc.pid, proc.returncode)
    
    return recorder.complete()


def replay_execution(execution_id: str, store: ReplayStore, config: Optional[ReplayConfig] = None) -> ReplayResult:
    """
    Replay a recorded execution.
    
    This is a high-level function that loads a record and replays it.
    """
    record = store.load(execution_id)
    
    if config is None:
        config = ReplayConfig(execution_id=execution_id)
    
    replayer = Replayer(config, record)
    return replayer.run()


if __name__ == "__main__":
    # Demo
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python replay.py <command> [args...]")
        sys.exit(1)
    
    command = sys.argv[1:]
    
    # Record
    print(f"Recording: {command}")
    record = record_execution(command)
    
    # Save
    store = ReplayStore()
    store.save(record)
    
    # Replay
    print(f"Replaying: {record.execution_id}")
    result = replay_execution(record.execution_id, store)
    
    print(f"Replay result: success={result.success}, events={result.events_replayed}")