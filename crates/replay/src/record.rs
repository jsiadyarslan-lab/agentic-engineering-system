//! Execution recorder

use crate::types::*;
use anyhow::Result;
use std::sync::Arc;
use tokio::sync::mpsc;
use tracing::{debug, info};

/// Recorder for capturing execution events
pub struct Recorder {
    config: RecordConfig,
    execution_record: ExecutionRecord,
    event_sender: mpsc::UnboundedSender<RecordedEvent>,
    event_receiver: mpsc::UnboundedReceiver<RecordedEvent>,
    sequence: u64,
    flushed: bool,
}

impl Recorder {
    /// Create a new recorder
    pub fn new(config: RecordConfig) -> Self {
        let (sender, receiver) = mpsc::unbounded_channel();
        
        let execution_record = ExecutionRecord {
            execution_id: config.execution_id,
            started_at: Utc::now(),
            completed_at: None,
            command: String::new(),
            args: Vec::new(),
            env: HashMap::new(),
            working_dir: std::env::current_dir()
                .unwrap_or_default()
                .to_string_lossy()
                .to_string(),
            stdin_hash: None,
            stdout_hash: None,
            stderr_hash: None,
            exit_code: None,
            limits: ExecutionLimitsSnapshot::default(),
            events: Vec::new(),
            artifacts: Vec::new(),
        };

        Self {
            config,
            execution_record,
            event_sender: sender,
            event_receiver: receiver,
            sequence: 0,
            flushed: false,
        }
    }

    /// Set the command being executed
    pub fn set_command(&mut self, command: String, args: Vec<String>) {
        self.execution_record.command = command;
        self.execution_record.args = args;
    }

    /// Set environment variables
    pub fn set_env(&mut self, env: HashMap<String, String>) {
        self.execution_record.env = env;
    }

    /// Set working directory
    pub fn set_working_dir(&mut self, dir: String) {
        self.execution_record.working_dir = dir;
    }

    /// Set execution limits snapshot
    pub fn set_limits(&mut self, limits: ExecutionLimitsSnapshot) {
        self.execution_record.limits = limits;
    }

    /// Record an event
    pub fn record_event(&mut self, event_type: EventType, payload: EventPayload) -> Result<()> {
        if let Some(max) = self.config.max_events {
            if self.sequence >= max as u64 {
                return Err(anyhow::anyhow!("Max events reached"));
            }
        }

        let event = RecordedEvent {
            event_id: Uuid::new_v4(),
            timestamp: Utc::now(),
            sequence: self.sequence,
            event_type,
            payload,
            thread_id: None, // Would be filled by platform-specific code
            process_id: None, // Would be filled by platform-specific code
        };

        self.sequence += 1;
        self.event_sender.send(event)?;

        Ok(())
    }

    /// Record process spawn
    pub fn record_process_spawn(&mut self, pid: u32, ppid: Option<u32>, command: String, args: Vec<String>) -> Result<()> {
        self.record_event(EventType::ProcessSpawn, EventPayload::ProcessSpawn {
            pid,
            ppid,
            command,
            args,
        })
    }

    /// Record process exit
    pub fn record_process_exit(&mut self, pid: u32, exit_code: i32) -> Result<()> {
        self.record_event(EventType::ProcessExit, EventPayload::ProcessExit {
            pid,
            exit_code,
        })
    }

    /// Record file read
    pub fn record_file_read(&mut self, fd: i32, path: String, offset: u64, length: usize, data_hash: String) -> Result<()> {
        if !self.config.capture_file_io {
            return Ok(());
        }
        self.record_event(EventType::FileRead, EventPayload::FileRead {
            fd,
            path,
            offset,
            length,
            data_hash,
        })
    }

    /// Record file write
    pub fn record_file_write(&mut self, fd: i32, path: String, offset: u64, length: usize, data_hash: String) -> Result<()> {
        if !self.config.capture_file_io {
            return Ok(());
        }
        self.record_event(EventType::FileWrite, EventPayload::FileWrite {
            fd,
            path,
            offset,
            length,
            data_hash,
        })
    }

    /// Record file open
    pub fn record_file_open(&mut self, fd: i32, path: String, flags: i32, mode: u32) -> Result<()> {
        if !self.config.capture_file_io {
            return Ok(());
        }
        self.record_event(EventType::FileOpen, EventPayload::FileOpen {
            fd,
            path,
            flags,
            mode,
        })
    }

    /// Record file close
    pub fn record_file_close(&mut self, fd: i32) -> Result<()> {
        if !self.config.capture_file_io {
            return Ok(());
        }
        self.record_event(EventType::FileClose, EventPayload::FileClose { fd })
    }

    /// Record network connect
    pub fn record_network_connect(&mut self, fd: i32, address: String, port: u16) -> Result<()> {
        if !self.config.capture_network {
            return Ok(());
        }
        self.record_event(EventType::NetworkConnect, EventPayload::NetworkConnect {
            fd,
            address,
            port,
        })
    }

    /// Record network send
    pub fn record_network_send(&mut self, fd: i32, length: usize, data_hash: String) -> Result<()> {
        if !self.config.capture_network {
            return Ok(());
        }
        self.record_event(EventType::NetworkSend, EventPayload::NetworkSend {
            fd,
            length,
            data_hash,
        })
    }

    /// Record network receive
    pub fn record_network_recv(&mut self, fd: i32, length: usize, data_hash: String) -> Result<()> {
        if !self.config.capture_network {
            return Ok(());
        }
        self.record_event(EventType::NetworkRecv, EventPayload::NetworkRecv {
            fd,
            length,
            data_hash,
        })
    }

    /// Record signal
    pub fn record_signal(&mut self, pid: u32, signal: i32) -> Result<()> {
        if !self.config.capture_signals {
            return Ok(());
        }
        self.record_event(EventType::Signal, EventPayload::Signal { pid, signal })
    }

    /// Add an artifact reference
    pub fn add_artifact(&mut self, artifact: ArtifactReference) {
        self.execution_record.artifacts.push(artifact);
    }

    /// Set stdin hash
    pub fn set_stdin_hash(&mut self, hash: String) {
        self.execution_record.stdin_hash = Some(hash);
    }

    /// Set stdout hash
    pub fn set_stdout_hash(&mut self, hash: String) {
        self.execution_record.stdout_hash = Some(hash);
    }

    /// Set stderr hash
    pub fn set_stderr_hash(&mut self, hash: String) {
        self.execution_record.stderr_hash = Some(hash);
    }

    /// Set exit code
    pub fn set_exit_code(&mut self, code: i32) {
        self.execution_record.exit_code = Some(code);
    }

    /// Flush pending events to the record
    pub async fn flush(&mut self) -> Result<()> {
        while let Ok(event) = self.event_receiver.try_recv() {
            self.execution_record.events.push(event);
        }
        self.flushed = true;
        Ok(())
    }

    /// Complete the recording and return the execution record
    pub async fn complete(mut self) -> Result<ExecutionRecord> {
        self.flush().await?;
        self.execution_record.completed_at = Some(Utc::now());
        info!("Recording completed for execution {}", self.execution_record.execution_id);
        Ok(self.execution_record)
    }

    /// Get a handle to the event sender for use in callbacks
    pub fn event_sender(&self) -> mpsc::UnboundedSender<RecordedEvent> {
        self.event_sender.clone()
    }
}

impl Default for ExecutionLimitsSnapshot {
    fn default() -> Self {
        Self {
            memory_limit_bytes: None,
            cpu_time_limit_secs: None,
            wall_time_limit_secs: None,
            process_limit: None,
            file_size_limit_bytes: None,
            open_files_limit: None,
        }
    }
}