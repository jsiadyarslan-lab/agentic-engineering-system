//! Network verification probes

use crate::policy::{NetworkPolicy, DnsPolicy};
use crate::error::NetworkError;
use crate::isolator::{VerificationResult, ProbeResult};
use std::net::{IpAddr, SocketAddr, ToSocketAddrs};
use std::time::{Duration, Instant};
use tokio::net::TcpStream;
use tokio::time::timeout;

/// Probe target for verification
#[derive(Debug, Clone)]
pub struct ProbeTarget {
    pub address: String,
    pub port: u16,
    pub probe_type: ProbeType,
}

/// Type of network probe
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProbeType {
    TcpConnect,
    HttpGet,
    DnsResolve,
    IcmpPing,
}

/// Run all verification probes for a network policy
pub async fn run_verification_probes(policy: &crate::policy::NetworkPolicy) -> crate::isolator::VerificationResult {
    let mut egress_test = ProbeResult {
        allowed: false,
        target: "8.8.8.8:53".to_string(),
        latency_ms: 0,
        error: None,
    };
    
    let mut ingress_test = ProbeResult {
        allowed: false,
        target: "0.0.0.0:80".to_string(),
        latency_ms: 0,
        error: None,
    };
    
    let mut dns_test = ProbeResult {
        allowed: false,
        target: "google.com".to_string(),
        latency_ms: 0,
        error: None,
    };
    
    // Run egress test
    if policy.mode != crate::policy::NetworkMode::Ingress && policy.mode != crate::policy::NetworkMode::None {
        egress_test = run_tcp_probe("8.8.8.8", 53, Duration::from_secs(5)).await;
    }
    
    // Run ingress test
    if policy.mode != crate::policy::NetworkMode::Egress && policy.mode != crate::policy::NetworkMode::None {
        ingress_test = run_tcp_listen_probe(80, Duration::from_secs(5)).await;
    }
    
    // Run DNS test
    if policy.dns_policy != crate::policy::DnsPolicy::BlockAll {
        dns_test = run_dns_probe("google.com").await;
    }
    
    let success = egress_test.allowed && ingress_test.allowed && dns_test.allowed;
    
    let details = format!("Egress: {}, Ingress: {}, DNS: {}", 
        if egress_test.allowed { "PASS" } else { "FAIL" },
        if ingress_test.allowed { "PASS" } else { "FAIL" },
        if dns_test.allowed { "PASS" } else { "FAIL" },
    );
    
    crate::isolator::VerificationResult {
        success,
        egress_test,
        ingress_test,
        dns_test,
        details,
    }
}

/// Run TCP connection probe
async fn run_tcp_probe(host: &str, port: u16, timeout_duration: Duration) -> ProbeResult {
    let start = Instant::now();
    let target = format!("{}:{}", host, port);
    
    let addr = format!("{}:{}", host, port);
    let result = tokio::time::timeout(timeout_duration, TcpStream::connect(&addr)).await;
    
    let latency = start.elapsed().as_millis() as u64;
    
    match result {
        Ok(Ok(_stream)) => ProbeResult {
            allowed: true,
            target: format!("{}:{}", host, port),
            latency_ms: latency,
            error: None,
        },
        Ok(Err(e)) => ProbeResult {
            allowed: false,
            target: format!("{}:{}", host, port),
            latency_ms: latency,
            error: Some(e.to_string()),
        },
        Err(_) => ProbeResult {
            allowed: false,
            target: format!("{}:{}", host, port),
            latency_ms: latency,
            error: Some("Timeout".to_string()),
        },
    }
}

/// Run TCP listener probe for ingress
async fn run_tcp_listen_probe(port: u16, _timeout: Duration) -> ProbeResult {
    let start = Instant::now();
    let target = format!("0.0.0.0:{}", port);
    
    // Try to bind to the port
    let listener_result = tokio::net::TcpListener::bind(format!("0.0.0.0:{}", port)).await;
    
    let latency = start.elapsed().as_millis() as u64;
    
    match listener_result {
        Ok(_listener) => ProbeResult {
            allowed: true,
            target,
            latency_ms: latency,
            error: None,
        },
        Err(e) => ProbeResult {
            allowed: false,
            target,
            latency_ms: latency,
            error: Some(e.to_string()),
        },
    }
}

/// Run DNS probe
async fn run_dns_probe(hostname: &str) -> ProbeResult {
    let start = Instant::now();
    let target = hostname.to_string();
    
    let result = tokio::net::lookup_host(format!("{}:53", hostname)).await;
    
    let latency = start.elapsed().as_millis() as u64;
    
    match result {
        Ok(_) => ProbeResult {
            allowed: true,
            target,
            latency_ms: latency,
            error: None,
        },
        Err(e) => ProbeResult {
            allowed: false,
            target,
            latency_ms: latency,
            error: Some(e.to_string()),
        },
    }
}