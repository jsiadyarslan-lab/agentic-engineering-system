use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use hex;
use sha2::{Digest, Sha256};
use sha1::Sha1;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::SystemTime;
use uuid::Uuid;
use walkdir::WalkDir;

pub mod error;
pub mod custody;
pub mod provenance;
pub mod sigstore_integration;

pub use error::ArtifactError;
pub use custody::{ArtifactCustody, ArtifactCustodyEntry, ArtifactKind};
pub use provenance::{ProvenanceChain, ProvenanceEntry, ProvenanceOperation, SigstoreBundle};
pub use sigstore_integration::SigstoreSigner;

/// Compute SHA256 hash of a file asynchronously
pub async fn hash_file(path: &Path) -> Result<String> {
    let mut file = tokio::fs::File::open(path).await
        .with_context(|| format!("Failed to open file: {}", path.display()))?;
    
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; 8192];
    
    loop {
        let n = tokio::io::AsyncReadExt::read(&mut file, &mut buffer).await
            .with_context(|| format!("Failed to read file: {}", path.display()))?;
        if n == 0 {
            break;
        }
        hasher.update(&buffer[..n]);
    }
    
    Ok(hex::encode(hasher.finalize()))
}

/// Compute SHA256 hash of bytes
pub fn hash_bytes(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);
    hex::encode(hasher.finalize())
}

/// Compute SHA1 hash of bytes (for compatibility)
pub fn hash_bytes_sha1(data: &[u8]) -> String {
    let mut hasher = Sha1::new();
    hasher.update(data);
    hex::encode(hasher.finalize())
}

/// Compute SHA256 hash of a file synchronously
pub fn hash_file_sync(path: &Path) -> Result<String> {
    let mut file = std::fs::File::open(path)
        .with_context(|| format!("Failed to open file: {}", path.display()))?;
    
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; 8192];
    
    use std::io::Read;
    loop {
        let n = file.read(&mut buffer)
            .with_context(|| format!("Failed to read file: {}", path.display()))?;
        if n == 0 {
            break;
        }
        hasher.update(&buffer[..n]);
    }
    
    Ok(hex::encode(hasher.finalize()))
}

/// Collect all artifacts from a directory
pub async fn collect_artifacts(
    artifacts_dir: &Path,
    execution_id: &str,
) -> Result<ArtifactCustody> {
    let mut custody = ArtifactCustody::new(execution_id.to_string());
    
    if !artifacts_dir.exists() {
        return Ok(custody);
    }
    
    for entry in WalkDir::new(artifacts_dir).into_iter().filter_map(|e| e.ok()) {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        
        // Determine artifact kind from path
        let kind = classify_artifact_kind(path, artifacts_dir);
        
        // Hash the file
        let sha256 = hash_file_sync(path)
            .with_context(|| format!("Failed to hash file: {}", path.display()))?;
        
        let metadata = std::fs::metadata(path)
            .with_context(|| format!("Failed to get metadata: {}", path.display()))?;
        
        let relative_path = path.strip_prefix(artifacts_dir)
            .unwrap_or(path)
            .to_string_lossy()
            .to_string();
        
        let entry = ArtifactCustodyEntry {
            id: Uuid::new_v4().to_string(),
            execution_id: execution_id.to_string(),
            path: relative_path,
            sha256,
            sha1: None,
            size: metadata.len(),
            kind: kind.to_string(),
            mime_type: None,
            created_at: chrono::Utc::now(),
        };
        
        custody.add_entry(entry);
    }
    
    Ok(custody)
}

/// Classify artifact kind from path
fn classify_artifact_kind(path: &Path, artifacts_dir: &Path) -> ArtifactKind {
    let relative = path.strip_prefix(artifacts_dir).unwrap_or(path);
    let path_str = relative.to_string_lossy().to_lowercase();
    
    if path_str.contains("stdout") || path_str.ends_with(".stdout") {
        ArtifactKind::Stdout
    } else if path_str.contains("stderr") || path_str.ends_with(".stderr") {
        ArtifactKind::Stderr
    } else if path_str.contains("log") || path_str.ends_with(".log") {
        ArtifactKind::Log
    } else if path_str.contains("artifact") || path_str.contains("output") {
        ArtifactKind::Artifact
    } else if path_str.contains("provenance") || path_str.ends_with(".prov") {
        ArtifactKind::Provenance
    } else {
        ArtifactKind::Other
    }
}

/// Sign artifact custody with Sigstore
pub async fn sign_artifacts(custody: &mut ArtifactCustody) -> Result<()> {
    let signer = SigstoreSigner::new().await?;
    let bundle = signer.sign_custody(custody).await?;
    custody.provenance.sigstore_bundle = Some(bundle);
    Ok(())
}

