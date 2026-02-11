use clap::Parser;
use serde::Deserialize;

pub const DEFAULT_LOG_LEVEL: &str = "off";
pub const DEFAULT_CONCURRENCY: usize = 10;
pub const DEFAULT_AUTH: Option<&str> = None;

#[derive(Deserialize, Debug, Parser)]
#[command(
    name = "contextforge-stdio-wrapper",
    about = "ContextForge stdio-to-HTTP bridge for MCP Gateway",
    long_about = "High-performance stdio-to-HTTP bridge that connects MCP clients to ContextForge AI Gateway.\n\nReads JSON-RPC messages from stdin, forwards them to the gateway over HTTP,\nand writes responses to stdout. Supports concurrent workers, TLS, and HTTP/2.\n\nPart of ContextForge AI Gateway: https://github.com/IBM/mcp-context-forge",
    version
)]
pub struct Config {
    /// Gateway MCP endpoint URL
    #[arg(long = "url", env = "MCP_SERVER_URL")]
    pub mcp_server_url: String,

    /// Authorization header value
    #[arg(long = "auth", env = "MCP_AUTH")]
    pub mcp_auth: Option<String>,

    /// Max concurrent tool calls
    #[arg(long, default_value_t = DEFAULT_CONCURRENCY, env = "CONCURRENCY")]
    pub concurrency: usize,

    #[arg(
	   long="log-level", 
	   default_value_t = String::from(DEFAULT_LOG_LEVEL),
	   env="LOG_LEVEL"
	)]
    pub mcp_wrapper_log_level: String,

    #[arg(short, long = "log-file", env = "MCP_LOG_FILE")]
    pub mcp_wrapper_log_file: Option<String>,

    /// Response timeout in seconds
    #[arg(long = "timeout", default_value_t = 60, env = "MCP_TOOL_CALL_TIMEOUT")]
    pub mcp_tool_call_timeout: u64,

    /// Path to a custom CA certificate file (PEM format, e.g., .pem, .crt, .cert)
    #[arg(long = "tls-cert", value_name = "PATH", env = "TLS_CERT")]
    pub tls_cert: Option<std::path::PathBuf>,

    /// Content type header to send to server
    #[arg(
        long,
        short = 'c',
        default_value = "application/json",
        env = "MCP_CONTENT_TYPE"
    )]
    pub mcp_content_type: String,

    /// Create separate HTTP connection pool per worker (default: false, uses shared pool)
    #[arg(
        long = "http-pool-per-worker",
        default_value_t = false,
        env = "HTTP_POOL_PER_WORKER"
    )]
    pub http_pool_per_worker: bool,

    /// Maximum idle connections per host in the HTTP pool
    #[arg(long = "http-pool-size", env = "HTTP_POOL_SIZE")]
    pub http_pool_size: Option<usize>,

    /// Enable HTTP/2 protocol (default: false)
    #[arg(long = "http2", default_value_t = false, env = "HTTP2")]
    pub http2: bool,

    /// HTTP connection pool idle timeout in seconds
    #[arg(long = "http-pool-idle-timeout", env = "HTTP_POOL_IDLE_TIMEOUT")]
    pub http_pool_idle_timeout: Option<u64>,

    /// Disable TLS certificate verification (insecure, use only for testing)
    #[arg(long = "insecure", default_value_t = false, env = "INSECURE")]
    pub insecure: bool,
}

/// Normalize an MCP server URL.
/// - If it ends with `/sse`, replace with `/mcp/`.
/// - If it ends with `/mcp`, append trailing slash.
/// - If it ends with `/mcp/`, leave it.
/// - Otherwise, append `/mcp/`.
#[must_use]
pub fn normalize_url(url: &str) -> String {
    if url.ends_with("/mcp/") {
        return url.to_string();
    }
    if url.ends_with("/mcp") {
        return format!("{url}/");
    }
    if let Some(base) = url.strip_suffix("/sse") {
        return format!("{base}/mcp/");
    }
    format!("{url}/mcp/")
}
