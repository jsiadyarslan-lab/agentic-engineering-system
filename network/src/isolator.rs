//! Network isolator trait and platform-specific implementations

use crate::policy::NetworkPolicy;
use crate::error::NetworkError;
use substrate_core::NetworkMode;
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::{Arc, RwLock};

/// Verification result for network isolation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VerificationResult {
    pub success: bool,
    pub egress_test: ProbeResult,
    pub ingress_test: ProbeResult,
    pub dns_test: ProbeResult,
    pub details: String,
}

/// Individual probe result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProbeResult {
    pub allowed: bool,
    pub target: String,
    pub latency_ms: u64,
    pub error: Option<String>,
}

/// Network isolator trait - platform-specific implementations
#[async_trait]
pub trait NetworkIsolator: Send + Sync {
    /// Apply network policy
    async fn apply_policy(&self, policy: &crate::policy::NetworkPolicy) -> Result<(), crate::error::NetworkError>;
    
    /// Remove network policy
    async fn remove_policy(&self, policy_id: &str) -> Result<(), crate::error::NetworkError>;
    
    /// Verify network isolation
    async fn verify_isolation(&self, policy: &crate::policy::NetworkPolicy) -> Result<VerificationResult, crate::error::NetworkError>;
    
    /// Get supported network modes
    fn supported_modes(&self) -> Vec<NetworkMode>;
    
    /// Apply NetworkMode::None (no restrictions)
    async fn apply_mode_none(&self) -> Result<(), crate::error::NetworkError>;
    
    /// Apply NetworkMode::Egress (allow egress, block ingress)
    async fn apply_egress_only(&self) -> Result<(), crate::error::NetworkError>;
    
    /// Apply NetworkMode::Ingress (allow ingress, block egress)
    async fn apply_ingress_only(&self) -> Result<(), crate::error::NetworkError>;
    
    /// Apply NetworkMode::EgressFiltered (filtered egress)
    async fn apply_filtered_egress(&self, policy: &crate::policy::NetworkPolicy) -> Result<(), crate::error::NetworkError>;
}

/// Base implementation for common functionality
pub struct BaseNetworkIsolator {
    pub active_policies: Arc<RwLock<HashMap<String, crate::policy::NetworkPolicy>>>,
}

impl BaseNetworkIsolator {
    pub fn new() -> Self {
        Self {
            active_policies: Arc::new(RwLock::new(HashMap::new())),
        }
    }
    
    pub fn store_policy(&self, policy_id: String, policy: crate::policy::NetworkPolicy) {
        self.active_policies.write().unwrap().insert(policy_id, policy);
    }
    
    pub fn remove_policy(&self, policy_id: &str) -> Option<crate::policy::NetworkPolicy> {
        self.active_policies.write().unwrap().remove(policy_id)
    }
    
    pub fn get_policy(&self, policy_id: &str) -> Option<crate::policy::NetworkPolicy> {
        self.active_policies.read().unwrap().get(policy_id).cloned()
    }
}

#[cfg(target_os = "linux")]
pub mod linux {
    use super::*;
    use crate::policy::NetworkPolicy;
    use crate::error::NetworkError;
    use std::process::Stdio;
    use tokio::process::Command;
    
    pub struct LinuxNetworkIsolator {
        base: super::BaseNetworkIsolator,
        table_name: String,
    pub struct LinuxNetworkIsolator {
        base: super::BaseNetworkIsolator,
        table_name: String,
    }
    
    impl LinuxNetworkIsolator {
        pub fn new() -> Self {
            Self { 
                base: super::BaseNetworkIsolator::new(),
                table_name: "agenthub_netiso".to_string(),
            }
        }
        
        /// Execute nft command with args
        async fn nft(&self, args: &[&str]) -> Result<String, NetworkError> {
            let output = Command::new("nft")
                .args(args)
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .output()
                .await
                .map_err(|e| NetworkError::CommandFailed(format!("Failed to execute nft: {}", e)))?;
            
            if !output.status.success() {
                let stderr = String::from_utf8_lossy(&output.stderr);
                return Err(NetworkError::CommandFailed(format!("nft failed: {}", stderr)));
            }
            
            Ok(String::from_utf8_lossy(&output.stdout).to_string())
        }
        
