//! gRPC service implementation for substrate

use std::sync::Arc;
use tonic::{Request, Response, Status};
use substrate_core::{
    SandboxRequest as CoreSandboxRequest,
    SandboxExecutionRecord as CoreExecutionRecord,
    ExecutionLimits as CoreExecutionLimits,
    NetworkMode as CoreNetworkMode,
    SandboxTermination as CoreSandboxTermination,
    ArtifactCustodyEntry as CoreArtifactCustodyEntry,
    Substrate,
    SubstrateDescriptor,
    SubstrateCapability,
    ResourceLimits as CoreResourceLimits,
    CapabilityRequest as CoreCapabilityRequest,
    CapabilityResponse as CoreCapabilityResponse,
    SubstrateError,
    SubstrateDescriptor,
    SubstrateCapability,
    ResourceLimits as CoreResourceLimits,
};
use tonic::{Request, Response, Status};
use tonic::transport::UnixListener;
use tokio::sync::Semaphore;
use tracing::{info, error, warn};

use substrate_linux::LinuxSubstrate;
use substrate_linux::LinuxSubstrateConfig;

mod proto {
    tonic::include_proto!("substrate");
}

pub mod proto {
    tonic::include_proto!("substrate");
}

/// Substrate gRPC service implementation
#[derive(Clone)]
pub struct SubstrateService {
    substrate: Arc<dyn Substrate>,
    semaphore: Arc<tokio::sync::Semaphore>,
}

impl SubstrateService {
    pub fn new(substrate: Arc<dyn Substrate>) -> Self {
        let max_concurrent = substrate.capability().max_concurrent_sandboxes as usize;
        Self {
            substrate,
            semaphore: Arc::new(tokio::sync::Semaphore::new(max_concurrent)),
        }
    }

    /// Convert proto ExecutionLimits to core ExecutionLimits
    fn proto_to_core_limits(limits: &crate::proto::ExecutionLimits) -> substrate_core::ExecutionLimits {
        substrate_core::ExecutionLimits {
            memory_bytes: if limits.memory_bytes == 0 { None } else { Some(limits.memory_bytes) },
            cpu_percent: if limits.cpu_percent == 0.0 { None } else { Some(limits.cpu_percent) },
            cpu_time_seconds: if limits.cpu_time_seconds == 0 { None } else { Some(limits.cpu_time_seconds) },
            max_processes: if limits.max_processes == 0 { None } else { Some(limits.max_processes) },
            max_file_size: if limits.max_file_size == 0 { None } else { Some(limits.max_file_size) },
            max_open_files: if limits.max_open_files == 0 { None } else { Some(limits.max_open_files) },
            wall_time_seconds: if limits.wall_time_seconds == 0 { None } else { Some(limits.wall_time_seconds) },
            max_output_bytes: if limits.max_output_bytes == 0 { None } else { Some(limits.max_output_bytes) },
            max_artifact_bytes: if limits.max_artifact_bytes == 0 { None } else { Some(limits.max_artifact_bytes) },
            max_workspace_bytes: if limits.max_workspace_bytes == 0 { None } else { Some(limits.max_workspace_bytes) },
        }
    }

    /// Convert proto NetworkMode to core NetworkMode
    fn proto_to_core_network(mode: i32) -> substrate_core::NetworkMode {
        match mode {
            0 => substrate_core::NetworkMode::None,
            1 => substrate_core::NetworkMode::Egress,
            2 => substrate_core::NetworkMode::Ingress,
            3 => substrate_core::NetworkMode::EgressFiltered,
            _ => substrate_core::NetworkMode::None,
        }
    }

    /// Convert core ExecutionLimits to proto
    fn core_to_proto_limits(limits: &substrate_core::ExecutionLimits) -> crate::proto::ExecutionLimits {
        crate::proto::ExecutionLimits {
            memory_bytes: limits.memory_bytes.unwrap_or(0),
            cpu_percent: limits.cpu_percent.unwrap_or(0.0),
            cpu_time_seconds: limits.cpu_time_seconds.unwrap_or(0),
            max_processes: limits.max_processes.unwrap_or(0),
            max_file_size: limits.max_file_size.unwrap_or(0),
            max_open_files: limits.max_open_files.unwrap_or(0),
            wall_time_seconds: limits.wall_time_seconds.unwrap_or(0),
            max_output_bytes: limits.max_output_bytes.unwrap_or(0),
            max_artifact_bytes: limits.max_artifact_bytes.unwrap_or(0),
            max_workspace_bytes: limits.max_workspace_bytes.unwrap_or(0),
        }
    }

