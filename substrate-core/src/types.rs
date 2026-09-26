//! Shared types for all substrate implementations

use serde::{Deserialize, Serialize};
use std::collections::HashSet;

/// Execution limits for sandbox
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ExecutionLimits {
    pub memory_bytes: Option<u64>,
    pub cpu_percent: Option<f64>,
    pub cpu_time_seconds: Option<u64>,
    pub max_processes: Option<u32>,
    pub max_file_size: Option<u64>,
    pub max_open_files: Option<u64>,
    pub wall_time_seconds: Option<u64>,
    pub max_output_bytes: Option<u64>,
    pub max_artifact_bytes: Option<u64>,
    pub max_workspace_bytes: Option<u64>,
}

impl ExecutionLimits {
    pub fn memory_bytes(&self) -> u64 {
        self.memory_bytes.unwrap_or(512 * 1024 * 1024) // 512MB default
    }

    pub fn cpu_percent(&self) -> f64 {
        self.cpu_percent.unwrap_or(100.0)
    }

    pub fn cpu_time_seconds(&self) -> u64 {
        self.cpu_time_seconds.unwrap_or(300) // 5 minutes default
    }

    pub fn max_processes(&self) -> u32 {
        self.max_processes.unwrap_or(100)
    }

    pub fn wall_time_seconds(&self) -> u64 {
        self.wall_time_seconds.unwrap_or(600) // 10 minutes default
    }
}

/// Network isolation modes
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
pub enum NetworkMode {
    #[default]
    None,
    Egress,
    Ingress,
    EgressFiltered,
}

/// Sandbox execution request
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SandboxRequest {
    pub sandbox_id: String,
    pub image: String,
    pub command: Vec<String>,
    pub limits: ExecutionLimits,
    pub env_names: HashSet<String>,
    pub network: NetworkMode,
    pub workspace_root: String,
    pub artifacts_dir: String,
}

/// Sandbox execution result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SandboxExecutionRecord {
    pub sandbox_id: String,
    pub executed: bool,
    pub exit_code: Option<i32>,
    pub termination: SandboxTermination,
    pub duration_ms: u64,
    pub stdout_reference: String,
    pub stderr_reference: String,
    pub limits_applied: ExecutionLimits,
    pub artifacts: Vec<ArtifactCustodyEntry>,
    pub started_at: f64,
    pub finished_at: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum SandboxTermination {
    Completed,
    Failed,
    Timeout,
    LimitBreach,
    FailedToStart,
    NotRun,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArtifactCustodyEntry {
    pub path: String,
    pub sha256: String,
    pub size: u64,
    pub kind: String,
}

/// Substrate descriptor
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubstrateDescriptor {
    pub name: String,
    pub isolation_class: String,
    pub network_support: String,
    pub version: String,
}