        /// Ensure our nftables table and base chains exist
        async fn ensure_table(&self) -> Result<(), NetworkError> {
            // Create table if not exists
            let _ = self.nft(&["add", "table", "inet", &self.table_name]).await;
            
            // Create base chains
            let _ = self.nft(&[
                "add", "chain", "inet", &self.table_name, "egress",
                "{", "type", "filter", "hook", "output", "priority", "0", ";", "policy", "accept", ";", "}"
            ]).await;
            
            let _ = self.nft(&[
                "add", "chain", "inet", &self.table_name, "ingress",
                "{", "type", "filter", "hook", "input", "priority", "0", ";", "policy", "accept", ";", "}"
            ]).await;
            
            // Create our policy chains (will hold our rules)
            let _ = self.nft(&[
                "add", "chain", "inet", &self.table_name, "egress_policy",
                "{", "type", "filter", "hook", "output", "priority", "10", ";", "policy", "accept", ";", "}"
            ]).await;
            
            let _ = self.nft(&[
                "add", "chain", "inet", &self.table_name, "ingress_policy",
                "{", "type", "filter", "hook", "input", "priority", "10", ";", "policy", "accept", ";", "}"
            ]).await;
            
            // Jump from base chains to policy chains
            let _ = self.nft(&[
                "add", "rule", "inet", &self.table_name, "egress",
                "jump", "egress_policy"
            ]).await;
            
            let _ = self.nft(&[
                "add", "rule", "inet", &self.table_name, "ingress",
                "jump", "ingress_policy"
            ]).await;
            
            Ok(())
        }
        
        /// Clear all rules from policy chains
        async fn clear_policy_chains(&self) -> Result<(), NetworkError> {
            let _ = self.nft(&["flush", "chain", "inet", &self.table_name, "egress_policy"]).await;
            let _ = self.nft(&["flush", "chain", "inet", &self.table_name, "ingress_policy"]).await;
            Ok(())
        }
        
        /// Remove our table entirely
        async fn remove_all(&self) -> Result<(), NetworkError> {
            let _ = self.nft(&["delete", "table", "inet", &self.table_name]).await;
            Ok(())
        }
    }
    
    #[async_trait::async_trait]
    impl super::NetworkIsolator for LinuxNetworkIsolator {
        async fn apply_policy(&self, policy: &crate::policy::NetworkPolicy) -> Result<(), crate::error::NetworkError> {
            // Store policy
            self.base.store_policy(policy.policy_id.clone(), policy.clone());
            
            // Ensure table exists
            self.ensure_table().await?;
            
            // Apply based on mode
            match policy.mode {
                crate::policy::NetworkMode::None => {
                    self.apply_mode_none().await?;
                }
                crate::policy::NetworkMode::Egress => {
                    self.apply_egress_only().await?;
                }
                crate::policy::NetworkMode::Ingress => {
                    self.apply_ingress_only().await?;
                }
                crate::policy::NetworkMode::EgressFiltered => {
                    self.apply_filtered_egress(policy).await?;
                }
            }
            
            self.base.store_policy(policy.policy_id.clone(), policy.clone());
            Ok(())
        }
        
        async fn apply_mode_none(&self) -> Result<(), crate::error::NetworkError> {
            self.clear_policy_chains().await?;
            Ok(())
        }
        
        async fn apply_egress_only(&self) -> Result<(), crate::error::NetworkError> {
            self.clear_policy_chains().await?;
            
            // Egress: accept all (default policy is accept, so no rules needed)
            // Ingress: drop all
            self.nft(&[
                "add", "rule", "inet", &self.table_name, "ingress_policy",
                "drop"
            ]).await?;
            
            Ok(())
        }
        
        async fn apply_ingress_only(&self) -> Result<(), crate::error::NetworkError> {
            self.clear_policy_chains().await?;
            
            // Egress: drop all
            self.nft(&[
                "add", "rule", "inet", &self.table_name, "egress_policy",
                "drop"
            ]).await?;
            
            // Ingress: accept all (default policy is accept)
            Ok(())
        }
        
