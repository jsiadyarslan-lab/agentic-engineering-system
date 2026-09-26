//! Core types for deterministic replay

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;
use chrono::{DateTime, Utc};

/// Unique identifier for an execution
pub type ExecutionId = Uuid;

/// Unique identifier for a recorded event
pub type EventId = Uuid;

/// Execution record containing all information needed for replay
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionRecord {
    pub execution_id: ExecutionId,
    pub started_at: DateTime<Utc>,
    pub completed_at: Option<DateTime<Utc>>,
    pub command: String,
    pub args: Vec<String>,
    pub env: HashMap<String, String>,
    pub working_dir: String,
    pub stdin_hash: Option<String>,
    pub stdout_hash: Option<String>,
    pub stderr_hash: Option<String>,
    pub exit_code: Option<i32>,
    pub limits: ExecutionLimitsSnapshot,
    pub events: Vec<RecordedEvent>,
    pub artifacts: Vec<ArtifactReference>,
}

/// Snapshot of execution limits at record time
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionLimitsSnapshot {
    pub memory_limit_bytes: Option<u64>,
    pub cpu_time_limit_secs: Option<u64>,
    pub wall_time_limit_secs: Option<u64>,
    pub process_limit: Option<u32>,
    pub file_size_limit_bytes: Option<u64>,
    pub open_files_limit: Option<u32>,
}

/// Individual recorded event
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecordedEvent {
    pub event_id: EventId,
    pub timestamp: DateTime<Utc>,
    pub sequence: u64,
    pub event_type: EventType,
    pub payload: EventPayload,
    pub thread_id: Option<u64>,
    pub process_id: Option<u32>,
}

/// Type of recorded event
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum EventType {
    /// Process spawn
    ProcessSpawn,
    /// Process exit
    ProcessExit,
    /// File read
    FileRead,
    /// File write
    FileWrite,
    /// File open
    FileOpen,
    /// File close
    FileClose,
    /// Network connect
    NetworkConnect,
    /// Network accept
    NetworkAccept,
    /// Network send
    NetworkSend,
    /// Network recv
    NetworkRecv,
    /// Signal received
    Signal,
    /// Syscall entry
    SyscallEnter,
    /// Syscall exit
    SyscallExit,
    /// Memory map
    Mmap,
    /// Memory unmap
    Munmap,
    /// Custom event
    Custom,
}

/// Event payload - varies by event type
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum EventPayload {
    ProcessSpawn {
        pid: u32,
        ppid: Option<u32>,
        command: String,
        args: Vec<String>,
    },
    ProcessExit {
        pid: u32,
        exit_code: i32,
    },
    FileRead {
        fd: i32,
        path: String,
        offset: u64,
        length: usize,
        data_hash: String,
    },
    FileWrite {
        fd: i32,
        path: String,
        offset: u64,
        length: usize,
        data_hash: String,
    },
    FileOpen {
        fd: i32,
        path: String,
        flags: i32,
        mode: u32,
    },
    FileClose {
        fd: i32,
    },
    NetworkConnect {
        fd: i32,
        address: String,
        port: u16,
    },
    NetworkAccept {
        fd: i32,
        client_address: String,
        client_port: u16,
    },
    NetworkSend {
        fd: i32,
        length: usize,
        data_hash: String,
    },
    NetworkRecv {
        fd: i32,
        length: usize,
        data_hash: String,
    },
    Signal {
        pid: u32,
        signal: i32,
    },
    SyscallEnter {
        syscall: i64,
        args: [u64; 6],
    },
    SyscallExit {
        syscall: i64,
        result: i64,
    },
    Mmap {
        addr: u64,
        length: usize,
        prot: i32,
        flags: i32,
        fd: i32,
        offset: u64,
    },
    Munmap {
        addr: u64,
        length: usize,
    },
    Custom {
        name: String,
        data: serde_json::Value,
    },
}

/// Reference to an artifact produced during execution
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArtifactReference {
    pub artifact_id: Uuid,
    pub name: String,
    pub path: String,
    pub hash: String,
    pub size: u64,
    pub content_type: String,
    pub created_at: DateTime<Utc>,
}

/// Configuration for recording
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecordConfig {
    pub execution_id: ExecutionId,
    pub capture_stdin: bool,
    pub capture_stdout: bool,
    pub capture_stderr: bool,
    pub capture_syscalls: bool,
    pub capture_file_io: bool,
    pub capture_network: bool,
    pub capture_signals: bool,
    pub capture_memory: bool,
    pub max_events: Option<usize>,
    pub event_buffer_size: usize,
    pub flush_interval_ms: u64,
}

impl Default for RecordConfig {
    fn default() -> Self {
        Self {
            execution_id: Uuid::new_v4(),
            capture_stdin: true,
            capture_stdout: true,
            capture_stderr: true,
            capture_syscalls: false, // High overhead
            capture_file_io: true,
            capture_network: true,
            capture_signals: true,
            capture_memory: false, // High overhead
            max_events: Some(1_000_000),
            event_buffer_size: 10000,
            flush_interval_ms: 1000,
        }
    }
}

/// Configuration for replay
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReplayConfig {
    pub execution_id: ExecutionId,
    pub verify_outputs: bool,
    pub verify_timing: bool,
    pub max_time_dilation: f64,
    pub deterministic_syscalls: bool,
    pub inject_failures: Vec<FailureInjection>,
}

impl Default for ReplayConfig {
    fn default() -> Self {
        Self {
            execution_id: Uuid::nil(),
            verify_outputs: true,
            verify_timing: false, // Timing is hard to make deterministic
            max_time_dilation: 10.0,
            deterministic_syscalls: true,
            inject_failures: Vec::new(),
        }
    }
}

/// Failure injection for chaos testing during replay
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FailureInjection {
    pub event_sequence: u64,
    pub failure_type: FailureType,
    pub probability: f64,
}

/// Types of failures that can be injected
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum FailureType {
    IoError(String),
    NetworkError(String),
    Timeout,
    Signal(i32),
    ResourceExhausted(String),
}

/// Result of a replay operation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReplayResult {
    pub execution_id: ExecutionId,
    pub success: bool,
    pub original_exit_code: Option<i32>,
    pub replay_exit_code: Option<i32>,
    pub outputs_match: bool,
    pub timing_match: bool,
    pub events_replayed: usize,
    pub events_mismatched: Vec<EventMismatch>,
    pub duration_ms: u64,
    pub error: Option<String>,
}

/// Mismatch between recorded and replayed event
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EventMismatch {
    pub sequence: u64,
    pub expected: RecordedEvent,
    pub actual: RecordedEvent,
    pub diff: String,
}