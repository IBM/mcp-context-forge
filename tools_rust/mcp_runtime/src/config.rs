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
