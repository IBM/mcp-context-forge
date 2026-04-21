// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! URL validation with hostname resolution and network filtering for the Rust MCP runtime.
//!
//! This module validates **OUTGOING** requests from the Rust runtime to Python backend services
//! (not client-facing requests). It protects against SSRF (Server-Side Request Forgery) attacks
//! via misconfigured or compromised environment variables (BACKEND_RPC_URL, etc.) that could
//! point to internal metadata endpoints or other sensitive network destinations.
//!
//! # Threat Model
//!
//! - **Attack vector**: Compromised/misconfigured environment variables
//! - **Target**: Cloud metadata endpoints (169.254.169.254), internal services
//! - **Defense**: Hostname resolution + network range blocking before HTTP request
//!
//! # Scope
//!
//! URLs validated before reqwest HTTP calls to backend services:
//! - Authentication: `backend_authenticate_url()`
//! - Tool operations: `backend_tools_call_resolve_url()`, `backend_tools_call_url()`, etc.
//! - All other backend RPC endpoints
//!
//! See `AppState::validate_backend_url()` in `lib.rs` for the standard call pattern.
//!
//! # Features
//!
//! - Length validation (configurable max length)
//! - Scheme allowlist (http, https, ws, wss only)
//! - Pattern blocking (javascript:, data:, file:, etc.)
//! - IPv6 blocking
//! - CRLF injection prevention
//! - Credentials in URL blocking
//! - Pattern detection for malformed content
//! - **Network Filtering**:
//!   - Hostname normalization
//!   - Blocked hostname list check
//!   - DNS resolution of all A/AAAA records
//!   - CIDR-based IP filtering
//!   - Localhost filtering (configurable, allowed by default)
//!   - Private network filtering (configurable)
//!   - Allowlist support for specific private ranges
//!
//! # Configuration
//!
//! All filtering settings are loaded from environment variables via `RuntimeConfig`:
//!
//! - `VALIDATION_ENABLED=true` - Enable validation (default: true)
//! - `BLOCKED_NETWORKS` - CIDR ranges to block (comma-separated)
//! - `BLOCKED_HOSTS` - Hostnames to block (comma-separated)
//! - `ALLOW_LOCALHOST=true` - Allow localhost access (default: true)
//! - `ALLOW_PRIVATE_NETWORKS=false` - Allow RFC1918 networks (default: false)
//! - `ALLOWED_NETWORKS` - Allowlist specific CIDR ranges (comma-separated)
//! - `DNS_FAIL_CLOSED=true` - Fail closed on DNS errors (default: true)
//! - `MAX_URL_LENGTH=2048` - Maximum URL length (default: 2048)

use crate::config::RuntimeConfig;
use async_trait::async_trait;
use hickory_resolver::TokioResolver;
use ipnetwork::IpNetwork;
use regex::Regex;
use std::collections::HashMap;
use std::net::IpAddr;
use std::sync::Arc;
use std::time::{Duration, Instant};
use thiserror::Error;
use tokio::sync::RwLock;
use tracing::debug;
use url::Url;

/// Type alias for DNS cache entry: (resolved IPs, expiry time)
type DnsCacheEntry = (Vec<IpAddr>, Instant);

/// Type alias for DNS cache: hostname -> cache entry
type DnsCache = HashMap<String, DnsCacheEntry>;

/// Trait for DNS resolution to allow mocking in tests.
#[async_trait]
pub trait DnsResolver: Send + Sync {
    /// Lookup IP addresses for a hostname.
    async fn lookup_ip(&self, hostname: &str) -> Result<Vec<IpAddr>, String>;
}

/// Real DNS resolver using hickory-resolver.
pub struct HickoryDnsResolver {
    resolver: Arc<TokioResolver>,
}

impl HickoryDnsResolver {
    /// Create a new hickory DNS resolver.
    pub fn new() -> Result<Self, String> {
        let resolver = TokioResolver::builder_tokio()
            .map_err(|e| format!("Failed to create DNS resolver builder: {}", e))?
            .build();
        Ok(Self {
            resolver: Arc::new(resolver),
        })
    }
}

