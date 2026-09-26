//! Unified Execution Limits and Resource Quotas for Agent-Hub Substrates
//!
//! This crate provides the canonical resource limit types used across all
//! execution substrates (Linux namespaces, Windows Job Objects, macOS Seatbelt,
//! Docker, Remote). It mirrors the Python `substrate.limits` module with
//! identical validation semantics.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use thiserror::Error;

/// Default execution limits (E1/D-13 owner-recorded defaults)
/// These are the ceiling defaults - requests may only LOWER limits, never raise them.
pub mod defaults {
    pub const TIMEOUT_SECONDS: u64 = 300;
    pub const VCPU: u32 = 2;
    pub const MEMORY_BYTES: u64 = 4 * 1024 * 1024 * 1024; // 4 GiB
    pub const MAX_PROCESSES: u32 = 32;
    pub const MAX_OUTPUT_BYTES: u64 = 10 * 1024 * 1024; // 10 MiB
    pub const MAX_ARTIFACT_BYTES: u64 = 100 * 1024 * 1024; // 100 MiB
    pub const MAX_WORKSPACE_BYTES: u64 = 1024 * 1024 * 1024; // 1 GiB
    pub const SANDBOX_NOFILE_LIMIT: u32 = 256;
}

/// Network isolation modes
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum NetworkMode {
    #[default]
    None,
    Egress,
    Ingress,
    EgressFiltered,
}

/// Execution termination status
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SandboxTermination {
    Completed,
    Failed,
    Timeout,
    LimitBreach,
    FailedToStart,
    NotRun,
}

/// Artifact custody entry
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArtifactCustodyEntry {
    pub path: String,
    pub sha256: String,
    pub size: u64,
    pub kind: String,
}

/// Substrate descriptor
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubstrateDescriptor {
    pub name: String,
    pub isolation_class: String,
    pub network_support: String,
    pub version: String,
}

/// Sandbox execution request
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SandboxRequest {
    pub sandbox_id: String,
    pub image: String,
    pub command: Vec<String>,
    pub limits: ExecutionLimits,
    pub env_names: std::collections::HashSet<String>,
    pub network: NetworkMode,
    pub workspace_root: String,
    pub artifacts_dir: String,
}

/// Sandbox execution record
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SandboxExecutionRecord {
    pub sandbox_id: String,
    pub executed: bool,
    pub exit_code: Option<i32>,
    pub termination: SandboxTermination,
    pub duration_ms: u64,
    pub stdout_reference: String,
    pub stderr_reference: String,
    pub limits_applied: ExecutionLimits,
    pub artifacts: Vec<ArtifactCustodyEntry>,
    pub started_at: f64,
    pub finished_at: f64,
}

/// Execution limits policy bound to a request or grant.
///
/// Fail-closed validation: structurally invalid values (non-positive, non-integer)
/// raise at construction time. Policy checks against defaults are performed by
/// `validate_against_defaults`, which never clamps and never raises.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExecutionLimits {
    /// Wall-clock timeout per execution (seconds)
    pub timeout_seconds: u64,
    /// CPU allocation (vCPU)
    pub vcpu: u32,
    /// Memory ceiling (bytes)
    pub memory_bytes: u64,
    /// Maximum process count inside the sandbox
    pub max_processes: u32,
    /// Combined stdout/stderr ceiling (bytes)
    pub max_output_bytes: u64,
    /// Per-execution artifact ceiling (bytes)
    pub max_artifact_bytes: u64,
    /// Workspace size ceiling (bytes)
    pub max_workspace_bytes: u64,
}

impl Default for ExecutionLimits {
    fn default() -> Self {
        Self {
            timeout_seconds: defaults::TIMEOUT_SECONDS,
            vcpu: defaults::VCPU,
            memory_bytes: defaults::MEMORY_BYTES,
            max_processes: defaults::MAX_PROCESSES,
            max_output_bytes: defaults::MAX_OUTPUT_BYTES,
            max_artifact_bytes: defaults::MAX_ARTIFACT_BYTES,
            max_workspace_bytes: defaults::MAX_WORKSPACE_BYTES,
        }
    }
}

impl ExecutionLimits {
    /// Create new execution limits with validation
    pub fn new(
        timeout_seconds: u64,
        vcpu: u32,
        memory_bytes: u64,
        max_processes: u32,
        max_output_bytes: u64,
        max_artifact_bytes: u64,
        max_workspace_bytes: u64,
    ) -> Result<Self, LimitsError> {
        Self::validate_field("timeout_seconds", timeout_seconds)?;
        Self::validate_field("vcpu", vcpu as u64)?;
        Self::validate_field("memory_bytes", memory_bytes)?;
        Self::validate_field("max_processes", max_processes as u64)?;
        Self::validate_field("max_output_bytes", max_output_bytes)?;
        Self::validate_field("max_artifact_bytes", max_artifact_bytes)?;
        Self::validate_field("max_workspace_bytes", max_workspace_bytes)?;

        Ok(Self {
            timeout_seconds,
            vcpu,
            memory_bytes,
            max_processes,
            max_output_bytes,
            max_artifact_bytes,
            max_workspace_bytes,
        })
    }

