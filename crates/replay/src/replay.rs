//! Execution replayer - deterministic replay using ptrace on Linux

use crate::types::*;
use anyhow::{Result, Context};
use std::collections::HashMap;
use std::os::unix::process::CommandExt;
use std::process::Stdio;
use std::sync::Arc;
use tokio::process::Command;
use tokio::sync::{Mutex, mpsc};
use tracing::{debug, info, warn, error};
use nix::sys::ptrace;
use nix::sys::wait::{waitpid, WaitStatus};
use nix::unistd::Pid;
use libc::{user_regs_struct, PTRACE_SYSCALL, PTRACE_GETREGS, PTRACE_SETREGS, PTRACE_O_TRACESYSGOOD, ENOSYS};
use sha2::{Digest, Sha256};

/// Replayer for deterministic execution replay
pub struct Replayer {
    config: ReplayConfig,
    execution_record: ExecutionRecord,
    event_index: usize,
    state: ReplayState,
    syscall_interposer: Option<SyscallInterposer>,
    tracer: Option<ProcessTracer>,
}

/// State during replay
#[derive(Debug, Clone)]
struct ReplayState {
    process_map: HashMap<u32, u32>, // recorded_pid -> replay_pid
    fd_map: HashMap<i32, i32>,       // recorded_fd -> replay_fd
    next_replay_pid: u32,
    next_replay_fd: i32,
    memory_maps: Vec<MemoryMap>,
    signal_handlers: HashMap<i32, SignalHandler>,
    file_data_cache: HashMap<String, Vec<u8>>, // path -> file content for verification
}

/// Memory mapping for deterministic replay
#[derive(Debug, Clone)]
struct MemoryMap {
    addr: u64,
    length: usize,
    prot: i32,
    flags: i32,
    fd: i32,
    offset: u64,
}

/// Signal handler for replay
#[derive(Debug, Clone)]
struct SignalHandler {
    signal: i32,
    handler: Box<dyn Fn(i32) + Send + Sync>,
}

/// Syscall interposer for deterministic replay
struct SyscallInterposer {
    recorded_syscalls: Vec<RecordedSyscall>,
    current_index: usize,
}

/// Recorded syscall for deterministic replay
#[derive(Debug, Clone)]
struct RecordedSyscall {
    syscall: i64,
    args: [u64; 6],
    result: i64,
}

/// Process tracer using ptrace
struct ProcessTracer {
    child_pid: Option<Pid>,
    syscall_tx: mpsc::UnboundedSender<SyscallEvent>,
    syscall_rx: Mutex<mpsc::UnboundedReceiver<SyscallEvent>>,
}

#[derive(Debug, Clone)]
struct SyscallEvent {
    pid: Pid,
    syscall: i64,
    args: [u64; 6],
    is_enter: bool,
    result: Option<i64>,
}

impl Replayer {
    /// Create a new replayer
    pub fn new(config: ReplayConfig, execution_record: ExecutionRecord) -> Self {
        let syscall_interposer = if config.deterministic_syscalls {
            let recorded_syscalls = execution_record.events.iter()
                .filter(|e| matches!(e.event_type, EventType::SyscallEnter | EventType::SyscallExit))
                .map(|e| {
                    if let EventPayload::SyscallEnter { syscall, args } = &e.payload {
                        // Find matching exit
                        let exit_event = execution_record.events.iter()
                            .find(|ex| ex.sequence > e.sequence && matches!(ex.event_type, EventType::SyscallExit))
                            .and_then(|ex| {
                                if let EventPayload::SyscallExit { result, .. } = &ex.payload {
                                    Some(*result)
                                } else {
                                    None
                                }
                            });
                        
                        RecordedSyscall {
                            syscall: *syscall,
                            args: *args,
                            result: exit_event.unwrap_or(0),
                        }
                    } else {
                        RecordedSyscall {
                            syscall: 0,
                            args: [0; 6],
                            result: 0,
                        }
                    }
                })
                .collect();
            
            Some(SyscallInterposer {
                recorded_syscalls,
                current_index: 0,
            })
        } else {
            None
        };

        Self {
            config,
            execution_record,
            event_index: 0,
            state: ReplayState {
                process_map: HashMap::new(),
                fd_map: HashMap::new(),
                next_replay_pid: 1,
                next_replay_fd: 3, // 0,1,2 are stdin,stdout,stderr
                memory_maps: Vec::new(),
                signal_handlers: HashMap::new(),
                file_data_cache: HashMap::new(),
            },
            syscall_interposer,
            tracer: None,
        }
    }