        async fn apply_filtered_egress(&self, policy: &crate::policy::NetworkPolicy) -> Result<(), crate::error::NetworkError> {
            self.clear_policy_chains().await?;
            
            // Ingress: drop all by default for filtered mode
            self.nft(&[
                "add", "rule", "inet", &self.table_name, "ingress_policy",
                "drop"
            ]).await?;
            
            // Egress: default drop, then add allow rules
            self.nft(&[
                "add", "rule", "inet", &self.table_name, "egress_policy",
                "drop"
            ]).await?;
            
            // Add allowlist rules (CIDR or IP)
            for cidr in &policy.egress_allowlist {
                if cidr.contains('/') {
                    // CIDR notation
                    self.nft(&[
                        "insert", "rule", "inet", &self.table_name, "egress_policy",
                        "ip", "daddr", cidr, "accept"
                    ]).await?;
                } else {
                    // Single IP
                    self.nft(&[
                        "insert", "rule", "inet", &self.table_name, "egress_policy",
                        "ip", "daddr", cidr, "accept"
                    ]).await?;
                }
            }
            
            // Add denylist rules (insert before allow for precedence)
            for cidr in &policy.egress_denylist {
                self.nft(&[
                    "insert", "rule", "inet", &self.table_name, "egress_policy",
                    "ip", "daddr", cidr, "drop"
                ]).await?;
            }
            
            // Allow localhost and private networks by default for functionality
            let defaults = ["127.0.0.1/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"];
            for cidr in defaults {
                self.nft(&[
                    "insert", "rule", "inet", &self.table_name, "egress_policy",
                    "ip", "daddr", cidr, "accept"
                ]).await?;
            }
            
            Ok(())
        }
        
        async fn remove_policy(&self, policy_id: &str) -> Result<(), crate::error::NetworkError> {
            self.base.remove_policy(policy_id);
            Ok(())
        }
        
        async fn verify_isolation(&self, policy: &crate::policy::NetworkPolicy) -> Result<crate::isolator::VerificationResult, crate::error::NetworkError> {
            let results = crate::probes::run_verification_probes(policy).await;
            Ok(results)
        }
        
        fn supported_modes(&self) -> Vec<NetworkMode> {
            vec![
                NetworkMode::None,
                NetworkMode::Egress,
                NetworkMode::Ingress,
                NetworkMode::EgressFiltered,
            ]
        }
        
        async fn apply_mode_none(&self) -> Result<(), crate::error::NetworkError> {
            self.clear_policy_chains().await?;
            Ok(())
        }
        
        async fn apply_egress_only(&self) -> Result<(), crate::error::NetworkError> {
            self.clear_policy_chains().await?;
            
            // Egress: accept all (default policy is accept, so no rules needed)
            // Ingress: drop all
            self.nft(&[
                "add", "rule", "inet", &self.table_name, "ingress_policy",
                "drop"
            ]).await?;
            
            Ok(())
        }
        
        async fn apply_ingress_only(&self) -> Result<(), crate::error::NetworkError> {
            self.clear_policy_chains().await?;
            
            // Egress: drop all
            self.nft(&[
                "add", "rule", "inet", &self.table_name, "egress_policy",
                "drop"
            ]).await?;
            
            // Ingress: accept all (default policy is accept)
            Ok(())
        }
        
        async fn apply_filtered_egress(&self, policy: &crate::policy::NetworkPolicy) -> Result<(), crate::error::NetworkError> {
            self.clear_policy_chains().await?;
            
            // Ingress: drop all by default for filtered mode
            self.nft(&[
                "add", "rule", "inet", &self.table_name, "ingress_policy",
                "drop"
            ]).await?;
            
            // Egress: default drop, then add allow rules
            self.nft(&[
                "add", "rule", "inet", &self.table_name, "egress_policy",
                "drop"
            ]).await?;
            
            // Add allowlist rules (CIDR or IP)
            for cidr in &policy.egress_allowlist {
                if cidr.contains('/') {
                    // CIDR notation
                    self.nft(&[
                        "insert", "rule", "inet", &self.table_name, "egress_policy",
                        "ip", "daddr", cidr, "accept"
                    ]).await?;
                } else {
                    // Single IP
                    self.nft(&[
                        "insert", "rule", "inet", &self.table_name, "egress_policy",
                        "ip", "daddr", cidr, "accept"
                    ]).await?;
                }
            }
            
            // Add denylist rules (insert before allow for precedence)
            for cidr in &policy.egress_denylist {
                self.nft(&[
                    "insert", "rule", "inet", &self.table_name, "egress_policy",
                    "ip", "daddr", cidr, "drop"
                ]).await?;
            }
            
            // Allow localhost and private networks by default for functionality
            let defaults = ["127.0.0.1/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"];
            for cidr in defaults {
                self.nft(&[
                    "insert", "rule", "inet", &self.table_name, "egress_policy",
                    "ip", "daddr", cidr, "accept"
                ]).await?;
            }
            
            Ok(())
        }
        
