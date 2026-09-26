use crate::error::{MacOSSubstrateError, Result};
use crate::types::SandboxProfile;
use std::path::Path;
use std::fs;

/// Sandbox profile management for macOS
pub struct ProfileManager {
    profiles: std::collections::HashMap<String, SandboxProfile>,
}

impl ProfileManager {
    pub fn new() -> Self {
        Self {
            profiles: std::collections::HashMap::new(),
        }
    }

    /// Register a sandbox profile
    pub fn register(&mut self, profile: SandboxProfile) {
        self.profiles.insert(profile.name.clone(), profile);
    }

    /// Get a profile by name
    pub fn get(&self, name: &str) -> Option<&SandboxProfile> {
        self.profiles.get(name)
    }

    /// Get a mutable reference to a profile
    pub fn get_mut(&mut self, name: &str) -> Option<&mut SandboxProfile> {
        self.profiles.get_mut(name)
    }

    /// List all registered profiles
    pub fn list(&self) -> Vec<&SandboxProfile> {
        self.profiles.values().collect()
    }

    /// Remove a profile
    pub fn remove(&mut self, name: &str) -> Option<SandboxProfile> {
        self.profiles.remove(name)
    }

    /// Save all profiles to disk
    pub fn save_all(&self, dir: &Path) -> Result<()> {
        fs::create_dir_all(dir).map_err(|e| MacOSSubstrateError::Profile(e.to_string()))?;
        
        for (name, profile) in &self.profiles {
            let file_path = dir.join(format!("{}.sb", name));
            let content = profile.to_string();
            fs::write(&file_path, content)
                .map_err(|e| MacOSSubstrateError::Profile(e.to_string()))?;
        }
        
        Ok(())
    }

    /// Load all profiles from disk
    pub fn load_all(dir: &Path) -> Result<Self> {
        let mut manager = Self::new();
        
        if !dir.exists() {
            return Ok(manager);
        }
        
        for entry in fs::read_dir(dir).map_err(|e| MacOSSubstrateError::Profile(e.to_string()))? {
            let entry = entry.map_err(|e| MacOSSubstrateError::Profile(e.to_string()))?;
            let path = entry.path();
            
            if path.extension().and_then(|s| s.to_str()) == Some("sb") {
                let content = fs::read_to_string(&path)
                    .map_err(|e| MacOSSubstrateError::Profile(e.to_string()))?;
                
                // Parse the sandbox profile from the file content
                // This would require a parser for the sandbox profile format
                // For now, we'll skip parsing and just note the file exists
            }
        }
        
        Ok(manager)
    }
}

/// Profile builder for creating sandbox profiles programmatically
pub struct ProfileBuilder {
    profile: crate::types::SandboxProfile,
}

impl ProfileBuilder {
    pub fn new(name: &str) -> Self {
        Self {
            profile: SandboxProfile::new(name),
        }
    }

    pub fn deny_default(mut self, deny: bool) -> Self {
        self.profile.deny_default = deny;
        self
    }

    pub fn allow_file_read(mut self, path: &Path) -> Self {
        self.profile.allow_file_read(path.to_path_buf());
        self
    }

    pub fn allow_file_write(mut self, path: &Path) -> Self {
        self.profile.allow_file_write(path.to_path_buf());
        self
    }

    pub fn allow_file_execute(mut self, path: &Path) -> Self {
        self.profile.allow_file_execute(path.to_path_buf());
        self
    }

    pub fn allow_network(mut self, outbound: bool, inbound: bool) -> Self {
        self.profile.allow_network(outbound, inbound);
        self
    }

    pub fn allow_process_execution(mut self) -> Self {
        self.profile.allow_process_execution();
        self
    }

    pub fn deny_default(mut self, deny: bool) -> Self {
        self.profile.deny_default = deny;
        self
    }

    pub fn build(self) -> SandboxProfile {
        self.profile
    }
}

/// Predefined profile templates
pub mod templates {
    use super::*;

    /// Minimal profile - only basic file read/write in home directory
    pub fn minimal() -> SandboxProfile {
        let mut profile = SandboxProfile::new("minimal");
        profile.deny_default = true;
        profile.allow_file_read(&std::path::PathBuf::from("/Users"));
        profile.allow_file_write(&std::path::PathBuf::from("/Users"));
        profile.allow_network(false, false);
        profile
    }

    /// Development profile - allows common development tools
    pub fn development() -> SandboxProfile {
        let mut profile = SandboxProfile::new("development");
        profile.deny_default = true;
        profile.allow_file_read(&std::path::PathBuf::from("/Users"));
        profile.allow_file_write(&std::path::PathBuf::from("/Users"));
        profile.allow_file_read(&std::path::PathBuf::from("/tmp"));
        profile.allow_file_write(&std::path::PathBuf::from("/tmp"));
        profile.allow_network(true, false);
        profile.allow_process_execution();
        profile
    }

    /// Network profile - allows network access
    pub fn network() -> SandboxProfile {
        let mut profile = SandboxProfile::new("network");
        profile.deny_default = true;
        profile.allow_file_read(&std::path::PathBuf::from("/Users"));
        profile.allow_file_read(&std::path::PathBuf::from("/etc"));
        profile.allow_network(true, false);
        profile
    }

    /// Full access profile (for testing)
    pub fn full_access() -> SandboxProfile {
        let mut profile = SandboxProfile::new("full-access");
        profile.deny_default = false;
        profile
    }

    /// Build profile - allows build tools and compilers
    pub fn build() -> SandboxProfile {
        let mut profile = SandboxProfile::new("build");
        profile.deny_default = true;
        profile.allow_file_read(&std::path::PathBuf::from("/Users"));
        profile.allow_file_write(&std::path::PathBuf::from("/Users"));
        profile.allow_file_read(&std::path::PathBuf::from("/tmp"));
        profile.allow_file_write(&std::path::PathBuf::from("/tmp"));
        profile.allow_file_read(&std::path::PathBuf::from("/usr"));
        profile.allow_file_write(&std::path::PathBuf::from("/tmp"));
        profile.allow_network(true, false);
        profile.allow_process_execution();
        profile
    }

    /// Test profile - allows test runners and tools
    pub fn test() -> SandboxProfile {
        let mut profile = SandboxProfile::new("test");
        profile.deny_default = true;
        profile.allow_file_read(&std::path::PathBuf::from("/Users"));
        profile.allow_file_write(&std::path::PathBuf::from("/Users"));
        profile.allow_file_read(&std::path::PathBuf::from("/tmp"));
        profile.allow_file_write(&std::path::PathBuf::from("/tmp"));
        profile.allow_network(true, false);
        profile.allow_process_execution();
        profile
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_minimal_profile() {
        let profile = templates::minimal();
        assert_eq!(profile.name, "minimal");
        assert!(profile.deny_default);
    }

    #[test]
    fn test_development_profile() {
        let profile = templates::development();
        assert_eq!(profile.name, "development");
        assert!(profile.deny_default);
    }

    #[test]
    fn test_profile_builder() {
        let profile = ProfileBuilder::new("test")
            .deny_default(true)
            .allow_file_read(&PathBuf::from("/tmp"))
            .allow_network(true, false)
            .build();
        
        assert_eq!(profile.name, "test");
        assert!(profile.deny_default);
    }
}