/// Verify artifact custody provenance
pub fn verify_provenance(custody: &ArtifactCustody) -> Result<bool> {
    // Verify SHA256 hashes match files
    // Verify provenance chain integrity
    // Verify Sigstore bundle if present
    
    // For now, basic chain integrity check
    for (i, entry) in custody.provenance.entries.iter().enumerate() {
        if i > 0 {
            let prev = &custody.provenance.entries[i - 1];
            if entry.prev_hash != Some(prev.hash()) {
                return Ok(false);
            }
        }
    }
    
    Ok(true)
}

/// Create artifact custody for a sandbox execution
pub async fn create_execution_custody(
    execution_id: &str,
    artifacts_dir: &Path,
    stdout_path: Option<&Path>,
    stderr_path: Option<&Path>,
) -> Result<ArtifactCustody> {
    let mut custody = ArtifactCustody::new(execution_id.to_string());
    
    // Add stdout if exists
    if let Some(path) = stdout_path {
        if path.exists() {
            let sha256 = hash_file_sync(path)?;
            let metadata = std::fs::metadata(path)?;
            let entry = ArtifactCustodyEntry {
                id: Uuid::new_v4().to_string(),
                execution_id: execution_id.to_string(),
                path: "stdout".to_string(),
                sha256,
                sha1: None,
                size: metadata.len(),
                kind: ArtifactKind::Stdout.to_string(),
                mime_type: Some("text/plain".to_string()),
                created_at: chrono::Utc::now(),
            };
            custody.add_entry(entry);
        }
    }
    
    // Add stderr if exists
    if let Some(path) = stderr_path {
        if path.exists() {
            let sha256 = hash_file_sync(path)?;
            let metadata = std::fs::metadata(path)?;
            let entry = ArtifactCustodyEntry {
                id: Uuid::new_v4().to_string(),
                execution_id: execution_id.to_string(),
                path: "stderr".to_string(),
                sha256,
                sha1: None,
                size: metadata.len(),
                kind: ArtifactKind::Stderr.to_string(),
                mime_type: Some("text/plain".to_string()),
                created_at: chrono::Utc::now(),
            };
            custody.add_entry(entry);
        }
    }
    
    // Collect other artifacts
    let artifacts = collect_artifacts(Path::new("."), execution_id).await?;
    for entry in artifacts.entries {
        custody.add_entry(entry);
    }
    
    // Create initial provenance entry
    custody.provenance.add_entry(ProvenanceEntry::new(
        ProvenanceOperation::Created,
        "substrate".to_string(),
        format!("Execution {} created", execution_id),
    ));
    
    Ok(custody)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;
    use tokio::io::AsyncWriteExt;

    #[tokio::test]
    async fn test_hash_file() {
        let dir = tempdir().unwrap();
        let file_path = dir.path().join("test.txt");
        let content = b"Hello, World!";
        tokio::fs::write(&file_path, content).await.unwrap();
        
        let hash = hash_file_sync(&dir.path().join("test.txt")).unwrap();
        let expected = hex::encode(sha2::Sha256::digest(content));
        assert_eq!(hash, expected);
    }

    #[tokio::test]
    async fn test_hash_bytes() {
        let data = b"test data";
        let hash = hash_bytes(data);
        let expected = hex::encode(sha2::Sha256::digest(data));
        assert_eq!(hash, expected);
    }

    #[tokio::test]
    async fn test_collect_artifacts() {
        let dir = tempdir().unwrap();
        let artifacts_dir = dir.path().join("artifacts");
        tokio::fs::create_dir_all(&artifacts_dir).await.unwrap();
        
        let file1 = artifacts_dir.join("output.txt");
        tokio::fs::write(&file1, b"test output").await.unwrap();
        
        let file2 = artifacts_dir.join("stdout.txt");
        tokio::fs::write(&file2, b"stdout content").await.unwrap();
        
        let custody = collect_artifacts(&artifacts_dir, "test-exec").await.unwrap();
        assert_eq!(custody.entries.len(), 2);
        
        // Check stdout classification
        let stdout_entry = custody.entries.iter()
            .find(|e| e.kind == "Stdout")
            .expect("Should have stdout entry");
        assert_eq!(stdout_entry.path, "stdout.txt");
    }

    #[test]
    fn test_hash_bytes_known() {
        let data = b"test";
        let hash = hash_bytes(b"test");
        // SHA256 of "test" = 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
        assert_eq!(hash, "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08");
    }

    #[test]
    fn test_provenance_chain() {
        let mut chain = ProvenanceChain::new();
        chain.add_entry(ProvenanceEntry::new(
            ProvenanceOperation::Created,
            "test".to_string(),
            "initial".to_string(),
        ));
        chain.add_entry(ProvenanceEntry::new(
            ProvenanceOperation::Signed,
            "sigstore".to_string(),
            "signed".to_string(),
        ));
        
        assert_eq!(chain.entries.len(), 2);
        assert_eq!(chain.entries[0].operation, ProvenanceOperation::Created);
        assert_eq!(chain.entries[1].operation, ProvenanceOperation::Signed);
    }
}