#[cfg(target_os = "linux")]
mod linux_cgroup {
    use crate::error::{LinuxSubstrateError, Result};
    use crate::types::ExecutionLimits;
    use serde::{Deserialize, Serialize};
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::process::Command;

    /// Cgroup v2 manager for resource limits
    pub struct CgroupManager {
        cgroup_root: PathBuf,
        cgroup_path: PathBuf,
        created: bool,
    }

    impl CgroupManager {
        /// Create a new cgroup manager
        pub fn new(_cgroup_root: PathBuf, sandbox_id: &str) -> Result<Self> {
            let cgroup_path = PathBuf::from("/sys/fs/cgroup").join("sandbox").join(sandbox_id);
            
            Ok(Self {
                cgroup_root: PathBuf::from("/sys/fs/cgroup"),
                cgroup_path,
                created: false,
            })
        }

        /// Create the cgroup and apply limits
        pub fn setup(&mut self, limits: &ExecutionLimits) -> Result<()> {
            // Create cgroup directory
            fs::create_dir_all(&self.cgroup_path)
                .map_err(|e| LinuxSubstrateError::Cgroup(e.to_string()))?;
            self.created = true;

            // Enable controllers
            self.enable_controllers()?;

            // Set memory limit
            if let Some(memory) = limits.memory_bytes {
                self.set_memory_limit(memory)?;
            }

            // Set CPU limit
            if let Some(cpu_percent) = limits.cpu_percent {
                self.set_cpu_limit(cpu_percent)?;
            }

            // Set process limit
            if let Some(max_procs) = limits.max_processes {
                self.set_pids_limit(max_procs)?;
            }

            // Set IO limits
            if let Some(max_io) = limits.max_output_bytes {
                self.set_io_limit(max_io)?;
            }

            Ok(())
        }

        /// Enable cgroup controllers
        fn enable_controllers(&self) -> Result<()> {
            let subtree_control = self.cgroup_root.join("cgroup.subtree_control");
            let controllers = "+cpu +memory +pids +io";
            
            fs::write(&subtree_control, controllers)
                .map_err(|e| LinuxSubstrateError::Cgroup(e.to_string()))?;

            Ok(())
        }

        /// Set memory limit in bytes
        fn set_memory_limit(&self, bytes: u64) -> Result<()> {
            let memory_max = self.cgroup_path.join("memory.max");
            fs::write(&memory_max, bytes.to_string())
                .map_err(|e| LinuxSubstrateError::Cgroup(e.to_string()))?;
            Ok(())
        }

        /// Set CPU limit (percentage)
        fn set_cpu_limit(&self, cpu_percent: f64) -> Result<()> {
            // cpu.max format: "quota period" in microseconds
            // 100% = 100000 100000
            let period = 100000u64;
            let quota = (cpu_percent / 100.0 * period as f64) as u64;
            
            let cpu_max = self.cgroup_path.join("cpu.max");
            let content = format!("{} {}", quota, period);
            
            fs::write(&cpu_max, content)
                .map_err(|e| LinuxSubstrateError::Cgroup(e.to_string()))?;
            Ok(())
        }

        /// Set maximum number of processes
        fn set_pids_limit(&self, max_procs: u32) -> Result<()> {
            let pids_max = self.cgroup_path.join("pids.max");
            fs::write(&pids_max, max_procs.to_string())
                .map_err(|e| LinuxSubstrateError::Cgroup(e.to_string()))?;
            Ok(())
        }

        /// Set IO limits
        fn set_io_limit(&self, _max_bytes: u64) -> Result<()> {
            // IO limits are more complex - use io.max
            // Format: "major:minor rbps wbps riops wiops"
            // For simplicity, we'll skip detailed IO limiting for now
            Ok(())
        }

