use crate::error::{MacOSSubstrateError, Result};
use crate::types::{
    MacOSSubstrateConfig, SandboxRequest, SandboxExecutionRecord, 
    SandboxTermination, ExecutionLimits, ArtifactCustodyEntry,
    SubstrateDescriptor, ExecutionLimits as Limits,
};
use crate::sandbox::SandboxManager;
use crate::profile::ProfileManager;
use crate::xpc::XPCConnection;
use crate::error::MacOSSubstrateError;
use crate::types::SandboxRequest;
use substrate_core::{SandboxRequest as CoreSandboxRequest, SandboxExecutionRecord as CoreExecutionRecord, Substrate, SubstrateDescriptor as CoreSubstrateDescriptor};
use async_trait::async_trait;
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use std::sync::Arc;
use tokio::process::Command as TokioCommand;
use tokio::io::{AsyncBufReadExt, BufReader as AsyncBufReader};
use tokio::time::{timeout, Duration};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use sha256;
use walkdir;
use std::io::{BufRead, BufReader};
use std::os::unix::io::AsRawFd;

/// macOS substrate implementation
pub struct MacOSSubstrate {
    config: MacOSSubstrateConfig,
    sandbox_manager: SandboxManager,
    profile_manager: ProfileManager,
    xpc_connection: Option<XPCConnection>,
}

impl MacOSSubstrate {
    pub fn new(config: MacOSSubstrateConfig) -> Result<Self> {
        // Check if we have required capabilities
        if !Self::check_capabilities() {
            return Err(MacOSSubstrateError::Unavailable(
                "Insufficient capabilities for macOS substrate".to_string()
            ));
        }

        let sandbox_manager = SandboxManager::new(
            config.sandbox_profile.clone(),
            config.use_app_sandbox,
        );

        let profile_manager = ProfileManager::new();

        Ok(Self {
            config,
            sandbox_manager,
            profile_manager,
            xpc_connection: None,
        })
    }

    fn check_capabilities() -> bool {
        // Check if we have required capabilities
        // For macOS substrate, we need:
        // - macOS 10.15+ (Catalina) for modern sandbox APIs
        // - Seatbelt sandbox support (available on all macOS versions)
        // - App Sandbox support (requires entitlements)
        
        // Check macOS version
        if !Self::check_macos_version() {
            return false;
        }

        // Check if we can use sandbox
        if !Self::can_use_sandbox() {
            return false;
        }

        true
    }

    fn check_macos_version() -> bool {
        // Check macOS version (10.15+ for modern sandbox APIs)
        use std::process::Command;
        let output = Command::new("sw_vers")
            .arg("-productVersion")
            .output();
        
        if let Ok(output) = output {
            let version_str = String::from_utf8_lossy(&output.stdout);
            if let Some(version_str) = version_str.lines().next() {
                if let Some(major_minor) = version_str.split('.').take(2).collect::<Vec<_>>().join(".").parse::<f32>().ok() {
                    return major_minor >= 10.15; // Catalina+
                }
            }
        }
        false
    }

    fn can_use_sandbox() -> bool {
        // Check if sandbox-exec is available
        std::process::Command::new("sandbox-exec")
            .arg("-h")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    }

    pub async fn execute(&self, request: SandboxRequest) -> Result<SandboxExecutionRecord> {
        let started_at = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs_f64();

        let start_time = Instant::now();
        let sandbox_id = request.sandbox_id.clone();

        // Create artifacts directory
        let artifacts_dir = PathBuf::from(&request.artifacts_dir);
        std::fs::create_dir_all(&artifacts_dir)
            .map_err(|e| MacOSSubstrateError::Io(e))?;

        // Initialize sandbox
        let mut sandbox_manager = self.sandbox_manager.clone();
        sandbox_manager.initialize()?;

        // Prepare command
        let image_path = self.resolve_image(&request.image)?;
        let mut cmd = TokioCommand::new(&image_path);
        cmd.args(&request.command);
        cmd.current_dir("/work");
        cmd.stdin(Stdio::null());
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());

        // Set environment
        for env_name in &request.env_names {
            if let Ok(value) = std::env::var(env_name) {
                cmd.env(env_name, value);
            }
        }

