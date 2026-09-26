//! Substrate factory for creating platform-specific substrate implementations

use crate::substrate::{
    Substrate, SubstrateDescriptor, SubstrateCapability, SubstrateError,
    SandboxRequest, SandboxExecutionRecord, CapabilityRequest, CapabilityResponse,
    ExecutionLimits, SubstrateDescriptor as CoreSubstrateDescriptor,
};
use async_trait::async_trait;
use std::sync::Arc;

/// Substrate factory for creating platform-specific substrate implementations
pub struct SubstrateFactory;

impl SubstrateFactory {
    /// Create a substrate based on the backend name
    /// 
    /// Supported backends:
    /// - "auto" - Auto-detect platform
    /// - "linux" - Linux substrate (namespaces, seccomp, cgroups)
    /// - "windows" - Windows substrate (Job Objects, Silos, AppContainers)
    /// - "macos" - macOS substrate (Seatbelt, App Sandbox)
    /// - "docker" - Docker substrate (containerized execution)
    /// - "remote" - Remote worker substrate (distributed execution)
    pub fn get_substrate(backend: &str) -> Result<Box<dyn Substrate>, SubstrateError> {
        match backend {
            "auto" => Self::detect_and_create(),
            "linux" => Ok(Box::new(substrate_linux::LinuxSubstrate::new(Default::default())?)),
            "windows" => Ok(Box::new(substrate_windows::WindowsSubstrate::new(Default::default())?)),
            "macos" => Ok(Box::new(substrate_macos::MacOSSubstrate::new(Default::default())?)),
            "docker" => Ok(Box::new(substrate_docker::DockerSubstrate::new(Default::default())?)),
            "remote" => Ok(Box::new(substrate_remote::RemoteSubstrate::new(Default::default())?)),
            _ => Err(SubstrateError::UnknownBackend(backend.to_string())),
        }
    }

    /// Auto-detect platform and create appropriate substrate
    fn detect_and_create() -> Result<Box<dyn Substrate>, SubstrateError> {
        #[cfg(target_os = "linux")]
        {
            return Ok(Box::new(substrate_linux::LinuxSubstrate::new(Default::default())?));
        }
        
        #[cfg(target_os = "windows")]
        {
            return Ok(Box::new(substrate_windows::WindowsSubstrate::new(Default::default())?));
        }
        
        #[cfg(target_os = "macos")]
        {
            return Ok(Box::new(substrate_macos::MacOSSubstrate::new(Default::default())?));
        }
        
        #[cfg(not(any(target_os = "linux", target_os = "windows", target_os = "macos")))]
        {
            return Err(SubstrateError::UnsupportedPlatform(
                format!("Unsupported platform: {}", std::env::consts::OS)
            ));
        }
    }
}

/// Test substrate for testing purposes
#[cfg(test)]
pub struct TestSubstrate {
    descriptor: SubstrateDescriptor,
}

#[cfg(test)]
impl TestSubstrate {
    pub fn new() -> Self {
        Self {
            descriptor: SubstrateDescriptor {
                name: "test".to_string(),
                isolation_class: "test".to_string(),
                network_support: "none".to_string(),
                version: "0.1.0".to_string(),
            },
        }
    }
}

#[cfg(test)]
#[async_trait]
impl Substrate for TestSubstrate {
    async fn execute(&self, _request: crate::substrate::SandboxRequest) -> Result<crate::substrate::SandboxExecutionRecord, crate::substrate::SubstrateError> {
        Ok(crate::substrate::SandboxExecutionRecord {
            sandbox_id: "test".to_string(),
            executed: true,
            exit_code: Some(0),
            termination: crate::substrate::SandboxTermination::Completed,
            duration_ms: 100,
            stdout_reference: "test".to_string(),
            stderr_reference: String::new(),
            limits_applied: crate::substrate::ExecutionLimits::default(),
            artifacts: vec![],
            started_at: 0.0,
            finished_at: 1.0,
        })
    }

    fn descriptor(&self) -> SubstrateDescriptor {
        self.descriptor.clone()
    }

    fn capability(&self) -> crate::substrate::SubstrateCapability {
        crate::substrate::SubstrateCapability {
            name: "test".to_string(),
            isolation_class: "test".to_string(),
            network_support: "none".to_string(),
            resource_limits: crate::substrate::ResourceLimits::default(),
            supported_profiles: vec!["test".to_string()],
            max_concurrent_sandboxes: 10,
        }
    }

    async fn negotiate_capability(&self, _requested: crate::substrate::CapabilityRequest) -> Result<crate::substrate::CapabilityResponse, crate::substrate::SubstrateError> {
        Ok(crate::substrate::CapabilityResponse {
            granted: vec!["test".to_string()],
            denied: vec![],
            adjusted_limits: crate::substrate::ExecutionLimits::default(),
            substrate_type: "test".to_string(),
        })
    }
}