    /// Validate a single field is positive
    fn validate_field(name: &str, value: u64) -> Result<(), LimitsError> {
        if value == 0 {
            Err(LimitsError::InvalidField {
                field: name.to_string(),
                reason: "must be positive".to_string(),
            })
        } else {
            Ok(())
        }
    }

    /// Get the default limits (E1/D-13)
    pub fn defaults() -> Self {
        Self::default()
    }
}

/// Machine-readable reasons a limits request is rejected
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LimitsRejectionReason {
    /// A requested limit exceeds the D-13 default (never clamped)
    ExceedsDefaults,
    /// The limits object is structurally invalid
    Invalid,
}

/// Outcome of validating requested limits against defaults
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LimitsValidation {
    pub valid: bool,
    pub reason: Option<LimitsRejectionReason>,
    pub violations: Vec<String>,
}

impl LimitsValidation {
    /// Create a valid validation result
    pub fn valid() -> Self {
        Self {
            valid: true,
            reason: None,
            violations: Vec::new(),
        }
    }

    /// Create an invalid validation result (exceeds defaults)
    pub fn exceeds_defaults(violations: Vec<String>) -> Self {
        Self {
            valid: false,
            reason: Some(LimitsRejectionReason::ExceedsDefaults),
            violations,
        }
    }

    /// Create an invalid validation result (structurally invalid)
    pub fn invalid(violations: Vec<String>) -> Self {
        Self {
            valid: false,
            reason: Some(LimitsRejectionReason::Invalid),
            violations,
        }
    }

    /// Get human-readable detail
    pub fn detail(&self) -> String {
        if self.valid {
            "requested limits are within the defaults".to_string()
        } else if self.reason == Some(LimitsRejectionReason::ExceedsDefaults) {
            format!("exceeds defaults: {}", self.violations.join(", "))
        } else {
            "invalid limits".to_string()
        }
    }
}

/// Validate limits against the defaults (fail-closed, never clamps)
pub fn validate_against_defaults(limits: &ExecutionLimits) -> LimitsValidation {
    let mut violations = Vec::new();

    if limits.timeout_seconds > defaults::TIMEOUT_SECONDS {
        violations.push("timeout_seconds".to_string());
    }
    if limits.vcpu > defaults::VCPU {
        violations.push("vcpu".to_string());
    }
    if limits.memory_bytes > defaults::MEMORY_BYTES {
        violations.push("memory_bytes".to_string());
    }
    if limits.max_processes > defaults::MAX_PROCESSES {
        violations.push("max_processes".to_string());
    }
    if limits.max_output_bytes > defaults::MAX_OUTPUT_BYTES {
        violations.push("max_output_bytes".to_string());
    }
    if limits.max_artifact_bytes > defaults::MAX_ARTIFACT_BYTES {
        violations.push("max_artifact_bytes".to_string());
    }
    if limits.max_workspace_bytes > defaults::MAX_WORKSPACE_BYTES {
        violations.push("max_workspace_bytes".to_string());
    }

    if violations.is_empty() {
        LimitsValidation::valid()
    } else {
        LimitsValidation::exceeds_defaults(violations)
    }
}

