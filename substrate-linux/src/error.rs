use thiserror::Error;

#[derive(Error, Debug)]
pub enum LinuxSubstrateError {
    #[error("Namespace creation failed: {0}")]
    Namespace(String),

    #[error("Seccomp error: {0}")]
    Seccomp(String),

    #[error("Cgroup error: {0}")]
    Cgroup(String),

    #[error("Landlock error: {0}")]
    Landlock(String),

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
}

pub type Result<T> = std::result::Result<T, LinuxSubstrateError>;