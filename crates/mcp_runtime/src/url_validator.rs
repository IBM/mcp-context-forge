// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti, ContextForge Team

//! URL validation with SSRF protection for the Rust MCP runtime.
//!
//! This module implements comprehensive URL validation to prevent Server-Side Request Forgery (SSRF)
//! attacks. It matches the security guarantees of the Python `SecurityValidator` implementation.
//!
//! # Features
//!
//! - Length validation (configurable max length)
//! - Scheme allowlist (http, https, ws, wss only)
//! - Dangerous pattern blocking (javascript:, data:, file:, etc.)
//! - IPv6 blocking
//! - CRLF injection prevention
//! - Credentials in URL blocking
//! - XSS pattern detection
//! - **SSRF Protection**:
//!   - Hostname normalization
//!   - Blocked hostname list check
//!   - DNS resolution of all A/AAAA records
//!   - CIDR-based IP blocking
//!   - Localhost blocking (configurable)
//!   - Private network blocking (configurable)
//!   - Allowlist support for specific private ranges
//!
//! # Configuration
//!
//! All SSRF protection settings are loaded from environment variables via `RuntimeConfig`:
//!
//! - `SSRF_PROTECTION_ENABLED=true` - Enable SSRF protection (default: true)
//! - `SSRF_BLOCKED_NETWORKS` - CIDR ranges to block (comma-separated)
//! - `SSRF_BLOCKED_HOSTS` - Hostnames to block (comma-separated)
//! - `SSRF_ALLOW_LOCALHOST=false` - Allow localhost access (default: false)
//! - `SSRF_ALLOW_PRIVATE_NETWORKS=false` - Allow RFC1918 networks (default: false)
//! - `SSRF_ALLOWED_NETWORKS` - Allowlist specific CIDR ranges (comma-separated)
//! - `SSRF_DNS_FAIL_CLOSED=true` - Fail closed on DNS errors (default: true)
//! - `MAX_URL_LENGTH=2048` - Maximum URL length (default: 2048)
//!
//! # Example
//!
//! ```rust,ignore
//! use crate::config::RuntimeConfig;
//! use crate::url_validator::UrlValidator;
//!
//! let config = RuntimeConfig::parse();
//! let validator = UrlValidator::from_config(&config);
//!
//! // Valid URL
//! assert!(validator.validate_url("https://api.example.com/v1", "Backend URL").is_ok());
//!
//! // Blocked by SSRF protection
//! assert!(validator.validate_url("http://169.254.169.254/", "Backend URL").is_err());
//! assert!(validator.validate_url("http://localhost/admin", "Backend URL").is_err());
//! ```

use crate::config::RuntimeConfig;
use hickory_resolver::config::{ResolverConfig, ResolverOpts};
use hickory_resolver::TokioAsyncResolver;
use ipnetwork::IpNetwork;
use regex::Regex;
use std::net::IpAddr;
use std::sync::Arc;
use thiserror::Error;
use tracing::{debug, warn};
use url::Url;

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

    #[error("{field}: URL contains unsupported or potentially dangerous protocol")]
    DangerousProtocol { field: String },

    #[error("{field}: URL contains IPv6 address which is not supported")]
    IPv6NotSupported { field: String },

    #[error("{field}: URL contains protocol-relative URL which is not supported")]
    ProtocolRelativeUrl { field: String },

    #[error("{field}: URL contains line breaks which are not allowed")]
    ContainsLineBreaks { field: String },

    #[error("{field}: URL contains spaces which are not allowed in URLs")]
    ContainsSpaces { field: String },

    #[error("{field}: URL is not a valid URL: {reason}")]
    InvalidUrl { field: String, reason: String },

    #[error("{field}: URL contains invalid IP address (0.0.0.0)")]
    InvalidZeroIp { field: String },

    #[error("{field}: URL contains invalid port number")]
    InvalidPort { field: String },

    #[error("{field}: URL contains credentials which are not allowed")]
    ContainsCredentials { field: String },

    #[error("{field}: URL contains HTML tags that may cause security issues")]
    ContainsHtmlTags { field: String },

    #[error("{field}: URL contains script patterns that may cause security issues")]
    ContainsScriptPatterns { field: String },

    #[error("{field}: URL contains blocked hostname '{hostname}' (SSRF protection)")]
    BlockedHostname { field: String, hostname: String },

    #[error("{field}: URL contains IP address blocked by SSRF protection (network: {network})")]
    BlockedNetwork { field: String, network: String },

    #[error("{field}: URL contains localhost address which is blocked by SSRF protection")]
    BlockedLocalhost { field: String },

    #[error("{field}: URL contains private network address which is blocked by SSRF protection")]
    BlockedPrivateNetwork { field: String },

    #[error("{field}: DNS resolution failed and SSRF_DNS_FAIL_CLOSED is enabled")]
    DnsResolutionFailed { field: String },

    #[error("{field}: DNS resolution returned no addresses and SSRF_DNS_FAIL_CLOSED is enabled")]
    DnsNoAddresses { field: String },
}

