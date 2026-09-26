//! Core substrate types and traits shared across all substrate implementations

pub mod error;
pub mod types;
pub mod traits;

pub use error::SubstrateError;
pub use types::*;
pub use traits::Substrate;
pub use traits::SubstrateCapability;
pub use traits::ResourceLimits;
pub use traits::CapabilityRequest;
pub use traits::CapabilityResponse;

pub mod prelude {
    pub use crate::error::SubstrateError;
    pub use crate::types::*;
    pub use crate::traits::Substrate;
    pub use crate::traits::SubstrateCapability;
    pub use crate::traits::ResourceLimits;
    pub use crate::traits::CapabilityRequest;
    pub use crate::traits::CapabilityResponse;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_execution_limits_defaults() {
        let limits = crate::types::ExecutionLimits::default();
        assert_eq!(limits.memory_bytes(), 512 * 1024 * 1024);
        assert_eq!(limits.cpu_percent(), 100.0);
        assert_eq!(limits.cpu_time_seconds(), 300);
        assert_eq!(limits.max_processes(), 100);
        assert_eq!(limits.wall_time_seconds(), 600);
    }
}