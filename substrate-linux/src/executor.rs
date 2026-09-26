#[cfg(target_os = "linux")]
mod linux_executor {
    use crate::error::{LinuxSubstrateError, Result};
    use crate::types::{
        LinuxSubstrateConfig, SandboxRequest, SandboxExecutionRecord,
        SandboxTermination, ExecutionLimits, ArtifactCustodyEntry,
        SubstrateDescriptor, NetworkMode,
    };
    use crate::namespace::{NamespaceConfig, create_namespaces, setup_mount_namespace};
    use crate::seccomp::apply_seccomp_filter;
    use crate::cgroup::CgroupManager;
    #[cfg(feature = "landlock")]
    use crate::landlock::LandlockManager;
    use sha2::{Digest, Sha256};
    use substrate_core::{
        SandboxRequest as CoreSandboxRequest,
        SandboxExecutionRecord as CoreExecutionRecord,
        SandboxTermination as CoreSandboxTermination,
        ExecutionLimits as CoreExecutionLimits,
        NetworkMode as CoreNetworkMode,
        ArtifactCustodyEntry as CoreArtifactCustodyEntry,
        Substrate,
        SubstrateDescriptor as CoreSubstrateDescriptor,
        SubstrateError,
        SubstrateCapability,
        ResourceLimits,
        CapabilityRequest,
        CapabilityResponse,
    };
    use async_trait::async_trait;
    use std::collections::HashSet;
    use std::path::{Path, PathBuf};
    use std::process::{Command, Stdio};
    use std::time::{Instant, SystemTime, UNIX_EPOCH};
    use std::io::{BufRead, BufReader};
    use std::sync::Arc;
    use tokio::process::Command as TokioCommand;
    use tokio::io::{AsyncBufReadExt, BufReader as AsyncBufReader};
    use tokio::time::{timeout, Duration};
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Mutex;
    use nix::unistd;

    /// Linux substrate implementation
    pub struct LinuxSubstrate {
        config: LinuxSubstrateConfig,
        #[allow(dead_code)]
        cgroup_root: std::path::PathBuf,
    }

    impl LinuxSubstrate {
        pub fn new(config: LinuxSubstrateConfig) -> Result<Self> {
            // Check if we have required capabilities
            if !Self::check_capabilities() {
                return Err(LinuxSubstrateError::Unavailable(
                    "Insufficient capabilities for Linux substrate".to_string()
                ));
            }

            Ok(Self {
                config,
                cgroup_root: std::path::PathBuf::from("/sys/fs/cgroup"),
            })
        }

        fn check_capabilities() -> bool {
            // Check if we can create namespaces (need CAP_SYS_ADMIN or unprivileged user ns)
            std::path::Path::new("/proc/sys/kernel/unprivileged_userns_clone").exists()
                || unistd::getuid().is_root()
        }

        pub fn descriptor(&self) -> SubstrateDescriptor {
            SubstrateDescriptor {
                name: "linux-namespace".to_string(),
                isolation_class: "linux-namespaces".to_string(),
                network_support: "none".to_string(),
                version: "0.1.0".to_string(),
            }
        }

        pub fn capability(&self) -> SubstrateCapability {
            SubstrateCapability {
                name: "linux-namespace".to_string(),
                isolation_class: "linux-namespaces".to_string(),
                network_support: "none".to_string(),
                resource_limits: ResourceLimits {
                    max_memory_bytes: Some(4 * 1024 * 1024 * 1024),
                    max_cpu_percent: Some(200.0),
                    max_cpu_time_seconds: Some(3600),
                    max_processes: Some(1000),
                    max_file_size: Some(1024 * 1024 * 1024),
                    max_open_files: Some(1024),
                    max_wall_time_seconds: Some(7200),
                    max_output_bytes: Some(100 * 1024 * 1024),
                    max_artifact_bytes: Some(500 * 1024 * 1024),
                    max_workspace_bytes: Some(10 * 1024 * 1024 * 1024),
                },
                supported_profiles: vec!["default".to_string(), "strict".to_string()],
                max_concurrent_sandboxes: 100,
            }
        }