/// URL validator with SSRF protection.
///
/// This struct provides comprehensive URL validation matching the Python SecurityValidator.
/// It checks for various security issues including SSRF, XSS, and other injection attacks.
pub struct UrlValidator {
    /// Master switch for SSRF protection
    ssrf_protection_enabled: bool,

    /// CIDR ranges to always block (e.g., cloud metadata endpoints)
    blocked_networks: Vec<IpNetwork>,

    /// Hostnames to always block (case-insensitive)
    blocked_hosts: Vec<String>,

    /// Allow localhost/loopback addresses (127.0.0.0/8, ::1)
    allow_localhost: bool,

    /// Allow RFC 1918 private network addresses
    allow_private_networks: bool,

    /// Optional CIDR allowlist for internal/private destinations
    allowed_networks: Vec<IpNetwork>,

    /// Fail closed on DNS resolution errors
    dns_fail_closed: bool,

    /// Maximum URL length
    max_url_length: usize,

    /// Allowed URL schemes
    allowed_schemes: Vec<String>,

    /// DNS resolver (async)
    resolver: Arc<TokioAsyncResolver>,

    /// Precompiled regex patterns
    dangerous_url_pattern: Regex,
    dangerous_html_pattern: Regex,
    dangerous_js_pattern: Regex,
}

