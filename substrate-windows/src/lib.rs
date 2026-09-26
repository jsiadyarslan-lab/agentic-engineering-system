//! Windows substrate implementation using Job Objects, Silos, and AppContainers

pub mod error;
pub mod types;
pub mod job_object;
pub mod silo;
pub mod appcontainer;
pub mod executor;

use crate::executor::WindowsSubstrate;
use crate::types::WindowsSubstrateConfig;

pub use crate::error::{WindowsSubstrateError, Result};
pub use crate::types::*;

/// Create a new Windows substrate with default configuration
pub fn new_windows_substrate() -> Result<WindowsSubstrate> {
    WindowsSubstrate::new(WindowsSubstrateConfig::default())
}

/// Create a Windows substrate with custom configuration
pub fn new_windows_substrate_with_config(config: WindowsSubstrateConfig) -> Result<crate::executor::WindowsSubstrate> {
    crate::executor::WindowsSubstrate::new(config)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_create_windows_substrate() {
        let substrate = WindowsSubstrate::new(WindowsSubstrateConfig::default());
        // May fail if not on Windows or without capabilities
        let _ = substrate;
    }
}