        async fn remove_policy(&self, policy_id: &str) -> Result<(), crate::error::NetworkError> {
            self.base.remove_policy(policy_id);
            Ok(())
        }
        
        async fn verify_isolation(&self, policy: &crate::policy::NetworkPolicy) -> Result<crate::isolator::VerificationResult, crate::error::NetworkError> {
            let results = crate::probes::run_verification_probes(policy).await;
            Ok(results)
        }
        
        fn supported_modes(&self) -> Vec<NetworkMode> {
            vec![
                NetworkMode::None,
                NetworkMode::Egress,
                NetworkMode::Ingress,
                NetworkMode::EgressFiltered,
            ]
        }
        
        async fn apply_mode_none(&self) -> Result<(), crate::error::NetworkError> {
            self.clear_policy_chains().await?;
            Ok(())
        }
        
        async fn apply_egress_only(&self) -> Result<(), crate::error::NetworkError> {
            self.clear_policy_chains().await?;
            
            // Egress: accept all (default policy is accept, so no rules needed)
            // Ingress: drop all
            self.nft(&[
                "add", "rule", "inet", &self.table_name, "ingress_policy",
                "drop"
            ]).await?;
            
            Ok(())
        }
        
        async fn apply_ingress_only(&self) -> Result<(), crate::error::NetworkError> {
            self.clear_policy_chains().await?;
            
            // Egress: drop all
            self.nft(&[
                "add", "rule", "inet", &self.table_name, "egress_policy",
                "drop"
            ]).await?;
            
            // Ingress: accept all (default policy is accept)
            Ok(())
        }
        
        async fn apply_filtered_egress(&self, policy: &crate::policy::NetworkPolicy) -> Result<(), crate::error::NetworkError> {
            self.clear_policy_chains().await?;
            
            // Ingress: drop all by default for filtered mode
            self.nft(&[
                "add", "rule", "inet", &self.table_name, "ingress_policy",
                "drop"
            ]).await?;
            
            // Egress: default drop, then add allow rules
            self.nft(&[
                "add", "rule", "inet", &self.table_name, "egress_policy",
                "drop"
            ]).await?;
            
            // Add allowlist rules (CIDR or IP)
            for cidr in &policy.egress_allowlist {
                if cidr.contains('/') {
                    // CIDR notation
                    self.nft(&[
                        "insert", "rule", "inet", &self.table_name, "egress_policy",
                        "ip", "daddr", cidr, "accept"
                    ]).await?;
                } else {
                    // Single IP
                    self.nft(&[
                        "insert", "rule", "inet", &self.table_name, "egress_policy",
                        "ip", "daddr", cidr, "accept"
                    ]).await?;
                }
            }
            
            // Add denylist rules (insert before allow for precedence)
            for cidr in &policy.egress_denylist {
                self.nft(&[
                    "insert", "rule", "inet", &self.table_name, "egress_policy",
                    "ip", "daddr", cidr, "drop"
                ]).await?;
            }
            
            // Allow localhost and private networks by default for functionality
            let defaults = ["127.0.0.1/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"];
            for cidr in defaults {
                self.nft(&[
                    "insert", "rule", "inet", &self.table_name, "egress_policy",
                    "ip", "daddr", cidr, "accept"
                ]).await?;
            }
            
            Ok(())
        }
        
        async fn remove_policy(&self, policy_id: &str) -> Result<(), crate::error::NetworkError> {
            self.base.remove_policy(policy_id);
            Ok(())
        }
        
        async fn verify_isolation(&self, policy: &crate::policy::NetworkPolicy) -> Result<crate::isolator::VerificationResult, crate::error::NetworkError> {
            let results = crate::probes::run_verification_probes(policy).await;
            Ok(results)
        }
        
        fn supported_modes(&self) -> Vec<NetworkMode> {
            vec![
                NetworkMode::None,
                NetworkMode::Egress,
                NetworkMode::Ingress,
                NetworkMode::EgressFiltered,
            ]
        }
    }
}

/// Re-export the Linux network isolator
#[cfg(target_os = "linux")]
pub use linux::*;

/// Windows implementation (stub)
#[cfg(target_os = "windows")]
pub mod windows {
    use super::*;
    use crate::policy::NetworkPolicy;
    use crate::error::NetworkError;
    