impl UrlValidator {
    /// Create a new URL validator from runtime configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - Invalid CIDR ranges in blocked_networks or allowed_networks
    /// - DNS resolver cannot be initialized
    pub fn from_config(config: &RuntimeConfig) -> Result<Self, String> {
        // Parse blocked networks
        let mut blocked_networks = Vec::new();
        for network_str in &config.ssrf_blocked_networks {
            match network_str.parse::<IpNetwork>() {
                Ok(network) => blocked_networks.push(network),
                Err(e) => {
                    warn!("Invalid CIDR in ssrf_blocked_networks: {} ({})", network_str, e);
                    // Continue with other networks - don't fail config load
                }
            }
        }

        // Parse allowed networks
        let mut allowed_networks = Vec::new();
        for network_str in &config.ssrf_allowed_networks {
            match network_str.parse::<IpNetwork>() {
                Ok(network) => allowed_networks.push(network),
                Err(e) => {
                    warn!("Invalid CIDR in ssrf_allowed_networks: {} ({})", network_str, e);
                    // Continue with other networks - don't fail config load
                }
            }
        }

        // Normalize blocked hostnames (lowercase, strip trailing dots)
        let blocked_hosts: Vec<String> = config
            .ssrf_blocked_hosts
            .iter()
            .map(|host| host.to_lowercase().trim_end_matches('.').to_string())
            .collect();

        // Create DNS resolver (async)
        let resolver = TokioAsyncResolver::tokio(ResolverConfig::default(), ResolverOpts::default());

        // Compile regex patterns (at creation time for performance)
        let dangerous_url_pattern = Regex::new(
            r"(?i)(javascript|data|file|vbscript|about|chrome|mailto):",
        )
        .map_err(|e| format!("Failed to compile dangerous_url_pattern regex: {}", e))?;

        let dangerous_html_pattern = Regex::new(
            r"(?i)<(script|iframe|object|embed|link|meta|base|form|img|svg|video|audio|source|track|area|map|canvas|applet|frame|frameset|html|head|body|style)\b|</*(script|iframe|object|embed|link|meta|base|form|img|svg|video|audio|source|track|area|map|canvas|applet|frame|frameset|html|head|body|style)>"
        ).map_err(|e| format!("Failed to compile dangerous_html_pattern regex: {}", e))?;

        let dangerous_js_pattern = Regex::new(
            r"(?i)(javascript:|vbscript:|on\w+\s*=|data:.*script)",
        )
        .map_err(|e| format!("Failed to compile dangerous_js_pattern regex: {}", e))?;

        Ok(Self {
            ssrf_protection_enabled: config.ssrf_protection_enabled,
            blocked_networks,
            blocked_hosts,
            allow_localhost: config.ssrf_allow_localhost,
            allow_private_networks: config.ssrf_allow_private_networks,
            allowed_networks,
            dns_fail_closed: config.ssrf_dns_fail_closed,
            max_url_length: config.max_url_length,
            allowed_schemes: vec![
                "http://".to_string(),
                "https://".to_string(),
                "ws://".to_string(),
                "wss://".to_string(),
            ],
            resolver: Arc::new(resolver),
            dangerous_url_pattern,
            dangerous_html_pattern,
            dangerous_js_pattern,
        })
    }

    /// Validate a URL for security issues.
    ///
    /// This is the main entry point for URL validation. It performs all checks including:
    /// - Length validation
    /// - Scheme validation
    /// - Dangerous pattern detection
    /// - SSRF protection (if enabled)
    /// - XSS pattern detection
    ///
    /// # Errors
    ///
    /// Returns `ValidationError` if the URL fails any security check.
    pub async fn validate_url(&self, value: &str, field_name: &str) -> Result<(), ValidationError> {
        // Check for empty URL
        if value.is_empty() {
            return Err(ValidationError::EmptyUrl {
                field: field_name.to_string(),
            });
        }

        // Length check
        if value.len() > self.max_url_length {
            return Err(ValidationError::TooLong {
                field: field_name.to_string(),
                max: self.max_url_length,
            });
        }

        // Check allowed schemes
        let value_lower = value.to_lowercase();
        if !self
            .allowed_schemes
            .iter()
            .any(|scheme| value_lower.starts_with(&scheme.to_lowercase()))
        {
            return Err(ValidationError::InvalidScheme {
                field: field_name.to_string(),
                allowed_schemes: self.allowed_schemes.join(", "),
            });
        }

        // Block dangerous URL patterns
        if self.dangerous_url_pattern.is_match(value) {
            return Err(ValidationError::DangerousProtocol {
                field: field_name.to_string(),
            });
        }

        // Block IPv6 URLs (URLs with square brackets)
        if value.contains('[') || value.contains(']') {
            return Err(ValidationError::IPv6NotSupported {
                field: field_name.to_string(),
            });
        }

        // Block protocol-relative URLs
        if value.starts_with("//") {
            return Err(ValidationError::ProtocolRelativeUrl {
                field: field_name.to_string(),
            });
        }

        // Check for CRLF injection
        if value.contains('\r') || value.contains('\n') {
            return Err(ValidationError::ContainsLineBreaks {
                field: field_name.to_string(),
            });
        }

        // Check for spaces in domain (not query string)
        let url_part = value.split('?').next().unwrap_or(value);
        if url_part.contains(' ') {
            return Err(ValidationError::ContainsSpaces {
                field: field_name.to_string(),
            });
        }

        // Parse URL
        let parsed_url = Url::parse(value).map_err(|e| ValidationError::InvalidUrl {
            field: field_name.to_string(),
            reason: e.to_string(),
        })?;

        // Check scheme and host are present
        if parsed_url.scheme().is_empty() || parsed_url.host_str().is_none() {
            return Err(ValidationError::InvalidUrl {
                field: field_name.to_string(),
                reason: "missing scheme or host".to_string(),
            });
        }

        // Additional validation: ensure netloc doesn't contain brackets (double-check)
        if let Some(host) = parsed_url.host_str() {
            if host.contains('[') || host.contains(']') {
                return Err(ValidationError::IPv6NotSupported {
                    field: field_name.to_string(),
                });
            }

            // Always block 0.0.0.0 (all interfaces) regardless of SSRF settings
            if host == "0.0.0.0" {
                return Err(ValidationError::InvalidZeroIp {
                    field: field_name.to_string(),
                });
            }

            // Apply SSRF protection if enabled
            if self.ssrf_protection_enabled {
                self.validate_ssrf(host, field_name).await?;
            }
        }

        // Validate port number
        if let Some(port) = parsed_url.port() {
            if port == 0 || port > 65535 {
                return Err(ValidationError::InvalidPort {
                    field: field_name.to_string(),
                });
            }
        }

        // Check for credentials in URL
        if !parsed_url.username().is_empty() || parsed_url.password().is_some() {
            return Err(ValidationError::ContainsCredentials {
                field: field_name.to_string(),
            });
        }

        // Check for XSS patterns in the entire URL
        if self.dangerous_html_pattern.is_match(value) {
            return Err(ValidationError::ContainsHtmlTags {
                field: field_name.to_string(),
            });
        }

        if self.dangerous_js_pattern.is_match(value) {
            return Err(ValidationError::ContainsScriptPatterns {
                field: field_name.to_string(),
            });
        }

        Ok(())
    }

