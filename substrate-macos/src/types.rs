use crate::error::{MacOSSubstrateError, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::path::PathBuf;
use std::time::Duration;

/// Configuration for macOS substrate
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MacOSSubstrateConfig {
    pub default_limits: ExecutionLimits,
    pub sandbox_profile: SandboxProfile,
    pub use_app_sandbox: bool,
    pub entitlements: Entitlements,
}

impl Default for MacOSSubstrateConfig {
    fn default() -> Self {
        Self {
            default_limits: ExecutionLimits::default(),
            sandbox_profile: SandboxProfile::default(),
            use_app_sandbox: true,
            entitlements: Entitlements::default(),
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

/// Sandbox profile for macOS
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SandboxProfile {
    pub name: String,
    pub version: u32,
    pub deny_default: bool,
    pub rules: Vec<SandboxRule>,
}

impl Default for SandboxProfile {
    fn default() -> Self {
        Self {
            name: "default".to_string(),
            version: 1,
            deny_default: true,
            rules: Vec::new(),
        }
    }
}

impl SandboxProfile {
    pub fn new(name: &str) -> Self {
        Self {
            name: name.to_string(),
            version: 1,
            deny_default: true,
            rules: Vec::new(),
        }
    }

    pub fn allow_file_read(&mut self, path: std::path::PathBuf) -> &mut Self {
        self.rules.push(SandboxRule::AllowFileRead(path));
        self
    }

    pub fn allow_file_write(&mut self, path: std::path::PathBuf) -> &mut Self {
        self.rules.push(SandboxRule::AllowFileWrite(path));
        self
    }

    pub fn allow_file_execute(&mut self, path: std::path::PathBuf) -> &mut Self {
        self.rules.push(SandboxRule::AllowFileExecute(path));
        self
    }

    pub fn allow_network(&mut self, outbound: bool, inbound: bool) -> &mut Self {
        if outbound {
            self.rules.push(SandboxRule::AllowNetworkOutbound);
        }
        if inbound {
            self.rules.push(SandboxRule::AllowNetworkInbound);
        }
        self
    }

    pub fn allow_process_execution(&mut self) -> &mut Self {
        self.rules.push(SandboxRule::AllowProcessExecution);
        self
    }

    pub fn deny_default(&mut self, deny: bool) -> &mut Self {
        self.deny_default = deny;
        self
    }

    pub fn to_string(&self) -> String {
        let mut result = format!("(version {}\n", self.version);
        result.push_str(&format!("(deny default {})\n", if self.deny_default { "1" } else { "0" }));
        
        for rule in &self.rules {
            result.push_str(&format!("{}\n", rule.to_string()));
        }
        
        result.push_str(")");
        result
    }
}

/// Sandbox rule for macOS sandbox profiles
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum SandboxRule {
    AllowFileRead(std::path::PathBuf),
    AllowFileWrite(std::path::PathBuf),
    AllowFileExecute(std::path::PathBuf),
    AllowNetworkOutbound,
    AllowNetworkInbound,
    AllowProcessExecution,
    AllowFileCreate(std::path::PathBuf),
    AllowFileDelete(std::path::PathBuf),
    AllowFileRename(std::path::PathBuf, std::path::PathBuf),
    AllowNetworkTCPOutbound(u16),
    AllowNetworkTCPInbound(u16),
    AllowNetworkUDPOutbound(u16),
    AllowNetworkUDPInbound(u16),
    AllowSysctlRead(String),
    AllowSysctlWrite(String),
    AllowIOKitRead(String),
    AllowIOKitWrite(String),
    AllowMachLookup(String),
    AllowMachRegister(String),
}

impl SandboxRule {
    pub fn to_string(&self) -> String {
        match self {
            SandboxRule::AllowFileRead(path) => format!("(allow file-read* (literal \"{}\"))", path.display()),
            SandboxRule::AllowFileWrite(path) => format!("(allow file-write* (literal \"{}\"))", path.display()),
            SandboxRule::AllowFileExecute(path) => format!("(allow file-execute* (literal \"{}\"))", path.display()),
            SandboxRule::AllowNetworkOutbound => "(allow network-outbound)".to_string(),
            SandboxRule::AllowNetworkInbound => "(allow network-inbound)".to_string(),
            SandboxRule::AllowProcessExecution => "(allow process-exec)".to_string(),
            SandboxRule::AllowFileCreate(path) => format!("(allow file-write* (literal \"{}\"))", path.display()),
            SandboxRule::AllowFileDelete(path) => format!("(allow file-delete (literal \"{}\"))", path.display()),
            SandboxRule::AllowFileRename(from, to) => format!("(allow file-rename (literal \"{}\") (literal \"{}\"))", from.display(), to.display()),
            SandboxRule::AllowNetworkTCPOutbound(port) => format!("(allow network-outbound (tcp {}))", port),
            SandboxRule::AllowNetworkTCPInbound(port) => format!("(allow network-inbound (tcp {}))", port),
            SandboxRule::AllowNetworkUDPOutbound(port) => format!("(allow network-outbound (udp {}))", port),
            SandboxRule::AllowNetworkUDPInbound(port) => format!("(allow network-inbound (udp {}))", port),
            SandboxRule::AllowSysctlRead(key) => format!("(allow sysctl-read \"{}\")", key),
            SandboxRule::AllowSysctlWrite(key) => format!("(allow sysctl-write \"{}\")", key),
            SandboxRule::AllowIOKitRead(key) => format!("(allow iokit-read \"{}\")", key),
            SandboxRule::AllowIOKitWrite(key) => format!("(allow iokit-write \"{}\")", key),
            SandboxRule::AllowMachLookup(name) => format!("(allow mach-lookup \"{}\")", name),
            SandboxRule::AllowMachRegister(name) => format!("(allow mach-register \"{}\")", name),
        }
    }
}

/// Entitlements for macOS App Sandbox
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Entitlements {
    pub com_apple_security_automation: bool,
    pub com_apple_security_files_user_selected: bool,
    pub com_apple_security_files_downloads: bool,
    pub com_apple_security_network_client: bool,
    pub com_apple_security_network_server: bool,
    pub com_apple_security_personal_information_addressbook: bool,
    pub com_apple_security_personal_information_calendars: bool,
    pub com_apple_security_personal_information_location: bool,
    pub com_apple_security_photos: bool,
    pub com_apple_security_reminders: bool,
}

impl Entitlements {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_automation(mut self, enable: bool) -> Self {
        self.com_apple_security_automation = enable;
        self
    }

    pub fn with_user_selected_files(mut self, enable: bool) -> Self {
        self.com_apple_security_files_user_selected = enable;
        self
    }

    pub fn with_downloads_folder(mut self, enable: bool) -> Self {
        self.com_apple_security_files_downloads = enable;
        self
    }

    pub fn with_network_client(mut self, enable: bool) -> Self {
        self.com_apple_security_network_client = enable;
        self
    }

    pub fn with_network_server(mut self, enable: bool) -> Self {
        self.com_apple_security_network_server = enable;
        self
    }

    pub fn with_address_book(mut self, enable: bool) -> Self {
        self.com_apple_security_personal_information_addressbook = enable;
        self
    }

    pub fn with_calendars(mut self, enable: bool) -> Self {
        self.com_apple_security_personal_information_calendars = enable;
        self
    }

    pub fn with_location(mut self, enable: bool) -> Self {
        self.com_apple_security_personal_information_location = enable;
        self
    }

    pub fn with_photos(mut self, enable: bool) -> Self {
        self.com_apple_security_photos = enable;
        self
    }

    pub fn with_reminders(mut self, enable: bool) -> Self {
        self.com_apple_security_reminders = enable;
        self
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

/// Sandbox profile for macOS
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SandboxProfile {
    pub name: String,
    pub version: u32,
    pub deny_default: bool,
    pub rules: Vec<SandboxRule>,
}

impl SandboxProfile {
    pub fn new(name: &str) -> Self {
        Self {
            name: name.to_string(),
            version: 1,
            deny_default: true,
            rules: Vec::new(),
        }
    }

    pub fn allow_file_read(&mut self, path: std::path::PathBuf) -> &mut Self {
        self.rules.push(SandboxRule::AllowFileRead(path));
        self
    }

    pub fn allow_file_write(&mut self, path: std::path::PathBuf) -> &mut Self {
        self.rules.push(SandboxRule::AllowFileWrite(path));
        self
    }

    pub fn allow_file_execute(&mut self, path: std::path::PathBuf) -> &mut Self {
        self.rules.push(SandboxRule::AllowFileExecute(path));
        self
    }

    pub fn allow_network(&mut self, outbound: bool, inbound: bool) -> &mut Self {
        if outbound {
            self.rules.push(SandboxRule::AllowNetworkOutbound);
        }
        if inbound {
            self.rules.push(SandboxRule::AllowNetworkInbound);
        }
        self
    }

    pub fn allow_process_execution(&mut self) -> &mut Self {
        self.rules.push(SandboxRule::AllowProcessExecution);
        self
    }

    pub fn deny_default(&mut self, deny: bool) -> &mut Self {
        self.deny_default = deny;
        self
    }

    pub fn to_string(&self) -> String {
        let mut result = format!("(version {}\n", self.version);
        result.push_str(&format!("(deny default {})\n", if self.deny_default { "1" } else { "0" }));
        
        for rule in &self.rules {
            result.push_str(&format!("{}\n", rule.to_string()));
        }
        
        result.push_str(")");
        result
    }
}

/// Sandbox rule for macOS sandbox profiles
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum SandboxRule {
    AllowFileRead(std::path::PathBuf),
    AllowFileWrite(std::path::PathBuf),
    AllowFileExecute(std::path::PathBuf),
    AllowNetworkOutbound,
    AllowNetworkInbound,
    AllowProcessExecution,
    AllowFileCreate(std::path::PathBuf),
    AllowFileDelete(std::path::PathBuf),
    AllowFileRename(std::path::PathBuf, std::path::PathBuf),
    AllowNetworkTCPOutbound(u16),
    AllowNetworkTCPInbound(u16),
    AllowNetworkUDPOutbound(u16),
    AllowNetworkUDPInbound(u16),
    AllowSysctlRead(String),
    AllowSysctlWrite(String),
    AllowIOKitRead(String),
    AllowIOKitWrite(String),
    AllowMachLookup(String),
    AllowMachRegister(String),
}

impl SandboxRule {
    pub fn to_string(&self) -> String {
        match self {
            SandboxRule::AllowFileRead(path) => format!("(allow file-read* (literal \"{}\"))", path.display()),
            SandboxRule::AllowFileWrite(path) => format!("(allow file-write* (literal \"{}\"))", path.display()),
            SandboxRule::AllowFileExecute(path) => format!("(allow file-execute* (literal \"{}\"))", path.display()),
            SandboxRule::AllowNetworkOutbound => "(allow network-outbound)".to_string(),
            SandboxRule::AllowNetworkInbound => "(allow network-inbound)".to_string(),
            SandboxRule::AllowProcessExecution => "(allow process-exec)".to_string(),
            SandboxRule::AllowFileCreate(path) => format!("(allow file-write* (literal \"{}\"))", path.display()),
            SandboxRule::AllowFileDelete(path) => format!("(allow file-delete (literal \"{}\"))", path.display()),
            SandboxRule::AllowFileRename(from, to) => format!("(allow file-rename (literal \"{}\") (literal \"{}\"))", from.display(), to.display()),
            SandboxRule::AllowNetworkTCPOutbound(port) => format!("(allow network-outbound (tcp {}))", port),
            SandboxRule::AllowNetworkTCPInbound(port) => format!("(allow network-inbound (tcp {}))", port),
            SandboxRule::AllowNetworkUDPOutbound(port) => format!("(allow network-outbound (udp {}))", port),
            SandboxRule::AllowNetworkUDPInbound(port) => format!("(allow network-inbound (udp {}))", port),
            SandboxRule::AllowSysctlRead(key) => format!("(allow sysctl-read \"{}\")", key),
            SandboxRule::AllowSysctlWrite(key) => format!("(allow sysctl-write \"{}\")", key),
            SandboxRule::AllowIOKitRead(key) => format!("(allow iokit-read \"{}\")", key),
            SandboxRule::AllowIOKitWrite(key) => format!("(allow iokit-write \"{}\")", key),
            SandboxRule::AllowMachLookup(name) => format!("(allow mach-lookup \"{}\")", name),
            SandboxRule::AllowMachRegister(name) => format!("(allow mach-register \"{}\")", name),
        }
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

/// Network isolation modes
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

/// Network isolation modes
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
pub enum NetworkMode {
    #[default]
    None,
    Egress,
    Ingress,
    EgressFiltered,
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

/// Configuration for macOS substrate
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MacOSSubstrateConfig {
    pub default_limits: ExecutionLimits,
    pub sandbox_profile: SandboxProfile,
    pub use_app_sandbox: bool,
    pub entitlements: Entitlements,
}

impl Default for MacOSSubstrateConfig {
    fn default() -> Self {
        Self {
            default_limits: ExecutionLimits::default(),
            sandbox_profile: SandboxProfile::default(),
            use_app_sandbox: true,
            entitlements: Entitlements::default(),
        }
    }
}

/// Entitlements for macOS App Sandbox
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Entitlements {
    pub com_apple_security_automation: bool,
    pub com_apple_security_files_user_selected: bool,
    pub com_apple_security_files_downloads: bool,
    pub com_apple_security_network_client: bool,
    pub com_apple_security_network_server: bool,
    pub com_apple_security_personal_information_addressbook: bool,
    pub com_apple_security_personal_information_calendars: bool,
    pub com_apple_security_personal_information_location: bool,
    pub com_apple_security_photos: bool,
    pub com_apple_security_reminders: bool,
}

impl Entitlements {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_automation(mut self, enable: bool) -> Self {
        self.com_apple_security_automation = enable;
        self
    }

    pub fn with_user_selected_files(mut self, enable: bool) -> Self {
        self.com_apple_security_files_user_selected = enable;
        self
    }

    pub fn with_downloads_folder(mut self, enable: bool) -> Self {
        self.com_apple_security_files_downloads = enable;
        self
    }

    pub fn with_network_client(mut self, enable: bool) -> Self {
        self.com_apple_security_network_client = enable;
        self
    }

    pub fn with_network_server(mut self, enable: bool) -> Self {
        self.com_apple_security_network_server = enable;
        self
    }

    pub fn with_address_book(mut self, enable: bool) -> Self {
        self.com_apple_security_personal_information_addressbook = enable;
        self
    }

    pub fn with_calendars(mut self, enable: bool) -> Self {
        self.com_apple_security_personal_information_calendars = enable;
        self
    }

    pub fn with_location(mut self, enable: bool) -> Self {
        self.com_apple_security_personal_information_location = enable;
        self
    }

    pub fn with_photos(mut self, enable: bool) -> Self {
        self.com_apple_security_photos = enable;
        self
    }

    pub fn with_reminders(mut self, enable: bool) -> Self {
        self.com_apple_security_reminders = enable;
        self
    }
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
}

use std::collections::HashSet;
use std::path::PathBuf;
use std::time::Duration;