//! Execution module - substrate abstraction and orchestration

pub mod substrate;
pub mod substrate_factory;

pub use substrate::{
    Substrate, SubstrateDescriptor, SubstrateCapability, SubstrateError,
    SandboxRequest, SandboxExecutionRecord, CapabilityRequest, CapabilityResponse,
    ExecutionLimits, ResourceLimits, SubstrateCapability,
    SandboxRequest, SandboxExecutionRecord, CapabilityRequest, CapabilityResponse,
    ExecutionLimits, ResourceLimits, SubstrateCapability,
    SandboxTermination, ArtifactCustodyEntry, NetworkMode,
};

pub use substrate_factory::SubstrateFactory;

// Substrate implementations are in separate crates:
// - substrate_linux::LinuxSubstrate
// - substrate_windows::WindowsSubstrate
// - substrate_macos::MacOSSubstrate
// - substrate_docker::DockerSubstrate
// - substrate_remote::RemoteSubstrate
// - substrate_core::TestSubstrate (for testing)