    /// Validate hostname/IP against SSRF protection rules.
    ///
    /// This method implements configurable SSRF (Server-Side Request Forgery) protection
    /// to prevent the gateway from being used to access internal resources or cloud
    /// metadata services.
    ///
    /// # SSRF Protection Rules
    ///
    /// 1. **Blocked Hostnames**: Check against blocklist (case-insensitive)
    /// 2. **DNS Resolution**: Resolve hostname to all IP addresses (A and AAAA records)
    /// 3. **Blocked Networks**: Check ALL resolved IPs against blocked CIDR ranges
    /// 4. **Localhost Check**: Block 127.0.0.0/8 and ::1 (if not allowed)
    /// 5. **Private Networks**: Block RFC 1918 ranges (if not allowed)
    /// 6. **Allowlist**: Allow specific private ranges even when private networks are blocked
    ///
    /// # Errors
    ///
    /// Returns `ValidationError` if the hostname/IP is blocked by SSRF protection rules.
    async fn validate_ssrf(&self, hostname: &str, field_name: &str) -> Result<(), ValidationError> {
        // Normalize hostname: lowercase, strip trailing dots (DNS FQDN notation)
        let hostname_normalized = hostname.to_lowercase().trim_end_matches('.').to_string();

        debug!(
            "SSRF validation for hostname: {} (normalized: {})",
            hostname, hostname_normalized
        );

        // Check blocked hostnames (case-insensitive, normalized)
        for blocked_host in &self.blocked_hosts {
            if hostname_normalized == *blocked_host {
                return Err(ValidationError::BlockedHostname {
                    field: field_name.to_string(),
                    hostname: hostname.to_string(),
                });
            }
        }

        // Resolve hostname to IP for network-based checks
        let ip_addresses = self.resolve_hostname_to_ips(&hostname_normalized).await;

        // Handle DNS resolution failure
        if ip_addresses.is_empty() {
            if self.dns_fail_closed {
                return Err(ValidationError::DnsNoAddresses {
                    field: field_name.to_string(),
                });
            }
            // Fail open: allow through (hostname blocking above catches known dangerous hostnames)
            return Ok(());
        }

        debug!(
            "Resolved {} to {} IP address(es): {:?}",
            hostname_normalized,
            ip_addresses.len(),
            ip_addresses
        );

        // Check ALL resolved addresses - if ANY is blocked, reject the request
        for ip_addr in ip_addresses {
            self.validate_ip_address(ip_addr, field_name)?;
        }

        Ok(())
    }