#[async_trait]
impl DnsResolver for HickoryDnsResolver {
    async fn lookup_ip(&self, hostname: &str) -> Result<Vec<IpAddr>, String> {
        match self.resolver.lookup_ip(hostname).await {
            Ok(lookup) => {
                let ips: Vec<IpAddr> = lookup.iter().collect();
                Ok(ips)
            }
            Err(e) => Err(format!("DNS lookup failed: {}", e)),
        }
    }
}

/// Mock DNS resolver for testing.
#[derive(Clone)]
pub struct MockDnsResolver {
    /// Map of hostname -> IP addresses
    responses: Arc<HashMap<String, Vec<IpAddr>>>,
}

impl MockDnsResolver {
    /// Create a new mock DNS resolver with predefined responses.
    pub fn new(responses: HashMap<String, Vec<IpAddr>>) -> Self {
        Self {
            responses: Arc::new(responses),
        }
    }
}

#[async_trait]
impl DnsResolver for MockDnsResolver {
    async fn lookup_ip(&self, hostname: &str) -> Result<Vec<IpAddr>, String> {
        // Normalize hostname: lowercase, strip trailing dots
        let normalized = hostname.to_lowercase().trim_end_matches('.').to_string();

        match self.responses.get(&normalized) {
            Some(ips) => Ok(ips.clone()),
            None => Err(format!("Mock DNS: no entry configured for {}", hostname)),
        }
    }
}

/// Errors that can occur during URL validation.
#[derive(Debug, Error)]
pub enum ValidationError {
    #[error("{field}: URL cannot be empty")]
    EmptyUrl { field: String },

    #[error("{field}: URL exceeds maximum length of {max}")]
    TooLong { field: String, max: usize },

    #[error("{field}: URL must start with one of: {allowed_schemes}")]
    InvalidScheme {
        field: String,
        allowed_schemes: String,
    },

    #[error("{field}: URL contains unsupported protocol")]
    DangerousProtocol { field: String },

    #[error("{field}: URL contains IPv6 address which is not supported")]
    IPv6NotSupported { field: String },

    #[error("{field}: URL contains protocol-relative format which is not supported")]
    ProtocolRelativeUrl { field: String },

    #[error("{field}: URL contains line breaks which are not allowed")]
    ContainsLineBreaks { field: String },

    #[error("{field}: URL contains spaces which are not allowed")]
    ContainsSpaces { field: String },

    #[error("{field}: URL is not valid: {reason}")]
    InvalidUrl { field: String, reason: String },

    #[error("{field}: URL contains invalid IP address (0.0.0.0)")]
    InvalidZeroIp { field: String },

    #[error("{field}: URL contains invalid port number")]
    InvalidPort { field: String },

    #[error("{field}: URL contains credentials which are not allowed")]
    ContainsCredentials { field: String },

    #[error("{field}: URL contains patterns that may cause issues")]
    ContainsSuspiciousPatterns { field: String },

    #[error("{field}: Hostname '{hostname}' is in the blocked list")]
    BlockedHostname { field: String, hostname: String },

    #[error("{field}: Cannot resolve hostname '{hostname}': {reason}")]
    DnsError {
        field: String,
        hostname: String,
        reason: String,
    },

    #[error("{field}: IP address {ip} is blocked by network filter {network}")]
    BlockedNetwork {
        field: String,
        ip: String,
        network: String,
    },

    #[error("{field}: IP address {ip} is in localhost range")]
    BlockedLocalhost { field: String, ip: String },

    #[error("{field}: IP address {ip} is in private network range {network}")]
    BlockedPrivateNetwork {
        field: String,
        ip: String,
        network: String,
    },
}

/// Configuration for URL validation.
#[derive(Clone)]
pub struct UrlValidatorConfig {
    pub enabled: bool,
    pub max_url_length: usize,
    pub blocked_networks: Vec<IpNetwork>,
    pub blocked_hosts: Vec<String>,
    pub allow_localhost: bool,
    pub allow_private_networks: bool,
    pub allowed_networks: Vec<IpNetwork>,
    pub dns_fail_closed: bool,
    pub dns_cache_ttl: Duration,
}

