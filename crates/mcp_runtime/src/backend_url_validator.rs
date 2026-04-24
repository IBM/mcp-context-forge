// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti, Mohan Lakshmaiah

//! Backend URL validation for outgoing Rust→Python HTTP requests.
//!
//! This module protects against SSRF (Server-Side Request Forgery) via misconfigured
//! environment variables by validating that backend service URLs point to approved hosts.
//!
//! # Scope
//!
//! **Validates**: Outgoing HTTP requests from Rust MCP runtime → Python backend services
//! **Does NOT validate**: Incoming client requests to the MCP runtime
//!
//! # Threat Model
//!
//! **Defends against**:
//! - Misconfigured `MCP_RUST_BACKEND_RPC_URL` pointing to cloud metadata endpoints (e.g., 169.254.169.254)
//! - Misconfigured backend URLs pointing to blocked internal CIDR ranges
//! - Accidental exposure of internal network resources via operator error
//!
//! # Out of Scope (deliberate, NOT a security guarantee)
//!
//! These attack vectors are explicitly **not** mitigated by this module. Operators who
//! need defense against them must pin DNS resolution and/or disable HTTP redirects at the
//! [`reqwest::Client`] builder level (the shared runtime client already sets
//! `redirect::Policy::none()`).
//!
//! - **DNS rebinding / DNS poisoning**: The allowlist is a string match on the URL host;
//!   the resolved IP is never checked. A host that is allowlisted at validation time can
//!   resolve to any IP at connection time.
//! - **`/etc/hosts` or resolver manipulation**: Same as above — no IP-level verification.
//! - **HTTP redirects**: The validator only inspects the initial URL. Redirects are
//!   neutralized at the client-builder layer via `redirect::Policy::none()`, not here.
//!
//! # Design
//!
//! Uses a simple allowlist + CIDR blocklist approach:
//! 1. Parse URL to extract host.
//! 2. If host is in the allowlist → allow.
//! 3. If host parses as an IP (after stripping IPv6 brackets, and mapping `::ffff:…`
//!    IPv4-compatible addresses back to IPv4), check against blocked CIDR ranges → deny
//!    if matched, allow otherwise.
//! 4. If host is a domain not in the allowlist → deny (fail-closed).
//!
//! No DNS resolution is performed — see "Out of Scope" above.

use ipnetwork::IpNetwork;
use std::{collections::HashSet, net::IpAddr, str::FromStr};
use tracing::{debug, error};
use url::Url;

use crate::config::RuntimeConfig;

fn parse_host_as_ip(host: &str) -> Option<IpAddr> {
    let stripped = host
        .strip_prefix('[')
        .and_then(|s| s.strip_suffix(']'))
        .unwrap_or(host);
    let ip = IpAddr::from_str(stripped).ok()?;
    match ip {
        IpAddr::V6(v6) => match v6.to_ipv4_mapped() {
            Some(v4) => Some(IpAddr::V4(v4)),
            None => Some(IpAddr::V6(v6)),
        },
        v4 => Some(v4),
    }
}

/// Backend URL validator with allowlist-based host filtering.
#[derive(Clone, Debug)]
pub struct BackendUrlValidator {
    /// Approved backend hostnames (e.g., "localhost", "127.0.0.1", "backend.internal")
    allowed_hosts: HashSet<String>,
    /// CIDR ranges to block for IP-based URLs (e.g., cloud metadata endpoints)
    blocked_networks: Vec<IpNetwork>,
    /// Maximum URL length
    max_url_length: usize,
    /// Whether validation is enabled
    validation_enabled: bool,
}

impl BackendUrlValidator {
    /// Creates a new validator from runtime configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if any blocked CIDR range is invalid.
    pub fn from_config(config: &RuntimeConfig) -> Result<Self, String> {
        let allowed_hosts: HashSet<String> = config
            .backend_allowed_hosts
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        let blocked_networks: Result<Vec<IpNetwork>, String> = config
            .backend_blocked_networks
            .split(',')
            .map(|s| s.trim())
            .filter(|s| !s.is_empty())
            .map(|cidr| {
                IpNetwork::from_str(cidr)
                    .map_err(|e| format!("Invalid CIDR network '{}': {}", cidr, e))
            })
            .collect();

        let blocked_networks = blocked_networks?;

        debug!(
            "Backend URL validator initialized: {} allowed hosts, {} blocked networks, validation_enabled={}",
            allowed_hosts.len(),
            blocked_networks.len(),
            config.backend_validation_enabled
        );

        Ok(Self {
            allowed_hosts,
            blocked_networks,
            max_url_length: config.backend_max_url_length,
            validation_enabled: config.backend_validation_enabled,
        })
    }