    pub struct WindowsNetworkIsolator {
        base: super::BaseNetworkIsolator,
    }
    
    impl WindowsNetworkIsolator {
        pub fn new() -> Self {
            Self { base: super::BaseNetworkIsolator::new() }
        }
    }
    
    #[async_trait::async_trait]
    impl super::NetworkIsolator for WindowsNetworkIsolator {
        async fn apply_policy(&self, policy: &crate::policy::NetworkPolicy) -> Result<(), crate::error::NetworkError> {
            // Store policy
            self.base.store_policy(policy.policy_id.clone(), policy.clone());
            
            // Apply based on mode (stub - Windows uses WFP)
            match policy.mode {
                crate::policy::NetworkMode::None => {
                    self.apply_mode_none().await?;
                }
                crate::policy::NetworkMode::Egress => {
                    self.apply_egress_only().await?;
                }
                crate::policy::NetworkMode::Ingress => {
                    self.apply_ingress_only().await?;
                }
                crate::policy::NetworkMode::EgressFiltered => {
                    self.apply_filtered_egress(policy).await?;
                }
            }
            
            self.base.store_policy(policy.policy_id.clone(), policy.clone());
            Ok(())
        }
        
        async fn apply_mode_none(&self) -> Result<(), crate::error::NetworkError> {
            // No restrictions - remove all our filters
            Ok(())
        }
        
        async fn apply_egress_only(&self) -> Result<(), crate::error::NetworkError> {
            // Allow all egress, block all ingress (stub - Windows uses WFP)
            Ok(())
        }
        
        async fn apply_ingress_only(&self) -> Result<(), crate::error::NetworkError> {
            // Allow ingress, block egress (stub)
            Ok(())
        }
        
        async fn apply_filtered_egress(&self, _policy: &crate::policy::NetworkPolicy) -> Result<(), crate::error::NetworkError> {
            // Allow egress only to allowed destinations (stub - Windows uses WFP)
            Ok(())
        }
        
        async fn remove_policy(&self, policy_id: &str) -> Result<(), crate::error::NetworkError> {
            self.base.remove_policy(policy_id);
            Ok(())
        }
        
        async fn verify_isolation(&self, policy: &crate::policy::NetworkPolicy) -> Result<crate::isolator::VerificationResult, crate::error::NetworkError> {
            let results = crate::probes::run_verification_probes(policy).await;
            Ok(results)
        }
        
        fn supported_modes(&self) -> Vec<NetworkMode> {
            vec![
                NetworkMode::None,
                NetworkMode::Egress,
                NetworkMode::Ingress,
                NetworkMode::EgressFiltered,
            ]
        }
    }
}

/// macOS implementation (stub)
#[cfg(target_os = "macos")]
pub mod macos {
    use super::*;
    use crate::policy::NetworkPolicy;
    use crate::error::NetworkError;
    
    pub struct MacosNetworkIsolator {
        base: super::BaseNetworkIsolator,
    }
    
    impl MacosNetworkIsolator {
        pub fn new() -> Self {
            Self { base: super::BaseNetworkIsolator::new() }
        }
    }
    
    #[async_trait::async_trait]
    impl super::NetworkIsolator for MacosNetworkIsolator {
        async fn apply_policy(&self, policy: &crate::policy::NetworkPolicy) -> Result<(), crate::error::NetworkError> {
            // Use PF (Packet Filter) on macOS (stub)
            self.base.store_policy(policy.policy_id.clone(), policy.clone());
            Ok(())
        }
        
        async fn remove_policy(&self, policy_id: &str) -> Result<(), crate::error::NetworkError> {
            self.base.remove_policy(policy_id);
            Ok(())
        }
        
        async fn verify_isolation(&self, policy: &crate::policy::NetworkPolicy) -> Result<crate::isolator::VerificationResult, crate::error::NetworkError> {
            let results = crate::probes::run_verification_probes(policy).await;
            Ok(results)
        }
        
        fn supported_modes(&self) -> Vec<NetworkMode> {
            vec![
                NetworkMode::None,
                NetworkMode::Egress,
                NetworkMode::Ingress,
                NetworkMode::EgressFiltered,
            ]
        }
        
