use crate::error::{WindowsSubstrateError, Result};
use serde::{Deserialize, Serialize};
use substrate_core::{
    ExecutionLimits as CoreExecutionLimits,
    NetworkMode as CoreNetworkMode,
    SandboxRequest as CoreSandboxRequest,
    SandboxExecutionRecord as CoreSandboxExecutionRecord,
    SandboxTermination as CoreSandboxTermination,
    ArtifactCustodyEntry as CoreArtifactCustodyEntry,
    SubstrateDescriptor as CoreSubstrateDescriptor,
    ExecutionLimits,
    NetworkMode,
    SandboxRequest,
    SandboxExecutionRecord,
    SandboxTermination,
    ArtifactCustodyEntry,
    SubstrateDescriptor,
};

/// Configuration for Windows substrate
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WindowsSubstrateConfig {
    pub default_limits: ExecutionLimits,
    pub job_object_limits: JobObjectLimits,
    pub silo_config: SiloConfig,
    pub appcontainer_config: AppContainerConfig,
}

impl Default for WindowsSubstrateConfig {
    fn default() -> Self {
        Self {
            default_limits: ExecutionLimits::default(),
            job_object_limits: JobObjectLimits::default(),
            silo_config: SiloConfig::default(),
            appcontainer_config: AppContainerConfig::default(),
        }
    }
}

/// Job Object limits
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct JobObjectLimits {
    pub memory_limit: Option<u64>,
    pub job_memory_limit: Option<u64>,
    pub process_memory_limit: Option<u64>,
    pub cpu_affinity: Option<Vec<usize>>,
    pub cpu_rate: Option<u32>, // percentage * 100
    pub max_processes: Option<u32>,
    pub io_rate: Option<u64>,
    pub process_time_limit: Option<u64>,
    pub job_time_limit: Option<u64>,
}

/// Silo configuration
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SiloConfig {
    pub enable_filesystem_isolation: bool,
    pub enable_registry_isolation: bool,
    pub root_path: Option<std::path::PathBuf>,
}

impl SiloConfig {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_filesystem_isolation(mut self, enable: bool) -> Self {
        self.enable_filesystem_isolation = enable;
        self
    }

    pub fn with_registry_isolation(mut self, enable: bool) -> Self {
        self.enable_registry_isolation = enable;
        self
    }

    pub fn with_root_path(mut self, path: std::path::PathBuf) -> Self {
        self.root_path = Some(path);
        self
    }
}

/// AppContainer configuration
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AppContainerConfig {
    pub enable_network_isolation: bool,
    pub capabilities: Vec<AppContainerCapability>,
    pub network_isolation: NetworkIsolation,
}

impl AppContainerConfig {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_network_isolation(mut self, isolation: NetworkIsolation) -> Self {
        self.network_isolation = isolation;
        self
    }

    pub fn with_capabilities(mut self, capabilities: Vec<AppContainerCapability>) -> Self {
        self.capabilities = capabilities;
        self
    }

    pub fn with_network_isolation_enabled(mut self, enable: bool) -> Self {
        self.enable_network_isolation = enable;
        self
    }
}

/// Network isolation modes for AppContainer
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
pub enum NetworkIsolation {
    #[default]
    None,
    LoopbackOnly,
    InternetClient,
    InternetClientServer,
    PrivateNetworkClientServer,
}

/// AppContainer capabilities
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum AppContainerCapability {
    InternetClient,
    InternetClientServer,
    PrivateNetworkClientServer,
    PicturesLibrary,
    VideosLibrary,
    MusicLibrary,
    DocumentsLibrary,
    RemovableStorage,
}

/// Windows-specific sandbox request with Windows-specific fields
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WindowsSandboxRequest {
    pub sandbox_id: String,
    pub image: String,
    pub command: Vec<String>,
    pub limits: ExecutionLimits,
    pub env_names: std::collections::HashSet<String>,
    pub network: NetworkMode,
    pub workspace_root: String,
    pub artifacts_dir: String,
}

/// Sandbox execution result with Windows-specific fields
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WindowsSandboxExecutionRecord {
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

/// Artifact custody entry
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WindowsArtifactCustodyEntry {
    pub path: String,
    pub sha256: String,
    pub size: u64,
    pub kind: String,
}

/// Substrate descriptor
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WindowsSubstrateDescriptor {
    pub name: String,
    pub isolation_class: String,
    pub network_support: String,
    pub version: String,
}

/// Conversion implementations from Windows types to Core types
impl From<ExecutionLimits> for CoreExecutionLimits {
    fn from(limits: ExecutionLimits) -> Self {
        CoreExecutionLimits {
            memory_bytes: limits.memory_bytes,
            cpu_percent: limits.cpu_percent,
            cpu_time_seconds: limits.cpu_time_seconds,
            max_processes: limits.max_processes,
            max_file_size: limits.max_file_size,
            max_open_files: limits.max_open_files.map(|v| v as u64),
            wall_time_seconds: limits.wall_time_seconds,
            max_output_bytes: limits.max_output_bytes,
            max_artifact_bytes: limits.max_artifact_bytes,
            max_workspace_bytes: limits.max_workspace_bytes,
        }
    }
}

impl From<NetworkMode> for CoreNetworkMode {
    fn from(mode: NetworkMode) -> Self {
        mode // Same enum definition
    }
}

impl From<SandboxTermination> for CoreSandboxTermination {
    fn from(term: SandboxTermination) -> Self {
        term // Same enum definition
    }
}

impl From<ArtifactCustodyEntry> for CoreArtifactCustodyEntry {
    fn from(entry: ArtifactCustodyEntry) -> Self {
        CoreArtifactCustodyEntry {
            path: entry.path,
            sha256: entry.sha256,
            size: entry.size,
            kind: entry.kind,
        }
    }
}

/// Conversion implementations from Core types to Windows types (needed by executor)
impl From<CoreExecutionLimits> for ExecutionLimits {
    fn from(limits: CoreExecutionLimits) -> Self {
        ExecutionLimits {
            memory_bytes: limits.memory_bytes,
            cpu_percent: limits.cpu_percent,
            cpu_time_seconds: limits.cpu_time_seconds,
            max_processes: limits.max_processes,
            max_file_size: limits.max_file_size,
            max_open_files: limits.max_open_files.map(|v| v as u32),
            wall_time_seconds: limits.wall_time_seconds,
            max_output_bytes: limits.max_output_bytes,
            max_artifact_bytes: limits.max_artifact_bytes,
            max_workspace_bytes: limits.max_workspace_bytes,
        }
    }
}

impl From<CoreNetworkMode> for NetworkMode {
    fn from(mode: CoreNetworkMode) -> Self {
        mode // Same enum definition
    }
}

impl From<CoreSandboxTermination> for SandboxTermination {
    fn from(term: CoreSandboxTermination) -> Self {
        term // Same enum definition
    }
}

impl From<CoreArtifactCustodyEntry> for ArtifactCustodyEntry {
    fn from(entry: CoreArtifactCustodyEntry) -> Self {
        ArtifactCustodyEntry {
            path: entry.path,
            sha256: entry.sha256,
            size: entry.size,
            kind: entry.kind,
        }
    }
}