    /// Resolve a hostname to all IP addresses (A and AAAA records).
    ///
    /// Returns an empty vector if DNS resolution fails or if the hostname is an IP address that cannot be parsed.
    async fn resolve_hostname_to_ips(&self, hostname: &str) -> Vec<IpAddr> {
        let mut ip_addresses = Vec::new();

        // Try to parse as IP address directly
        if let Ok(ip_addr) = hostname.parse::<IpAddr>() {
            return vec![ip_addr];
        }

        // It's a hostname, resolve ALL addresses (IPv4 and IPv6)
        match self.resolver.lookup_ip(hostname).await {
            Ok(lookup) => {
                for ip in lookup.iter() {
                    ip_addresses.push(ip);
                }
            }
            Err(e) => {
                debug!("DNS resolution failed for {}: {}", hostname, e);
                // Return empty vec - caller will handle fail-closed/fail-open
            }
        }

        ip_addresses
    }

    /// Validate a single IP address against SSRF protection rules.
    ///
    /// # Errors
    ///
    /// Returns `ValidationError` if the IP address is blocked by any SSRF protection rule.
    fn validate_ip_address(&self, ip_addr: IpAddr, field_name: &str) -> Result<(), ValidationError> {
        // Check against blocked networks (always blocked regardless of other settings)
        for network in &self.blocked_networks {
            if network.contains(ip_addr) {
                return Err(ValidationError::BlockedNetwork {
                    field: field_name.to_string(),
                    network: network.to_string(),
                });
            }
        }

        // Check localhost/loopback (if not allowed)
        if !self.allow_localhost && ip_addr.is_loopback() {
            return Err(ValidationError::BlockedLocalhost {
                field: field_name.to_string(),
            });
        }

        // Check private networks (if not allowed)
        if !self.allow_private_networks && is_private_ip(ip_addr) && !ip_addr.is_loopback() {
            // Check if it's in the allowlist
            let mut allowed_private = false;
            for network in &self.allowed_networks {
                if network.contains(ip_addr) {
                    allowed_private = true;
                    break;
                }
            }

            if !allowed_private {
                return Err(ValidationError::BlockedPrivateNetwork {
                    field: field_name.to_string(),
                });
            }
        }

        Ok(())
    }
}

