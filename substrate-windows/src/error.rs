use thiserror::Error;

#[derive(Error, Debug)]
pub enum WindowsSubstrateError {
    #[error("Job Object error: {0}")]
    JobObject(String),

    #[error("Silo error: {0}")]
    Silo(String),

    #[error("AppContainer error: {0}")]
    AppContainer(String),

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

    #[error("Windows API error: {0}")]
    WindowsApi(#[from] windows::core::Error),

    #[error("Silo error: {0}")]
    SiloApi(String),

    #[error("AppContainer error: {0}")]
    AppContainerApi(String),

    #[error("Job Object error: {0}")]
    JobObjectApi(String),
}

pub type Result<T> = std::result::Result<T, WindowsSubstrateError>;