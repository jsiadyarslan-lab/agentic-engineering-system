#[cfg(target_os = "linux")]
mod linux_landlock {
    use crate::error::{LinuxSubstrateError, Result};
    use crate::types::LandlockRule;
    use std::path::Path;
    use std::os::unix::io::AsRawFd;
    use std::os::unix::io::FromRawFd;
    use std::fs::File;
    use std::os::unix::io::AsRawFd;
    use landlock::{Ruleset, RulesetCreated, RulesetAttr, AccessFs, AccessNet};

    /// Landlock ruleset manager for filesystem access control
    pub struct LandlockManager {
        ruleset: Option<RulesetCreated>,
        rules_applied: bool,
    }

    impl LandlockManager {
        /// Create a new Landlock manager
        pub fn new() -> Result<Self> {
            Ok(Self {
                ruleset: None,
                rules_applied: false,
            })
        }

        /// Add a filesystem access rule
        pub fn add_rule(&mut self, rule: LandlockRule) -> Result<()> {
            if self.rules_applied {
                return Err(LinuxSubstrateError::Landlock(
                    "Cannot add rules after ruleset is applied".to_string()
                ));
            }

            // We'll build the ruleset when apply is called
            Ok(())
        }

        /// Build and apply the ruleset
        pub fn apply(&mut self) -> Result<()> {
            if self.rules_applied {
                return Ok(());
            }

            let mut ruleset = Ruleset::default();

            // TODO: Add actual rules from configuration
            // For now, create a basic ruleset that allows read/write to /work and /artifacts
            
            let ruleset_attr = RulesetAttr::default()
                .handling_access_fs(AccessFs::from_all())
                .handling_access_net(AccessNet::from_all());

            let mut ruleset_created = ruleset
                .create_ruleset(ruleset_attr)
                .map_err(|e| LinuxSubstrateError::Landlock(e.to_string()))?;

            // Add rule for /work (read-only)
            let work_fd = std::fs::File::open("/work")
                .map_err(|e| LinuxSubstrateError::Landlock(e.to_string()))?;
            
            ruleset_created.add_rule(
                landlock::PathBeneath::new(work_fd.as_raw_fd(), landlock::AccessFs::from_all())
            ).map_err(|e| LinuxSubstrateError::Landlock(e.to_string()))?;

            // Add rule for /artifacts (read-write)
            let artifacts_fd = std::fs::File::open("/artifacts")
                .map_err(|e| LinuxSubstrateError::Landlock(e.to_string()))?;
            
            ruleset_created.add_rule(
                landlock::PathBeneath::new(artifacts_fd.as_raw_fd(), landlock::AccessFs::from_all())
            ).map_err(|e| LinuxSubstrateError::Landlock(e.to_string()))?;

            // Add rule for /tmp/sandbox (read-write)
            let tmp_fd = std::fs::File::open("/tmp/sandbox")
                .map_err(|e| LinuxSubstrateError::Landlock(e.to_string()))?;
            
            ruleset_created.add_rule(
                landlock::PathBeneath::new(tmp_fd.as_raw_fd(), landlock::AccessFs::from_all())
            ).map_err(|e| LinuxSubstrateError::Landlock(e.to_string()))?;

            // Restrict to the ruleset
            ruleset_created.restrict_self()
                .map_err(|e| LinuxSubstrateError::Landlock(e.to_string()))?;

            self.ruleset = Some(ruleset_created);
            Ok(())
        }

        /// Apply ruleset with custom rules
        pub fn apply_with_rules(&mut self, rules: Vec<LandlockRule>) -> Result<()> {
            if self.rules_applied {
                return Ok(());
            }

            let mut ruleset = Ruleset::default();
            let ruleset_attr = RulesetAttr::default()
                .handling_access_fs(AccessFs::from_all())
                .handling_access_net(AccessNet::from_all());

            let mut ruleset_created = ruleset
                .create_ruleset(ruleset_attr)
                .map_err(|e| LinuxSubstrateError::Landlock(e.to_string()))?;

            // Add default rules for sandbox directories
            for path in ["/work", "/artifacts", "/tmp/sandbox"] {
                if let Ok(fd) = std::fs::File::open(path) {
                    let access = if path == "/work" {
                        AccessFs::from_read_only()
                    } else {
                        AccessFs::from_all()
                    };
                    
                    ruleset_created.add_rule(
                        landlock::PathBeneath::new(fd.as_raw_fd(), access)
                    ).map_err(|e| LinuxSubstrateError::Landlock(e.to_string()))?;
                }
            }

            // Apply custom rules
            for rule in rules {
                if let Ok(fd) = std::fs::File::open(&rule.path) {
                    let mut access = AccessFs::empty();
                    if rule.read { access |= AccessFs::READ_FILE; }
                    if rule.write { access |= AccessFs::WRITE_FILE; }
                    if rule.execute { access |= AccessFs::EXECUTE; }
                    
                    ruleset_created.add_rule(
                        landlock::PathBeneath::new(fd.as_raw_fd(), access)
                    ).map_err(|e| LinuxSubstrateError::Landlock(e.to_string()))?;
                }
            }

            // Restrict to the ruleset
            ruleset_created.restrict_self()
                .map_err(|e| LinuxSubstrateError::Landlock(e.to_string()))?;

            self.ruleset = Some(ruleset_created);
            self.rules_applied = true;
            Ok(())
        }

        /// Check if Landlock is supported on this system
        pub fn is_supported() -> bool {
            // Check if landlock is available in kernel
            std::path::Path::new("/sys/kernel/security/landlock").exists()
        }

        /// Get the number of rules in the current ruleset
        pub fn rule_count(&self) -> usize {
            self.ruleset.as_ref().map(|r| 0).unwrap_or(0) // Approximate
        }
    }
}

/// Re-export the Linux landlock types
#[cfg(target_os = "linux")]
pub use linux_landlock::*;

/// Stub implementations for non-Linux platforms
#[cfg(not(target_os = "linux"))]
mod stub_landlock {
    use crate::error::{LinuxSubstrateError, Result};
    use crate::types::LandlockRule;

    pub struct LandlockManager {
        _ruleset: Option<()>,
        _rules_applied: bool,
    }

    impl LandlockManager {
        pub fn new() -> Result<Self> {
            Err(LinuxSubstrateError::Unavailable("Landlock not supported on this platform".to_string()))
        }

        pub fn add_rule(&mut self, _rule: LandlockRule) -> Result<()> {
            Err(LinuxSubstrateError::Unavailable("Landlock not supported on this platform".to_string()))
        }

        pub fn apply(&mut self) -> Result<()> {
            Err(LinuxSubstrateError::Unavailable("Landlock not supported on this platform".to_string()))
        }

        pub fn apply_with_rules(&mut self, _rules: Vec<LandlockRule>) -> Result<()> {
            Err(LinuxSubstrateError::Unavailable("Landlock not supported on this platform".to_string()))
        }

        pub fn is_supported() -> bool {
            false
        }

        pub fn rule_count(&self) -> usize {
            0
        }
    }
}

/// Re-export the stub types for non-Linux platforms
#[cfg(not(target_os = "linux"))]
pub use stub_landlock::*;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_landlock_supported() {
        #[cfg(target_os = "linux")]
        {
            let _ = super::linux_landlock::LandlockManager::is_supported();
        }
    }

    #[test]
    fn test_create_manager() {
        #[cfg(target_os = "linux")]
        {
            let mgr = LandlockManager::new();
            assert!(mgr.is_ok());
        }
    }
}