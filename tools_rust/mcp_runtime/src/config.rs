use clap::Parser;
use std::{net::SocketAddr, path::PathBuf};

const DEFAULT_SUPPORTED_PROTOCOL_VERSIONS: &[&str] =
    &["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];

#[derive(Debug, Clone, Parser)]
#[command(name = "contextforge-mcp-runtime")]
#[command(about = "Experimental Rust MCP runtime edge for ContextForge")]
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
}

#[derive(Debug, Clone)]
pub enum ListenTarget {
    Http(SocketAddr),
    Uds(PathBuf),
}

impl RuntimeConfig {
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

    pub fn listen_target(&self) -> Result<ListenTarget, String> {
        if let Some(path) = &self.listen_uds {
            return Ok(ListenTarget::Uds(path.clone()));
        }

        self.listen_http
            .parse::<SocketAddr>()
            .map(ListenTarget::Http)
            .map_err(|err| format!("invalid listen address '{}': {err}", self.listen_http))
    }
}