/// Check if an IP address is in a private network range.
///
/// This checks RFC 1918 private ranges:
/// - 10.0.0.0/8
/// - 172.16.0.0/12
/// - 192.168.0.0/16
/// - fd00::/8 (IPv6 ULA)
/// - fc00::/7 (IPv6 ULA)
fn is_private_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ipv4) => {
            let octets = ipv4.octets();
            // 10.0.0.0/8
            octets[0] == 10
                // 172.16.0.0/12
                || (octets[0] == 172 && (octets[1] >= 16 && octets[1] <= 31))
                // 192.168.0.0/16
                || (octets[0] == 192 && octets[1] == 168)
        }
        IpAddr::V6(ipv6) => {
            let segments = ipv6.segments();
            // fc00::/7 (includes fd00::/8)
            (segments[0] & 0xfe00) == 0xfc00
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::RuntimeConfig;

    fn create_test_config() -> RuntimeConfig {
        // Create a test config with default SSRF protection
        let args = vec!["test"];
        RuntimeConfig::try_parse_from(args).unwrap()
    }

    fn create_permissive_config() -> RuntimeConfig {
        // Create a config that allows localhost and private networks
        let args = vec![
            "test",
            "--ssrf-allow-localhost",
            "true",
            "--ssrf-allow-private-networks",
            "true",
        ];
        RuntimeConfig::try_parse_from(args).unwrap()
    }

    #[tokio::test]
    async fn test_empty_url() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).unwrap();

        let result = validator.validate_url("", "test").await;
        assert!(matches!(result, Err(ValidationError::EmptyUrl { .. })));
    }

    #[tokio::test]
    async fn test_url_too_long() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).unwrap();

        let long_url = format!("https://example.com/{}", "a".repeat(3000));
        let result = validator.validate_url(&long_url, "test").await;
        assert!(matches!(result, Err(ValidationError::TooLong { .. })));
    }

    #[tokio::test]
    async fn test_invalid_scheme() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).unwrap();

        let result = validator.validate_url("ftp://example.com", "test").await;
        assert!(matches!(result, Err(ValidationError::InvalidScheme { .. })));
    }

    #[tokio::test]
    async fn test_dangerous_protocols() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).unwrap();

        let dangerous_urls = vec![
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "file:///etc/passwd",
        ];

        for url in dangerous_urls {
            let result = validator.validate_url(url, "test").await;
            assert!(result.is_err(), "Should block dangerous URL: {}", url);
        }
    }

    #[tokio::test]
    async fn test_ipv6_blocked() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).unwrap();

        let result = validator.validate_url("https://[::1]:8080/", "test").await;
        assert!(matches!(
            result,
            Err(ValidationError::IPv6NotSupported { .. })
        ));
    }

    #[tokio::test]
    async fn test_crlf_injection() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).unwrap();

        let result = validator
            .validate_url("https://example.com\rHost: evil.com", "test")
            .await;
        assert!(matches!(
            result,
            Err(ValidationError::ContainsLineBreaks { .. })
        ));
    }

    #[tokio::test]
    async fn test_credentials_in_url() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).unwrap();

        let result = validator
            .validate_url("https://user:pass@example.com/", "test")
            .await;
        assert!(matches!(
            result,
            Err(ValidationError::ContainsCredentials { .. })
        ));
    }

    #[tokio::test]
    async fn test_allows_public_urls() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).unwrap();

        let public_urls = vec![
            "https://api.example.com/v1",
            "http://example.com:8080/path",
            "wss://example.com/ws",
        ];

        for url in public_urls {
            let result = validator.validate_url(url, "test").await;
            assert!(result.is_ok(), "Should allow public URL: {}", url);
        }
    }

    #[tokio::test]
    async fn test_blocks_localhost_by_default() {
        let config = create_test_config();
        let validator = UrlValidator::from_config(&config).unwrap();

        let localhost_urls = vec!["http://localhost/", "http://127.0.0.1/"];

        for url in localhost_urls {
            let result = validator.validate_url(url, "test").await;
            assert!(result.is_err(), "Should block localhost URL: {}", url);
        }
    }

    #[tokio::test]
    async fn test_allows_localhost_when_configured() {
        let config = create_permissive_config();
        let validator = UrlValidator::from_config(&config).unwrap();

        let result = validator
            .validate_url("http://localhost:4444/rpc", "test")
            .await;
        assert!(result.is_ok(), "Should allow localhost when configured");
    }

    #[tokio::test]
    async fn test_is_private_ip() {
        // Test RFC 1918 private ranges
        assert!(is_private_ip("10.0.0.1".parse().unwrap()));
        assert!(is_private_ip("172.16.0.1".parse().unwrap()));
        assert!(is_private_ip("192.168.1.1".parse().unwrap()));

        // Test public IPs
        assert!(!is_private_ip("8.8.8.8".parse().unwrap()));
        assert!(!is_private_ip("1.1.1.1".parse().unwrap()));
    }
}