        async fn apply_mode_none(&self) -> Result<(), crate::error::NetworkError> {
            Ok(())
        }
        
        async fn apply_egress_only(&self) -> Result<(), crate::error::NetworkError> {
            Ok(())
        }
        
        async fn apply_ingress_only(&self) -> Result<(), crate::error::NetworkError> {
            Ok(())
        }
        
        async fn apply_filtered_egress(&self, _policy: &crate::policy::NetworkPolicy) -> Result<(), crate::error::NetworkError> {
            Ok(())
        }
        
        async fn remove_policy(&self, policy_id: &str) -> Result<(), crate::error::NetworkError> {
            self.base.remove_policy(policy_id);
            Ok(())
        }
        
        async fn verify_isolation(&self, policy: &crate::policy::NetworkPolicy) -> Result<crate::isolator::VerificationResult, crate::error::NetworkError> {
            let results = crate::probes::run_verification_probes(policy).await;
            Ok(results)
        }
        
        fn supported_modes(&self) -> Vec<NetworkMode> {
            vec![
                NetworkMode::None,
                NetworkMode::Egress,
                NetworkMode::Ingress,
                NetworkMode::EgressFiltered,
            ]
        }
    }
}

pub mod docker {
    use super::*;
    use crate::policy::NetworkPolicy;
    use crate::error::NetworkError;
    
    pub struct DockerNetworkIsolator {
        base: super::BaseNetworkIsolator,
    }
    
    impl DockerNetworkIsolator {
        pub fn new() -> Self {
            Self { base: super::BaseNetworkIsolator::new() }
        }
    }
    
    #[async_trait::async_trait]
    impl super::NetworkIsolator for DockerNetworkIsolator {
        async fn apply_policy(&self, policy: &crate::policy::NetworkPolicy) -> Result<(), crate::error::NetworkError> {
            // Use Docker network isolation
            self.base.store_policy(policy.policy_id.clone(), policy.clone());
            Ok(())
        }
        
        async fn apply_mode_none(&self) -> Result<(), crate::error::NetworkError> {
            Ok(())
        }
        
        async fn apply_egress_only(&self) -> Result<(), crate::error::NetworkError> {
            Ok(())
        }
        
        async fn apply_ingress_only(&self) -> Result<(), crate::error::NetworkError> {
            Ok(())
        }
        
        async fn apply_filtered_egress(&self, _policy: &crate::policy::NetworkPolicy) -> Result<(), crate::error::NetworkError> {
            Ok(())
        }
        
        async fn remove_policy(&self, policy_id: &str) -> Result<(), crate::error::NetworkError> {
            self.base.remove_policy(policy_id);
            Ok(())
        }
        
        async fn verify_isolation(&self, policy: &crate::policy::NetworkPolicy) -> Result<crate::isolator::VerificationResult, crate::error::NetworkError> {
            let results = crate::probes::run_verification_probes(policy).await;
            Ok(results)
        }
        
        fn supported_modes(&self) -> Vec<NetworkMode> {
            vec![
                NetworkMode::None,
                NetworkMode::Egress,
                NetworkMode::Ingress,
                NetworkMode::EgressFiltered,
            ]
        }
        
        async fn apply_mode_none(&self) -> Result<(), crate::error::NetworkError> {
            Ok(())
        }
        
        async fn apply_egress_only(&self) -> Result<(), crate::error::NetworkError> {
            Ok(())
        }
        
        async fn apply_ingress_only(&self) -> Result<(), crate::error::NetworkError> {
            Ok(())
        }
        
        async fn apply_filtered_egress(&self, _policy: &crate::policy::NetworkPolicy) -> Result<(), crate::error::NetworkError> {
            Ok(())
        }
        
        async fn remove_policy(&self, policy_id: &str) -> Result<(), crate::error::NetworkError> {
            self.base.remove_policy(policy_id);
            Ok(())
        }
        
        async fn verify_isolation(&self, policy: &crate::policy::NetworkPolicy) -> Result<crate::isolator::VerificationResult, crate::error::NetworkError> {
            let results = crate::probes::run_verification_probes(policy).await;
            Ok(results)
        }
        
        fn supported_modes(&self) -> Vec<NetworkMode> {
            vec![
                NetworkMode::None,
                NetworkMode::Egress,
                NetworkMode::Ingress,
                NetworkMode::EgressFiltered,
            ]
        }
    }
}