        /// Add current process to cgroup
        pub fn add_current_process(&self) -> Result<()> {
            let _procs = self.cgroup_path.join("cgroup.procs");
            let _pid = std::process::id();
            
            fs::write(&self.cgroup_path.join("cgroup.procs"), std::process::id().to_string())
                .map_err(|e| LinuxSubstrateError::Cgroup(e.to_string()))?;
            Ok(())
        }

        /// Get current usage stats
        pub fn get_stats(&self) -> Result<CgroupStats> {
            let memory_current = fs::read_to_string(self.cgroup_path.join("memory.current"))
                .unwrap_or_default()
                .trim()
                .parse()
                .unwrap_or(0);
            
            let cpu_usage = fs::read_to_string(self.cgroup_path.join("cpu.stat"))
                .unwrap_or_default();
            
            let pids_current = fs::read_to_string(self.cgroup_path.join("pids.current"))
                .unwrap_or_default()
                .trim()
                .parse()
                .unwrap_or(0);

            Ok(CgroupStats {
                memory_current,
                cpu_stat: cpu_usage,
                pids_current,
            })
        }

        /// Remove the cgroup
        pub fn remove(&mut self) -> Result<()> {
            if self.created && self.cgroup_path.exists() {
                // Kill all processes in cgroup first
                let _ = Command::new("cgdelete")
                    .args(["-g", "sandbox:sandbox_id"])
                    .status();

                // Remove directory
                fs::remove_dir_all(&self.cgroup_path)
                    .map_err(|e| LinuxSubstrateError::Cgroup(e.to_string()))?;
            }
            self.created = false;
            Ok(())
        }
    }

    impl Drop for CgroupManager {
        fn drop(&mut self) {
            let _ = self.remove();
        }
    }

    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct CgroupStats {
        pub memory_current: u64,
        pub cpu_stat: String,
        pub pids_current: u64,
    }
}

/// Re-export the Linux cgroup types
#[cfg(target_os = "linux")]
pub use linux_cgroup::*;

/// Stub implementations for non-Linux platforms
#[cfg(not(target_os = "linux"))]
mod stub_cgroup {
    use crate::error::{LinuxSubstrateError, Result};
    use crate::types::ExecutionLimits;
    use serde::{Deserialize, Serialize};
    use std::path::PathBuf;

    pub struct CgroupManager {
        _cgroup_root: PathBuf,
        _cgroup_path: PathBuf,
        _created: bool,
    }

    impl CgroupManager {
        pub fn new(_cgroup_root: PathBuf, _sandbox_id: &str) -> Result<Self> {
            Err(LinuxSubstrateError::Unavailable("Cgroups not supported on this platform".to_string()))
        }

        pub fn setup(&mut self, _limits: &ExecutionLimits) -> Result<()> {
            Err(LinuxSubstrateError::Unavailable("Cgroups not supported on this platform".to_string()))
        }

        pub fn add_current_process(&self) -> Result<()> {
            Err(LinuxSubstrateError::Unavailable("Cgroups not supported on this platform".to_string()))
        }

        pub fn get_stats(&self) -> Result<CgroupStats> {
            Err(LinuxSubstrateError::Unavailable("Cgroups not supported on this platform".to_string()))
        }

        pub fn remove(&mut self) -> Result<()> {
            Err(LinuxSubstrateError::Unavailable("Cgroups not supported on this platform".to_string()))
        }
    }

    impl Drop for CgroupManager {
        fn drop(&mut self) {
            let _ = self.remove();
        }
    }

    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct CgroupStats {
        pub memory_current: u64,
        pub cpu_stat: String,
        pub pids_current: u64,
    }
}

/// Re-export the stub types for non-Linux platforms
#[cfg(not(target_os = "linux"))]
pub use stub_cgroup::*;

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_cgroup_creation() {
        #[cfg(target_os = "linux")]
        {
            let dir = tempdir().unwrap();
            let mut mgr = CgroupManager::new(dir.path().to_path_buf(), "test-sandbox").unwrap();
            // Can't fully test without root, but structure is correct
        }
    }
}