/// Parse limits from a mapping (e.g., JSON request)
pub fn limits_from_mapping(values: Option<HashMap<String, serde_json::Value>>) -> Result<ExecutionLimits, LimitsError> {
    let mut limits = ExecutionLimits::default();

    if let Some(map) = values {
        for (key, value) in map {
            match key.as_str() {
                "timeout_seconds" => {
                    limits.timeout_seconds = value.as_u64().ok_or_else(|| LimitsError::InvalidField {
                        field: "timeout_seconds".to_string(),
                        reason: "must be an integer".to_string(),
                    })?;
                }
                "vcpu" => {
                    limits.vcpu = value.as_u64().ok_or_else(|| LimitsError::InvalidField {
                        field: "vcpu".to_string(),
                        reason: "must be an integer".to_string(),
                    })? as u32;
                }
                "memory_bytes" => {
                    limits.memory_bytes = value.as_u64().ok_or_else(|| LimitsError::InvalidField {
                        field: "memory_bytes".to_string(),
                        reason: "must be an integer".to_string(),
                    })?;
                }
                "max_processes" => {
                    limits.max_processes = value.as_u64().ok_or_else(|| LimitsError::InvalidField {
                        field: "max_processes".to_string(),
                        reason: "must be an integer".to_string(),
                    })? as u32;
                }
                "max_output_bytes" => {
                    limits.max_output_bytes = value.as_u64().ok_or_else(|| LimitsError::InvalidField {
                        field: "max_output_bytes".to_string(),
                        reason: "must be an integer".to_string(),
                    })?;
                }
                "max_artifact_bytes" => {
                    limits.max_artifact_bytes = value.as_u64().ok_or_else(|| LimitsError::InvalidField {
                        field: "max_artifact_bytes".to_string(),
                        reason: "must be an integer".to_string(),
                    })?;
                }
                "max_workspace_bytes" => {
                    limits.max_workspace_bytes = value.as_u64().ok_or_else(|| LimitsError::InvalidField {
                        field: "max_workspace_bytes".to_string(),
                        reason: "must be an integer".to_string(),
                    })?;
                }
                unknown => {
                    return Err(LimitsError::UnknownField(unknown.to_string()));
                }
            }
        }

        // Validate all fields are positive
        validate_all(&limits)?;
    }

    Ok(limits)
}

fn validate_all(limits: &ExecutionLimits) -> Result<(), LimitsError> {
    validate_field("timeout_seconds", limits.timeout_seconds)?;
    validate_field("vcpu", limits.vcpu as u64)?;
    validate_field("memory_bytes", limits.memory_bytes)?;
    validate_field("max_processes", limits.max_processes as u64)?;
    validate_field("max_output_bytes", limits.max_output_bytes)?;
    validate_field("max_artifact_bytes", limits.max_artifact_bytes)?;
    validate_field("max_workspace_bytes", limits.max_workspace_bytes)?;
    Ok(())
}

fn validate_field(name: &str, value: u64) -> Result<(), LimitsError> {
    if value == 0 {
        Err(LimitsError::InvalidField {
            field: name.to_string(),
            reason: "must be positive".to_string(),
        })
    } else {
        Ok(())
    }
}

/// Resource quotas for substrates (system-level resource allocations)
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ResourceQuotas {
    /// Maximum memory allocation for the substrate (bytes)
    pub max_memory_bytes: u64,
    /// Maximum CPU allocation (vCPU)
    pub max_vcpu: u32,
    /// Maximum concurrent sandboxes
    pub max_concurrent_sandboxes: u32,
    /// Maximum total processes across all sandboxes
    pub max_total_processes: u32,
    /// Maximum total output bytes across all sandboxes
    pub max_total_output_bytes: u64,
    /// Maximum total artifact bytes across all sandboxes
    pub max_total_artifact_bytes: u64,
    /// Maximum total workspace bytes across all sandboxes
    pub max_total_workspace_bytes: u64,
}

impl ResourceQuotas {
    /// Create default resource quotas for a substrate
    pub fn default_for_substrate(substrate_name: &str) -> Self {
        match substrate_name {
            "local-namespace-substrate" => Self {
                max_memory_bytes: 16 * 1024 * 1024 * 1024, // 16 GiB
                max_vcpu: 8,
                max_concurrent_sandboxes: 16,
                max_total_processes: 512,
                max_total_output_bytes: 100 * 1024 * 1024, // 100 MiB
                max_total_artifact_bytes: 1024 * 1024 * 1024, // 1 GiB
                max_total_workspace_bytes: 16 * 1024 * 1024 * 1024, // 16 GiB
            },
            "docker" => Self {
                max_memory_bytes: 32 * 1024 * 1024 * 1024, // 32 GiB
                max_vcpu: 16,
                max_concurrent_sandboxes: 32,
                max_total_processes: 1024,
                max_total_output_bytes: 500 * 1024 * 1024, // 500 MiB
                max_total_artifact_bytes: 10 * 1024 * 1024 * 1024, // 10 GiB
                max_total_workspace_bytes: 100 * 1024 * 1024 * 1024, // 100 GiB
            },
            _ => Self {
                max_memory_bytes: 8 * 1024 * 1024 * 1024, // 8 GiB
                max_vcpu: 4,
                max_concurrent_sandboxes: 8,
                max_total_processes: 256,
                max_total_output_bytes: 50 * 1024 * 1024, // 50 MiB
                max_total_artifact_bytes: 512 * 1024 * 1024, // 512 MiB
                max_total_workspace_bytes: 8 * 1024 * 1024 * 1024, // 8 GiB
            },
        }
    }
}

/// Capability request from agent to substrate
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CapabilityRequest {
    pub required: Vec<String>,
    pub preferred: Vec<String>,
    pub resource_limits: ExecutionLimits,
}

