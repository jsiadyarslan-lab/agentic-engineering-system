//! Network policy definitions

use serde::{Deserialize, Serialize};
pub use substrate_core::NetworkMode;

/// Network isolation policy
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct NetworkPolicy {
    pub mode: NetworkMode,
    pub egress_allowlist: Vec<String>,      // CIDR or hostname
    pub egress_denylist: Vec<String>,
    pub ingress_allowlist: Vec<String>,
    pub ingress_denylist: Vec<String>,
    pub dns_policy: DnsPolicy,
    pub policy_id: String,
}

impl NetworkPolicy {
    pub fn new(mode: NetworkMode) -> Self {
        Self {
            mode,
            ..Default::default()
        }
    }
    
    pub fn with_egress_allowlist(mut self, allowlist: Vec<String>) -> Self {
        self.egress_allowlist = allowlist;
        self
    }
    
    pub fn with_egress_denylist(mut self, denylist: Vec<String>) -> Self {
        self.egress_denylist = denylist;
        self
    }
    
    pub fn with_ingress_allowlist(mut self, allowlist: Vec<String>) -> Self {
        self.ingress_allowlist = allowlist;
        self
    }
    
    pub fn with_ingress_denylist(mut self, denylist: Vec<String>) -> Self {
        self.ingress_denylist = denylist;
        self
    }
    
    pub fn with_dns_policy(mut self, policy: DnsPolicy) -> Self {
        self.dns_policy = policy;
        self
    }
    
    pub fn with_policy_id(mut self, id: String) -> Self {
        self.policy_id = id;
        self
    }
    
    pub fn is_egress_allowed(&self, target: &str) -> bool {
        match self.mode {
            NetworkMode::None | NetworkMode::Ingress => false,
            NetworkMode::Egress => true,
            NetworkMode::EgressFiltered => {
                if !self.egress_denylist.is_empty() && self.matches_denylist(target) {
                    return false;
                }
                if !self.egress_allowlist.is_empty() && !self.matches_allowlist(target) {
                    return false;
                }
                true
            }
        }
    }
    
    pub fn is_ingress_allowed(&self, target: &str) -> bool {
        match self.mode {
            NetworkMode::None | NetworkMode::Egress => false,
            NetworkMode::Ingress => true,
            NetworkMode::EgressFiltered => {
                if !self.ingress_denylist.is_empty() && self.matches_ingress_denylist(target) {
                    return false;
                }
                if !self.ingress_allowlist.is_empty() && !self.matches_ingress_allowlist(target) {
                    return false;
                }
                true
            }
        }
    }
    
    fn matches_allowlist(&self, target: &str) -> bool {
        self.egress_allowlist.iter().any(|pattern| self.matches_pattern(target, pattern))
    }
    
    fn matches_denylist(&self, target: &str) -> bool {
        self.egress_denylist.iter().any(|pattern| self.matches_pattern(target, pattern))
    }
    
    fn matches_ingress_allowlist(&self, target: &str) -> bool {
        self.ingress_allowlist.iter().any(|pattern| self.matches_pattern(target, pattern))
    }
    
    fn matches_ingress_denylist(&self, target: &str) -> bool {
        self.ingress_denylist.iter().any(|pattern| self.matches_pattern(target, pattern))
    }
    
    fn matches_pattern(&self, target: &str, pattern: &str) -> bool {
        if pattern.contains('/') {
            // CIDR notation
            if let Ok(network) = pattern.parse::<ipnet::IpNet>() {
                if let Ok(addr) = target.parse::<std::net::IpAddr>() {
                    return network.contains(&addr);
                }
            }
            false
        } else if pattern.contains('*') {
            // Wildcard hostname
            let regex = pattern.replace('.', "\\.").replace('*', ".*");
            if let Ok(re) = regex::Regex::new(&format!("^{}$", regex)) {
                return re.is_match(target);
            }
            false
        } else {
            // Exact match
            target == pattern
        }
    }
}

/// DNS resolution policy
#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub enum DnsPolicy {
    #[default]
    AllowAll,
    AllowList(Vec<String>),
    DenyList(Vec<String>),
    BlockAll,
}

impl DnsPolicy {
    pub fn is_allowed(&self, hostname: &str) -> bool {
        match self {
            DnsPolicy::AllowAll => true,
            DnsPolicy::BlockAll => false,
            DnsPolicy::AllowList(list) => list.iter().any(|h| hostname == h || hostname.ends_with(&format!(".{}", h))),
            DnsPolicy::DenyList(list) => !list.iter().any(|h| hostname == h || hostname.ends_with(&format!(".{}", h))),
        }
    }
}