    /// Convert core NetworkMode to proto
    fn core_to_proto_network(mode: substrate_core::NetworkMode) -> i32 {
        match mode {
            substrate_core::NetworkMode::None => 0,
            substrate_core::NetworkMode::Egress => 1,
            substrate_core::NetworkMode::Ingress => 2,
            substrate_core::NetworkMode::EgressFiltered => 3,
        }
    }

    /// Convert core SandboxTermination to proto
    fn core_to_proto_termination(term: substrate_core::SandboxTermination) -> i32 {
        match term {
            substrate_core::SandboxTermination::Completed => 0,
            substrate_core::SandboxTermination::Failed => 1,
            substrate_core::SandboxTermination::Timeout => 2,
            substrate_core::SandboxTermination::LimitBreach => 2,
            substrate_core::SandboxTermination::FailedToStart => 4,
            substrate_core::SandboxTermination::NotRun => 5,
        }
    }

    /// Convert core ArtifactCustodyEntry to proto
    fn core_to_proto_artifact(artifact: substrate_core::ArtifactCustodyEntry) -> crate::proto::ArtifactCustodyEntry {
        crate::proto::ArtifactCustodyEntry {
            path: artifact.path,
            sha256: artifact.sha256,
            size: artifact.size,
            kind: artifact.kind,
        }
    }

    /// Convert proto CapabilityRequest to core
    fn proto_to_core_cap_request(req: &crate::proto::CapabilityRequest) -> substrate_core::CapabilityRequest {
        substrate_core::CapabilityRequest {
            required: req.required.clone(),
            preferred: req.preferred.clone(),
            resource_limits: Self::proto_to_core_limits(req.resource_limits.as_ref().unwrap()),
        }
    }

    /// Convert core CapabilityResponse to proto
    fn core_to_proto_cap_response(resp: &substrate_core::CapabilityResponse) -> crate::proto::CapabilityResponse {
        crate::proto::CapabilityResponse {
            granted: resp.granted.clone(),
            denied: resp.denied.clone(),
            adjusted_limits: Self::core_to_proto_limits(&resp.adjusted_limits),
            substrate_type: resp.substrate_type.clone(),
        }
    }
}

#[tonic::async_trait]
impl crate::proto::substrate_service_server::SubstrateService for SubstrateService {
    async fn execute(
        &self,
        request: Request<ExecuteRequest>,
    ) -> Result<Response<ExecuteResponse>, Status> {
        let req = request.into_inner();
        
        // Acquire semaphore for concurrency control
        let _permit = self.semaphore.acquire().await.map_err(|_| {
            Status::resource_exhausted("Too many concurrent executions")
        })?;

        let req = request.into_inner();
        
        // Convert proto request to core request
        let core_req = substrate_core::SandboxRequest {
            sandbox_id: req.sandbox_id,
            image: req.image,
            command: req.command,
            limits: Self::proto_to_core_limits(req.limits.as_ref().unwrap()),
            env_names: req.env.into_iter().map(|(k, v)| k).collect(),
            network: Self::proto_to_core_network(req.network),
            workspace_root: req.workspace_root,
            artifacts_dir: req.artifacts_dir,
        };

        // Execute on substrate
        let result = self.substrate.execute(core_req).await
            .map_err(|e| Status::internal(format!("Execution failed: {}", e)))?;
        
        // Convert result to proto
        let response = crate::proto::ExecuteResponse {
            sandbox_id: result.sandbox_id,
            executed: result.executed,
            exit_code: result.exit_code.unwrap_or(0),
            termination: Self::core_to_proto_termination(result.termination),
            duration_ms: result.duration_ms,
            stdout: result.stdout_reference,
            stderr: result.stderr_reference,
            limits_applied: Some(Self::core_to_proto_limits(&result.limits_applied)),
            artifacts: result.artifacts.into_iter().map(Self::core_to_proto_artifact).collect(),
            started_at: result.started_at,
            finished_at: result.finished_at,
        };

        Ok(Response::new(response))
    }

