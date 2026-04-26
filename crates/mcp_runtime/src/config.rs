// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! CLI and environment-backed configuration for the Rust MCP runtime.

use clap::Parser;
use std::{net::SocketAddr, path::PathBuf};

const DEFAULT_SUPPORTED_PROTOCOL_VERSIONS: &[&str] =
    &["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];

/// Default maximum request body size (10MB)
pub const DEFAULT_MAX_REQUEST_BODY_SIZE_BYTES: usize = 10_485_760;

#[derive(Debug, Clone, Parser)]
#[command(name = "contextforge-mcp-runtime")]
#[command(about = "Experimental Rust MCP runtime edge for ContextForge")]
/// Runtime configuration parsed from CLI flags and environment variables.
///
/// These options are intentionally low-level. In normal compose/test workflows,
/// the top-level `RUST_MCP_MODE` helper configures the right runtime behavior
/// and these values are only used as advanced overrides.
pub struct RuntimeConfig {
    #[arg(
        long,
        env = "MCP_RUST_BACKEND_RPC_URL",
        default_value = "http://127.0.0.1:4444/rpc"
    )]
    pub backend_rpc_url: String,

    #[arg(long, env = "MCP_RUST_LISTEN_HTTP", default_value = "127.0.0.1:8787")]
    pub listen_http: String,

    #[arg(long, env = "MCP_RUST_LISTEN_UDS")]
    pub listen_uds: Option<PathBuf>,

    #[arg(long, env = "MCP_RUST_PUBLIC_LISTEN_HTTP")]
    pub public_listen_http: Option<String>,

    #[arg(long, env = "MCP_RUST_PROTOCOL_VERSION", default_value = "2025-11-25")]
    pub protocol_version: String,

    #[arg(
        long = "supported-protocol-version",
        env = "MCP_RUST_SUPPORTED_PROTOCOL_VERSIONS",
        value_delimiter = ','
    )]
    pub supported_protocol_versions: Vec<String>,

    #[arg(long, env = "MCP_RUST_SERVER_NAME", default_value = "ContextForge")]
    pub server_name: String,

    #[arg(long, env = "MCP_RUST_SERVER_VERSION", default_value = env!("CARGO_PKG_VERSION"))]
    pub server_version: String,

    #[arg(
        long,
        env = "MCP_RUST_INSTRUCTIONS",
        default_value = "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration."
    )]
    pub instructions: String,

    #[arg(long, env = "MCP_RUST_REQUEST_TIMEOUT_MS", default_value_t = 30_000)]
    pub request_timeout_ms: u64,

    #[arg(
        long,
        env = "MCP_RUST_CLIENT_CONNECT_TIMEOUT_MS",
        default_value_t = 5_000
    )]
    pub client_connect_timeout_ms: u64,

    #[arg(
        long,
        env = "MCP_RUST_CLIENT_POOL_IDLE_TIMEOUT_SECONDS",
        default_value_t = 90
    )]
    pub client_pool_idle_timeout_seconds: u64,

    #[arg(
        long,
        env = "MCP_RUST_CLIENT_POOL_MAX_IDLE_PER_HOST",
        default_value_t = 1024
    )]
    pub client_pool_max_idle_per_host: usize,

    #[arg(
        long,
        env = "MCP_RUST_CLIENT_TCP_KEEPALIVE_SECONDS",
        default_value_t = 30
    )]
    pub client_tcp_keepalive_seconds: u64,

    #[arg(
        long,
        env = "MCP_RUST_TOOLS_CALL_PLAN_TTL_SECONDS",
        default_value_t = 30
    )]
    pub tools_call_plan_ttl_seconds: u64,

    #[arg(
        long,
        env = "MCP_RUST_UPSTREAM_SESSION_TTL_SECONDS",
        default_value_t = 300
    )]
    pub upstream_session_ttl_seconds: u64,

    #[arg(
        long,
        env = "MCP_RUST_USE_RMCP_UPSTREAM_CLIENT",
        default_value_t = false
    )]
    pub use_rmcp_upstream_client: bool,

    #[arg(long, env = "MCP_RUST_SESSION_CORE_ENABLED", default_value_t = false)]
    pub session_core_enabled: bool,

    #[arg(long, env = "MCP_RUST_EVENT_STORE_ENABLED", default_value_t = false)]
    pub event_store_enabled: bool,

    #[arg(long, env = "MCP_RUST_RESUME_CORE_ENABLED", default_value_t = false)]
    pub resume_core_enabled: bool,

    #[arg(
        long,
        env = "MCP_RUST_LIVE_STREAM_CORE_ENABLED",
        default_value_t = false
    )]
    pub live_stream_core_enabled: bool,

    #[arg(long, env = "MCP_RUST_AFFINITY_CORE_ENABLED", default_value_t = false)]
    pub affinity_core_enabled: bool,

    #[arg(
        long,
        env = "MCP_RUST_SESSION_AUTH_REUSE_ENABLED",
        default_value_t = false
    )]
    pub session_auth_reuse_enabled: bool,

    #[arg(
        long,
        env = "MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS",
        default_value_t = 30
    )]
    pub session_auth_reuse_ttl_seconds: u64,

    #[arg(long, env = "MCP_RUST_SESSION_TTL_SECONDS", default_value_t = 3_600)]
    pub session_ttl_seconds: u64,

    #[arg(
        long,
        env = "MCP_RUST_EVENT_STORE_MAX_EVENTS_PER_STREAM",
        default_value_t = 100
    )]
    pub event_store_max_events_per_stream: usize,

    #[arg(
        long,
        env = "MCP_RUST_EVENT_STORE_TTL_SECONDS",
        default_value_t = 3_600
    )]
    pub event_store_ttl_seconds: u64,

    #[arg(
        long,
        env = "MCP_RUST_EVENT_STORE_POLL_INTERVAL_MS",
        default_value_t = 250
    )]
    pub event_store_poll_interval_ms: u64,

    #[arg(long, env = "MCP_RUST_CACHE_PREFIX", default_value = "mcpgw:")]
    pub cache_prefix: String,

    #[arg(long, env = "MCP_RUST_DATABASE_URL")]
    pub database_url: Option<String>,

    #[arg(long, env = "MCP_RUST_REDIS_URL")]
    pub redis_url: Option<String>,

    #[arg(long, env = "MCP_RUST_DB_POOL_MAX_SIZE", default_value_t = 20)]
    pub db_pool_max_size: usize,

    #[arg(long, env = "MCP_RUST_LOG", default_value = "info")]
    pub log_filter: String,

    #[arg(
        long,
        env = "MCP_RUST_BACKEND_VALIDATION_ENABLED",
        default_value_t = true
    )]
    pub backend_validation_enabled: bool,

    #[arg(
        long,
        env = "MCP_RUST_BACKEND_ALLOWED_HOSTS",
        default_value = "localhost,127.0.0.1,[::1]"
    )]
    pub backend_allowed_hosts: String,

    #[arg(
        long,
        env = "MCP_RUST_BACKEND_BLOCKED_NETWORKS",
        default_value = "169.254.169.254/32,fd00::1/128"
    )]
    pub backend_blocked_networks: String,

    #[arg(long, env = "MCP_RUST_BACKEND_MAX_URL_LENGTH", default_value_t = 2048)]
    pub backend_max_url_length: usize,

    #[arg(
        long,
        env = "MCP_RUST_MAX_REQUEST_BODY_SIZE_BYTES",
        default_value_t = DEFAULT_MAX_REQUEST_BODY_SIZE_BYTES
    )]
    pub max_request_body_size_bytes: usize,

    #[arg(long, env = "MCP_RUST_EXIT_AFTER_STARTUP_MS", hide = true)]
    pub exit_after_startup_ms: Option<u64>,
}

