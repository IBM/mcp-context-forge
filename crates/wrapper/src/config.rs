use clap::Parser;
use reqwest::Url;
use serde::Deserialize;
use std::fmt;

pub const DEFAULT_LOG_LEVEL: &str = "off";
pub const DEFAULT_CONCURRENCY: usize = 10;
pub const DEFAULT_AUTH: Option<&str> = None; // pragma: allowlist secret

#[derive(Deserialize, Parser)]
pub struct Config {
    /// Gateway MCP endpoint URL
    #[arg(long = "url", env = "MCP_SERVER_URL")]
    pub mcp_server_url: String,

    /// Authorization header value
    #[arg(long = "auth", env = "MCP_AUTH")]
    pub authorization_header: Option<String>,

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

impl fmt::Debug for Config {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Config")
            .field(
                "mcp_server_url",
                &sanitize_url_for_debug(&self.mcp_server_url),
            )
            .field(
                "authorization_header",
                &self.authorization_header.as_ref().map(|_| "<redacted>"),
            )
            .field("concurrency", &self.concurrency)
            .field("mcp_wrapper_log_level", &self.mcp_wrapper_log_level)
            .field("mcp_wrapper_log_file", &self.mcp_wrapper_log_file)
            .field("mcp_tool_call_timeout", &self.mcp_tool_call_timeout)
            .field("tls_cert", &self.tls_cert)
            .field("mcp_content_type", &self.mcp_content_type)
            .field("http_pool_per_worker", &self.http_pool_per_worker)
            .field("http_pool_size", &self.http_pool_size)
            .field("http2", &self.http2)
            .field("http_pool_idle_timeout", &self.http_pool_idle_timeout)
            .field("insecure", &self.insecure)
            .finish()
    }
}

fn sanitize_url_for_debug(raw: &str) -> String {
    let Ok(mut url) = Url::parse(raw) else {
        return raw.to_string();
    };
    if !url.username().is_empty() || url.password().is_some() {
        let _ = url.set_username("redacted");
        let _ = url.set_password(None);
    }
    url.to_string()
}
