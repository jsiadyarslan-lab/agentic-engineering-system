use thiserror::Error;

#[derive(Error, Debug)]
pub enum MacOSSubstrateError {
    #[error("Sandbox error: {0}")]
    Sandbox(String),

    #[error("Profile error: {0}")]
    Profile(String),

    #[error("XPC error: {0}")]
    XPC(String),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Process execution failed: {0}")]
    Execution(String),

    #[error("Resource limit exceeded: {0}")]
    ResourceLimit(String),

    #[error("Configuration error: {0}")]
    Config(String),

    #[error("Substrate not available: {0}")]
    Unavailable(String),

    #[error("Entitlements error: {0}")]
    Entitlements(String),

    #[error("Sandbox profile error: {0}")]
    ProfileError(String),

    #[error("XPC connection error: {0}")]
    XPCConnection(String),

    #[error("Entitlements error: {0}")]
    EntitlementsError(String),

    #[error("Sandbox profile error: {0}")]
    SandboxProfileError(String),
}

pub type Result<T> = std::result::Result<T, MacOSSubstrateError>;