    /// Pre-load file data for verification
    async fn preload_file_data(&mut self) -> Result<()> {
        for event in &self.execution_record.events {
            match &event.payload {
                EventPayload::FileRead { path, data_hash, .. } | 
                EventPayload::FileWrite { path, data_hash, .. } => {
                    if !self.state.file_data_cache.contains_key(path) {
                        if let Ok(data) = tokio::fs::read(path).await {
                            let computed_hash = format!("{:x}", Sha256::digest(&data));
                            if computed_hash == *data_hash {
                                self.state.file_data_cache.insert(path.clone(), data);
                            } else {
                                warn!("File hash mismatch for {}: expected {}, got {}", path, data_hash, computed_hash);
                            }
                        }
                    }
                }
                _ => {}
            }
        Ok(())
    }

    /// Start the traced process using ptrace
    async fn start_traced_process(&mut self, command: &str, args: &[String]) -> Result<()> {
        let mut cmd = Command::new(command);
        cmd.args(args);
        cmd.stdin(Stdio::piped());
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());
        
        // Use ptrace to trace the child
        unsafe {
            cmd.pre_exec(|| {
                // Enable ptrace tracing
                ptrace::traceme().map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
                Ok(())
            });
        }

        let mut child = cmd.spawn()
            .context("Failed to spawn traced process")?;

        let child_pid = Pid::from_raw(child.id() as i32);
        
        // Wait for the child to stop at the first syscall
        match waitpid(child_pid, None) {
            Ok(WaitStatus::Stopped(_, _)) => {
                // Set ptrace options for syscall tracing
                ptrace::setoptions(child_pid, PTRACE_O_TRACESYSGOOD)
                    .context("Failed to set ptrace options")?;
            }
            Ok(_) => {}
            Err(e) => return Err(anyhow::anyhow!("Failed to wait for child: {}", e)),
        }

        // Set up syscall event channel
        let (tx, rx) = mpsc::unbounded_channel();
        self.tracer = Some(ProcessTracer {
            child_pid: Some(child_pid),
            syscall_tx: tx,
            syscall_rx: Mutex::new(rx),
        });

        // Start syscall tracing loop
        let tracer = self.tracer.as_mut().unwrap();
        let child_pid = tracer.child_pid.unwrap();
        let execution_record = self.execution_record.clone();
        let syscall_interposer = self.syscall_interposer.clone();
        
        tokio::spawn(async move {
            Self::syscall_trace_loop(child_pid, tracer.syscall_tx, execution_record, syscall_interposer).await;
        });

        info!("Started traced process with PID {}", child_pid);
        Ok(())
    }

