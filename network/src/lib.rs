//! Network isolation modes and policy enforcement

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use thiserror::Error;

pub mod error;
pub mod policy;
pub mod isolator;
pub mod probes;

pub use error::NetworkError;
pub use policy::{NetworkPolicy, DnsPolicy, DnsPolicy as DnsPolicyEnum, NetworkMode};
pub use isolator::{NetworkIsolator, VerificationResult, ProbeResult};
pub use probes::{ProbeTarget, ProbeType, run_verification_probes};

// Re-export platform-specific isolators
#[cfg(target_os = "linux")]
pub use isolator::linux::LinuxNetworkIsolator;
#[cfg(target_os = "windows")]
pub use isolator::windows::WindowsNetworkIsolator;
#[cfg(target_os = "macos")]
pub use isolator::macos::MacosNetworkIsolator;
pub use isolator::docker::DockerNetworkIsolator;

/// Factory function to create the appropriate network isolator for the current platform
pub fn create_network_isolator() -> Box<dyn NetworkIsolator> {
    #[cfg(target_os = "linux")]
    return Box::new(isolator::linux::LinuxNetworkIsolator::new());
    
    #[cfg(target_os = "windows")]
    return Box::new(isolator::windows::WindowsNetworkIsolator::new());
    
    #[cfg(target_os = "macos")]
    return Box::new(isolator::macos::MacosNetworkIsolator::new());
    
    #[cfg(not(any(target_os = "linux", target_os = "windows", target_os = "macos")))]
    return Box::new(isolator::docker::DockerNetworkIsolator::new());
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_network_mode_serialization() {
        let modes = vec![
            NetworkMode::None,
            NetworkMode::Egress,
            NetworkMode::Ingress,
            NetworkMode::EgressFiltered,
        ];
        
        for mode in modes {
            let json = serde_json::to_string(&mode).unwrap();
            let deserialized: NetworkMode = serde_json::from_str(&json).unwrap();
            assert_eq!(mode, deserialized);
        }
    }
}