    async fn execute_stream(
        &self,
        request: Request<ExecuteStreamRequest>,
    ) -> Result<Response<tonic::codec::Streaming<ExecuteStreamResponse>>, Status> {
        let req = request.into_inner().request.unwrap();
        
        // Acquire semaphore
        let _permit = self.semaphore.acquire().await.map_err(|_| {
            Status::resource_exhausted("Too many concurrent executions")
        })?;

        let req = req.request.unwrap();
        
        let core_req = substrate_core::SandboxRequest {
            sandbox_id: req.sandbox_id,
            image: req.image,
            command: req.command,
            limits: Self::proto_to_core_limits(req.limits.unwrap_or_default()),
            env_names: req.env_names,
            network: Self::proto_to_core_network(req.network),
            workspace_root: req.workspace_root,
            artifacts_dir: req.artifacts_dir,
        };

        let substrate = self.substrate.clone();
        let (tx, rx) = tokio::sync::mpsc::channel(100);
        
        let substrate_clone = substrate.clone();
        let core_req = core_req;
        
        tokio::spawn(async move {
            let result = substrate_clone.execute(core_req).await;
            
            match result {
                Ok(result) => {
                    let response = ExecuteStreamResponse {
                        log: None,
                        final_response: Some(ExecuteResponse {
                            sandbox_id: result.sandbox_id,
                            executed: result.executed,
                            exit_code: result.exit_code.unwrap_or(0),
                            termination: crate::service::SubstrateService::core_to_proto_termination(result.termination),
                            duration_ms: result.duration_ms,
                            stdout: result.stdout_reference,
                            stderr: result.stderr_reference,
                            limits_applied: Some(crate::service::SubstrateService::core_to_proto_limits(&result.limits_applied)),
                            artifacts: result.artifacts.into_iter().map(crate::service::SubstrateService::core_to_proto_artifact).collect(),
                            started_at: result.started_at,
                            finished_at: result.finished_at,
                        }),
                    };
                    let _ = tx.send(Ok(ExecuteStreamResponse {
                        log: None,
                        final_response: Some(response),
                    })).await;
                }
                Err(e) => {
                    let _ = tx.send(Err(Status::internal(format!("Execution failed: {}", e)))).await;
                }
            });
        });
        
        let stream = tokio_stream::wrappers::ReceiverStream::new(rx);
        Ok(Response::new(Box::pin(stream)))
    }

    async fn health_check(
        &self,
        _request: Request<HealthCheckRequest>,
    ) -> Result<Response<HealthCheckResponse>, Status> {
        let capability = self.substrate.capability();
        let resp = HealthCheckResponse {
            status: Some(HealthStatus {
                status: 0, // HEALTHY
                message: "Substrate is healthy".to_string(),
                timestamp: std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_secs_f64(),
            }),
        };
        Ok(Response::new(resp))
    }

    async fn negotiate_capability(
        &self,
        request: Request<CapabilityRequest>,
    ) -> Result<Response<CapabilityResponse>, Status> {
        let req = request.into_inner();
        let core_req = CapabilityRequest {
            required: req.required,
            preferred: req.preferred,
            resource_limits: Self::proto_to_core_limits(req.resource_limits.as_ref().unwrap()),
        };
        
        let result = self.substrate.negotiate_capability(core_req).await
            .map_err(|e| Status::internal(format!("Capability negotiation failed: {}", e)))?;
        
        let response = CapabilityResponse {
            granted: result.granted,
            denied: result.denied,
            adjusted_limits: Some(Self::core_to_proto_limits(&result.adjusted_limits)),
            substrate_type: result.substrate_type,
        };
        
        Ok(Response::new(response))
    }
}

/// Run the gRPC server
pub async fn run_server(socket_path: &str) -> Result<(), Box<dyn std::error::Error>> {
    // Remove existing socket file
    let _ = std::fs::remove_file(socket_path);
    
    // Create substrate
    let config = LinuxSubstrateConfig::default();
    let substrate = Arc::new(LinuxSubstrate::new(LinuxSubstrateConfig::default())?);
    
    let service = SubstrateService::new(Arc::new(substrate));
    
    let listener = UnixListener::bind(socket_path)?;
    
    info!("Starting substrate gRPC server on {}", socket_path);
    
    Server::builder()
        .add_service(crate::proto::substrate_service_server::SubstrateServiceServer::new(SubstrateService::new(
            Arc::new(LinuxSubstrate::new(LinuxSubstrateConfig::default())?),
        )))
        .serve_with_incoming(tokio_stream::wrappers::UnixListenerStream::new(listener))
        .await?;
    
    Ok(())
}