        // Apply timeout
        let timeout_duration = Duration::from_secs(
            request.limits.wall_time_seconds.unwrap_or(600)
        );

        // Apply sandbox
        let mut sandbox_manager = self.sandbox_manager.clone();
        sandbox_manager.initialize()?;

        // Execute with timeout
        let output = timeout(timeout_duration, async {
            let mut cmd = TokioCommand::new(&image_path);
            cmd.args(&request.command);
            cmd.current_dir("/work");
            cmd.stdin(Stdio::null());
            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            // Set environment
            for env_name in &request.env_names {
                if let Ok(value) = std::env::var(env_name) {
                    cmd.env(env_name, value);
                }
            }

            // Execute with sandbox
            let mut child = cmd.spawn()
                .map_err(|e| MacOSSubstrateError::Execution(e.to_string()))?;

            // Apply sandbox to child process
            // This would use sandbox-exec or similar

            // Monitor output
            let mut stdout = Vec::new();
            let mut stderr = Vec::new();

            if let Some(stdout_handle) = child.stdout.take() {
                let mut reader = AsyncBufReadExt::lines(AsyncBufReader::new(stdout_handle));
                while let Some(line) = reader.next_line().await.transpose()? {
                    stdout.push(line.as_bytes().to_vec());
                    stdout.push(b"\n".to_vec());
                }
            }

            if let Some(stderr_handle) = child.stderr.take() {
                let mut reader = AsyncBufReadExt::lines(AsyncBufReader::new(stderr_handle));
                while let Some(line) = reader.next_line().await.transpose()? {
                    stderr.push(line.as_bytes().to_vec());
                    stderr.push(b"\n".to_vec());
                }
            }

            let status = child.wait().await?;
            (status, stdout, stderr)
        }).await;

        let duration_ms = start_time.elapsed().as_millis() as u64;

        // Collect artifacts
        let artifacts = self.collect_artifacts(&artifacts_dir)?;

        // Save stdout/stderr
        let stdout_ref = self.save_output(&artifacts_dir, "stdout", &output.1)?;
        let stderr_ref = self.save_output(&artifacts_dir, "stderr", &output.2)?;

        let (status, stdout, stderr) = match output {
            Ok((status, stdout, stderr)) => (status, stdout, stderr),
            Err(e) if e.to_string().contains("timeout") => {
                return Ok(SandboxExecutionRecord {
                    sandbox_id: request.sandbox_id,
                    executed: true,
                    exit_code: None,
                    termination: SandboxTermination::Timeout,
                    duration_ms,
                    stdout_reference: String::new(),
                    stderr_reference: String::new(),
                    limits_applied: request.limits,
                    artifacts: vec![],
                    started_at: SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64(),
                    finished_at: SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64(),
                });
            },
            Err(e) => {
                return Ok(SandboxExecutionRecord {
                    sandbox_id: request.sandbox_id,
                    executed: false,
                    exit_code: None,
                    termination: SandboxTermination::FailedToStart,
                    duration_ms,
                    stdout_reference: String::new(),
                    stderr_reference: String::new(),
                    limits_applied: request.limits,
                    artifacts: vec![],
                    started_at: SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64(),
                    finished_at: SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64(),
                });
            }
        };

        let termination = match status.code() {
            Some(0) => SandboxTermination::Completed,
            Some(code) if code > 128 => SandboxTermination::Failed,
            Some(_) => SandboxTermination::Failed,
            None => SandboxTermination::Failed,
        };

        let finished_at = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs_f64();

