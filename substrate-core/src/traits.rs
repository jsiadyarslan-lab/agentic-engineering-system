//! Substrate traits

use async_trait::async_trait;
use crate::types::*;
use serde::{Deserialize, Serialize};

/// Substrate capability description
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubstrateCapability {
    pub name: String,
    pub isolation_class: String,
    pub network_support: String,
    pub resource_limits: ResourceLimits,
    pub supported_profiles: Vec<String>,
    pub max_concurrent_sandboxes: u32,
}

/// Resource limits supported by the substrate
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ResourceLimits {
    pub max_memory_bytes: Option<u64>,
    pub max_cpu_percent: Option<f64>,
    pub max_cpu_time_seconds: Option<u64>,
    pub max_processes: Option<u32>,
    pub max_file_size: Option<u64>,
    pub max_open_files: Option<u64>,
    pub max_wall_time_seconds: Option<u64>,
    pub max_output_bytes: Option<u64>,
    pub max_artifact_bytes: Option<u64>,
    pub max_workspace_bytes: Option<u64>,
}

/// Capability negotiation request
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CapabilityRequest {
    pub required: Vec<String>,
    pub preferred: Vec<String>,
    pub resource_limits: ExecutionLimits,
}

/// Capability negotiation response
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CapabilityResponse {
    pub granted: Vec<String>,
    pub denied: Vec<String>,
    pub adjusted_limits: ExecutionLimits,
    pub substrate_type: String,
}

/// Abstract Substrate trait - all substrate implementations must implement this
#[async_trait::async_trait]
pub trait Substrate: Send + Sync {
    /// Execute a sandbox request
    async fn execute(&self, request: SandboxRequest) -> Result<SandboxExecutionRecord, crate::error::SubstrateError>;
    
    /// Get substrate descriptor
    fn descriptor(&self) -> SubstrateDescriptor;
    
    /// Get substrate capability
    fn capability(&self) -> SubstrateCapability;
    
    /// Negotiate capabilities with the agent
    async fn negotiate_capability(&self, requested: CapabilityRequest) -> Result<CapabilityResponse, crate::error::SubstrateError>;
}