    /// Validates a backend URL.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - Validation is enabled and URL exceeds max length
    /// - URL cannot be parsed
    /// - Host is not in allowlist and is not an allowed IP
    /// - Host is an IP address in a blocked CIDR range
    pub fn validate_url(&self, url: &str, description: &str) -> Result<(), String> {
        if !self.validation_enabled {
            return Ok(());
        }

        // Length check
        if url.len() > self.max_url_length {
            error!(
                "Backend URL too long for {}: {} bytes (max {})",
                description,
                url.len(),
                self.max_url_length
            );
            return Err(format!(
                "URL exceeds maximum length of {} bytes",
                self.max_url_length
            ));
        }

        // Parse URL
        let parsed = Url::parse(url).map_err(|e| {
            error!("Failed to parse backend URL for {}: {}", description, e);
            format!("Invalid URL: {}", e)
        })?;

        let host = parsed.host_str().ok_or_else(|| {
            error!("Backend URL missing host for {}", description);
            "URL missing host".to_string()
        })?;

        if self.allowed_hosts.contains(host) {
            debug!(
                "Backend URL for {} approved via allowlist: {}",
                description, host
            );
            return Ok(());
        }

        if let Some(ip) = parse_host_as_ip(host) {
            for network in &self.blocked_networks {
                if network.contains(ip) {
                    error!(
                        "Backend URL for {} rejected: IP {} is in blocked network {}",
                        description, ip, network
                    );
                    return Err(format!(
                        "IP address {} is in blocked network {}",
                        ip, network
                    ));
                }
            }
            debug!(
                "Backend URL for {} approved: IP {} not in blocked networks",
                description, ip
            );
            return Ok(());
        }

        error!(
            "Backend URL for {} rejected: domain '{}' not in approved hosts",
            description, host
        );
        Err(format!("Domain '{}' not in approved backend hosts", host))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_config(
        allowed_hosts: &str,
        blocked_networks: &str,
        validation_enabled: bool,
    ) -> RuntimeConfig {
        RuntimeConfig {
            backend_rpc_url: "http://127.0.0.1:4444/rpc".to_string(),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            public_listen_http: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: Vec::new(),
            server_name: "Test".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "Test".to_string(),
            request_timeout_ms: 30_000,
            client_connect_timeout_ms: 5_000,
            client_pool_idle_timeout_seconds: 90,
            client_pool_max_idle_per_host: 1024,
            client_tcp_keepalive_seconds: 30,
            tools_call_plan_ttl_seconds: 30,
            upstream_session_ttl_seconds: 300,
            use_rmcp_upstream_client: false,
            session_core_enabled: false,
            event_store_enabled: false,
            resume_core_enabled: false,
            live_stream_core_enabled: false,
            affinity_core_enabled: false,
            session_auth_reuse_enabled: false,
            session_auth_reuse_ttl_seconds: 30,
            session_ttl_seconds: 3_600,
            event_store_max_events_per_stream: 100,
            event_store_ttl_seconds: 3_600,
            event_store_poll_interval_ms: 250,
            cache_prefix: "test:".to_string(),
            database_url: None,
            redis_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            exit_after_startup_ms: None,
            backend_validation_enabled: validation_enabled,
            backend_allowed_hosts: allowed_hosts.to_string(),
            backend_blocked_networks: blocked_networks.to_string(),
            backend_max_url_length: 2048,
        }
    }

    #[test]
    fn allowlist_approval() {
        let config = test_config("localhost,backend.internal", "169.254.169.254/32", true);
        let validator = BackendUrlValidator::from_config(&config).expect("validator");

        assert!(
            validator
                .validate_url("http://localhost:4444/rpc", "test")
                .is_ok()
        );
        assert!(
            validator
                .validate_url("http://backend.internal/api", "test")
                .is_ok()
        );
    }

    #[test]
    fn allowlist_rejection() {
        let config = test_config("localhost", "169.254.169.254/32", true);
        let validator = BackendUrlValidator::from_config(&config).expect("validator");

        let result = validator.validate_url("http://evil.com/api", "test");
        assert!(result.is_err());
        assert!(
            result
                .unwrap_err()
                .contains("not in approved backend hosts")
        );
    }

    #[test]
    fn ip_allowlist() {
        let config = test_config("127.0.0.1,192.168.1.10", "169.254.169.254/32", true);
        let validator = BackendUrlValidator::from_config(&config).expect("validator");

        assert!(
            validator
                .validate_url("http://127.0.0.1:4444/rpc", "test")
                .is_ok()
        );
        assert!(
            validator
                .validate_url("http://192.168.1.10/api", "test")
                .is_ok()
        );
    }

    #[test]
    fn cidr_blocking() {
        let config = test_config("", "169.254.169.254/32,10.0.0.0/8", true);
        let validator = BackendUrlValidator::from_config(&config).expect("validator");

        let result = validator.validate_url("http://169.254.169.254/metadata", "test");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("blocked network"));

        let result = validator.validate_url("http://10.5.10.20/internal", "test");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("blocked network"));
    }

    #[test]
    fn ip_not_in_blocklist_allowed() {
        let config = test_config("", "169.254.169.254/32", true);
        let validator = BackendUrlValidator::from_config(&config).expect("validator");

        // IP not in blocklist = allowed (even if not in allowlist)
        assert!(
            validator
                .validate_url("http://192.168.1.1/api", "test")
                .is_ok()
        );
    }

    #[test]
    fn url_length_limit() {
        let config = test_config("localhost", "", true);
        let validator = BackendUrlValidator::from_config(&config).expect("validator");

        let long_url = format!("http://localhost/{}", "x".repeat(3000));
        let result = validator.validate_url(&long_url, "test");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("maximum length"));
    }

    #[test]
    fn validation_disabled() {
        let config = test_config("", "169.254.169.254/32", false);
        let validator = BackendUrlValidator::from_config(&config).expect("validator");

        // Everything allowed when validation disabled
        assert!(
            validator
                .validate_url("http://evil.com/api", "test")
                .is_ok()
        );
        assert!(
            validator
                .validate_url("http://169.254.169.254/metadata", "test")
                .is_ok()
        );
    }

    #[test]
    fn invalid_url_rejected() {
        let config = test_config("localhost", "", true);
        let validator = BackendUrlValidator::from_config(&config).expect("validator");

        let result = validator.validate_url("not-a-url", "test");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Invalid URL"));
    }

    #[test]
    fn invalid_cidr_rejected_at_construction() {
        let config = test_config("localhost", "invalid-cidr", true);
        let result = BackendUrlValidator::from_config(&config);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Invalid CIDR network"));
    }

    #[test]
    fn ipv6_loopback_blocklist_hits_through_brackets() {
        let config = test_config("", "::1/128", true);
        let validator = BackendUrlValidator::from_config(&config).expect("validator");

        let result = validator.validate_url("http://[::1]/api", "test");
        assert!(
            result.is_err(),
            "bracketed IPv6 loopback must be caught by CIDR blocklist"
        );
        let msg = result.unwrap_err();
        assert!(
            msg.contains("blocked network"),
            "expected CIDR rejection, got: {msg}"
        );
    }

    #[test]
    fn ipv4_mapped_ipv6_caught_by_ipv4_cidr_block() {
        let config = test_config("", "169.254.169.254/32", true);
        let validator = BackendUrlValidator::from_config(&config).expect("validator");

        let result = validator.validate_url("http://[::ffff:169.254.169.254]/metadata", "test");
        assert!(
            result.is_err(),
            "::ffff:169.254.169.254 must be caught by IPv4 CIDR blocklist"
        );
        let msg = result.unwrap_err();
        assert!(
            msg.contains("blocked network"),
            "expected CIDR rejection, got: {msg}"
        );
    }

    #[test]
    fn ipv6_in_allowlist_approved_via_brackets() {
        let config = test_config("[::1],localhost", "", true);
        let validator = BackendUrlValidator::from_config(&config).expect("validator");

        let result = validator.validate_url("http://[::1]:4444/rpc", "test");
        assert!(
            result.is_ok(),
            "[::1] allowlisted with brackets should match url::Url::host_str output"
        );
    }
}