#[derive(Debug, Clone)]
/// Primary listener target for the runtime.
pub enum ListenTarget {
    Http(SocketAddr),
    Uds(PathBuf),
}

impl RuntimeConfig {
    #[must_use]
    /// Returns the effective list of protocol versions accepted by this runtime.
    ///
    /// The configured primary protocol version is always included even when the
    /// caller provided an explicit supported-version list.
    pub fn effective_supported_protocol_versions(&self) -> Vec<String> {
        let mut versions = self.supported_protocol_versions.clone();

        if versions.is_empty() {
            versions = DEFAULT_SUPPORTED_PROTOCOL_VERSIONS
                .iter()
                .map(|version| (*version).to_string())
                .collect();
        }

        if !versions
            .iter()
            .any(|version| version == &self.protocol_version)
        {
            versions.insert(0, self.protocol_version.clone());
        }

        versions
    }

    /// Returns the primary listen target for the runtime.
    ///
    /// # Errors
    ///
    /// Returns an error when `listen_http` is configured with an invalid socket address.
    pub fn listen_target(&self) -> Result<ListenTarget, String> {
        if let Some(path) = &self.listen_uds {
            return Ok(ListenTarget::Uds(path.clone()));
        }

        self.listen_http
            .parse::<SocketAddr>()
            .map(ListenTarget::Http)
            .map_err(|err| format!("invalid listen address '{}': {err}", self.listen_http))
    }