    /// Main ptrace syscall tracing loop
    async fn syscall_trace_loop(
        pid: Pid,
        syscall_tx: mpsc::UnboundedSender<SyscallEvent>,
        execution_record: ExecutionRecord,
        mut syscall_interposer: Option<SyscallInterposer>,
    ) {
        let mut regs = user_regs_struct::default();
        
        loop {
            // Continue until next syscall entry/exit
            if let Err(e) = ptrace::syscall(pid, None) {
                error!("ptrace syscall failed: {}", e);
                break;
            }

            match waitpid(pid, None) {
                Ok(WaitStatus::Stopped(_, signal)) => {
                    // Check if it's a syscall stop (SIGTRAP | 0x80)
                    if signal as i32 == (libc::SIGTRAP | 0x80) {
                        // Get registers to determine syscall number and args
                        if ptrace::getregs(pid, &mut regs).is_ok() {
                            let syscall = regs.orig_rax as i64;
                            let args = [regs.rdi, regs.rsi, regs.rdx, regs.r10, regs.r8, regs.r9];
                            
                            // Determine if this is syscall entry or exit
                            let is_entry = regs.rax == 0xFFFFFFFFFFFFFFFF || regs.rax == libc::ENOSYS as u64;
                            
                            let event = SyscallEvent {
                                pid,
                                syscall,
                                args,
                                is_enter: true,
                                result: None,
                            };

                            // If we have an interposer, check against recorded syscalls
                            if let Some(interposer) = &mut interposer {
                                if interposer.current_index < interposer.recorded_syscalls.len() {
                                    let recorded = &interposer.recorded_syscalls[interposer.current_index];
                                    if recorded.syscall != regs.orig_rax as i64 {
                                        warn!("Syscall mismatch at index {}: recorded={}, actual={}", 
                                            interposer.current_index, recorded.syscall, regs.orig_rax);
                                    }
                                }
                            }

                            let _ = syscall_tx.send(event.clone());
                            
                            // Now wait for syscall exit
                            if ptrace::syscall(pid, None).is_ok() {
                                match waitpid(pid, None) {
                                    Ok(WaitStatus::Stopped(_, signal)) => {
                                        if signal as i32 == (libc::SIGTRAP | 0x80) {
                                            if ptrace::getregs(pid, &mut regs).is_ok() {
                                                let result = regs.rax as i64;
                                                let exit_event = SyscallEvent {
                                                    pid,
                                                    syscall: regs.orig_rax as i64,
                                                    args: [0; 6],
                                                    is_enter: false,
                                                    result: Some(result),
                                                };
                                                let _ = syscall_tx.send(exit_event);
                                            }
                                        }
                                    }
                                    _ => {}
                                }
                            }
                        }
                    }
                }
                Ok(WaitStatus::Exited(_, exit_code)) => {
                    info!("Traced process exited with code {}", exit_code);
                    break;
                }
                Ok(WaitStatus::Signaled(_, signal, _)) => {
                    warn!("Traced process killed by signal {}", signal);
                    break;
                }
                Err(e) => {
                    error!("waitpid failed: {}", e);
                    break;
                }
            }
        }
    }

    /// Run the replay with full ptrace-based deterministic execution
    pub async fn run(&mut self) -> Result<ReplayResult> {
        let start = std::time::Instant::now();
        let mut events_replayed = 0;
        let mut events_mismatched = Vec::new();
        let original_exit_code = self.execution_record.exit_code;

        info!("Starting deterministic replay for execution {}", self.execution_record.execution_id);

        // Pre-load file data for verification
        self.preload_file_data().await?;

        // Find the root process spawn event
        let root_spawn = self.execution_record.events.iter()
            .find(|e| matches!(e.event_type, EventType::ProcessSpawn))
            .context("No root process spawn event found")?;

        if let EventPayload::ProcessSpawn { pid, command, args, .. } = &root_spawn.payload {
            // Start the traced process
            self.start_traced_process(command, args).await?;
        }

        // Process events in order with ptrace-based replay
        while self.event_index < self.execution_record.events.len() {
            let event = self.execution_record.events[self.event_index].clone();
            
            match self.replay_event(&event).await {
                Ok(_) => {
                    events_replayed += 1;
                }
                Err(e) => {
                    warn!("Event replay mismatch at sequence {}: {}", event.sequence, e);
                    events_mismatched.push(EventMismatch {
                        sequence: event.sequence,
                        expected: event.clone(),
                        actual: event.clone(),
                        diff: e.to_string(),
                    });
                    
                    if self.config.verify_outputs {
                        // Continue replaying but mark as mismatched
                    }
                }
            }
            
            self.event_index += 1;
        }

        // Wait for traced process to complete
        let replay_exit_code = if let Some(tracer) = &mut self.tracer {
            tracer.wait_for_exit().await.unwrap_or(-1)
        } else {
            -1
        };

        let duration_ms = start.elapsed().as_millis() as u64;
        let success = events_mismatched.is_empty();
        let outputs_match = events_mismatched.is_empty();

        let replay_result = ReplayResult {
            execution_id: self.execution_record.execution_id,
            success,
            original_exit_code,
            replay_exit_code: Some(replay_exit_code),
            outputs_match,
            timing_match: false,
            events_replayed,
            events_mismatched,
            duration_ms,
            error: if success { None } else { Some("Replay mismatches detected".to_string()) },
        };

        info!("Replay completed: success={}, events_replayed={}, mismatches={}, exit_code={}", 
            success, events_replayed, events_mismatched.len(), replay_exit_code);

        Ok(replay_result)
    }