impl Default for UrlValidatorConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            max_url_length: 2048,
            blocked_networks: vec![
                "169.254.169.254/32".parse().unwrap(), // Cloud metadata endpoints
            ],
            blocked_hosts: vec![
                "metadata.google.internal".to_string(),
                "metadata.goog".to_string(),
            ],
            allow_localhost: true, // Allow localhost by default for development
            allow_private_networks: false,
            allowed_networks: vec![],
            dns_fail_closed: true,
            dns_cache_ttl: Duration::from_secs(300), // 5 minutes
        }
    }
}

/// URL validator with network filtering capabilities.
pub struct UrlValidator {
    config: UrlValidatorConfig,
    resolver: Arc<dyn DnsResolver>,
    dns_cache: Arc<RwLock<DnsCache>>,
    suspicious_pattern: Regex,
}

impl UrlValidator {
    /// Create a validator from runtime configuration.
    pub fn from_config(runtime_config: &RuntimeConfig) -> Result<Self, String> {
        // Read config from RuntimeConfig (sourced from clap + env vars)
        let mut config = UrlValidatorConfig {
            enabled: runtime_config.validation_enabled,
            max_url_length: runtime_config.max_url_length,
            allow_localhost: runtime_config.allow_localhost,
            allow_private_networks: runtime_config.allow_private_networks,
            dns_fail_closed: runtime_config.dns_fail_closed,
            blocked_networks: Vec::new(),
            blocked_hosts: Vec::new(),
            allowed_networks: Vec::new(),
            dns_cache_ttl: Duration::from_secs(300), // Keep 5-minute cache TTL
        };

        // Parse blocked networks - FAIL CLOSED on invalid CIDR
        for network_str in runtime_config
            .blocked_networks
            .iter()
            .map(|s| s.trim())
            .filter(|s| !s.is_empty())
        {
            match network_str.parse::<IpNetwork>() {
                Ok(network) => config.blocked_networks.push(network),
                Err(e) => {
                    return Err(format!(
                        "Invalid CIDR in BLOCKED_NETWORKS '{}': {}",
                        network_str, e
                    ));
                }
            }
        }

        // Parse allowed networks - FAIL CLOSED on invalid CIDR
        for network_str in runtime_config
            .allowed_networks
            .iter()
            .map(|s| s.trim())
            .filter(|s| !s.is_empty())
        {
            match network_str.parse::<IpNetwork>() {
                Ok(network) => config.allowed_networks.push(network),
                Err(e) => {
                    return Err(format!(
                        "Invalid CIDR in ALLOWED_NETWORKS '{}': {}",
                        network_str, e
                    ));
                }
            }
        }

        // Parse blocked hosts
        config.blocked_hosts = runtime_config
            .blocked_hosts
            .iter()
            .map(|s| s.trim().to_lowercase())
            .filter(|s| !s.is_empty())
            .collect();

        let resolver = Arc::new(HickoryDnsResolver::new()?) as Arc<dyn DnsResolver>;
        let dns_cache = Arc::new(RwLock::new(HashMap::new()));

        // Pattern for detecting suspicious content
        // Note: \bon\w+ uses word boundary to match HTML event handlers (onclick, onerror)
        // without matching words containing "on" (like session_id)
        let suspicious_pattern =
            Regex::new(r"(?i)<script|javascript:|data:|vbscript:|\bon\w+\s*=").unwrap();

        Ok(Self {
            config,
            resolver,
            dns_cache,
            suspicious_pattern,
        })
    }

    /// Create a validator with a custom DNS resolver (for testing).
    pub fn with_resolver(config: UrlValidatorConfig, resolver: Arc<dyn DnsResolver>) -> Self {
        let dns_cache = Arc::new(RwLock::new(HashMap::new()));
        // Note: \bon\w+ uses word boundary to match HTML event handlers (onclick, onerror)
        // without matching words containing "on" (like session_id)
        let suspicious_pattern =
            Regex::new(r"(?i)<script|javascript:|data:|vbscript:|\bon\w+\s*=").unwrap();

        Self {
            config,
            resolver,
            dns_cache,
            suspicious_pattern,
        }
    }

