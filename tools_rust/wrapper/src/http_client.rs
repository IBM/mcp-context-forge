use crate::config::Config;
use crate::streamer_error::{build_error, invalid_error, read_error};
use reqwest::Client;
use tokio::fs::read;
use tracing::warn;

use std::time::Duration;
/// Creates an HTTP client from configuration
/// # Errors
/// * wrong parameters, invalid certs
pub async fn get_http_client(config: &Config) -> Result<Client, String> {
    let mut build = Client::builder()
        .timeout(Duration::from_secs(config.mcp_tool_call_timeout))
        .tcp_nodelay(true);

    if config.http2 {
        build = build.http2_prior_knowledge();
    }

    if let Some(pool_size) = config.http_pool_size {
        build = build.pool_max_idle_per_host(pool_size);
    }

    if let Some(idle_timeout) = config.http_pool_idle_timeout {
        build = build.pool_idle_timeout(Duration::from_secs(idle_timeout));
    }

    if config.insecure {
        warn!("TLS certificate verification disabled (--insecure). Do NOT use in production.");
        build = build.danger_accept_invalid_certs(true);
    }

    if let Some(cert_path) = &config.tls_cert {
        let cert_bytes = read(cert_path)
            .await
            .map_err(|e| read_error(cert_path, &e))?;
        let cert = reqwest::Certificate::from_pem(&cert_bytes)
            .map_err(|e| invalid_error(cert_path, &e))?;
        build = build.add_root_certificate(cert);
    }

    build.build().map_err(|e| build_error(&e))
}