        pub async fn negotiate_capability(&self, requested: CapabilityRequest) -> std::result::Result<CapabilityResponse, SubstrateError> {
            let capability = self.capability();
            
            let mut granted = Vec::new();
            let mut denied = Vec::new();
            
            // Check required capabilities
            for req in &requested.required {
                if capability.supported_profiles.contains(req) || req == "code_execution" || req == "filesystem_write" {
                    granted.push(req.clone());
                } else {
                    denied.push(req.clone());
                }
            }
            
            // Check preferred capabilities
            for pref in &requested.preferred {
                if capability.supported_profiles.contains(pref) && !granted.contains(pref) {
                    granted.push(pref.clone());
                }
            }
            
            // Adjust limits based on substrate capabilities
            let mut adjusted_limits = requested.resource_limits;
            if let Some(max_mem) = capability.resource_limits.max_memory_bytes {
                adjusted_limits.memory_bytes = Some(adjusted_limits.memory_bytes.unwrap_or(max_mem).min(max_mem));
            }
            if let Some(max_cpu) = capability.resource_limits.max_cpu_percent {
                adjusted_limits.cpu_percent = Some(adjusted_limits.cpu_percent.unwrap_or(max_cpu).min(max_cpu));
            }
            
            Ok(CapabilityResponse {
                granted,
                denied,
                adjusted_limits,
                substrate_type: "linux-namespace".to_string(),
            })
        }

        /// Execute a sandbox request (internal method returning local types)
        pub async fn execute_local(&self, request: SandboxRequest) -> Result<SandboxExecutionRecord> {
            let started_at = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_secs_f64();

            let start_time = Instant::now();
            let sandbox_id = request.sandbox_id.clone();

            // Create artifacts directory
            let artifacts_dir = PathBuf::from(&request.artifacts_dir);
            std::fs::create_dir_all(&artifacts_dir)
                .map_err(|e| LinuxSubstrateError::Io(e))?;

            // Setup cgroup
            let mut cgroup = CgroupManager::new(
                std::path::PathBuf::from("/sys/fs/cgroup"),
                &sandbox_id
            )?;
            cgroup.setup(&request.limits)?;

            // Setup namespaces
            let namespace_config = NamespaceConfig {
                enable_user: self.config.enable_user_namespace,
                enable_mount: true,
                enable_pid: true,
                enable_network: request.network != NetworkMode::None,
                enable_uts: true,
                enable_ipc: true,
                enable_cgroup: false,
                uid_map: vec![(0, unistd::getuid().as_raw(), 1)],
                gid_map: vec![(0, unistd::getgid().as_raw(), 1)],
                mount_propagation: crate::namespace::MountPropagation::Private,
            };

            let _namespace_guard = crate::namespace::create_namespaces(&NamespaceConfig {
                enable_user: self.config.enable_user_namespace,
                enable_mount: true,
                enable_pid: true,
                enable_network: request.network != NetworkMode::None,
                enable_uts: true,
                enable_ipc: true,
                enable_cgroup: false,
                uid_map: vec![(0, unistd::getuid().as_raw(), 1)],
                gid_map: vec![(0, unistd::getgid().as_raw(), 1)],
                mount_propagation: crate::namespace::MountPropagation::Private,
            })?;

            // Setup mount namespace
            let workspace_root = PathBuf::from(&request.workspace_root);
            crate::namespace::setup_mount_namespace(&workspace_root, &PathBuf::from(&request.artifacts_dir))?;

            // Apply landlock
            #[cfg(feature = "landlock")]
            {
                let mut landlock = LandlockManager::new();
                landlock.apply()?;
            }

            // Apply seccomp
            apply_seccomp_filter(self.config.seccomp_profile.clone())?;

            // Add current process to cgroup
            let mut cgroup = CgroupManager::new(
                std::path::PathBuf::from("/sys/fs/cgroup"),
                &sandbox_id
            )?;
            cgroup.add_current_process()?;

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

            // Set resource limits
            self.apply_resource_limits(&mut cmd, &request.limits)?;

            // Apply timeout
            let timeout_duration = Duration::from_secs(
                request.limits.wall_time_seconds.unwrap_or(600)
            );

            // Execute with timeout
            let mut child = cmd.spawn()
                .map_err(|e| LinuxSubstrateError::Execution(e.to_string()))?;

            // Add to cgroup
            let mut cgroup = CgroupManager::new(
                std::path::PathBuf::from("/sys/fs/cgroup"),
                &sandbox_id
            )?;
            cgroup.add_current_process()?;

            // Wait with timeout
            let output = timeout(timeout_duration, async {
                let mut stdout = Vec::new();
                let mut stderr = Vec::new();

                if let Some(stdout_handle) = child.stdout.take() {
                    let mut reader = AsyncBufReadExt::lines(AsyncBufReader::new(stdout_handle));
                    while let Some(line) = reader.next_line().await? {
                        stdout.push(line.as_bytes().to_vec());
                        stdout.push(b"\n".to_vec());
                    }
                }

                if let Some(stderr_handle) = child.stderr.take() {
                    let mut reader = AsyncBufReadExt::lines(AsyncBufReader::new(stderr_handle));
                    while let Some(line) = reader.next_line().await? {
                        stderr.push(line.as_bytes().to_vec());
                        stderr.push(b"\n".to_vec());
                    }
                }

                let status = child.wait().await?;
                (status, stdout, stderr)
            }).await;

            let duration_ms = start_time.elapsed().as_millis() as u64;

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

            // Collect artifacts
            let artifacts = self.collect_artifacts(&artifacts_dir).await?;

            // Save stdout/stderr
            let stdout_ref = self.save_output(&artifacts_dir, "stdout", &stdout).await?;
            let stderr_ref = self.save_output(&artifacts_dir, "stderr", &stderr).await?;

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
                duration_ms: start_time.elapsed().as_millis() as u64,
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

            Err(LinuxSubstrateError::Config(
                format!("Image not found: {}", image)
            ))
        }

