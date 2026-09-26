//! Replay store for persisting execution records

use crate::types::*;
use anyhow::Result;
use std::path::{Path, PathBuf};
use tokio::fs;
use tracing::{debug, info};

/// Configuration for the replay store
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoreConfig {
    pub root_dir: PathBuf,
    pub max_records: Option<usize>,
    pub compression: bool,
    pub index_enabled: bool,
}

impl Default for StoreConfig {
    fn default() -> Self {
        Self {
            root_dir: PathBuf::from("./replay_store"),
            max_records: Some(10000),
            compression: true,
            index_enabled: true,
        }
    }
}

/// Replay store for persisting and retrieving execution records
pub struct ReplayStore {
    config: StoreConfig,
    index: Option<StoreIndex>,
}

/// Index for fast lookups
#[derive(Debug, Clone, Serialize, Deserialize)]
struct StoreIndex {
    records: Vec<IndexEntry>,
}

/// Index entry for a record
#[derive(Debug, Clone, Serialize, Deserialize)]
struct IndexEntry {
    execution_id: ExecutionId,
    started_at: DateTime<Utc>,
    command: String,
    exit_code: Option<i32>,
    file_path: PathBuf,
}

impl ReplayStore {
    /// Create a new replay store
    pub async fn new(config: StoreConfig) -> Result<Self> {
        fs::create_dir_all(&config.root_dir).await?;
        
        let index_path = config.root_dir.join("index.json");
        let index = if config.index_enabled && index_path.exists() {
            let data = fs::read(&index_path).await?;
            Some(serde_json::from_slice(&data)?)
        } else if config.index_enabled {
            Some(StoreIndex { records: Vec::new() })
        } else {
            None
        };

        Ok(Self { config, index })
    }

    /// Save an execution record
    pub async fn save(&mut self, record: &ExecutionRecord) -> Result<()> {
        let file_name = format!("{}.json", record.execution_id);
        let file_path = self.config.root_dir.join(&file_name);
        
        let data = if self.config.compression {
            let json = serde_json::to_vec(record)?;
            compress(&json)?
        } else {
            serde_json::to_vec(record)?
        };
        
        fs::write(&file_path, data).await?;
        
        // Update index
        if let Some(index) = &mut self.index {
            index.records.push(IndexEntry {
                execution_id: record.execution_id,
                started_at: record.started_at,
                command: record.command.clone(),
                exit_code: record.exit_code,
                file_path: file_name.into(),
            });
            
            // Enforce max records
            if let Some(max) = self.config.max_records {
                if index.records.len() > max {
                    // Remove oldest records
                    let to_remove = index.records.len() - max;
                    let removed = index.records.drain(0..to_remove).collect::<Vec<_>>();
                    for entry in removed {
                        let old_path = self.config.root_dir.join(&entry.file_path);
                        let _ = fs::remove_file(old_path).await;
                    }
                }
            }
            
            self.save_index().await?;
        }
        
        info!("Saved execution record {}", record.execution_id);
        Ok(())
    }

    /// Load an execution record
    pub async fn load(&self, execution_id: ExecutionId) -> Result<ExecutionRecord> {
        let file_name = format!("{}.json", execution_id);
        let file_path = self.config.root_dir.join(&file_name);
        
        let data = fs::read(&file_path).await?;
        
        let record = if self.config.compression {
            let decompressed = decompress(&data)?;
            serde_json::from_slice(&decompressed)?
        } else {
            serde_json::from_slice(&data)?
        };
        
        debug!("Loaded execution record {}", execution_id);
        Ok(record)
    }

    /// List all execution records
    pub async fn list(&self) -> Result<Vec<ExecutionRecordSummary>> {
        let mut summaries = Vec::new();
        
        if let Some(index) = &self.index {
            for entry in &index.records {
                summaries.push(ExecutionRecordSummary {
                    execution_id: entry.execution_id,
                    started_at: entry.started_at,
                    command: entry.command.clone(),
                    exit_code: entry.exit_code,
                });
            }
        } else {
            // Scan directory
            let mut entries = fs::read_dir(&self.config.root_dir).await?;
            while let Some(entry) = entries.next_entry().await? {
                if entry.path().extension().and_then(|s| s.to_str()) == Some("json") {
                    if let Ok(record) = self.load_from_path(&entry.path()).await {
                        summaries.push(ExecutionRecordSummary {
                            execution_id: record.execution_id,
                            started_at: record.started_at,
                            command: record.command,
                            exit_code: record.exit_code,
                        });
                    }
                }
            }
        }
        
        Ok(summaries)
    }

    /// Load record from specific path
    async fn load_from_path(&self, path: &Path) -> Result<ExecutionRecord> {
        let data = fs::read(path).await?;
        
        if self.config.compression {
            let decompressed = decompress(&data)?;
            Ok(serde_json::from_slice(&decompressed)?)
        } else {
            Ok(serde_json::from_slice(&data)?)
        }
    }

    /// Delete an execution record
    pub async fn delete(&mut self, execution_id: ExecutionId) -> Result<()> {
        let file_name = format!("{}.json", execution_id);
        let file_path = self.config.root_dir.join(&file_name);
        
        fs::remove_file(&file_path).await?;
        
        if let Some(index) = &mut self.index {
            index.records.retain(|e| e.execution_id != execution_id);
            self.save_index().await?;
        }
        
        info!("Deleted execution record {}", execution_id);
        Ok(())
    }

    /// Save index to disk
    async fn save_index(&self) -> Result<()> {
        if let Some(index) = &self.index {
            let index_path = self.config.root_dir.join("index.json");
            let data = serde_json::to_vec_pretty(index)?;
            fs::write(&index_path, data).await?;
        }
        Ok(())
    }

    /// Get store statistics
    pub async fn stats(&self) -> Result<StoreStats> {
        let mut total_size = 0u64;
        let mut record_count = 0usize;
        
        let mut entries = fs::read_dir(&self.config.root_dir).await?;
        while let Some(entry) = entries.next_entry().await? {
            let metadata = entry.metadata().await?;
            total_size += metadata.len();
            record_count += 1;
        }
        
        Ok(StoreStats {
            record_count,
            total_size_bytes: total_size,
            root_dir: self.config.root_dir.clone(),
        })
    }
}

/// Summary of an execution record
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionRecordSummary {
    pub execution_id: ExecutionId,
    pub started_at: DateTime<Utc>,
    pub command: String,
    pub exit_code: Option<i32>,
}

/// Store statistics
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoreStats {
    pub record_count: usize,
    pub total_size_bytes: u64,
    pub root_dir: PathBuf,
}

/// Compress data using zstd
fn compress(data: &[u8]) -> Result<Vec<u8>> {
    use zstd::stream::encode_all;
    Ok(encode_all(data, 3)?)
}

/// Decompress data using zstd
fn decompress(data: &[u8]) -> Result<Vec<u8>> {
    use zstd::stream::decode_all;
    Ok(decode_all(data)?)
}