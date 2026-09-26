use crate::error::{LinuxSubstrateError, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::path::PathBuf;
use std::time::Duration;

/// Configuration for Linux substrate
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LinuxSubstrateConfig {
    pub default_limits: ExecutionLimits,
    pub seccomp_profile: SeccompProfile,
    pub landlock_rules: Vec<LandlockRule>,
    pub cgroup_root: PathBuf,
    pub enable_user_namespace: bool,
    pub default_network: NetworkMode,
}

impl Default for LinuxSubstrateConfig {
    fn default() -> Self {
        Self {
            default_limits: ExecutionLimits::default(),
            seccomp_profile: SeccompProfile::Default,
            landlock_rules: vec![],
            cgroup_root: PathBuf::from("/sys/fs/cgroup"),
            enable_user_namespace: true,
            default_network: NetworkMode::None,
        }
    }
}

/// Execution limits for sandbox
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ExecutionLimits {
    pub memory_bytes: Option<u64>,
    pub cpu_percent: Option<f64>,
    pub cpu_time_seconds: Option<u64>,
    pub max_processes: Option<u32>,
    pub max_file_size: Option<u64>,
    pub max_open_files: Option<u32>,
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

/// Seccomp profiles
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum SeccompProfile {
    Default,
    Strict,
    Custom(String),
}

impl Default for SeccompProfile {
    fn default() -> Self {
        Self::Default
    }
}

/// Landlock filesystem access rule
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LandlockRule {
    pub path: PathBuf,
    pub read: bool,
    pub write: bool,
    pub execute: bool,
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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubstrateDescriptor {
    pub name: String,
    pub isolation_class: String,
    pub network_support: String,
    pub version: String,
}