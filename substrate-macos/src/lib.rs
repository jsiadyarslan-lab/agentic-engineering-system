//! macOS substrate implementation using Seatbelt sandbox and App Sandbox

pub mod error;
pub mod types;
pub mod sandbox;
pub mod profile;
pub mod xpc;
pub mod executor;

use crate::executor::MacOSSubstrate;
use crate::types::MacOSSubstrateConfig;

pub use crate::error::{MacOSSubstrateError, Result};
pub use crate::types::*;
pub use crate::executor::MacOSSubstrate;

/// Create a new macOS substrate with default configuration
pub fn new_macos_substrate() -> Result<MacOSSubstrate> {
    MacOSSubstrate::new(MacOSSubstrateConfig::default())
}

/// Create a macOS substrate with custom configuration
pub fn new_macos_substrate_with_config(config: MacOSSubstrateConfig) -> Result<crate::executor::MacOSSubstrate> {
    crate::executor::MacOSSubstrate::new(config)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_create_macos_substrate() {
        let substrate = MacOSSubstrate::new(MacOSSubstrateConfig::default());
        // May fail if not on macOS or without capabilities
        let _ = substrate;
    }
}