        fn apply_resource_limits(&self, _cmd: &mut TokioCommand, _limits: &ExecutionLimits) -> Result<()> {
            // Note: Resource limits are applied via cgroup, but we can also set rlimits
            // For now, we rely on cgroup limits
            Ok(())
        }

        async fn collect_artifacts(&self, artifacts_dir: &Path) -> Result<Vec<ArtifactCustodyEntry>> {
            let mut artifacts = Vec::new();
            
            if artifacts_dir.exists() {
                for entry in walkdir::WalkDir::new(artifacts_dir) {
                    let entry = entry.map_err(|e| LinuxSubstrateError::Io(std::io::Error::new(std::io::ErrorKind::Other, e)))?;
                    if entry.file_type().is_file() {
                        let path = entry.path();
                        let relative = path.strip_prefix(artifacts_dir)
                            .map_err(|e| LinuxSubstrateError::Io(std::io::Error::new(std::io::ErrorKind::Other, e)))?;
                        
                        let metadata = entry.metadata()
                            .map_err(|e| LinuxSubstrateError::Io(std::io::Error::new(std::io::ErrorKind::Other, e)))?;
                        
                        let content = std::fs::read(path)
                            .map_err(|e| LinuxSubstrateError::Io(e))?;
                        let mut hasher = Sha256::new();
                        hasher.update(&content);
                        let sha256 = format!("{:x}", hasher.finalize());
                        
                        artifacts.push(ArtifactCustodyEntry {
                            path: relative.to_string_lossy().to_string(),
                            sha256,
                            size: metadata.len(),
                            kind: "file".to_string(),
                        });
                    }
                }
            }
            
            Ok(artifacts)
        }

        async fn save_output(&self, _artifacts_dir: &Path, name: &str, data: &[Vec<u8>]) -> Result<String> {
            let output: Vec<u8> = data.iter().flatten().cloned().collect();
            let filename = format!("{}.txt", name);
            let path = std::path::Path::new("/artifacts").join(&filename);
            
            tokio::fs::write(&path, &output)
                .await
                .map_err(|e| LinuxSubstrateError::Io(e))?;
            
            Ok(path.to_string_lossy().to_string())
        }
    }

    #[async_trait]
    impl Substrate for LinuxSubstrate {
        async fn execute(&self, request: CoreSandboxRequest) -> std::result::Result<CoreExecutionRecord, SubstrateError> {
            // Convert request from core types to local types
            let sandbox_req = SandboxRequest {
                sandbox_id: request.sandbox_id,
                image: request.image,
                command: request.command,
                limits: request.limits.into(),
                env_names: request.env_names,
                network: request.network.into(),
                workspace_root: request.workspace_root,
                artifacts_dir: request.artifacts_dir,
            };

            let result = self.execute_local(sandbox_req).await
                .map_err(|e| SubstrateError::ExecutionFailed(e.to_string()))?;
            
            // Convert back to core types
            Ok(CoreExecutionRecord {
                sandbox_id: result.sandbox_id,
                executed: result.executed,
                exit_code: result.exit_code,
                termination: CoreSandboxTermination::from(result.termination),
                duration_ms: result.duration_ms,
                stdout_reference: result.stdout_reference,
                stderr_reference: result.stderr_reference,
                limits_applied: result.limits_applied.into(),
                artifacts: result.artifacts.into_iter().map(|a| a.into()).collect(),
                started_at: result.started_at,
                finished_at: result.finished_at,
            })
        }

