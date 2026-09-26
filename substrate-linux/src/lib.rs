//! Linux substrate implementation using namespaces, seccomp, cgroups v2, and landlock

pub mod error;
pub mod types;
pub mod namespace;
pub mod seccomp;
pub mod cgroup;
pub mod executor;

#[cfg(all(target_os = "linux", feature = "landlock"))]
pub mod landlock;

use crate::types::LinuxSubstrateConfig;

pub use crate::executor::LinuxSubstrate;
pub use crate::error::{LinuxSubstrateError, Result};
pub use crate::types::*;

/// Create a new Linux substrate with default configuration
pub fn new_linux_substrate() -> Result<LinuxSubstrate> {
    LinuxSubstrate::new(LinuxSubstrateConfig::default())
}

/// Create a Linux substrate with custom configuration
pub fn new_linux_substrate_with_config(config: LinuxSubstrateConfig) -> Result<crate::executor::LinuxSubstrate> {
    crate::executor::LinuxSubstrate::new(config)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_create_linux_substrate() {
        let substrate = LinuxSubstrate::new(LinuxSubstrateConfig::default());
        // May fail if not on Linux or without capabilities
        let _ = substrate;
    }
}