    /// Returns the optional public HTTP listen address when it differs from the primary listener.
    ///
    /// # Errors
    ///
    /// Returns an error when `public_listen_http` is configured with an invalid socket address
    /// or when deriving the primary listen target fails.
    pub fn public_listen_addr(&self) -> Result<Option<SocketAddr>, String> {
        let Some(addr) = self.public_listen_http.as_deref() else {
            return Ok(None);
        };

        let parsed = addr
            .parse::<SocketAddr>()
            .map_err(|err| format!("invalid public listen address '{addr}': {err}"))?;

        match self.listen_target()? {
            ListenTarget::Http(existing) if existing == parsed => Ok(None),
            _ => Ok(Some(parsed)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{ListenTarget, RuntimeConfig};
    use clap::Parser;
    use std::path::{Path, PathBuf};

    fn config_from<I, T>(args: I) -> RuntimeConfig
    where
        I: IntoIterator<Item = T>,
        T: Into<std::ffi::OsString> + Clone,
    {
        RuntimeConfig::parse_from(args)
    }

    #[test]
    fn effective_supported_protocol_versions_uses_defaults_and_inserts_protocol() {
        let config = config_from([
            "contextforge-mcp-runtime",
            "--protocol-version",
            "2099-01-01",
        ]);

        let versions = config.effective_supported_protocol_versions();

        assert_eq!(versions.first().map(String::as_str), Some("2099-01-01"));
        assert!(versions.iter().any(|value| value == "2025-11-25"));
        assert!(versions.iter().any(|value| value == "2025-03-26"));
    }

    #[test]
    fn effective_supported_protocol_versions_preserves_existing_protocol() {
        let config = config_from([
            "contextforge-mcp-runtime",
            "--protocol-version",
            "2025-03-26",
            "--supported-protocol-version",
            "2025-03-26,2025-06-18",
        ]);

        let versions = config.effective_supported_protocol_versions();

        assert_eq!(
            versions,
            vec!["2025-03-26".to_string(), "2025-06-18".to_string()]
        );
    }

    #[test]
    fn listen_target_uses_uds_when_configured() {
        let mut config = config_from(["contextforge-mcp-runtime"]);
        config.listen_uds = Some(PathBuf::from("/tmp/contextforge.sock"));

        assert!(matches!(
            config.listen_target().expect("uds target"),
            ListenTarget::Uds(path) if path == Path::new("/tmp/contextforge.sock")
        ));
    }

    #[test]
    fn listen_target_rejects_invalid_http_address() {
        let config = config_from(["contextforge-mcp-runtime", "--listen-http", "not-an-addr"]);

        let error = config
            .listen_target()
            .expect_err("invalid listen addr should fail");

        assert!(error.contains("invalid listen address"));
        assert!(error.contains("not-an-addr"));
    }

    #[test]
    fn public_listen_addr_returns_none_when_unset() {
        let config = config_from(["contextforge-mcp-runtime"]);

        assert_eq!(config.public_listen_addr().expect("public addr"), None);
    }

    #[test]
    fn public_listen_addr_returns_none_when_same_as_primary_http_listener() {
        let config = config_from([
            "contextforge-mcp-runtime",
            "--listen-http",
            "127.0.0.1:8787",
            "--public-listen-http",
            "127.0.0.1:8787",
        ]);

        assert_eq!(config.public_listen_addr().expect("public addr"), None);
    }

    #[test]
    fn public_listen_addr_returns_some_when_distinct() {
        let config = config_from([
            "contextforge-mcp-runtime",
            "--listen-http",
            "127.0.0.1:8787",
            "--public-listen-http",
            "127.0.0.1:9797",
        ]);

        assert_eq!(
            config.public_listen_addr().expect("public addr"),
            Some("127.0.0.1:9797".parse().expect("socket addr"))
        );
    }

    #[test]
    fn public_listen_addr_rejects_invalid_public_address() {
        let config = config_from([
            "contextforge-mcp-runtime",
            "--public-listen-http",
            "invalid-public-addr",
        ]);

        let error = config
            .public_listen_addr()
            .expect_err("invalid public addr should fail");

        assert!(error.contains("invalid public listen address"));
        assert!(error.contains("invalid-public-addr"));
    }

    #[test]
    fn public_listen_addr_ignores_public_http_when_primary_target_is_uds() {
        let mut config = config_from([
            "contextforge-mcp-runtime",
            "--public-listen-http",
            "127.0.0.1:9797",
        ]);
        config.listen_uds = Some(PathBuf::from("/tmp/contextforge.sock"));

        assert_eq!(
            config.public_listen_addr().expect("public addr"),
            Some("127.0.0.1:9797".parse().expect("socket addr"))
        );
    }

    #[test]
    fn hidden_exit_after_startup_flag_is_parseable() {
        let config = config_from(["contextforge-mcp-runtime", "--exit-after-startup-ms", "25"]);

        assert_eq!(config.exit_after_startup_ms, Some(25));
    }
}