        fn descriptor(&self) -> CoreSubstrateDescriptor {
            let d = self.descriptor();
            CoreSubstrateDescriptor {
                name: d.name,
                isolation_class: d.isolation_class,
                network_support: d.network_support,
                version: d.version,
            }
        }

        fn capability(&self) -> SubstrateCapability {
            self.capability()
        }

        async fn negotiate_capability(&self, requested: CapabilityRequest) -> std::result::Result<CapabilityResponse, SubstrateError> {
            self.negotiate_capability(request).await
        }
    }
}

/// Re-export the Linux substrate
#[cfg(target_os = "linux")]
pub use linux_executor::*;

/// Stub implementations for non-Linux platforms
#[cfg(not(target_os = "linux"))]
mod stub_executor {
    use crate::error::{LinuxSubstrateError, Result};
    use crate::types::{
        LinuxSubstrateConfig, SubstrateDescriptor,
    };
    use substrate_core::{
        SandboxRequest as CoreSandboxRequest, 
        SandboxExecutionRecord as CoreExecutionRecord, 
        Substrate, 
        SubstrateDescriptor as CoreSubstrateDescriptor, 
        SubstrateError,
        SubstrateCapability,
        ResourceLimits,
        CapabilityRequest,
        CapabilityResponse,
    };
    use async_trait::async_trait;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    /// Linux substrate implementation (stub for non-Linux)
    pub struct LinuxSubstrateStub {
        config: LinuxSubstrateConfig,
    }

    impl LinuxSubstrateStub {
        pub fn new(_config: LinuxSubstrateConfig) -> Result<Self> {
            Err(LinuxSubstrateError::Unavailable(
                "Linux substrate not supported on this platform. Requires Linux with namespaces, seccomp, cgroups v2, and landlock support.".to_string()
            ))
        }

        pub fn descriptor(&self) -> SubstrateDescriptor {
            SubstrateDescriptor {
                name: "linux-namespace".to_string(),
                isolation_class: "linux-namespaces".to_string(),
                network_support: "none".to_string(),
                version: "0.1.0".to_string(),
            }
        }

        pub fn capability(&self) -> SubstrateCapability {
            SubstrateCapability {
                name: "linux-namespace".to_string(),
                isolation_class: "linux-namespaces".to_string(),
                network_support: "none".to_string(),
                resource_limits: ResourceLimits {
                    max_memory_bytes: Some(4 * 1024 * 1024 * 1024),
                    max_cpu_percent: Some(200.0),
                    max_cpu_time_seconds: Some(3600),
                    max_processes: Some(1000),
                    max_file_size: Some(1024 * 1024 * 1024),
                    max_open_files: Some(1024),
                    max_wall_time_seconds: Some(7200),
                    max_output_bytes: Some(100 * 1024 * 1024),
                    max_artifact_bytes: Some(500 * 1024 * 1024),
                    max_workspace_bytes: Some(10 * 1024 * 1024 * 1024),
                },
                supported_profiles: vec!["default".to_string(), "strict".to_string()],
                max_concurrent_sandboxes: 100,
            }
        }

        async fn negotiate_capability(&self, _requested: CapabilityRequest) -> std::result::Result<CapabilityResponse, SubstrateError> {
            Err(SubstrateError::NotAvailable(
                "Linux substrate not supported on this platform".to_string()
            ))
        }
    }

    #[async_trait]
    impl Substrate for LinuxSubstrateStub {
        async fn execute(&self, _request: CoreSandboxRequest) -> std::result::Result<CoreExecutionRecord, SubstrateError> {
            Err(SubstrateError::NotAvailable(
                "Linux substrate not supported on this platform".to_string()
            ))
        }

        fn descriptor(&self) -> CoreSubstrateDescriptor {
            CoreSubstrateDescriptor {
                name: "linux-namespace".to_string(),
                isolation_class: "linux-namespaces".to_string(),
                network_support: "none".to_string(),
                version: "0.1.0".to_string(),
            }
        }

        fn capability(&self) -> SubstrateCapability {
            self.capability()
        }

        async fn negotiate_capability(&self, _requested: CapabilityRequest) -> std::result::Result<CapabilityResponse, SubstrateError> {
            Err(SubstrateError::NotAvailable(
                "Linux substrate not supported on this platform".to_string()
            ))
        }
    }
}

/// Re-export the stub substrate for non-Linux platforms
#[cfg(not(target_os = "linux"))]
pub use stub_executor::LinuxSubstrateStub as LinuxSubstrate;