    /// Validate a URL.
    pub async fn validate_url(&self, url: &str, field: &str) -> Result<(), ValidationError> {
        if !self.config.enabled {
            return Ok(());
        }

        // Basic checks
        if url.is_empty() {
            return Err(ValidationError::EmptyUrl {
                field: field.to_string(),
            });
        }

        if url.len() > self.config.max_url_length {
            return Err(ValidationError::TooLong {
                field: field.to_string(),
                max: self.config.max_url_length,
            });
        }

        // Check for line breaks and spaces
        if url.contains('\n') || url.contains('\r') {
            return Err(ValidationError::ContainsLineBreaks {
                field: field.to_string(),
            });
        }

        if url.contains(' ') {
            return Err(ValidationError::ContainsSpaces {
                field: field.to_string(),
            });
        }

        // Check for protocol-relative URLs
        if url.starts_with("//") {
            return Err(ValidationError::ProtocolRelativeUrl {
                field: field.to_string(),
            });
        }

        // Check for suspicious patterns
        if self.suspicious_pattern.is_match(url) {
            return Err(ValidationError::ContainsSuspiciousPatterns {
                field: field.to_string(),
            });
        }

        // Parse URL
        let parsed_url = Url::parse(url).map_err(|e| ValidationError::InvalidUrl {
            field: field.to_string(),
            reason: e.to_string(),
        })?;

        // Validate scheme
        let scheme = parsed_url.scheme();
        if !["http", "https", "ws", "wss"].contains(&scheme) {
            return Err(ValidationError::InvalidScheme {
                field: field.to_string(),
                allowed_schemes: "http, https, ws, wss".to_string(),
            });
        }

        // Check for credentials in URL
        if !parsed_url.username().is_empty() || parsed_url.password().is_some() {
            return Err(ValidationError::ContainsCredentials {
                field: field.to_string(),
            });
        }

        // Get hostname
        let hostname = parsed_url
            .host_str()
            .ok_or_else(|| ValidationError::InvalidUrl {
                field: field.to_string(),
                reason: "Missing hostname".to_string(),
            })?;

        // Check for IPv6
        if hostname.contains(':') && hostname.contains('[') {
            return Err(ValidationError::IPv6NotSupported {
                field: field.to_string(),
            });
        }

        // Check for 0.0.0.0
        if hostname == "0.0.0.0" {
            return Err(ValidationError::InvalidZeroIp {
                field: field.to_string(),
            });
        }

        // Normalize hostname
        let normalized_hostname = hostname.to_lowercase().trim_end_matches('.').to_string();

        // Check blocked hostnames
        if self.config.blocked_hosts.contains(&normalized_hostname) {
            return Err(ValidationError::BlockedHostname {
                field: field.to_string(),
                hostname: normalized_hostname,
            });
        }

        // Resolve hostname to IPs
        let ips = match self.resolve_hostname_cached(&normalized_hostname).await {
            Ok(ips) => ips,
            Err(e) => {
                // DNS resolution failed - apply fail-closed/open policy
                if self.config.dns_fail_closed {
                    return Err(e);
                } else {
                    // Fail-open: allow on DNS errors
                    debug!(
                        "DNS resolution failed for {}, failing open",
                        normalized_hostname
                    );
                    return Ok(());
                }
            }
        };

        // If DNS returns empty (legitimately no records), fail closed
        if ips.is_empty() {
            return Err(ValidationError::DnsError {
                field: field.to_string(),
                hostname: normalized_hostname,
                reason: "No DNS records found".to_string(),
            });
        }

        // Check each resolved IP
        for ip in &ips {
            self.validate_ip(ip, field)?;
        }

        Ok(())
    }

    /// Resolve hostname to IPs with caching.
    async fn resolve_hostname_cached(
        &self,
        hostname: &str,
    ) -> Result<Vec<IpAddr>, ValidationError> {
        // Try parsing as IP first
        if let Ok(ip) = hostname.parse::<IpAddr>() {
            return Ok(vec![ip]);
        }

        // Check cache (read lock)
        {
            let cache = self.dns_cache.read().await;
            if let Some((ips, expiry)) = cache.get(hostname) {
                if Instant::now() < *expiry {
                    debug!("DNS cache hit for {}", hostname);
                    return Ok(ips.clone());
                }
            }
        }

        // Cache miss - resolve
        debug!("DNS cache miss for {}, resolving...", hostname);
        let ips =
            self.resolver
                .lookup_ip(hostname)
                .await
                .map_err(|e| ValidationError::DnsError {
                    field: "Backend URL".to_string(),
                    hostname: hostname.to_string(),
                    reason: e,
                })?;

        // Update cache (write lock)
        {
            let mut cache = self.dns_cache.write().await;
            let expiry = Instant::now() + self.config.dns_cache_ttl;
            cache.insert(hostname.to_string(), (ips.clone(), expiry));
        }

        Ok(ips)
    }

