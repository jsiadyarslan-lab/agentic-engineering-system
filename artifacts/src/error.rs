use thiserror::Error;

#[derive(Error, Debug)]
pub enum ArtifactError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    
    #[error("Hash computation failed: {0}")]
    HashError(String),
    
    #[error("Artifact not found: {0}")]
    NotFound(String),
    
    #[error("Invalid artifact: {0}")]
    InvalidArtifact(String),
    
    #[error("Provenance verification failed: {0}")]
    ProvenanceError(String),
    
    #[error("Sigstore error: {0}")]
    SigstoreError(String),
    
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
    
    #[error("Walkdir error: {0}")]
    Walkdir(#[from] walkdir::Error),
    
    #[error("Hex decode error: {0}")]
    Hex(#[from] hex::FromHexError),
    
    #[error("UUID error: {0}")]
    Uuid(#[from] uuid::Error),
}