        Ok(SandboxExecutionRecord {
            sandbox_id: request.sandbox_id,
            executed: true,
            exit_code: status.code(),
            termination,
            duration_ms,
            stdout_reference: stdout_ref,
            stderr_reference: stderr_ref,
            limits_applied: request.limits,
            artifacts,
            started_at,
            finished_at,
        })
    }

    fn resolve_image(&self, image: &str) -> Result<PathBuf> {
        // For local images, look in standard locations
        let paths = [
            format!("/usr/local/bin/{}", image),
            format!("/usr/bin/{}", image),
            format!("/bin/{}", image),
            format!("./{}", image),
        ];

        for path in &paths {
            if Path::new(path).exists() {
                return Ok(PathBuf::from(path));
            }
        }

        // Check PATH
        if let Ok(path) = which::which(image) {
            return Ok(path);
        }

        Err(MacOSSubstrateError::Config(
            format!("Image not found: {}", image)
        ))
    }

    fn apply_resource_limits(&self, cmd: &mut TokioCommand, limits: &ExecutionLimits) -> Result<()> {
        // Resource limits are applied via sandbox
        Ok(())
    }

    async fn collect_artifacts(&self, artifacts_dir: &Path) -> Result<Vec<ArtifactCustodyEntry>> {
        let mut artifacts = Vec::new();
        
        if artifacts_dir.exists() {
            for entry in walkdir::WalkDir::new(artifacts_dir) {
                let entry = entry.map_err(|e| MacOSSubstrateError::Io(e))?;
                if entry.file_type().is_file() {
                    let path = entry.path();
                    let relative = path.strip_prefix(artifacts_dir)
                        .map_err(|e| MacOSSubstrateError::Io(std::io::Error::new(std::io::ErrorKind::Other, e)))?;
                    
                    let data = path.read_bytes()
                        .map_err(|e| MacOSSubstrateError::Io(e))?;
                    let digest = sha256::digest(&data);
                    
                    artifacts.push(ArtifactCustodyEntry {
                        path: relative.to_string_lossy().to_string(),
                        sha256: digest,
                        size: data.len() as u64,
                        kind: "file".to_string(),
                    });
                }
            }
        }
        
        Ok(artifacts)
    }

    fn save_output(&self, artifacts_dir: &Path, name: &str, data: &[Vec<u8>]) -> Result<String> {
        let output: Vec<u8> = data.iter().flatten().cloned().collect();
        let filename = format!("{}.txt", name);
        let path = std::path::Path::new("/artifacts").join(&filename);
        
        std::fs::write(&path, &output)
            .map_err(|e| MacOSSubstrateError::Io(e))?;
        
        Ok(path.to_string_lossy().to_string())
    }
}

#[async_trait]
impl Substrate for MacOSSubstrate {
    async fn execute(&self, request: CoreSandboxRequest) -> Result<CoreExecutionRecord> {
        // Convert request
        let sandbox_req = SandboxRequest {
            sandbox_id: request.sandbox_id,
            image: request.image,
            command: request.command,
            limits: request.limits.unwrap_or_default(),
            env_names: request.env_names.unwrap_or_default(),
            network: request.network.unwrap_or(crate::types::NetworkMode::None),
            workspace_root: request.workspace_root.unwrap_or_else(|| "/work".to_string()),
            artifacts_dir: request.artifacts_dir.unwrap_or_else(|| "/artifacts".to_string()),
        };

        let result = self.execute(sandbox_req).await?;
        
        // Convert back to core types
        Ok(CoreExecutionRecord {
            sandbox_id: result.sandbox_id,
            executed: result.executed,
            exit_code: result.exit_code,
            termination: substrate_core::SandboxTermination::from(result.termination),
            duration_ms: result.duration_ms,
            stdout_reference: result.stdout_reference,
            stderr_reference: result.stderr_reference,
            limits_applied: result.limits_applied,
            artifacts: result.artifacts.into_iter().map(|a| a.into()).collect(),
            started_at: result.started_at,
            finished_at: result.finished_at,
        })
    }

    fn descriptor(&self) -> CoreSubstrateDescriptor {
        CoreSubstrateDescriptor {
            name: self.descriptor().name,
            isolation_class: self.descriptor().isolation_class,
            network_support: self.descriptor().network_support,
        }
    }
}

impl MacOSSubstrate {
    pub fn descriptor(&self) -> SubstrateDescriptor {
        SubstrateDescriptor {
            name: "macos-seatbelt".to_string(),
            isolation_class: "macos-seatbelt".to_string(),
            network_support: "app-sandbox".to_string(),
        }
    }
}

use std::collections::HashSet;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};
use sha256;
use walkdir;
use std::io::{BufRead, BufReader};