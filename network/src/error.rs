//! Network isolation errors

use thiserror::Error;

#[derive(Error, Debug)]
pub enum NetworkError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    
    #[error("Policy error: {0}")]
    Policy(String),
    
    #[error("Isolation not supported: {0}")]
    Unsupported(String),
    
    #[error("Permission denied: {0}")]
    PermissionDenied(String),
    
    #[error("Firewall error: {0}")]
    Firewall(String),
    
    #[error("Command failed: {0}")]
    CommandFailed(String),
    
    #[error("DNS error: {0}")]
    Dns(String),
    
    #[error("Verification failed: {0}")]
    VerificationFailed(String),
    
    #[error("Unsupported platform: {0}")]
    UnsupportedPlatform(String),
    
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
    
    #[error("Parse error: {0}")]
    Parse(#[from] std::net::AddrParseError),
}