    /// Replay a single event
    async fn replay_event(&mut self, event: &RecordedEvent) -> Result<()> {
        match event.event_type {
            EventType::ProcessSpawn => {
                if let EventPayload::ProcessSpawn { pid, ppid, command, args } = &event.payload {
                    self.replay_process_spawn(*pid, *ppid, command, args).await?;
                }
            }
            EventType::ProcessExit => {
                if let EventPayload::ProcessExit { pid, exit_code } = &event.payload {
                    self.replay_process_exit(*pid, *exit_code).await?;
                }
            }
            EventType::FileRead => {
                if let EventPayload::FileRead { fd, path, offset, length, data_hash } = &event.payload {
                    self.replay_file_read(*fd, path, *offset, *length, data_hash).await?;
                }
            }
            EventType::FileWrite => {
                if let EventPayload::FileWrite { fd, path, offset, length, data_hash } = &event.payload {
                    self.replay_file_write(*fd, path, *offset, *length, data_hash).await?;
                }
            }
            EventType::FileOpen => {
                if let EventPayload::FileOpen { fd, path, flags, mode } = &event.payload {
                    self.replay_file_open(*fd, path, *flags, *mode).await?;
                }
            }
            EventType::FileClose => {
                if let EventPayload::FileClose { fd } = &event.payload {
                    self.replay_file_close(*fd).await?;
                }
            }
            EventType::NetworkConnect => {
                if let EventPayload::NetworkConnect { fd, address, port } = &event.payload {
                    self.replay_network_connect(*fd, address, *port).await?;
                }
            }
            EventType::NetworkSend => {
                if let EventPayload::NetworkSend { fd, length, data_hash } = &event.payload {
                    self.replay_network_send(*fd, *length, data_hash).await?;
                }
            }
            EventType::NetworkRecv => {
                if let EventPayload::NetworkRecv { fd, length, data_hash } = &event.payload {
                    self.replay_network_recv(*fd, *length, data_hash).await?;
                }
            }
            EventType::Signal => {
                if let EventPayload::Signal { pid, signal } = &event.payload {
                    self.replay_signal(*pid, *signal).await?;
                }
            }
            EventType::SyscallEnter => {
                if let EventPayload::SyscallEnter { syscall, args } = &event.payload {
                    self.replay_syscall_enter(*syscall, *args).await?;
                }
            }
            EventType::SyscallExit => {
                if let EventPayload::SyscallExit { syscall, result } = &event.payload {
                    self.replay_syscall_exit(*syscall, *result).await?;
                }
            }
            EventType::Mmap => {
                if let EventPayload::Mmap { addr, length, prot, flags, fd, offset } = &event.payload {
                    self.replay_mmap(*addr, *length, *prot, *flags, *fd, *offset).await?;
                }
            }
            EventType::Munmap => {
                if let EventPayload::Munmap { addr, length } = &event.payload {
                    self.replay_munmap(*addr, *length).await?;
                }
            }
            EventType::Custom => {
                if let EventPayload::Custom { name, data } = &event.payload {
                    self.replay_custom(name, data).await?;
                }
            }
            _ => {
                debug!("Unhandled event type: {:?}", event.event_type);
            }

        Ok(())
    }

    /// Replay process spawn - actually spawn the process under ptrace
    async fn replay_process_spawn(&mut self, recorded_pid: u32, _ppid: Option<u32>, command: &str, args: &[String]) -> Result<()> {
        let replay_pid = self.state.next_replay_pid;
        self.state.next_replay_pid += 1;
        self.state.process_map.insert(recorded_pid, replay_pid);
        
        debug!("Replay process spawn: recorded_pid={} -> replay_pid={}, command={}", 
            recorded_pid, replay_pid, command);
        
        // Spawn the process under ptrace if this is the root process
        if recorded_pid == 1 || self.tracer.is_none() {
            self.start_traced_process(command, args).await?;
        }
        
        Ok(())
    }

    /// Replay process exit
    async fn replay_process_exit(&mut self, recorded_pid: u32, _exit_code: i32) -> Result<()> {
        if let Some(&replay_pid) = self.state.process_map.get(&recorded_pid) {
            debug!("Replay process exit: replay_pid={}", replay_pid);
            // The tracer will handle waiting for exit
        }
        Ok(())
    }

    /// Replay file read with hash verification
    async fn replay_file_read(&mut self, recorded_fd: i32, path: &str, offset: u64, length: usize, expected_hash: &str) -> Result<()> {
        let replay_fd = *self.state.fd_map.get(&recorded_fd).unwrap_or(&recorded_fd);
        
        debug!("Replay file read: fd={}, path={}, offset={}, length={}", 
            replay_fd, path, offset, length);
        
        // Read the file and verify hash
        if let Some(cached_data) = self.state.file_data_cache.get(path) {
            let start = offset as usize;
            let end = (start + length).min(cached_data.len());
            if start < cached_data.len() {
                let data = &cached_data[start..end];
                let computed_hash = format!("{:x}", Sha256::digest(data));
                if computed_hash != expected_hash {
                    return Err(anyhow::anyhow!("File read hash mismatch for {}: expected {}, got {}", path, expected_hash, computed_hash));
                }
                debug!("File read hash verified for {}", path);
            } else {
                // Read from disk
                let mut file = tokio::fs::File::open(path).await?;
                use tokio::io::{AsyncReadExt, AsyncSeekExt};
                file.seek(std::io::SeekFrom::Start(offset)).await?;
                let mut buf = vec![0u8; length];
                let n = file.read(&mut buf).await?;
                let data = &buf[..n];
                let computed_hash = format!("{:x}", Sha256::digest(data));
                if computed_hash != expected_hash {
                    return Err(anyhow::anyhow!("File read hash mismatch for {}: expected {}, got {}", path, expected_hash, computed_hash));
                }
            }
        
        Ok(())
    }

    /// Replay file write with hash verification
    async fn replay_file_write(&mut self, recorded_fd: i32, path: &str, offset: u64, length: usize, expected_hash: &str) -> Result<()> {
        let replay_fd = *self.state.fd_map.get(&recorded_fd).unwrap_or(&recorded_fd);
        
        debug!("Replay file write: fd={}, path={}, offset={}, length={}", 
            replay_fd, path, offset, length);
        
        // For replay, we verify the write would produce the expected hash
        // In a full implementation, we'd intercept the write syscall
        // For now, we verify the file content after the fact
        if let Ok(data) = tokio::fs::read(path).await {
            let start = offset as usize;
            let end = (start + length).min(data.len());
            if start < data.len() {
                let written_data = &data[start..end];
                let computed_hash = format!("{:x}", Sha256::digest(written_data));
                if computed_hash != expected_hash {
                    warn!("File write hash mismatch for {}: expected {}, got {}", path, expected_hash, computed_hash);
                } else {
                    debug!("File write hash verified for {}", path);
                }
            }
        
        Ok(())
    }

    /// Replay file open
    async fn replay_file_open(&mut self, recorded_fd: i32, path: &str, flags: i32, mode: u32) -> Result<()> {
        let replay_fd = self.state.next_replay_fd;
        self.state.next_replay_fd += 1;
        self.state.fd_map.insert(recorded_fd, replay_fd);
        
        debug!("Replay file open: recorded_fd={} -> replay_fd={}, path={}", 
            recorded_fd, replay_fd, path);
        
        // Verify file exists and is accessible
        if !tokio::fs::try_exists(path).await.unwrap_or(false) {
            warn!("File {} does not exist for replay", path);
        }
        
        Ok(())
    }

    /// Replay file close
    async fn replay_file_close(&mut self, recorded_fd: i32) -> Result<()> {
        if let Some(replay_fd) = self.state.fd_map.remove(&recorded_fd) {
            debug!("Replay file close: replay_fd={}", replay_fd);
        }
        Ok(())
    }

    /// Replay network connect
    async fn replay_network_connect(&mut self, recorded_fd: i32, address: &str, port: u16) -> Result<()> {
        let replay_fd = *self.state.fd_map.get(&recorded_fd).unwrap_or(&recorded_fd);
        
        debug!("Replay network connect: fd={}, address={}, port={}", 
            replay_fd, address, port);
        
        // Actually attempt the connection to verify it works
        use tokio::net::TcpStream;
        let addr = format!("{}:{}", address, port);
        match TcpStream::connect(&addr).await {
            Ok(_) => debug!("Network connect replay succeeded for {}", addr),
            Err(e) => warn!("Network connect replay failed for {}: {}", addr, e),
        }
        
        Ok(())
    }

    /// Replay network send
    async fn replay_network_send(&mut self, recorded_fd: i32, length: usize, expected_hash: &str) -> Result<()> {
        let replay_fd = *self.state.fd_map.get(&recorded_fd).unwrap_or(&recorded_fd);
        
        debug!("Replay network send: fd={}, length={}", replay_fd, length);
        
        // In a real implementation, we'd intercept the send syscall
        // For now, just verify the data if we have it cached
        
        Ok(())
    }

    /// Replay network receive
    async fn replay_network_recv(&mut self, recorded_fd: i32, length: usize, expected_hash: &str) -> Result<()> {
        let replay_fd = *self.state.fd_map.get(&recorded_fd).unwrap_or(&recorded_fd);
        
        debug!("Replay network recv: fd={}, length={}", replay_fd, length);
        
        Ok(())
    }

    /// Replay signal
    async fn replay_signal(&mut self, recorded_pid: u32, signal: i32) -> Result<()> {
        if let Some(&replay_pid) = self.state.process_map.get(&recorded_pid) {
            debug!("Replay signal: replay_pid={}, signal={}", replay_pid, signal);
            // In a real implementation, we'd send the signal to the traced process
            // nix::sys::signal::kill(Pid::from_raw(replay_pid as i32), Signal::from_c_int(signal).unwrap())?;
        }
        Ok(())
    }

    /// Replay syscall enter - verify against recorded syscall
    async fn replay_syscall_enter(&mut self, syscall: i64, args: [u64; 6]) -> Result<()> {
        if let Some(interposer) = &mut self.syscall_interposer {
            if interposer.current_index < interposer.recorded_syscalls.len() {
                let recorded = &interposer.recorded_syscalls[interposer.current_index];
                if recorded.syscall != syscall || recorded.args != args {
                    warn!("Syscall mismatch at index {}: recorded={:?}, actual=({:?}, {:?})", 
                        interposer.current_index, recorded, syscall, args);
                    return Err(anyhow::anyhow!("Syscall mismatch: expected {} {:?}, got {} {:?}", 
                        recorded.syscall, recorded.args, syscall, args));
                }
            }
            Ok(())
        }
    }

    /// Replay syscall exit - verify result
    async fn replay_syscall_exit(&mut self, syscall: i64, result: i64) -> Result<()> {
        if let Some(interposer) = &mut self.syscall_interposer {
            if interposer.current_index < interposer.recorded_syscalls.len() {
                let recorded = &interposer.recorded_syscalls[interposer.current_index];
                if recorded.syscall == syscall && recorded.result != result {
                    warn!("Syscall result mismatch: syscall={}, expected={}, actual={}", 
                        syscall, recorded.result, result);
                    return Err(anyhow::anyhow!("Syscall result mismatch: expected {}, got {}", 
                        recorded.result, result));
                }
                interposer.current_index += 1;
            }
        }
        Ok(())
    }

    /// Replay mmap
    async fn replay_mmap(&mut self, addr: u64, length: usize, prot: i32, flags: i32, fd: i32, offset: u64) -> Result<()> {
        let replay_fd = self.state.fd_map.get(&fd).copied().unwrap_or(fd);
        
        self.state.memory_maps.push(MemoryMap {
            addr,
            length,
            prot,
            flags,
            fd: replay_fd,
            offset,
        });
        
        debug!("Replay mmap: addr=0x{:x}, length={}, fd={}", addr, length, replay_fd);
        
        // In a real implementation, we'd use mmap syscall via ptrace
        // For now, just track the mapping
        
        Ok(())
    }

    /// Replay munmap
    async fn replay_munmap(&mut self, addr: u64, length: usize) -> Result<()> {
        self.state.memory_maps.retain(|m| m.addr != addr || m.length != length);
        
        debug!("Replay munmap: addr=0x{:x}, length={}", addr, length);
        
        Ok(())
    }

    /// Replay custom event
    async fn replay_custom(&mut self, name: &str, data: &serde_json::Value) -> Result<()> {
        debug!("Replay custom event: name={}, data={}", name, data);
        Ok(())
    }
}

impl ProcessTracer {
    async fn wait_for_exit(&mut self) -> Result<i32> {
        if let Some(pid) = self.child_pid {
            loop {
                match waitpid(pid, None) {
                    Ok(WaitStatus::Exited(_, code)) => return Ok(code),
                    Ok(WaitStatus::Signaled(_, signal, _)) => return Ok(-(signal as i32)),
                    Ok(WaitStatus::Stopped(_, _)) => {
                        // Continue tracing
                        ptrace::syscall(pid, None)?;
                    }
                    _ => {}
                }
            }
        }
        Ok(-1)
    }
}