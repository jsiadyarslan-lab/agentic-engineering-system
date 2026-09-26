use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use uuid::Uuid;

/// Provenance operation types
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "PascalCase")]
pub enum ProvenanceOperation {
    Created,
    Copied,
    Moved,
    Signed,
    Verified,
    Modified,
    Deleted,
}

impl std::fmt::Display for ProvenanceOperation {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ProvenanceOperation::Created => write!(f, "Created"),
            ProvenanceOperation::Copied => write!(f, "Copied"),
            ProvenanceOperation::Moved => write!(f, "Moved"),
            ProvenanceOperation::Signed => write!(f, "Signed"),
            ProvenanceOperation::Verified => write!(f, "Verified"),
            ProvenanceOperation::Modified => write!(f, "Modified"),
            ProvenanceOperation::Deleted => write!(f, "Deleted"),
        }
    }
}

/// Single provenance chain entry
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProvenanceEntry {
    pub id: String,
    pub operation: ProvenanceOperation,
    pub actor: String,
    pub description: String,
    pub artifact_sha256: String,
    pub prev_hash: Option<String>,
    pub metadata: HashMap<String, String>,
    #[serde(with = "chrono::serde::ts_seconds")]
    pub timestamp: chrono::DateTime<Utc>,
}

impl ProvenanceEntry {
    pub fn new(
        operation: ProvenanceOperation,
        actor: String,
        description: String,
    ) -> Self {
        let artifact_sha256 = format!("provenance-{}", uuid::Uuid::new_v4());
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            operation,
            actor,
            description,
            artifact_sha256,
            prev_hash: None,
            metadata: HashMap::new(),
            timestamp: Utc::now(),
        }
    }
    
    pub fn with_artifact_sha256(mut self, sha256: String) -> Self {
        self.artifact_sha256 = sha256;
        self
    }
    
    pub fn with_prev_hash(mut self, prev_hash: String) -> Self {
        self.prev_hash = Some(prev_hash);
        self
    }
    
    pub fn with_metadata(mut self, key: String, value: String) -> Self {
        self.metadata.insert(key, value);
        self
    }
    
    pub fn hash(&self) -> String {
        use sha2::{Digest, Sha256};
        let mut hasher = sha2::Sha256::new();
        hasher.update(self.id.as_bytes());
        hasher.update(format!("{:?}", self.operation).as_bytes());
        hasher.update(self.actor.as_bytes());
        hasher.update(self.description.as_bytes());
        hasher.update(self.artifact_sha256.as_bytes());
        if let Some(prev) = &self.prev_hash {
            hasher.update(prev.as_bytes());
        }
        let ts = self.timestamp.timestamp();
        hasher.update(&ts.to_le_bytes());
        hex::encode(hasher.finalize())
    }
}

/// Append-only provenance chain
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ProvenanceChain {
    pub entries: Vec<ProvenanceEntry>,
    pub sigstore_bundle: Option<SigstoreBundle>,
}

impl ProvenanceChain {
    pub fn new() -> Self {
        Self::default()
    }
    
    pub fn add_entry(&mut self, mut entry: ProvenanceEntry) {
        // Link to previous entry
        if let Some(last) = self.entries.last() {
            entry.prev_hash = Some(last.hash());
        }
        self.entries.push(entry);
    }
    
    pub fn last_hash(&self) -> Option<String> {
        self.entries.last().map(|e| e.hash())
    }
    
    pub fn verify_chain(&self) -> bool {
        for (i, entry) in self.entries.iter().enumerate() {
            // Check hash matches computed
            let computed = entry.hash();
            // Note: we don't store the computed hash in the entry itself
            // In production, we'd store it and verify here
            
            // Check chain linkage
            if i > 0 {
                if entry.prev_hash != self.entries[i - 1].hash().into() {
                    return false;
                }
            } else if entry.prev_hash.is_some() {
                return false; // First entry should not have prev_hash
            }
        }
        true
    }
    
    pub fn len(&self) -> usize {
        self.entries.len()
    }
    
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
    
    pub fn iter(&self) -> std::slice::Iter<ProvenanceEntry> {
        self.entries.iter()
    }
}

/// Sigstore bundle for signing
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SigstoreBundle {
    pub signed_payload: Vec<u8>,
    pub signature: Vec<u8>,
    pub certificate: Vec<u8>,
    pub transparency_log_entry: String,
    pub public_key: Option<String>,
}

impl SigstoreBundle {
    pub fn new(
        signed_payload: Vec<u8>,
        signature: Vec<u8>,
        certificate: Vec<u8>,
        transparency_log_entry: String,
    ) -> Self {
        Self {
            signed_payload,
            signature,
            certificate,
            transparency_log_entry,
            public_key: None,
        }
    }
    
    pub fn with_public_key(mut self, public_key: String) -> Self {
        self.public_key = Some(public_key);
        self
    }
}