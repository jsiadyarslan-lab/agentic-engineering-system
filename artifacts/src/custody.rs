use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Artifact custody entry representing a single artifact
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArtifactCustodyEntry {
    pub id: String,
    pub execution_id: String,
    pub path: String,
    pub sha256: String,
    pub sha1: Option<String>,
    pub size: u64,
    pub kind: String,
    pub mime_type: Option<String>,
    #[serde(with = "chrono::serde::ts_seconds")]
    pub created_at: DateTime<Utc>,
}

impl ArtifactCustodyEntry {
    pub fn new(
        execution_id: String,
        path: String,
        sha256: String,
        size: u64,
        kind: ArtifactKind,
    ) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            execution_id,
            path,
            sha256,
            sha1: None,
            size,
            kind: kind.to_string(),
            mime_type: None,
            created_at: Utc::now(),
        }
    }
    
    pub fn with_sha1(mut self, sha1: String) -> Self {
        self.sha1 = Some(sha1);
        self
    }
    
    pub fn with_mime_type(mut self, mime_type: String) -> Self {
        self.mime_type = Some(mime_type);
        self
    }
    
    pub fn verify_hash(&self, data: &[u8]) -> bool {
        use sha2::{Digest, Sha256};
        let hash = sha2::Sha256::digest(data);
        hex::encode(hash) == self.sha256
    }
}

/// Artifact kind classification
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "PascalCase")]
pub enum ArtifactKind {
    Stdout,
    Stderr,
    Log,
    Artifact,
    Provenance,
    Other,
}

impl std::fmt::Display for ArtifactKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ArtifactKind::Stdout => write!(f, "Stdout"),
            ArtifactKind::Stderr => write!(f, "Stderr"),
            ArtifactKind::Log => write!(f, "Log"),
            ArtifactKind::Artifact => write!(f, "Artifact"),
            ArtifactKind::Provenance => write!(f, "Provenance"),
            ArtifactKind::Other => write!(f, "Other"),
        }
    }
}

impl std::str::FromStr for ArtifactKind {
    type Err = String;
    
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "stdout" => Ok(ArtifactKind::Stdout),
            "stderr" => Ok(ArtifactKind::Stderr),
            "log" => Ok(ArtifactKind::Log),
            "artifact" => Ok(ArtifactKind::Artifact),
            "provenance" => Ok(ArtifactKind::Provenance),
            _ => Ok(ArtifactKind::Other),
        }
    }
}

/// Complete artifact custody for an execution
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArtifactCustody {
    pub execution_id: String,
    pub entries: Vec<ArtifactCustodyEntry>,
    pub provenance: ProvenanceChain,
    #[serde(with = "chrono::serde::ts_seconds")]
    pub created_at: chrono::DateTime<Utc>,
}

impl ArtifactCustody {
    pub fn new(execution_id: String) -> Self {
        Self {
            execution_id,
            entries: Vec::new(),
            provenance: ProvenanceChain::new(),
            created_at: chrono::Utc::now(),
        }
    }
    
    pub fn add_entry(&mut self, entry: crate::custody::ArtifactCustodyEntry) {
        self.entries.push(entry);
    }
    
    pub fn get_entry(&self, path: &str) -> Option<&ArtifactCustodyEntry> {
        self.entries.iter().find(|e| e.path == path)
    }
    
    pub fn total_size(&self) -> u64 {
        self.entries.iter().map(|e| e.size).sum()
    }
    
    pub fn entry_count(&self) -> usize {
        self.entries.len()
    }
}

impl ArtifactCustodyEntry {
    pub fn hash(&self) -> String {
        use sha2::{Digest, Sha256};
        let mut hasher = sha2::Sha256::new();
        hasher.update(self.id.as_bytes());
        hasher.update(self.execution_id.as_bytes());
        hasher.update(self.path.as_bytes());
        hasher.update(self.sha256.as_bytes());
        hasher.update(self.size.to_le_bytes());
        hasher.update(self.kind.as_bytes());
        let ts = self.created_at.timestamp();
        hasher.update(&ts.to_le_bytes());
        hex::encode(hasher.finalize())
    }
}

use crate::provenance::ProvenanceChain;