/// Capability response from substrate to agent
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CapabilityResponse {
    pub granted: Vec<String>,
    pub denied: Vec<String>,
    pub adjusted_limits: ExecutionLimits,
    pub substrate_type: String,
}

/// Errors for limits operations
#[derive(Debug, Error)]
pub enum LimitsError {
    #[error("invalid field '{field}': {reason}")]
    InvalidField { field: String, reason: String },
    #[error("unknown limit field: {0}")]
    UnknownField(String),
    #[error("validation failed: {0}")]
    ValidationFailed(String),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_defaults() {
        let limits = ExecutionLimits::default();
        assert_eq!(limits.timeout_seconds, defaults::TIMEOUT_SECONDS);
        assert_eq!(limits.vcpu, defaults::VCPU);
        assert_eq!(limits.memory_bytes, defaults::MEMORY_BYTES);
        assert_eq!(limits.max_processes, defaults::MAX_PROCESSES);
        assert_eq!(limits.max_output_bytes, defaults::MAX_OUTPUT_BYTES);
        assert_eq!(limits.max_artifact_bytes, defaults::MAX_ARTIFACT_BYTES);
        assert_eq!(limits.max_workspace_bytes, defaults::MAX_WORKSPACE_BYTES);
    }

    #[test]
    fn test_new_valid() {
        let limits = ExecutionLimits::new(60, 1, 1024 * 1024 * 1024, 16, 1024 * 1024, 10 * 1024 * 1024, 100 * 1024 * 1024);
        assert!(limits.is_ok());
    }

    #[test]
    fn test_new_invalid_zero() {
        let limits = ExecutionLimits::new(0, 1, 1024 * 1024 * 1024, 16, 1024 * 1024, 10 * 1024 * 1024, 100 * 1024 * 1024);
        assert!(limits.is_err());
        assert!(matches!(limits, Err(LimitsError::InvalidField { field, .. }) if field == "timeout_seconds"));
    }

    #[test]
    fn test_validate_against_defaults_valid() {
        let limits = ExecutionLimits::default();
        let result = validate_against_defaults(&limits);
        assert!(result.valid);
    }

    #[test]
    fn test_validate_against_defaults_exceeds() {
        let mut limits = ExecutionLimits::default();
        limits.timeout_seconds = defaults::TIMEOUT_SECONDS + 1;
        let result = validate_against_defaults(&limits);
        assert!(!result.valid);
        assert_eq!(result.reason, Some(LimitsRejectionReason::ExceedsDefaults));
        assert!(result.violations.contains(&"timeout_seconds".to_string()));
    }

    #[test]
    fn test_limits_from_mapping() {
        let mut map = HashMap::new();
        map.insert("timeout_seconds".to_string(), serde_json::Value::Number(60.into()));
        map.insert("max_processes".to_string(), serde_json::Value::Number(16.into()));
        
        let limits = limits_from_mapping(Some(map)).unwrap();
        assert_eq!(limits.timeout_seconds, 60);
        assert_eq!(limits.max_processes, 16);
        // Other fields should be defaults
        assert_eq!(limits.vcpu, defaults::VCPU);
    }

    #[test]
    fn test_limits_from_mapping_unknown_field() {
        let mut map = HashMap::new();
        map.insert("unknown_field".to_string(), serde_json::Value::Number(10.into()));
        
        let result = limits_from_mapping(Some(map));
        assert!(result.is_err());
        assert!(matches!(result, Err(LimitsError::UnknownField(_))));
    }

    #[test]
    fn test_resource_quotas_default() {
        let quotas = ResourceQuotas::default_for_substrate("local-namespace-substrate");
        assert_eq!(quotas.max_memory_bytes, 16 * 1024 * 1024 * 1024);
        assert_eq!(quotas.max_vcpu, 8);
        assert_eq!(quotas.max_concurrent_sandboxes, 16);
    }

    #[test]
    fn test_capability_request_response() {
        let request = CapabilityRequest {
            required: vec!["memory".to_string(), "cpu".to_string()],
            preferred: vec!["network".to_string()],
            resource_limits: ExecutionLimits::default(),
        };
        
        let response = CapabilityResponse {
            granted: vec!["memory".to_string(), "cpu".to_string()],
            denied: vec!["network".to_string()],
            adjusted_limits: ExecutionLimits::default(),
            substrate_type: "local-namespace-substrate".to_string(),
        };
        
        let request_json = serde_json::to_string(&request).unwrap();
        let response_json = serde_json::to_string(&response).unwrap();
        
        assert!(request_json.contains("memory"));
        assert!(response_json.contains("granted"));
    }
}