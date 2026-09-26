//! Error types for substrate-core

use thiserror::Error;

#[derive(Debug, thiserror::Error)]
pub enum SubstrateError {
    #[error("Unknown backend: {0}")]
    UnknownBackend(String),
    
    #[error("Unsupported platform: {0}")]
    UnsupportedPlatform(String),
    
    #[error("Capability negotiation failed: {0}")]
    CapabilityNegotiationFailed(String),
    
    #[error("Substrate not available: {0}")]
    NotAvailable(String),
    
    #[error("Execution failed: {0}")]
    ExecutionFailed(String),
    
    #[error("Resource limit exceeded: {0}")]
    ResourceLimitExceeded(String),
    
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
}