    /// Validate an IP address against filtering rules.
    fn validate_ip(&self, ip: &IpAddr, field: &str) -> Result<(), ValidationError> {
        // Check if in allowlist
        if !self.config.allowed_networks.is_empty() {
            let in_allowlist = self
                .config
                .allowed_networks
                .iter()
                .any(|network| network.contains(*ip));

            if in_allowlist {
                return Ok(());
            }
        }

        // Check blocked networks
        for network in &self.config.blocked_networks {
            if network.contains(*ip) {
                return Err(ValidationError::BlockedNetwork {
                    field: field.to_string(),
                    ip: ip.to_string(),
                    network: network.to_string(),
                });
            }
        }

        // Check localhost
        if !self.config.allow_localhost && ip.is_loopback() {
            return Err(ValidationError::BlockedLocalhost {
                field: field.to_string(),
                ip: ip.to_string(),
            });
        }

        // Check private networks
        if !self.config.allow_private_networks {
            let private_networks = [
                "10.0.0.0/8",
                "172.16.0.0/12",
                "192.168.0.0/16",
                "169.254.0.0/16", // Link-local
            ];

            for network_str in &private_networks {
                let network: IpNetwork = network_str.parse().unwrap();
                if network.contains(*ip) {
                    return Err(ValidationError::BlockedPrivateNetwork {
                        field: field.to_string(),
                        ip: ip.to_string(),
                        network: network.to_string(),
                    });
                }
            }
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::Parser;

    fn create_test_config() -> RuntimeConfig {
        RuntimeConfig::try_parse_from(["test"]).expect("Failed to create test config")
    }

    #[tokio::test]
    async fn test_valid_public_url() {
        let mut responses = HashMap::new();
        responses.insert(
            "api.example.com".to_string(),
            vec!["93.184.216.34".parse().unwrap()], // Public IP
        );
        let resolver = Arc::new(MockDnsResolver::new(responses));

        let config = UrlValidatorConfig::default();
        let validator = UrlValidator::with_resolver(config, resolver);

        let result = validator
            .validate_url("https://api.example.com/v1", "test")
            .await;
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_empty_url() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).expect("Failed to create validator");

        let result = validator.validate_url("", "test").await;
        assert!(matches!(result, Err(ValidationError::EmptyUrl { .. })));
    }

    #[tokio::test]
    async fn test_url_too_long() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).expect("Failed to create validator");

        let long_url = format!("https://example.com/{}", "a".repeat(3000));
        let result = validator.validate_url(&long_url, "test").await;
        assert!(matches!(result, Err(ValidationError::TooLong { .. })));
    }

    #[tokio::test]
    async fn test_invalid_scheme() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).expect("Failed to create validator");

        let result = validator.validate_url("ftp://example.com/", "test").await;
        assert!(matches!(result, Err(ValidationError::InvalidScheme { .. })));
    }

    #[tokio::test]
    async fn test_credentials_in_url() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).expect("Failed to create validator");

        let result = validator
            .validate_url("https://user:pass@example.com/", "test") // pragma: allowlist secret
            .await;
        assert!(matches!(
            result,
            Err(ValidationError::ContainsCredentials { .. })
        ));
    }

    #[tokio::test]
    async fn test_localhost_allowed_by_default() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).expect("Failed to create validator");

        let result = validator
            .validate_url("http://127.0.0.1:4444/rpc", "test")
            .await;
        assert!(result.is_ok(), "Localhost should be allowed by default");
    }

    #[tokio::test]
    async fn test_localhost_with_query_params() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).expect("Failed to create validator");

        let result = validator
            .validate_url(
                "http://127.0.0.1:8787/_internal/mcp/transport?session_id=test",
                "test",
            )
            .await;
        assert!(
            result.is_ok(),
            "Localhost with query params should be allowed: {:?}",
            result.err()
        );
    }
}
